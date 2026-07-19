"""ChessBot move selection with opening book, alpha-beta search, and difficulty-based blunders."""

import os
import random
import time

import chess
import chess.polyglot

from chess_game.engine.piece_tables import PIECE_DATA as _RAW
from chess_game.log import get_logger

_LOGGER = get_logger()


class SearchAborted(Exception):
    """Raised internally when an in-flight search's abort event is set."""

# ── Constants ─────────────────────────────────────────────────────────────────

INF = 10_000_000

# Transposition table entry flags
_EXACT      = 0
_LOWERBOUND = 1
_UPPERBOUND = 2

_MAX_TT_SIZE = 500_000   # ~50 MB cap

# ── Unified difficulty configuration ─────────────────────────────────────────

# Each entry maps a 1–10 difficulty level to:
#   depth        – search depth fed to the alpha-beta engine
#   blunder_prob – probability (0.0–1.0) of NOT playing the best move
DIFFICULTY_CONFIG = {
    1:  {'depth': 1, 'blunder_prob': 0.80},
    2:  {'depth': 1, 'blunder_prob': 0.70},
    3:  {'depth': 2, 'blunder_prob': 0.60},
    4:  {'depth': 2, 'blunder_prob': 0.50},
    5:  {'depth': 3, 'blunder_prob': 0.40},
    6:  {'depth': 3, 'blunder_prob': 0.30},
    7:  {'depth': 4, 'blunder_prob': 0.20},
    8:  {'depth': 4, 'blunder_prob': 0.10},
    9:  {'depth': 5, 'blunder_prob': 0.05},
    10: {'depth': 6, 'blunder_prob': 0.00},  # perfect play, no blunders
}

# Weights for the blunder pool (2nd through 5th best move)
_BLUNDER_WEIGHTS = [50, 30, 15, 5]

# ── Piece table lookup ────────────────────────────────────────────────────────
# Each value in _RAW is now (material, midgame_pst, endgame_pst) — see
# piece_tables.PIECE_DATA. _PT_MAP keeps that full three-tuple so _evaluate
# can taper between the two PSTs; _MATERIAL only ever needs index 0.

_PT_MAP = {
    chess.PAWN:   _RAW[' '],
    chess.KNIGHT: _RAW['N'],
    chess.BISHOP: _RAW['B'],
    chess.ROOK:   _RAW['R'],
    chess.QUEEN:  _RAW['Q'],
    chess.KING:   _RAW['K'],
}

_MATERIAL = [0] * 7
_MATERIAL[chess.PAWN]   = _RAW[' '][0]
_MATERIAL[chess.KNIGHT] = _RAW['N'][0]
_MATERIAL[chess.BISHOP] = _RAW['B'][0]
_MATERIAL[chess.ROOK]   = _RAW['R'][0]
_MATERIAL[chess.QUEEN]  = _RAW['Q'][0]
_MATERIAL[chess.KING]   = _RAW['K'][0]

_PST_INDEX = {
    chess.WHITE: [0] * 64,
    chess.BLACK: [0] * 64,
}
for sq in range(64):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    _PST_INDEX[chess.WHITE][sq] = (7 - rank) * 8 + file
    _PST_INDEX[chess.BLACK][sq] = rank * 8 + file

# Game phase is based on non-pawn material and ranges from 0
# (kings-and-pawns) to 24 (full opening material).
_PHASE_MAX = 24
_PHASE_WEIGHTS = {
    chess.KNIGHT: 1,
    chess.BISHOP: 1,
    chess.ROOK:   2,
    chess.QUEEN:  4,
}


def _phase(board):
    """Estimate game phase from non-pawn material: 0 = endgame, 24 = opening."""
    raw = 0
    for piece_type, weight in _PHASE_WEIGHTS.items():
        raw += weight * len(board.pieces(piece_type, chess.WHITE))
        raw += weight * len(board.pieces(piece_type, chess.BLACK))
    return max(0, min(_PHASE_MAX, raw))


# Non-pawn material total (in centipawn units) below which null-move
# pruning is skipped, to avoid zugzwang-prone king-and-pawn endgames where
# "passing" is illegally optimistic. Roughly one minor piece per side.
_NULL_MOVE_MATERIAL_FLOOR = 2 * _MATERIAL[chess.KNIGHT]

# Minimum depth before null-move pruning is attempted — at low depth the
# reduced sub-search (depth - 3) would go negative or be too shallow to
# trust, so this stage is skipped entirely below it.
_NULL_MOVE_MIN_DEPTH = 3


