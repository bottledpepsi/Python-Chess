"""Headless smoke tests for the App event dispatcher and render orchestrator.

app.py is the integration layer wiring together Game, the render/ modules,
and widgets — it was previously untested (0% coverage). These tests build a
real App under the dummy SDL drivers (see conftest._pygame_session) and
drive _handle_event with synthetic pygame events, asserting on Game state
transitions and adapter contents rather than on rendered pixels.
"""
from __future__ import annotations

import chess
import pygame
import pytest

from chess_game.app import App
from chess_game.layout import sq_to_screen
from chess_game.state import GameState


@pytest.fixture
def app(isolated_save_dir):
    """A fresh App with no save files on disk, so menu clicks land on a
    new game rather than triggering the continue/new-game overlay.

    App.__init__ creates its own pygame.display.set_mode(..., SCALED |
    RESIZABLE) window. Under the dummy SDL driver, calling set_mode a
    second time with SCALED after the session fixture's plain set_mode
    fails to create a renderer, so the display is cycled first.
    """
    pygame.display.quit()
    pygame.display.init()
    return App()


def _click(app, x, y, button=1):
    app._handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=(x, y)), x, y)


def _finish_animation(app):
    """Force any in-flight piece-slide animation to be considered finished,
    so the next synthetic click isn't swallowed by the is_animating guard
    (real gameplay relies on ~120ms of actual wall-clock time elapsing
    between clicks, which doesn't happen between two back-to-back test
    events fired in the same instant)."""
    if app.game.anim is not None:
        app.game.anim.start_ms = -10_000


def _key(app, key, mod=0, mx=0, my=0):
    app._handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod), mx, my)


def _square_center(sq, board_flipped=False):
    return sq_to_screen(sq, board_flipped)


# ── MENU ─────────────────────────────────────────────────────────────────────

def test_menu_pvp_click_starts_pvp_game(app):
    assert app.game.state == GameState.MENU
    rect = app.menu_buttons[0].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.PVP
    assert app.game.adapter is not None


def test_menu_bot_click_goes_to_color_pick(app):
    rect = app.menu_buttons[1].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.COLOR_PICK


def test_menu_preferences_click_goes_to_preferences(app):
    rect = app.menu_buttons[2].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.PREFERENCES


# ── COLOR_PICK ───────────────────────────────────────────────────────────────

def test_color_pick_click_sets_color_and_advances(app):
    app.game.state = GameState.COLOR_PICK
    app._render(16)
    rect = app.picker_rects['white']
    _click(app, rect.centerx, rect.centery)
    assert app.game.player_color == 'white'
    assert app.game.board_flipped is False
    assert app.game.state == GameState.DIFFICULTY


def test_color_pick_black_flips_board(app):
    app.game.state = GameState.COLOR_PICK
    app._render(16)
    rect = app.picker_rects['black']
    _click(app, rect.centerx, rect.centery)
    assert app.game.player_color == 'black'
    assert app.game.board_flipped is True


# ── DIFFICULTY ───────────────────────────────────────────────────────────────

def test_difficulty_confirm_starts_bot_game(app):
    app.game.state = GameState.DIFFICULTY
    app.game.player_color = 'white'
    app._render(16)
    rect = app.diff_confirm_rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.BOT
    assert app.game.adapter is not None


def test_difficulty_confirm_as_black_launches_bot_move(app):
    app.game.state = GameState.DIFFICULTY
    app.game.player_color = 'black'
    app._render(16)
    rect = app.diff_confirm_rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.BOT
    assert app.game.bot_thinking


# ── PVP move application ────────────────────────────────────────────────────

def test_pvp_click_source_then_target_applies_move(app):
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    to_x, to_y = _square_center(chess.E4)
    _click(app, from_x, from_y)
    _click(app, to_x, to_y)

    assert app.game.adapter.san_history == ['e4']
    assert chess.Move.from_uci('e2e4') in app.game.adapter.board.move_stack


def test_pvp_capture_updates_san_history(app):
    app.game.state = GameState.PVP
    app.start_game()

    moves = ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1b5']
    for uci in moves:
        _finish_animation(app)
        mv = chess.Move.from_uci(uci)
        fx, fy = _square_center(mv.from_square)
        tx, ty = _square_center(mv.to_square)
        _click(app, fx, fy)
        _click(app, tx, ty)

    assert len(app.game.adapter.san_history) == 5


