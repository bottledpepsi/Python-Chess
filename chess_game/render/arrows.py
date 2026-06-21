"""Board annotation arrow rendering, ported verbatim from main.py with the
board_flipped global swapped for an explicit parameter.
"""
from __future__ import annotations

import math

import pygame

from chess_game.layout import arrow_path
from chess_game.theme import (
    ARROW_HEAD_SIZE,
    ARROW_THEMES,
    ARROW_WIDTH,
    BOARD_PX,
    BOARD_X,
    BOARD_Y,
)


def _draw_arrow(surface, start, end, color, width=ARROW_WIDTH, head_size=ARROW_HEAD_SIZE):
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1:
        return

    nx = dx / dist
    ny = dy / dist
    perp_x = -ny
    perp_y = nx
    head_dx = nx * head_size
    head_dy = ny * head_size
    tip = (ex, ey)
    base = (ex - head_dx, ey - head_dy)

    half_w = width / 2
    p1 = (sx + perp_x * half_w, sy + perp_y * half_w)
    p2 = (base[0] + perp_x * half_w, base[1] + perp_y * half_w)
    p3 = (base[0] - perp_x * half_w, base[1] - perp_y * half_w)
    p4 = (sx - perp_x * half_w, sy - perp_y * half_w)

    wing1 = (base[0] + perp_x * head_size * 0.55,
             base[1] + perp_y * head_size * 0.55)
    wing2 = (base[0] - perp_x * head_size * 0.55,
             base[1] - perp_y * head_size * 0.55)

    pygame.draw.polygon(surface, color, [p1, p2, p3, p4])
    pygame.draw.polygon(surface, color, [tip, wing1, wing2])


def _draw_polyline_arrow(surface, points, color, width=ARROW_WIDTH, head_size=ARROW_HEAD_SIZE):
    if len(points) < 2:
        return
    for i in range(len(points) - 1):
        segment_start = points[i]
        segment_end = points[i + 1]
        if i == len(points) - 2:
            _draw_arrow(surface, segment_start, segment_end, color, width, head_size)
        else:
            pygame.draw.line(surface, color, segment_start, segment_end, width)


def draw_board_arrow_overlay(screen, all_arrows, arrow_theme_name, board_flipped):
    """Blit all annotation arrows onto `screen` at the board's position.
    Pure: takes all_arrows explicitly rather than reading a module global."""
    if not all_arrows:
        return
    arrow_color = ARROW_THEMES[arrow_theme_name]
    arrow_surf = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
    for start_sq, end_sq in all_arrows:
        points = arrow_path(start_sq, end_sq, board_flipped)
        _draw_polyline_arrow(arrow_surf, points, arrow_color)
    screen.blit(arrow_surf, (BOARD_X, BOARD_Y))