def _pst_index(sq, color):
    """
    Map a square to the correct PST index.
    Row 0 of each PST = rank 8 (top from White's perspective).
    """
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    return (7 - rank) * 8 + file if color == chess.WHITE else rank * 8 + file


# ── Static evaluation ─────────────────────────────────────────────────────────

def _evaluate(board, bot_color):
    """Evaluate board material and phase-weighted positional value."""
    score = 0
    pt_map = _PT_MAP
    pst_index = _PST_INDEX
    phase = _phase(board)
    inv_phase = _PHASE_MAX - phase
    for sq, piece in board.piece_map().items():
        material, mid_pst, end_pst = pt_map[piece.piece_type]
        idx = pst_index[piece.color][sq]
        tapered_pst = (mid_pst[idx] * phase + end_pst[idx] * inv_phase) // _PHASE_MAX
        val = material + tapered_pst
        score += val if piece.color == bot_color else -val
    return score


def _non_pawn_material(board, color):
    """Count non-pawn material for null-move pruning safety."""
    total = 0
    for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        total += len(board.pieces(piece_type, color)) * _MATERIAL[piece_type]
    return total


# ── Move ordering ─────────────────────────────────────────────────────────────

def _mvv_lva_score(board, move):
    """Most-Valuable-Victim / Least-Valuable-Attacker heuristic for captures."""
    victim_type = board.piece_type_at(move.to_square)
    attacker_type = board.piece_type_at(move.from_square)
    if victim_type and attacker_type:
        return _MATERIAL[victim_type] - _MATERIAL[attacker_type]
    return 0


def _order_moves(board, moves, killers, tt_move, history):
    """Order moves using TT best move, captures, killers, then history."""
    tt_list     = []
    captures    = []
    killer_list = []
    quiet       = []
    for move in moves:
        if tt_move and move == tt_move:
            tt_list.append(move)
            continue
        if board.is_capture(move):
            captures.append((move, _mvv_lva_score(board, move)))
            continue
        if move in killers:
            killer_list.append(move)
            continue
        quiet.append((move, history.get(move.uci(), 0)))
    captures.sort(key=lambda x: x[1], reverse=True)
    quiet.sort(key=lambda x: x[1], reverse=True)
    return tt_list + [m for m, _ in captures] + killer_list + [m for m, _ in quiet]


# ── Quiescence search ─────────────────────────────────────────────────────────

def _quiesce(board, alpha, beta, maximising, bot_color, abort=None):
    """
    Capture-only search past depth 0 to avoid the horizon effect.
    Stand-pat score acts as a lower bound — the side to move can always
    choose not to capture.
    """
    if abort is not None and abort.is_set():
        raise SearchAborted()

    if board.is_game_over():
        outcome = board.outcome()
        if outcome is None or outcome.winner is None:
            return 0
        return INF if outcome.winner == bot_color else -INF

    stand_pat = _evaluate(board, bot_color)
    if maximising:
        if stand_pat >= beta:
            return beta
        alpha = max(alpha, stand_pat)
        for move in board.generate_legal_captures():
            board.push(move)
            score = _quiesce(board, alpha, beta, False, bot_color, abort)
            board.pop()
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        return alpha
    else:
        if stand_pat <= alpha:
            return alpha
        beta = min(beta, stand_pat)
        for move in board.generate_legal_captures():
            board.push(move)
            score = _quiesce(board, alpha, beta, True, bot_color, abort)
            board.pop()
            beta = min(beta, score)
            if beta <= alpha:
                break
        return beta


# ── Alpha-beta with TT + killers ──────────────────────────────────────────────

