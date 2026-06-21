"""Pure square <-> pixel coordinate math, unit-testable without pygame.

These functions take board_flipped explicitly rather than reading a
module global, so they're pure and trivially testable.
"""
from __future__ import annotations

import chess

from chess_game.theme import BOARD_X, BOARD_Y, TILE


def sq_to_screen(sq: int, board_flipped: bool) -> tuple[int, int]:
    """Absolute screen-pixel centre of `sq`, including the BOARD_X/Y offset."""
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    if board_flipped:
        x = BOARD_X + (7 - file) * TILE + TILE // 2
        y = BOARD_Y + rank * TILE + TILE // 2
    else:
        x = BOARD_X + file * TILE + TILE // 2
        y = BOARD_Y + (7 - rank) * TILE + TILE // 2
    return x, y


def sq_to_board(sq: int, board_flipped: bool) -> tuple[int, int]:
    """Board-surface-local pixel centre of `sq` (no BOARD_X/Y offset)."""
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    if board_flipped:
        x = (7 - file) * TILE + TILE // 2
        y = rank * TILE + TILE // 2
    else:
        x = file * TILE + TILE // 2
        y = (7 - rank) * TILE + TILE // 2
    return x, y


def pixel_to_sq(bx: int, by: int, board_flipped: bool) -> int:
    """Board-local pixel coordinates -> chess square, clamped to the board."""
    col = max(0, min(7, bx // TILE))
    row = max(0, min(7, by // TILE))
    if board_flipped:
        return chess.square(7 - col, row)
    return chess.square(col, 7 - row)


def arrow_path(start_sq: int, end_sq: int, board_flipped: bool) -> list[tuple[int, int]]:
    """Board-local point path for an arrow from start_sq to end_sq.

    Knight-move-shaped arrows (1,2) or (2,1) file/rank deltas get an
    elbow point so the arrow visually traces an L-shape rather than a
    straight diagonal line through unrelated squares.
    """
    start = sq_to_board(start_sq, board_flipped)
    end = sq_to_board(end_sq, board_flipped)
    dx = abs(chess.square_file(end_sq) - chess.square_file(start_sq))
    dy = abs(chess.square_rank(end_sq) - chess.square_rank(start_sq))
    if (dx, dy) in ((1, 2), (2, 1)):
        if dy > dx:
            corner = (start[0], end[1])
        else:
            corner = (end[0], start[1])
        return [start, corner, end]
    return [start, end]


def build_review_board(move_stack: list[chess.Move], ply: int) -> chess.Board:
    """Return a fresh chess.Board with the first `ply` moves of move_stack applied."""
    b = chess.Board()
    for move in move_stack[:ply]:
        b.push(move)
    return b
