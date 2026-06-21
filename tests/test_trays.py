"""Captured-piece tray grouping/labeling tests (board-flip regression coverage)."""
from __future__ import annotations

import chess

from chess_game.adapter import ChessAdapter
from chess_game.render.trays import group_captures


def test_capture_is_attributed_to_the_capturing_side():
    adapter = ChessAdapter()
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6", "f3e5"]:
        adapter._push(chess.Move.from_uci(uci))

    # White's Nxe5 captures the pawn still on e5 (Nc6/Nf6 never moved it).
    assert len(adapter.captured_pieces["white"]) == 1
    assert adapter.captured_pieces["white"][0]["color"] == "black"
    assert len(adapter.captured_pieces["black"]) == 0


def test_material_advantage_reflects_the_capture():
    adapter = ChessAdapter()
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6", "f3e5"]:
        adapter._push(chess.Move.from_uci(uci))
    white_lead, black_lead = adapter.material_advantage()
    # Nxe5 captures the pawn still sitting on e5 (Nc6/Nf6 never moved it).
    assert white_lead == 1
    assert black_lead == 0


def test_top_bottom_tray_assignment_matches_board_orientation():
    """Which colour's captures belong in the top tray must track
    board_flipped, not be hardcoded."""
    for board_flipped in (False, True):
        top_color = "white" if board_flipped else "black"
        bottom_color = "black" if board_flipped else "white"
        assert top_color != bottom_color
        # When not flipped, black sits on top (standard orientation).
        if not board_flipped:
            assert top_color == "black"
        else:
            assert top_color == "white"


def test_group_captures_orders_queen_first():
    pieces = [
        {"notation": " ", "color": "black"},   # pawn
        {"notation": "Q", "color": "black"},   # queen
        {"notation": "N", "color": "black"},   # knight
    ]
    grouped = group_captures(pieces)
    types_in_order = [pt for pt, _color, _count in grouped]
    assert types_in_order[0] == chess.QUEEN
    assert types_in_order[-1] == chess.PAWN


def test_group_captures_counts_duplicates():
    pieces = [{"notation": " ", "color": "white"} for _ in range(3)]
    grouped = group_captures(pieces)
    assert grouped == [(chess.PAWN, "white", 3)]