def _alphabeta(board, depth, alpha, beta, maximising, bot_color,
               killers, tt, history, root=False, abort=None):
    """Recursive alpha-beta search with TT, killers, history, null-move, and quiescence."""
    if abort is not None and abort.is_set():
        raise SearchAborted()

    orig_alpha = alpha

    # ── TT lookup ─────────────────────────────────────────────────────────────
    key      = board._transposition_key()
    tt_move  = None
    tt_entry = tt.get(key)
    if tt_entry is not None:
        e_depth, e_score, e_flag, e_move = tt_entry
        tt_move = e_move
        if e_depth >= depth:
            if e_flag == _EXACT:
                return e_score, e_move
            elif e_flag == _LOWERBOUND:
                alpha = max(alpha, e_score)
            elif e_flag == _UPPERBOUND:
                beta = min(beta, e_score)
            if alpha >= beta:
                return e_score, e_move

    # ── Terminal checks ────────────────────────────────────────────────────────
    if board.is_game_over():
        outcome = board.outcome()
        if outcome is None or outcome.winner is None:
            return 0, None
        return (INF if outcome.winner == bot_color else -INF), None

    if depth == 0:
        return _quiesce(board, alpha, beta, maximising, bot_color, abort), None

    # ── Null-move pruning ────────────────────────────────────────────────────
    # Idea: give the side to move a free "pass" and search at a reduced depth
    # with a null window just outside beta/alpha. If even doing nothing is
    # too good for the opponent to tolerate (maximiser) — or too bad for them
    # to allow (minimiser) — the real move at this node is assumed to also
    # cause a cutoff, so the whole subtree is pruned without expanding it.
    #
    # Not applied at the root (root=True relies on every move being scored),
    # never while in check (a "pass" while in check isn't a legal position to
    # reason about), and never when material is too thin (see
    # _non_pawn_material) since zugzwang positions are exactly where passing
    # is illegally optimistic and the heuristic would prune a winning move.
    if (
        not root
        and depth >= _NULL_MOVE_MIN_DEPTH
        and not board.is_check()
        and _non_pawn_material(board, board.turn) >= _NULL_MOVE_MATERIAL_FLOOR
    ):
        board.push(chess.Move.null())
        if maximising:
            null_score, _ = _alphabeta(
                board, depth - 3, beta - 1, beta,
                False, bot_color, killers, tt, history, abort=abort
            )
            board.pop()
            if null_score >= beta:
                return beta, None
        else:
            null_score, _ = _alphabeta(
                board, depth - 3, alpha, alpha + 1,
                True, bot_color, killers, tt, history, abort=abort
            )
            board.pop()
            if null_score <= alpha:
                return alpha, None

    # ── Move generation + ordering ────────────────────────────────────────────
    depth_killers = killers[depth] if depth < len(killers) else []
    moves = _order_moves(board, list(board.legal_moves), depth_killers, tt_move, history)
    if not moves:
        return 0, None

    best_score = -INF if maximising else INF
    best_move  = None

    for move_index, move in enumerate(moves):
        capture_move = board.is_capture(move)
        board.push(move)
        if move_index == 0:
            score, _ = _alphabeta(
                board, depth - 1, alpha, beta,
                not maximising, bot_color, killers, tt, history, abort=abort
            )
        else:
            if maximising:
                score, _ = _alphabeta(
                    board, depth - 1, alpha, min(beta, alpha + 1),
                    not maximising, bot_color, killers, tt, history, abort=abort
                )
                if score > alpha and score < beta:
                    score, _ = _alphabeta(
                        board, depth - 1, score, beta,
                        not maximising, bot_color, killers, tt, history, abort=abort
                    )
            else:
                score, _ = _alphabeta(
                    board, depth - 1, max(alpha, beta - 1), beta,
                    not maximising, bot_color, killers, tt, history, abort=abort
                )
                if score > alpha and score < beta:
                    score, _ = _alphabeta(
                        board, depth - 1, alpha, score,
                        not maximising, bot_color, killers, tt, history, abort=abort
                    )
        board.pop()

        if maximising:
            if score > best_score:
                best_score, best_move = score, move
            alpha = max(alpha, best_score)
        else:
            if score < best_score:
                best_score, best_move = score, move
            beta = min(beta, best_score)

        if beta <= alpha:
            # Update killers (quiet moves only; captures are MVV-LVA ordered)
            if depth < len(killers) and not capture_move:
                k = killers[depth]
                if move != k[0]:
                    k[1] = k[0]
                    k[0] = move
                history[move.uci()] = history.get(move.uci(), 0) + depth * depth
            break

    # ── TT store ──────────────────────────────────────────────────────────────
    if len(tt) < _MAX_TT_SIZE:
        if best_score <= orig_alpha:
            flag = _UPPERBOUND
        elif best_score >= beta:
            flag = _LOWERBOUND
        else:
            flag = _EXACT
        tt[key] = (depth, best_score, flag, best_move)

    return best_score, best_move


# ── Root ranking (no inter-sibling pruning) ───────────────────────────────────

def _rank_all_moves(board, depth, bot_color, killers, tt, history, abort=None):
    """Rank all root moves independently for top-N scoring."""
    scored = []
    key = board._transposition_key()
    tt_entry = tt.get(key)
    tt_move = tt_entry[3] if tt_entry is not None else None
    moves = _order_moves(
        board, list(board.legal_moves),
        killers[depth] if depth < len(killers) else [],
        tt_move, history,
    )

    for move in moves:
        if abort is not None and abort.is_set():
            raise SearchAborted()
        board.push(move)
        score, _ = _alphabeta(
            board, depth - 1, -INF, INF,
            False, bot_color, killers, tt, history, abort=abort
        )
        board.pop()
        scored.append((score, move))

    # Highest score = best from bot's perspective
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