def test_move_animation_actually_paints_a_sliding_sprite(app):
    """Regression test: starting an animation (anim is not None) is not
    enough — _render_game must actually blit the interpolated sprite, or
    the destination square is simply blank for the ~120ms animation
    window (the static piece there is suppressed by animation_suppress_set)
    and nothing visible slides.

    Rendered on an isolated blank surface (not app.screen) so the board's
    own last-move highlight and other state-dependent decorations on the
    source/destination squares can't mask whether the sprite itself was
    drawn.
    """
    app.game.state = GameState.PVP
    app.start_game()
    app.game.reduced_motion = False

    from_x, from_y = _square_center(chess.E2)
    to_x, to_y = _square_center(chess.E4)
    _click(app, from_x, from_y)
    _click(app, to_x, to_y)

    anim = app.game.anim
    assert anim is not None
    item = anim.items[0]
    assert item.img is not None

    blank = pygame.Surface((800, 700))
    bg_color = (10, 10, 10)
    blank.fill(bg_color)
    app.screen = blank

    halfway_ms = anim.start_ms + 60  # ANIM_MS is 120, so this is mid-flight
    app._draw_anim_items(anim, halfway_ms)

    from chess_game.anim import ANIM_MS, ease_out
    eased = ease_out(60 / ANIM_MS)
    cx = item.sx + (item.ex - item.sx) * eased
    cy = item.sy + (item.ey - item.sy) * eased

    painted = any(
        blank.get_at((int(cx + dx), int(cy + dy)))[:3] != bg_color
        for dx in range(-30, 30, 2)
        for dy in range(-30, 30, 2)
    )
    assert painted, "no pixels around the interpolated position differ from the blank background"


# ── Esc navigation ───────────────────────────────────────────────────────────

def test_esc_backs_out_of_color_pick_to_menu(app):
    app.game.state = GameState.COLOR_PICK
    app._render(16)
    _key(app, pygame.K_ESCAPE)
    assert app.game.state == GameState.MENU


def test_esc_backs_out_of_difficulty_to_color_pick(app):
    app.game.state = GameState.DIFFICULTY
    app._render(16)
    _key(app, pygame.K_ESCAPE)
    assert app.game.state == GameState.COLOR_PICK


def test_esc_backs_out_of_preferences_to_menu(app):
    app.game.state = GameState.PREFERENCES
    app._render(16)
    _key(app, pygame.K_ESCAPE)
    assert app.game.state == GameState.MENU


# ── Promotion via Q/R/B/N ────────────────────────────────────────────────────

def test_promotion_keyboard_completes_with_chosen_piece(app):
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # Walk a white pawn to a7 via two captures, with filler moves to pass
    # the turn back to white. a8 is still black's rook, so the promotion
    # move is the diagonal capture a7xb8.
    setup_moves = [
        'a2a4', 'b7b5', 'a4b5', 'a7a6', 'b5a6',
        'd7d5', 'a6a7', 'd5d4',
    ]
    for uci in setup_moves:
        g.adapter.apply_move(chess.Move.from_uci(uci))
    assert g.adapter.turn == 'white'

    fx, fy = _square_center(chess.A7, g.board_flipped)
    tx, ty = _square_center(chess.B8, g.board_flipped)
    _click(app, fx, fy)
    _click(app, tx, ty)
    assert g.adapter.promotion_pending is not None

    _key(app, pygame.K_n)
    assert g.adapter.promotion_pending is None
    promoted = g.adapter.board.piece_at(chess.B8)
    assert promoted is not None
    assert promoted.piece_type == chess.KNIGHT


def test_promotion_keyboard_noop_when_nothing_pending(app):
    app.game.state = GameState.PVP
    app.start_game()
    # No promotion pending; pressing Q must not raise or alter state.
    _key(app, pygame.K_q)
    assert app.game.adapter.promotion_pending is None
    assert app.game.state == GameState.PVP


# ── Tab/Enter focus navigation ──────────────────────────────────────────────

def test_tab_moves_focus_to_next_menu_button(app):
    assert app.menu_focus.index == -1
    _key(app, pygame.K_TAB)
    assert app.menu_focus.index == 0
    assert app.menu_buttons[0].focused is True
    _key(app, pygame.K_TAB)
    assert app.menu_focus.index == 1
    assert app.menu_buttons[0].focused is False
    assert app.menu_buttons[1].focused is True


def test_enter_activates_focused_menu_button(app):
    _key(app, pygame.K_TAB)  # focus button 0 (PvP)
    _key(app, pygame.K_RETURN)
    assert app.game.state == GameState.PVP


def test_shift_tab_cycles_backwards(app):
    _key(app, pygame.K_TAB)
    _key(app, pygame.K_TAB)
    assert app.menu_focus.index == 1
    _key(app, pygame.K_TAB, mod=pygame.KMOD_SHIFT)
    assert app.menu_focus.index == 0


def test_tab_is_noop_during_pvp_play(app):
    app.game.state = GameState.PVP
    app.start_game()
    _key(app, pygame.K_TAB)  # must not raise; PVP has no FocusGroup
    assert app.game.state == GameState.PVP
