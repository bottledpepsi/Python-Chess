"""Pure coordinate-math tests."""
from __future__ import annotations

import chess

from chess_game.layout import (
    arrow_path,
    build_review_board,
    pixel_to_sq,
    sq_to_board,
    sq_to_screen,
)
from chess_game.theme import BOARD_X, BOARD_Y


def test_sq_to_board_pixel_to_sq_roundtrip_unflipped():
    for sq in chess.SQUARES:
        bx, by = sq_to_board(sq, False)
        assert pixel_to_sq(bx, by, False) == sq


def test_sq_to_board_pixel_to_sq_roundtrip_flipped():
    for sq in chess.SQUARES:
        bx, by = sq_to_board(sq, True)
        assert pixel_to_sq(bx, by, True) == sq


def test_sq_to_screen_includes_board_offset():
    bx, by = sq_to_board(chess.E4, False)
    sx, sy = sq_to_screen(chess.E4, False)
    assert sx == bx + BOARD_X
    assert sy == by + BOARD_Y


def test_arrow_path_straight_move_is_two_points():
    path = arrow_path(chess.E2, chess.E4, False)
    assert len(path) == 2


def test_arrow_path_knight_move_has_elbow():
    path = arrow_path(chess.B1, chess.C3, False)
    assert len(path) == 3


def test_build_review_board_applies_exact_ply_count():
    moves = [chess.Move.from_uci(m) for m in ["e2e4", "e7e5", "g1f3", "b8c6"]]
    board = build_review_board(moves, 2)
    assert len(board.move_stack) == 2
    assert board.move_stack == moves[:2]


def test_build_review_board_zero_ply_is_start_position():
    moves = [chess.Move.from_uci("e2e4")]
    board = build_review_board(moves, 0)
    assert board.fen() == chess.Board().fen()
