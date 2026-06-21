"""
ChessAdapter
============
Thin wrapper around a chess.Board that exposes only what main.py needs.

v3 additions
------------
  - san_history: list of SAN strings for every move pushed, used by the
    move-history panel and save/load system.
"""

import chess

# Map chess piece type → old notation char (kept for tray-display compatibility)
_NOTATION = {
    chess.PAWN:   ' ',
    chess.KNIGHT: 'N',
    chess.BISHOP: 'B',
    chess.ROOK:   'R',
    chess.QUEEN:  'Q',
    chess.KING:   'K',
}


class ChessAdapter:

    def __init__(self):
        self.board              = chess.Board()
        self.selected_square    = None
        self._valid_targets     = set()
        self.last_move          = None
        self.anim_from          = None
        self.anim_to            = None
        self.promotion_pending  = None
        self.captured_pieces    = {'white': [], 'black': []}
        self.san_history        = []   # SAN string for every pushed move

    # ── Read-only properties ──────────────────────────────────────────────────

    @property
    def turn(self):
        return 'white' if self.board.turn == chess.WHITE else 'black'

    @property
    def check_square(self):
        if self.board.is_check():
            return self.board.king(self.board.turn)
        return None

    @property
    def is_game_over(self):
        return self.board.is_game_over(claim_draw=True)

    @property
    def game_result_text(self):
        if not self.is_game_over:
            return None
        outcome = self.board.outcome(claim_draw=True)
        if outcome is None:
            return None

        _TERMINATION_LABEL = {
            chess.Termination.CHECKMATE:             'by Checkmate',
            chess.Termination.STALEMATE:             'by Stalemate',
            chess.Termination.INSUFFICIENT_MATERIAL: 'Insufficient Material',
            chess.Termination.SEVENTYFIVE_MOVES:     '75-Move Rule',
            chess.Termination.FIVEFOLD_REPETITION:   'Fivefold Repetition',
            chess.Termination.FIFTY_MOVES:           '50-Move Rule',
            chess.Termination.THREEFOLD_REPETITION:  'Threefold Repetition',
        }
        subtitle = _TERMINATION_LABEL.get(outcome.termination, '')

        if outcome.winner == chess.WHITE:
            return ('White Wins!', subtitle)
        if outcome.winner == chess.BLACK:
            return ('Black Wins!', subtitle)
        return ('Draw', subtitle)

    # ── Material helpers ──────────────────────────────────────────────────────

    _PIECE_POINTS = {
        chess.PAWN:   1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK:   5,
        chess.QUEEN:  9,
    }

    _NOTATION_TO_PT = {
        ' ': chess.PAWN,   'N': chess.KNIGHT, 'B': chess.BISHOP,
        'R': chess.ROOK,   'Q': chess.QUEEN,  'K': chess.KING,
    }

    def material_advantage(self):
        white_pts = sum(
            self._PIECE_POINTS.get(self._NOTATION_TO_PT.get(p['notation']), 0)
            for p in self.captured_pieces['white']
        )
        black_pts = sum(
            self._PIECE_POINTS.get(self._NOTATION_TO_PT.get(p['notation']), 0)
            for p in self.captured_pieces['black']
        )
        diff = white_pts - black_pts
        return (max(0, diff), max(0, -diff))

    @property
    def valid_move_targets(self):
        return self._valid_targets

    # ── Click handling ────────────────────────────────────────────────────────

    def handle_click(self, sq):
        piece = self.board.piece_at(sq)

        if self.selected_square is None:
            if piece and piece.color == self.board.turn:
                self._select(sq)
                return 'selected'
            return None

        if sq in self._valid_targets:
            if self._needs_promotion(self.selected_square, sq):
                self.promotion_pending = chess.Move(self.selected_square, sq)
                self.anim_from         = self.selected_square
                self.anim_to           = sq
                self.selected_square   = None
                self._valid_targets    = set()
                return 'promotion'
            move = chess.Move(self.selected_square, sq)
            return self._push(move)

        elif piece and piece.color == self.board.turn:
            self._select(sq)
            return 'selected'
        else:
            self.selected_square = None
            self._valid_targets  = set()
            return 'deselected'

    def complete_promotion(self, piece_type):
        move = chess.Move(
            self.promotion_pending.from_square,
            self.promotion_pending.to_square,
            promotion=piece_type,
        )
        result = self._push(move)
        self.promotion_pending = None
        return result

    def apply_move(self, move):
        return self._push(move)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _select(self, sq):
        self.selected_square = sq
        self._valid_targets  = {
            m.to_square
            for m in self.board.legal_moves
            if m.from_square == sq
        }

    def _needs_promotion(self, from_sq, to_sq):
        piece = self.board.piece_at(from_sq)
        if piece is None or piece.piece_type != chess.PAWN:
            return False
        to_rank = chess.square_rank(to_sq)
        return to_rank == 7 if piece.color == chess.WHITE else to_rank == 0

    def _push(self, move):
        """Track capture, record SAN, set anim hints, push move, clear selection."""
        is_capture = self.board.is_capture(move)
        is_ep      = self.board.is_en_passant(move)
        capturer   = 'white' if self.board.turn == chess.WHITE else 'black'

        if is_capture:
            cap = (chess.Piece(chess.PAWN, not self.board.turn)
                   if is_ep else self.board.piece_at(move.to_square))
            if cap:
                self.captured_pieces[capturer].append({
                    'notation': _NOTATION.get(cap.piece_type, '?'),
                    'color':    'white' if cap.color == chess.WHITE else 'black',
                })

        # Record SAN *before* pushing (board must be in pre-move state)
        san = self.board.san(move)

        self.anim_from       = move.from_square
        self.anim_to         = move.to_square
        self.last_move       = move
        self.board.push(move)
        self.san_history.append(san)
        self.selected_square = None
        self._valid_targets  = set()

        if is_ep:
            return 'en_passant'
        return 'capture' if is_capture else 'move'