# ── Opening book helper ───────────────────────────────────────────────────────

def _weighted_book_choice(entries):
    """
    Pick one entry from a list of polyglot entries using weight-proportional
    random selection.  Falls back to uniform if all weights are zero.
    """
    total = sum(e.weight for e in entries)
    if total == 0:
        return random.choice(entries)
    roll = random.uniform(0, total)
    cumulative = 0
    for entry in entries:
        cumulative += entry.weight
        if roll < cumulative:
            return entry
    return entries[-1]


# ── Public bot class ──────────────────────────────────────────────────────────

class ChessBot:
    """Chess engine with opening book support and difficulty-based search."""

    def __init__(self, max_depth: int = 3, book_path: str | None = None):
        self.max_depth = max_depth
        self._tt: dict[tuple, tuple[int, int, int, chess.Move | None]] = {}   # transposition table; persists across moves in a game
        # History heuristic table: quiet-move UCI -> cutoff score. Lives on
        # the instance (not a module global) so it never leaks between
        # separate ChessBot instances or across games — see clear_tt().
        self._history: dict[str, int] = {}

        # ── Opening book setup ────────────────────────────────────────────────
        # book_path must be supplied by the caller (e.g. via resource_path in
        # main.py).  If None or the file is absent the bot skips book play.
        self._book_path = book_path
        self._book_active = False   # True once successfully opened
        self._book_in_use = True    # False once the position leaves the book
        self._book_reader = None    # MemoryMappedReader, kept open for the game

        self._open_book()

    # ── Book lifecycle ────────────────────────────────────────────────────────

    def _open_book(self):
        """Try to open the Polyglot book file.  Silently no-ops if None or missing."""
        if not self._book_path or not os.path.isfile(self._book_path):
            if self._book_path:
                _LOGGER.warning('Book not found: %s (will use engine only)', self._book_path)
            self._book_active = False
            self._book_in_use = False
            return
        try:
            self._book_reader = chess.polyglot.open_reader(self._book_path)
            self._book_active = True
            self._book_in_use = True
            _LOGGER.info('Book loaded: %s', self._book_path)
        except OSError:
            _LOGGER.exception('Failed to open book: %s', self._book_path)
            self._book_active = False
            self._book_in_use = False

    def _reset_book(self):
        """Reset the opening book reader for a new game."""
        if self._book_reader is not None:
            try:
                self._book_reader.close()
            except OSError:
                _LOGGER.exception('Failed to close book reader')
            self._book_reader = None
        self._book_active = False
        self._book_in_use = False
        self._open_book()

    def _query_book(self, board):
        """
        Query the book for the current position.

        Returns a chess.Move chosen by weighted random selection, or None if:
          - the book is not active / exhausted, or
          - no entries exist for this position (book phase ends here).
        """
        if not self._book_active or not self._book_in_use:
            return None

        try:
            entries = list(self._book_reader.find_all(board))
        except OSError:
            _LOGGER.exception('Book read error')
            self._book_in_use = False
            return None

        if not entries:
            # Human deviated beyond all book lines — exit book phase
            self._book_in_use = False
            _LOGGER.debug('No book entries for this position — exiting book phase')
            return None

        chosen = _weighted_book_choice(entries)
        move   = chosen.move

        # Normalise promotion piece (polyglot sometimes omits it for queens)
        if move.promotion is None and board.piece_type_at(move.from_square) == chess.PAWN:
            dest_rank = chess.square_rank(move.to_square)
            if dest_rank in (0, 7):
                move = chess.Move(move.from_square, move.to_square,
                                  promotion=chess.QUEEN)

        # Sanity-check: the book move must be legal in this position
        if move not in board.legal_moves:
            _LOGGER.warning('Illegal book move %s — exiting book phase', move.uci())
            self._book_in_use = False
            return None

        _LOGGER.debug('Playing book move: %s (weight %s, %d candidate(s))',
                       move.uci(), chosen.weight, len(entries))
        return move

    # ── Public interface ──────────────────────────────────────────────────────

    def clear_tt(self):
        """
        Clear the transposition table and history heuristic, and reset the
        opening book, for a new game. Call at the start of every new game.

        Clearing _history here (alongside _tt) is what fixes the cross-game
        move-ordering leak: without it, quiet-move scores from a finished
        game would keep influencing ordering decisions in the next one.
        """
        self._tt.clear()
        self._history.clear()
        self._reset_book()

    def get_move(self, board, color, difficulty_level: int = 10, abort=None,
                 min_think_time_s: float = 1.0):
        """
        Return the selected move for *color* given the unified difficulty level.
        Guaranteed to take at least min_think_time_s seconds before returning
        (default 1.0s, matched to human-vs-bot play so a move never appears
        to snap in instantly), unless the search is aborted first.

        Callers that don't need this pacing at all — headless batch play,
        or two engines playing each other with nobody watching a human
        pace their own moves against it — can pass min_think_time_s=0.0 to
        return as soon as the search itself finishes, with no artificial
        floor. See Game.launch_engine_match_move for exactly this case.

        Parameters
        ----------
        abort : threading.Event, optional
            If set at any point during the search, raises SearchAborted so
            the caller (BotWorker) can drop the in-flight computation
            instead of blocking on a stale move.
        """
        start_time = time.time()

        cfg          = DIFFICULTY_CONFIG.get(difficulty_level, DIFFICULTY_CONFIG[10])
        depth        = cfg['depth']
        blunder_prob = cfg['blunder_prob']

        self.max_depth = int(depth)

        _LOGGER.debug(
            'Level %s | depth %s | blunder %.0f%% | TT: %d entries',
            difficulty_level, depth, blunder_prob * 100, len(self._tt)
        )

        def _determine_move():
            if abort is not None and abort.is_set():
                raise SearchAborted()

            book_move = self._query_book(board)
            if book_move is not None:
                return book_move

            if abort is not None and abort.is_set():
                raise SearchAborted()

            mate_move = self._find_immediate_checkmate(board)
            if mate_move:
                bm = (f'{chess.square_name(mate_move.from_square)}'
                      f' -> {chess.square_name(mate_move.to_square)}')
                _LOGGER.debug('Checkmate override! Playing %s', bm)
                return mate_move

            top_moves = self._search_top_n(board, color, depth, n=5, abort=abort)

            if not top_moves:
                fallback = list(board.legal_moves)
                return fallback[0] if fallback else None

            best_move = top_moves[0][1]

            if blunder_prob == 0.0 or random.random() >= blunder_prob:
                bm = (f'{chess.square_name(best_move.from_square)}'
                      f' -> {chess.square_name(best_move.to_square)}')
                _LOGGER.debug('Best move: %s (score %s)', bm, top_moves[0][0])
                return best_move

            pool = top_moves[1:]
            if not pool:
                return best_move

            selected = self._weighted_blunder_select(pool)
            bm = (f'{chess.square_name(selected.from_square)}'
                  f' -> {chess.square_name(selected.to_square)}')
            rank = next(i + 2 for i, (_, m) in enumerate(pool) if m == selected)
            _LOGGER.debug('Blunder! Playing rank-%d move: %s', rank, bm)
            return selected

        final_move = _determine_move()

        elapsed = time.time() - start_time
        remaining = min_think_time_s - elapsed
        if remaining > 0:
            if abort is not None:
                abort.wait(remaining)
            else:
                time.sleep(remaining)

        return final_move

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_immediate_checkmate(self, board):
        """Return an immediate mate move if one exists; otherwise None."""
        for move in board.legal_moves:
            if not board.gives_check(move):
                continue
            board.push(move)
            is_mate = board.is_checkmate()
            board.pop()
            if is_mate:
                return move
        return None

    def _search_top_n(self, board, color, depth, n=5, abort=None):
        """Iterative deepening plus full root move ranking for top-N choices."""
        bot_color = chess.WHITE if color == 'white' else chess.BLACK
        killers   = [[None, None] for _ in range(depth + 1)]

        # Warm the transposition table with shallower passes
        for d in range(1, depth):
            _alphabeta(
                board, d, -INF, INF,
                True, bot_color, killers, self._tt, self._history, root=True, abort=abort
            )

        # Final full-depth ranking (all root moves scored without inter-sibling pruning)
        ranked = _rank_all_moves(board, depth, bot_color, killers, self._tt, self._history, abort=abort)
        return ranked[:n]

    def _weighted_blunder_select(self, pool):
        """Choose a lower-ranked move from the blunder candidate pool."""
        n              = len(pool)
        active_weights = _BLUNDER_WEIGHTS[:n]   # trim to available moves
        total          = sum(active_weights)
        roll           = random.uniform(0.0, total)

        cumulative = 0.0
        for i, weight in enumerate(active_weights):
            cumulative += weight
            if roll < cumulative:
                return pool[i][1]

        # Floating-point safety fallback: return the last available option
        return pool[-1][1]
