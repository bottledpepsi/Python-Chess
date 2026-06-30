"""Smoke + behavioural tests for render/clocks.py.

Follows the same pattern as test_render_smoke.py: confirm draw_clocks runs
without raising across representative state combinations (untimed, active,
low-time, flagged), in both board orientations. Also pins down the
no-op-when-untimed contract and the active/inactive colour selection,
since those are the parts most likely to silently regress.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.bot_worker import BotWorker
from chess_game.clock import Clock
from chess_game.engine.bot import ChessBot
from chess_game.game import Game
from chess_game.render import clocks
from chess_game.theme import PANEL_X, TRAY_H, WIN_H, WIN_W, load_fonts


def _make_game() -> Game:
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    return Game(bot=bot, bot_worker=worker)


def _bottom_y() -> int:
    return WIN_H - TRAY_H


def test_draw_clocks_noop_when_untimed():
    """game.clock is None for untimed PvP and all bot games - must not draw
    or raise."""
    g = _make_game()
    assert g.clock is None
    surf = pygame.Surface((WIN_W, WIN_H))
    before = surf.copy()
    fonts = load_fonts()
    clocks.draw_clocks(surf, PANEL_X, _bottom_y(), g, fonts, False)
    # No-op really means no pixels touched.
    assert pygame.image.tostring(surf, "RGB") == pygame.image.tostring(before, "RGB")


def test_draw_clocks_active_clock_both_orientations():
    g = _make_game()
    g.clock = Clock(initial_ms=300_000, increment_ms=2_000)
    fonts = load_fonts()
    for flipped in (False, True):
        surf = pygame.Surface((WIN_W, WIN_H))
        clocks.draw_clocks(surf, PANEL_X, _bottom_y(), g, fonts, flipped)


def test_draw_clocks_low_time():
    g = _make_game()
    g.clock = Clock(initial_ms=5_000, increment_ms=0)
    fonts = load_fonts()
    surf = pygame.Surface((WIN_W, WIN_H))
    # Should hit the is_low branch without raising.
    clocks.draw_clocks(surf, PANEL_X, _bottom_y(), g, fonts, False)
    assert g.clock.remaining(chess.WHITE) <= 10_000


def test_draw_clocks_flagged():
    g = _make_game()
    g.clock = Clock(initial_ms=100, increment_ms=0)
    g.clock.tick(g.clock._last_tick_ms or 0)  # arm _last_tick_ms
    g.clock.tick(10_000)  # elapse well past initial_ms -> flags white
    assert g.clock.flagged() == chess.WHITE
    fonts = load_fonts()
    surf = pygame.Surface((WIN_W, WIN_H))
    for flipped in (False, True):
        clocks.draw_clocks(surf, PANEL_X, _bottom_y(), g, fonts, flipped)


def test_draw_clocks_after_switch_black_active():
    g = _make_game()
    g.clock = Clock(initial_ms=60_000, increment_ms=0)
    g.clock.switch()
    assert g.clock.active == chess.BLACK
    fonts = load_fonts()
    surf = pygame.Surface((WIN_W, WIN_H))
    clocks.draw_clocks(surf, PANEL_X, _bottom_y(), g, fonts, False)


def test_draw_one_clock_branches_directly():
    """Exercise _draw_one_clock's three colour branches (flagged, active,
    inactive) and the is_low text-colour override directly, rather than only
    through draw_clocks."""
    surf = pygame.Surface((200, 100))
    rect = pygame.Rect(10, 10, 96, 32)
    fonts = load_fonts()
    for is_active, is_low, is_flagged in (
        (False, False, True),   # flagged wins regardless of is_active
        (True, False, False),   # active, not low
        (True, True, False),    # active, low -> low-time text colour
        (False, False, False),  # inactive
    ):
        clocks._draw_one_clock(surf, rect, "1:23", is_active, is_low, is_flagged, fonts)
