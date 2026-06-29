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

def test_menu_local_play_click_goes_to_opponent_pick(app):
    assert app.game.state == GameState.MENU
    rect = app.menu_buttons[0].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.OPPONENT_PICK


def test_menu_online_play_button_is_disabled(app):
    """Online Play is a disabled button — clicking it must NOT change state."""
    assert app.menu_buttons[1].disabled is True
    rect = app.menu_buttons[1].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.MENU


def test_menu_preferences_click_goes_to_preferences(app):
    rect = app.menu_buttons[2].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.PREFERENCES


# ── OPPONENT_PICK ────────────────────────────────────────────────────────────

def test_opponent_pick_player_goes_to_time_control_pick(app):
    app.game.state = GameState.OPPONENT_PICK
    app._render(16)
    rect = app.opponent_rects['player']
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.TIME_CONTROL_PICK
    # No game has actually started yet - that happens on Start Game.
    assert app.game.adapter is None


def test_time_control_pick_none_starts_untimed_pvp_game(app):
    app.game.state = GameState.OPPONENT_PICK
    app._render(16)
    _click(app, app.opponent_rects['player'].centerx, app.opponent_rects['player'].centery)
    assert app.game.state == GameState.TIME_CONTROL_PICK
    app._render(16)
    rect = app.tc_choice_rects['none']
    _click(app, rect.centerx, rect.centery)
    _click(app, app.tc_confirm_rect.centerx, app.tc_confirm_rect.centery)
    assert app.game.state == GameState.PVP
    assert app.game.adapter is not None
    assert app.game.clock is None


def test_time_control_pick_preset_starts_timed_pvp_game(app):
    app.game.state = GameState.OPPONENT_PICK
    app._render(16)
    _click(app, app.opponent_rects['player'].centerx, app.opponent_rects['player'].centery)
    app._render(16)
    rect = app.tc_choice_rects['3+2']
    _click(app, rect.centerx, rect.centery)
    _click(app, app.tc_confirm_rect.centerx, app.tc_confirm_rect.centery)
    assert app.game.state == GameState.PVP
    assert app.game.clock is not None
    assert app.game.clock.remaining(chess.WHITE) == 180_000
    assert app.game.clock.remaining(chess.BLACK) == 180_000


def test_time_control_pick_back_returns_to_opponent_pick(app):
    app.game.state = GameState.TIME_CONTROL_PICK
    app._render(16)
    _click(app, app.tc_back.centerx, app.tc_back.centery)
    assert app.game.state == GameState.OPPONENT_PICK


def test_opponent_pick_bot_goes_to_color_pick(app):
    app.game.state = GameState.OPPONENT_PICK
    app._render(16)
    rect = app.opponent_rects['bot']
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.COLOR_PICK


def test_opponent_pick_back_returns_to_menu(app):
    app.game.state = GameState.OPPONENT_PICK
    app._render(16)
    # Back button is the top-left "← Back" rect.
    _click(app, app.opponent_back.centerx, app.opponent_back.centery)
    assert app.game.state == GameState.MENU


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


def test_color_pick_back_returns_to_opponent_pick(app):
    """Esc from color pick should now return to OPPONENT_PICK, not MENU."""
    app.game.state = GameState.COLOR_PICK
    app._render(16)
    _key(app, pygame.K_ESCAPE)
    assert app.game.state == GameState.OPPONENT_PICK


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


# ── In-game main menu overlay (Save & Quit / Export PGN / Quit) ──────────────

def test_export_pgn_button_writes_file_and_keeps_game_open(app, tmp_path, monkeypatch):
    from chess_game import io as save_io

    app.game.state = GameState.PVP
    app.start_game()

    moves = ['e2e4', 'e7e5']
    for uci in moves:
        _finish_animation(app)
        mv = chess.Move.from_uci(uci)
        fx, fy = _square_center(mv.from_square)
        tx, ty = _square_center(mv.to_square)
        _click(app, fx, fy)
        _click(app, tx, ty)

    export_path = tmp_path / "exported.pgn"
    monkeypatch.setattr(save_io, "pgn_export_path", lambda: export_path)

    app.game.main_menu_overlay = True
    app._render(16)  # populates overlay_export_btn

    assert app.overlay_export_btn is not None
    cx, cy = app.overlay_export_btn.center
    _click(app, cx, cy)

    assert export_path.exists()
    assert "1. e4 e5" in export_path.read_text()
    # Exporting is non-destructive: the in-progress game is untouched.
    assert app.game.main_menu_overlay is False
    assert app.game.state == GameState.PVP
    assert app.game.adapter is not None


# ── Esc navigation ───────────────────────────────────────────────────────────

