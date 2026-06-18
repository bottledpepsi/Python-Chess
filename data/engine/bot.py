"""
ChessBot — difficulty-aware move selector with probabilistic blunder injection
           and GM-level Polyglot opening book support.

Architecture overview
---------------------
The public entry point is a single method:

    move = bot.get_move(board, color, difficulty_level)   # difficulty_level: 1–10

Internally this orchestrates four distinct stages:

  Stage 0 – Opening book lookup (gm2001.bin)
      On every bot turn while the book is active, query the Polyglot opening
      book for all entries matching the current board position.  If any entries
      exist, one is chosen at random (weighted by the entry's weight field) and
      returned immediately — bypassing all minimax logic.

      Tracking the chosen line
      ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
      At game start the bot picks ONE random opening line from all root
      entries.  It tries to follow that line move-by-move.  If the human
      deviates, the bot searches the book for any entries that still match
      the current position (regardless of which line they come from) and
      picks randomly among those.  Once the current position has NO book
      entries at all, the book phase ends for the rest of the game.

  Stage 1 – Checkmate override
      Before any probability rolls, scan every root legal move for an
      immediate checkmate.  If one exists it is returned unconditionally,
      bypassing all difficulty logic.  Even a Level-1 bot never misses
      a forced win.

  Stage 2 – Alpha-beta search for top-N candidates
      Run the alpha-beta engine (with TT, killers, quiescence) at the
      depth prescribed by DIFFICULTY_CONFIG[level].  Every root move is
      evaluated independently so the ranking is never distorted by
      cross-sibling pruning.  The top-5 scoring moves are retained.

  Stage 3 – Blunder injection
      Roll a random float against the level's blunder_prob.  On a clean
      roll (or Level 10, which has 0% blunder), return the best move.
      On a blunder roll, pick a runner-up from the retained pool using
      the weighted distribution specified below.

Unified difficulty configuration
---------------------------------
Level  Search depth   Blunder prob
  1       1 ply           80 %
  2       1 ply           70 %
  3       2 ply           60 %
  4       2 ply           50 %
  5       3 ply           40 %
  6       3 ply           30 %
  7       4 ply           20 %
  8       4 ply           10 %
  9       5 ply            5 %
 10       6 ply            0 %   ← always plays best move

Blunder pool weights (runner-up selection)
-------------------------------------------
  50 %  →  2nd-best move  (minor positional slip)
  30 %  →  3rd-best move  (noticeable tactical mistake)
  15 %  →  4th-best move  (clear tactical blunder)
   5 %  →  5th-best move  (severe oversight / hanging piece)

Pool is bounds-checked: if fewer than N candidates exist the weights
are sliced and re-normalised automatically.
"""

import os
import random
import time
import chess
import chess.polyglot
from data.engine.piece_tables import PIECE_DATA as _RAW

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

_HISTORY = {}


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
    """Material + positional score from bot_color's perspective."""
    score = 0
    pt_map = _PT_MAP
    pst_index = _PST_INDEX
    for sq, piece in board.piece_map().items():
        material, pst = pt_map[piece.piece_type]
        positional = pst[pst_index[piece.color][sq]]
        val = material + positional
        score += val if piece.color == bot_color else -val
    return score


# ── Move ordering ─────────────────────────────────────────────────────────────

def _mvv_lva_score(board, move):
    """Most-Valuable-Victim / Least-Valuable-Attacker heuristic for captures."""
    victim_type = board.piece_type_at(move.to_square)
    attacker_type = board.piece_type_at(move.from_square)
    if victim_type and attacker_type:
        return _MATERIAL[victim_type] - _MATERIAL[attacker_type]
    return 0


def _order_moves(board, moves, killers, tt_move):
    """
    Priority ordering: TT best move → captures (MVV-LVA) → killers → quiet.
    Better ordering means more early cutoffs → faster search.
    """
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
        quiet.append((move, _HISTORY.get(move.uci(), 0)))
    captures.sort(key=lambda x: x[1], reverse=True)
    quiet.sort(key=lambda x: x[1], reverse=True)
    return tt_list + [m for m, _ in captures] + killer_list + [m for m, _ in quiet]


# ── Quiescence search ─────────────────────────────────────────────────────────

def _quiesce(board, alpha, beta, maximising, bot_color):
    """
    Capture-only search past depth 0 to avoid the horizon effect.
    Stand-pat score acts as a lower bound — the side to move can always
    choose not to capture.
    """
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
            score = _quiesce(board, alpha, beta, False, bot_color)
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
            score = _quiesce(board, alpha, beta, True, bot_color)
            board.pop()
            beta = min(beta, score)
            if beta <= alpha:
                break
        return beta


# ── Alpha-beta with TT + killers ──────────────────────────────────────────────

