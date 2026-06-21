"""Pure board rendering, with a cached indicator-surface helper.

draw_board is pure: surface in, nothing mutated outside the surface.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.theme import (
    BOARD_PX,
    BOARD_THEMES,
    SQ_CHK_D,
    SQ_CHK_L,
    SQ_LAST_D,
    SQ_LAST_L,
    SQ_SEL_D,
    SQ_SEL_L,
    TILE,
)

_IND_R = TILE // 2
_ind_dot: pygame.Surface | None = None
_ind_ring: pygame.Surface | None = None


def _indicators() -> tuple[pygame.Surface, pygame.Surface]:
    """Lazily build (and cache) the move-indicator dot/ring surfaces."""
    global _ind_dot, _ind_ring
    if _ind_dot is None or _ind_ring is None:
        dot = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        ring = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        pygame.draw.circle(dot, (0, 0, 0, 80), (_IND_R, _IND_R), _IND_R // 3)
        pygame.draw.circle(ring, (0, 0, 0, 85), (_IND_R, _IND_R), _IND_R - 4, 6)
        _ind_dot, _ind_ring = dot, ring
    return _ind_dot, _ind_ring


def square_screen_pos(sq: int, board_flipped: bool) -> tuple[int, int]:
    """Top-left pixel of `sq` within a BOARD_PX x BOARD_PX surface."""
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    if board_flipped:
        return (7 - file) * TILE, rank * TILE
    return file * TILE, (7 - rank) * TILE


def draw_board(
    board_surf,
    board,
    piece_imgs,
    board_theme_name,
    board_flipped,
    check_sq,
    last_move,
    sel_sq,
    targets,
    suppress,
):
    """Draw squares, highlights, pieces, and move indicators onto board_surf.

    Pure: takes the surface and all the data it needs, mutates only that
    surface. No globals, no module-level adapter/board_flipped reads.
    """
    theme = BOARD_THEMES[board_theme_name]
    theme_light, theme_dark = theme["light"], theme["dark"]
    ind_dot, ind_ring = _indicators()

    for rank in range(8):
        for file in range(8):
            sq = chess.square(file, rank)
            sx, sy = square_screen_pos(sq, board_flipped)
            rect = pygame.Rect(sx, sy, TILE, TILE)
            is_light = (file + rank) % 2 == 1

            if sq == check_sq:
                col = SQ_CHK_L if is_light else SQ_CHK_D
            elif sq == sel_sq:
                col = SQ_SEL_L if is_light else SQ_SEL_D
            elif last_move and sq in (last_move.from_square, last_move.to_square):
                col = SQ_LAST_L if is_light else SQ_LAST_D
            else:
                col = theme_light if is_light else theme_dark

            pygame.draw.rect(board_surf, col, rect)

            if not (suppress and sq in suppress):
                piece = board.piece_at(sq)
                if piece:
                    img = piece_imgs.get((piece.piece_type, piece.color))
                    if img:
                        board_surf.blit(img, img.get_rect(center=rect.center))

            if sel_sq is not None and sq in targets:
                cx, cy = rect.center
                has_piece = board.piece_at(sq) is not None and not (suppress and sq in suppress)
                surf = ind_ring if has_piece else ind_dot
                board_surf.blit(surf, (cx - _IND_R, cy - _IND_R))


def draw_labels(screen, board_flipped, fonts):
    """Draw rank (1-8) and file (a-h) labels around the board, pure."""
    from chess_game.theme import BOARD_X, BOARD_Y, LABEL_COL

    files = 'hgfedcba' if board_flipped else 'abcdefgh'
    for y in range(8):
        rank = str(y + 1) if board_flipped else str(8 - y)
        s = fonts.label.render(rank, True, LABEL_COL)
        ry = BOARD_Y + y * TILE + (TILE - s.get_height()) // 2
        screen.blit(s, (BOARD_X - s.get_width() - 4, ry))
    for x, letter in enumerate(files):
        s = fonts.label.render(letter, True, LABEL_COL)
        fx = BOARD_X + x * TILE + (TILE - s.get_width()) // 2
        screen.blit(s, (fx, BOARD_Y + BOARD_PX + 5))