def test_esc_backs_out_of_color_pick_to_opponent_pick(app):
    app.game.state = GameState.COLOR_PICK
    app._render(16)
    _key(app, pygame.K_ESCAPE)
    assert app.game.state == GameState.OPPONENT_PICK


def test_esc_backs_out_of_opponent_pick_to_menu(app):
    app.game.state = GameState.OPPONENT_PICK
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
    _key(app, pygame.K_TAB)  # focus button 0 (Local Play)
    _key(app, pygame.K_RETURN)
    assert app.game.state == GameState.OPPONENT_PICK


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


# ── PvP chess clock ──────────────────────────────────────────────────────────

def test_flag_fall_ends_game(app, monkeypatch):
    """Driving a clock past zero via _tick_chess_clock must end the game
    with the non-flagging side credited as the winner. The fake clock
    source is patched in so the test doesn't depend on real wall-clock
    time accumulated earlier in the test run."""
    from chess_game.clock import Clock

    fake_now = [0]
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: fake_now[0])

    app.game.state = GameState.PVP
    app.start_game()
    app.game.maybe_create_clock("1+0")
    app.game.clock = Clock(1_000)  # force a 1-second clock regardless of preset

    app._tick_chess_clock()  # establishes the clock's tick baseline at t=0
    assert app.game.game_over is False

    fake_now[0] = 1_100  # 1.1s later - past the 1-second flag point
    app._tick_chess_clock()

    assert app.game.game_over is True
    assert app.game.winner_result == ("Black Wins!", "on Time")


def test_clock_does_not_tick_during_animation(app):
    app.game.state = GameState.PVP
    app.start_game()
    app.game.maybe_create_clock("3+2")
    app.game.clock.tick(0)

    from chess_game.anim import AnimationState
    app.game.anim = AnimationState(items=[object()], start_ms=pygame.time.get_ticks())

    remaining_before = app.game.clock.remaining(chess.WHITE)
    app._tick_chess_clock()
    assert app.game.clock.remaining(chess.WHITE) == remaining_before


def test_clock_does_not_tick_for_bot_games(app):
    """Bot games never have a clock at all, so _tick_chess_clock must be a
    silent no-op rather than erroring on a missing g.clock."""
    app.game.state = GameState.BOT
    app.start_game()
    assert app.game.clock is None
    app._tick_chess_clock()  # must not raise
    assert app.game.clock is None


def test_clock_switches_exactly_once_per_pvp_move(app):
    app.game.state = GameState.PVP
    app.start_game()
    app.game.maybe_create_clock("5+0")
    assert app.game.clock.active == chess.WHITE

    _click(app, *_square_center(chess.E2))
    _click(app, *_square_center(chess.E4))

    assert app.game.adapter.san_history == ['e4']
    assert app.game.clock.active == chess.BLACK


def test_clock_save_resume_roundtrip(app, isolated_save_dir):
    app.game.state = GameState.PVP
    app.start_game()
    app.game.maybe_create_clock("3+2")

    _click(app, *_square_center(chess.E2))
    _click(app, *_square_center(chess.E4))
    _finish_animation(app)

    # Spend down White's clock a bit before saving, so the roundtrip check
    # is meaningful (not just "whatever the untouched initial value was").
    app.game.clock.times[chess.WHITE] = 150_000
    app.game.clock.times[chess.BLACK] = 178_000
    app.write_save()

    from chess_game import io as save_io
    saved = save_io.read_save("pvp")
    assert saved is not None
    assert saved.time_control == "3+2"
    assert saved.white_time_ms == 150_000
    assert saved.black_time_ms == 178_000
    assert saved.active_side == "black"

    pygame.display.quit()
    pygame.display.init()
    resumed = App()
    resumed.continue_saved_game(saved, GameState.PVP)
    assert resumed.game.clock is not None
    assert resumed.game.clock.remaining(chess.WHITE) == 150_000
    assert resumed.game.clock.remaining(chess.BLACK) == 178_000
    assert resumed.game.clock.active == chess.BLACK
    # _last_tick_ms must be reset so the resumed clock doesn't subtract the
    # real-world gap between save and resume on its first tick.
    assert resumed.game.clock._last_tick_ms is None


def test_bot_game_never_gets_a_clock_even_with_saved_preference(app, isolated_save_dir):
    """A user's saved default_time_control preference must never leak into
    bot games - clocks are PvP-only, full stop."""
    from chess_game import io as save_io
    save_io.write_preferences("white_blue", "yellow", default_time_control="5+0")

    app.game.state = GameState.BOT
    app.start_game()
    assert app.game.clock is None