def _alphabeta(board, depth, alpha, beta, maximising, bot_color,
               killers, tt, root=False):
    """
    Recursive alpha-beta with:
      - Transposition table (exact / lower / upper bound entries)
      - Killer move heuristic (two slots per depth)
      - Quiescence search at leaf nodes
    """
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
        return _quiesce(board, alpha, beta, maximising, bot_color), None

    # ── Move generation + ordering ────────────────────────────────────────────
    depth_killers = killers[depth] if depth < len(killers) else []
    moves = _order_moves(board, list(board.legal_moves), depth_killers, tt_move)
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
                not maximising, bot_color, killers, tt
            )
        else:
            if maximising:
                score, _ = _alphabeta(
                    board, depth - 1, alpha, min(beta, alpha + 1),
                    not maximising, bot_color, killers, tt
                )
                if score > alpha and score < beta:
                    score, _ = _alphabeta(
                        board, depth - 1, score, beta,
                        not maximising, bot_color, killers, tt
                    )
            else:
                score, _ = _alphabeta(
                    board, depth - 1, max(alpha, beta - 1), beta,
                    not maximising, bot_color, killers, tt
                )
                if score > alpha and score < beta:
                    score, _ = _alphabeta(
                        board, depth - 1, alpha, score,
                        not maximising, bot_color, killers, tt
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
                _HISTORY[move.uci()] = _HISTORY.get(move.uci(), 0) + depth * depth
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

def _rank_all_moves(board, depth, bot_color, killers, tt):
    """
    Score every legal root move at `depth`.

    Alpha-beta is applied WITHIN each subtree for efficiency, but NOT
    between sibling root moves.  This ensures every root move gets an
    accurate independent score — essential for a reliable top-N ranking.

    Returns a list of (score, move) sorted best → worst from bot_color's view.
    """
    scored = []
    key = board._transposition_key()
    tt_entry = tt.get(key)
    tt_move = tt_entry[3] if tt_entry is not None else None
    moves = _order_moves(
        board, list(board.legal_moves),
        killers[depth] if depth < len(killers) else [],
        tt_move,
    )

    for move in moves:
        board.push(move)
        score, _ = _alphabeta(
            board, depth - 1, -INF, INF,
            False, bot_color, killers, tt
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
    """
    Chess engine with unified 1–10 difficulty control and Polyglot opening
    book support (gm2001.bin).

    Opening book behaviour
    ----------------------
    - On the first bot move the book is queried for the start position.
      All available entries are candidates; one is chosen by weighted random
      selection (proportional to the entry's weight field).
    - On subsequent bot moves, the current board position is looked up.
      If entries exist, one is chosen randomly from those entries.
    - As soon as the current position has no book entries (because the human
      played an unexpected move and no continuations remain), the book phase
      ends permanently for this game.
    - clear_tt() / new-game resets the book state so the next game picks a
      fresh line.

    Public API
    ----------
    bot = ChessBot()
    move = bot.get_move(board, color, difficulty_level)
    bot.clear_tt()
    """

    def __init__(self, max_depth: int = 3, book_path: str = None):
        self.max_depth = max_depth
        self._tt = {}   # transposition table; persists across moves in a game

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
                print(f'[Book] Not found: {self._book_path}  (will use engine only)')
            self._book_active = False
            self._book_in_use = False
            return
        try:
            self._book_reader = chess.polyglot.open_reader(self._book_path)
            self._book_active = True
            self._book_in_use = True
            print(f'[Book] Loaded: {self._book_path}')
        except Exception as exc:
            print(f'[Book] Failed to open {self._book_path}: {exc}')
            self._book_active = False
            self._book_in_use = False

    def _reset_book(self):
        """
        Called at game start (clear_tt).  Closes and re-opens the reader so
        each new game starts fresh with a new random line selection.
        """
        if self._book_reader is not None:
            try:
                self._book_reader.close()
            except Exception:
                pass
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
        except Exception as exc:
            print(f'[Book] Read error: {exc}')
            self._book_in_use = False
            return None

        if not entries:
            # Human deviated beyond all book lines — exit book phase
            self._book_in_use = False
            print('[Book] No entries for this position — exiting book phase')
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
            print(f'[Book] Illegal book move {move.uci()} — exiting book phase')
            self._book_in_use = False
            return None

        print(f'[Book] Playing book move: {move.uci()}  '
              f'(weight {chosen.weight}, {len(entries)} candidate(s))')
        return move

    # ── Public interface ──────────────────────────────────────────────────────

    def clear_tt(self):
        """
        Clear the transposition table and reset the opening book for a new game.
        Call at the start of every new game.
        """
        self._tt.clear()
        self._reset_book()

    def get_move(self, board, color, difficulty_level: int = 10):
        """
        Return the selected move for *color* given the unified difficulty level.
        Guaranteed to take at least 1.0 second before returning.
        """
        start_time = time.time()  # <--- Record start time

        cfg          = DIFFICULTY_CONFIG.get(difficulty_level, DIFFICULTY_CONFIG[10])
        depth        = cfg['depth']
        blunder_prob = cfg['blunder_prob']

        # Update max_depth so it reflects the active configuration
        self.max_depth = depth

        print(
            f'[Bot] Level {difficulty_level} | depth {depth} | '
            f'blunder {blunder_prob:.0%} | TT: {len(self._tt)} entries'
        )

        # Helper internal function to handle the original pipeline return logic
        def _determine_move():
            # ── Stage 0: Opening book ─────────────────────────────────────────
            book_move = self._query_book(board)
            if book_move is not None:
                return book_move

            # ── Stage 1: Checkmate override ───────────────────────────────────
            mate_move = self._find_immediate_checkmate(board)
            if mate_move:
                bm = (f'{chess.square_name(mate_move.from_square)}'
                      f' -> {chess.square_name(mate_move.to_square)}')
                print(f'[Bot] ★ Checkmate override! Playing {bm}')
                return mate_move

            # ── Stage 2: Search for top-5 candidates ───────────────────────────
            top_moves = self._search_top_n(board, color, depth, n=5)

            if not top_moves:
                fallback = list(board.legal_moves)
                return fallback[0] if fallback else None

            best_move = top_moves[0][1]

            # ── Stage 3: Blunder injection ────────────────────────────────────
            if blunder_prob == 0.0 or random.random() >= blunder_prob:
                bm = (f'{chess.square_name(best_move.from_square)}'
                      f' -> {chess.square_name(best_move.to_square)}')
                print(f'[Bot] → Best move: {bm}  (score {top_moves[0][0]})')
                return best_move

            pool = top_moves[1:]   
            if not pool:
                return best_move

            selected = self._weighted_blunder_select(pool)
            bm = (f'{chess.square_name(selected.from_square)}'
                  f' -> {chess.square_name(selected.to_square)}')
            rank = next(i + 2 for i, (_, m) in enumerate(pool) if m == selected)
            print(f'[Bot] ↯ Blunder! Playing rank-{rank} move: {bm}')
            return selected

        # Get the chosen move from the pipeline
        final_move = _determine_move()

        # ── Enforce minimum 1-second delay ────────────────────────────────────
        elapsed = time.time() - start_time
        remaining = 1.0 - elapsed
        if remaining > 0:
            time.sleep(remaining)

        return final_move

    # ── Private helpers ───────────────────────────────────────────────────────

    def _find_immediate_checkmate(self, board):
        """
        Scan every root legal move for an immediate checkmate.

        This is a shallow O(n) sweep — no deep search required.
        Returns the checkmate move if found, otherwise None.

        Note: this fires before any blunder logic, so even the weakest bot
        will always accept a forced win when it's on the board.
        """
        for move in board.legal_moves:
            if not board.gives_check(move):
                continue
            board.push(move)
            is_mate = board.is_checkmate()
            board.pop()
            if is_mate:
                return move
        return None

    def _search_top_n(self, board, color, depth, n=5):
        """
        Run iterative-deepening alpha-beta and return the top `n` root moves.

        Iterative deepening warms the TT so deeper passes benefit from
        previously computed best-move hints (TT-guided ordering).  At the
        final depth every root move is scored independently (no cross-sibling
        pruning) to guarantee accurate rankings.

        Returns
        -------
        list of (score, chess.Move), length ≤ n, sorted best → worst
        """
        bot_color = chess.WHITE if color == 'white' else chess.BLACK
        killers   = [[None, None] for _ in range(depth + 1)]

        # Warm the transposition table with shallower passes
        for d in range(1, depth):
            _alphabeta(
                board, d, -INF, INF,
                True, bot_color, killers, self._tt, root=True
            )

        # Final full-depth ranking (all root moves scored without inter-sibling pruning)
        ranked = _rank_all_moves(board, depth, bot_color, killers, self._tt)
        return ranked[:n]

    def _weighted_blunder_select(self, pool):
        """
        Choose a move from the blunder candidate pool using weighted probabilities.

        Nominal distribution (when pool has 4 entries):
          50 % → 2nd-best  (pool index 0) — minor positional slip
          30 % → 3rd-best  (pool index 1) — noticeable tactical mistake
          15 % → 4th-best  (pool index 2) — clear tactical blunder
           5 % → 5th-best  (pool index 3) — severe oversight / hanging piece

        Graceful degradation: if the pool has fewer than 4 entries the
        weight list is trimmed to match and the roll is re-normalised
        automatically.  No IndexError can occur.

        Parameters
        ----------
        pool : list of (score, chess.Move)  — runner-up moves, best first

        Returns
        -------
        chess.Move
        """
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
