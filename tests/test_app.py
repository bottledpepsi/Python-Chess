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


# ── In-game menu overlay: Resign / Offer Draw / Quit confirmation ────────────

def test_resign_button_opens_confirmation_without_ending_game(app):
    """Clicking Resign must not end the game immediately — it should raise
    a confirmation dialog first, since resigning is irreversible."""
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()

    app.game.main_menu_overlay = True
    app._render(16)
    assert app.overlay_resign_btn is not None
    _click(app, *app.overlay_resign_btn.center)

    assert app.game.confirm_dialog is not None
    assert app.game.confirm_dialog['action'] == 'resign'
    assert app.game.game_over is False


def test_resign_confirmed_in_bot_game_awards_win_to_bot(app):
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()

    app.game.main_menu_overlay = True
    app._render(16)
    _click(app, *app.overlay_resign_btn.center)
    app._render(16)
    assert app.confirm_yes_btn is not None
    _click(app, *app.confirm_yes_btn.center)

    assert app.game.game_over is True
    assert app.game.winner_result == ("Black Wins!", "by Resignation")
    assert app.game.confirm_dialog is None
    assert app.game.main_menu_overlay is False


def test_resign_confirmed_in_pvp_game_credits_the_side_to_move(app):
    app.game.state = GameState.PVP
    app.start_game()
    assert app.game.adapter.turn == 'white'

    app.game.main_menu_overlay = True
    app._render(16)
    _click(app, *app.overlay_resign_btn.center)
    app._render(16)
    _click(app, *app.confirm_yes_btn.center)

    assert app.game.winner_result == ("Black Wins!", "by Resignation")


def test_offer_draw_confirmed_ends_game_as_draw(app):
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()

    app.game.main_menu_overlay = True
    app._render(16)
    assert app.overlay_draw_btn is not None
    _click(app, *app.overlay_draw_btn.center)
    app._render(16)
    _click(app, *app.confirm_yes_btn.center)

    assert app.game.game_over is True
    assert app.game.winner_result == ("Draw", "by Agreement")


def test_confirm_dialog_cancel_returns_to_menu_without_side_effects(app):
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()

    app.game.main_menu_overlay = True
    app._render(16)
    _click(app, *app.overlay_resign_btn.center)
    app._render(16)
    assert app.confirm_cancel_btn is not None
    _click(app, *app.confirm_cancel_btn.center)

    assert app.game.confirm_dialog is None
    assert app.game.game_over is False
    # Cancelling returns to the menu underneath, not the live board.
    assert app.game.main_menu_overlay is True


def test_esc_cancels_confirm_dialog_before_closing_menu(app):
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()

    app.game.main_menu_overlay = True
    app._render(16)
    _click(app, *app.overlay_resign_btn.center)
    assert app.game.confirm_dialog is not None

    _key(app, pygame.K_ESCAPE)
    assert app.game.confirm_dialog is None
    assert app.game.main_menu_overlay is True  # first Esc only dismisses the dialog

    _key(app, pygame.K_ESCAPE)
    assert app.game.main_menu_overlay is False


def test_quit_without_saving_requires_confirmation_before_discarding(app, isolated_save_dir):
    from chess_game import io as save_io

    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()
    app.write_save()
    assert save_io.read_save('bot') is not None

    app.game.main_menu_overlay = True
    app._render(16)
    _click(app, *app.overlay_quit_btn.center)

    # Still just a pending confirmation — nothing discarded yet.
    assert app.game.confirm_dialog is not None
    assert app.game.state == GameState.BOT
    assert save_io.read_save('bot') is not None

    app._render(16)
    _click(app, *app.confirm_yes_btn.center)

    assert app.game.state == GameState.MENU
    assert save_io.read_save('bot') is None


# ── In-game menu overlay: Preferences shortcut ────────────────────────────────

def test_preferences_button_in_game_menu_returns_to_game_on_back(app):
    app.game.state = GameState.PVP
    app.start_game()

    app.game.main_menu_overlay = True
    app._render(16)
    assert app.overlay_preferences_btn is not None
    _click(app, *app.overlay_preferences_btn.center)

    assert app.game.state == GameState.PREFERENCES
    assert app.game.main_menu_overlay is False

    app._render(16)
    assert app.pref_back_rect is not None
    _click(app, *app.pref_back_rect.center)

    # Back returns to the PVP game in progress, not the main menu.
    assert app.game.state == GameState.PVP
    assert app.game.adapter is not None


def test_sound_toggle_mutes_sound_manager_and_persists(app, isolated_save_dir):
    from chess_game import io as save_io

    assert app.game.sound_enabled is True
    app.game.state = GameState.PREFERENCES
    app._render(16)
    assert app.pref_sound_rect is not None

    _click(app, *app.pref_sound_rect.center)

    assert app.game.sound_enabled is False
    assert app.sounds.muted is True
    assert save_io.read_preferences()['sound_enabled'] is False


# ── Winner overlay: Rematch / Review Game / Main Menu ─────────────────────────

def test_rematch_button_starts_new_bot_game_with_same_settings(app):
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.game.bot_level = 4
    app.start_game()
    app.game.resign('white')  # quickest way to reach a game-over state
    app.game.winner_alpha = 255

    app._render(16)
    assert app.gameover_btn_rects is not None
    _click(app, *app.gameover_btn_rects['rematch'].center)

    assert app.game.state == GameState.BOT
    assert app.game.game_over is False
    assert app.game.bot_level == 4  # settings carried over, no picker involved
    assert app.game.adapter is not None
    assert len(app.game.adapter.san_history) == 0


def test_review_game_button_enters_review_and_hides_winner_overlay(app):
    app.game.state = GameState.PVP
    app.start_game()
    mv = chess.Move.from_uci('e2e4')
    fx, fy = _square_center(mv.from_square)
    tx, ty = _square_center(mv.to_square)
    _click(app, fx, fy)
    _click(app, tx, ty)
    app.game.resign('black')
    app.game.winner_alpha = 255

    app._render(16)
    assert app.gameover_btn_rects is not None
    _click(app, *app.gameover_btn_rects['review'].center)

    assert app.game.review.active is True
    # Entering review hides the winner overlay so the board is visible.
    app._render(16)
    assert app.gameover_btn_rects is None


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


# ── QUIT event ───────────────────────────────────────────────────────────
#
# Previously entirely uncovered (input_handler.py:119-123). Exercises the
# pygame.QUIT handler's worker-shutdown sequence before it calls
# pygame.quit() + sys.exit() (mocked here so the test process itself
# doesn't exit).

def test_quit_event_cancels_native_bot_worker_and_stops_analysis_engine(app, monkeypatch):
    """On pygame.QUIT, the native bot_worker must be cancelled/joined and
    analysis_worker's engine subprocess must be stopped before exit."""
    calls = []
    monkeypatch.setattr(app.game.bot_worker, "cancel", lambda: calls.append("bot_cancel"))
    monkeypatch.setattr(app.game.bot_worker, "join", lambda timeout=None: calls.append("bot_join"))
    monkeypatch.setattr(app.analysis_worker, "stop_engine", lambda: calls.append("analysis_stop"))
    monkeypatch.setattr(pygame, "quit", lambda: calls.append("pygame_quit"))
    monkeypatch.setattr("sys.exit", lambda *a: (_ for _ in ()).throw(SystemExit))

    with pytest.raises(SystemExit):
        app._handle_event(pygame.event.Event(pygame.QUIT), 0, 0)

    assert "bot_cancel" in calls
    assert "bot_join" in calls
    assert "analysis_stop" in calls
    assert "pygame_quit" in calls


def test_quit_event_does_not_stop_stockfish_bot_worker(app, monkeypatch):
    """Documents a known gap rather than papering over it: the QUIT
    handler currently shuts down the native bot_worker and the analysis
    engine, but never cancels or stops game.stockfish_bot_worker (the
    engine used to actually play bot moves when "Vs Bot" is set to
    Stockfish). If a Stockfish search is in flight when the window is
    closed, that subprocess is not cleanly terminated here.

    This test asserts the *current* behaviour so a future fix is a
    deliberate, visible change to this test rather than a silent one —
    it is not an endorsement of leaving the subprocess unterminated.
    """
    calls = []
    monkeypatch.setattr(app.game.bot_worker, "cancel", lambda: None)
    monkeypatch.setattr(app.game.bot_worker, "join", lambda timeout=None: None)
    monkeypatch.setattr(app.analysis_worker, "stop_engine", lambda: None)
    monkeypatch.setattr(
        app.game.stockfish_bot_worker, "cancel", lambda: calls.append("sf_cancel")
    )
    monkeypatch.setattr(
        app.game.stockfish_bot_worker, "stop_engine", lambda: calls.append("sf_stop")
    )
    monkeypatch.setattr(pygame, "quit", lambda: None)
    monkeypatch.setattr("sys.exit", lambda *a: (_ for _ in ()).throw(SystemExit))

    with pytest.raises(SystemExit):
        app._handle_event(pygame.event.Event(pygame.QUIT), 0, 0)

    assert calls == [], (
        "stockfish_bot_worker.cancel()/stop_engine() were called on QUIT — "
        "if this now passes with calls made, update this test to assert "
        "the (now fixed) cleanup instead of its absence."
    )


# ── Fullscreen toggle (F11) ───────────────────────────────────────────────
#
# Previously entirely uncovered (app.py:448-472). Under the dummy SDL
# driver, pygame.display.toggle_fullscreen() reliably fails to return 1,
# so this also exercises the display-recreation fallback path.

def test_f11_toggles_fullscreen_flag_and_persists_preference(app, isolated_save_dir):
    from chess_game import io as save_io

    assert app._fullscreen is False
    _key(app, pygame.K_F11)
    assert app._fullscreen is True

    prefs = save_io.read_preferences()
    assert prefs.get("fullscreen") is True

    _key(app, pygame.K_F11)
    assert app._fullscreen is False
    prefs = save_io.read_preferences()
    assert prefs.get("fullscreen") is False


def test_f11_works_regardless_of_current_screen(app):
    """F11 is documented as working "at any time, regardless of what
    screen or popup is active" — spot-check it from a non-menu state."""
    app.game.state = GameState.PVP
    app.game.confirm_dialog = {"action": "resign", "message": "Resign?"}
    starting = app._fullscreen

    _key(app, pygame.K_F11)

    assert app._fullscreen is not starting
    # The confirm dialog must be untouched — F11 is orthogonal to it.
    assert app.game.confirm_dialog is not None


# ── Analysis toggle + missing-engine modal ────────────────────────────────
#
# Previously entirely uncovered (app.py:216-229). No real Stockfish
# binary is present in the test environment, so analysis_worker is
# expected to be unavailable — this exercises the "engine not found"
# branch organically rather than needing to fake a working engine.

def test_toggle_analysis_on_shows_missing_engine_modal_when_unavailable(app):
    assert app.game.analysis_enabled is False
    assert app.game.analysis_missing_modal_shown is False

    app._toggle_analysis()

    assert app.game.analysis_enabled is True
    if not app.analysis_worker.engine_available:
        assert app.pending_analysis_missing_modal is True
        assert app.game.analysis_missing_modal_shown is True


def test_toggle_analysis_missing_modal_only_shown_once(app):
    """A second toggle-off-then-on shouldn't re-trigger the modal once
    it's already been shown this App lifetime."""
    app._toggle_analysis()  # on
    if not app.analysis_worker.engine_available:
        app.pending_analysis_missing_modal = False  # simulate the user dismissing it
        app._toggle_analysis()  # off
        app._toggle_analysis()  # on again
        assert app.pending_analysis_missing_modal is False


def test_toggle_analysis_off_clears_eval_display_state(app):
    app.game.analysis_enabled = True
    app.game.analysis_eval = 150
    app.game.eval_bar_display_ratio = 0.7

    app._toggle_analysis()

    assert app.game.analysis_enabled is False
    assert app.game.eval_bar_display_ratio is None


# ── Stockfish download start/poll ─────────────────────────────────────────
#
# Previously entirely uncovered (app.py:231-268).

def test_start_stockfish_download_is_noop_while_already_busy(app, monkeypatch):
    monkeypatch.setattr(
        type(app.stockfish_downloader), "busy",
        property(lambda self: True),
    )
    started = []
    monkeypatch.setattr(app.stockfish_downloader, "start", lambda d: started.append(d))

    app._start_stockfish_download()

    assert started == []


def test_poll_stockfish_download_no_result_is_noop(app, monkeypatch):
    monkeypatch.setattr(app.stockfish_downloader, "take_result", lambda: None)
    before = app.stockfish_download_status
    app._poll_stockfish_download()
    assert app.stockfish_download_status == before


def test_poll_stockfish_download_error_sets_error_status(app, monkeypatch):
    monkeypatch.setattr(
        app.stockfish_downloader, "take_result", lambda: (None, "network error")
    )
    app._poll_stockfish_download()
    assert app.stockfish_download_status == "error"
    assert app.stockfish_download_error == "network error"


def test_poll_stockfish_download_success_updates_engine_path(app, monkeypatch, isolated_save_dir):
    """A successful download must update analysis_worker's engine path
    and clear the "missing engine" one-shot latch so the modal can be
    shown again if a *later* engine attempt also fails."""
    app.game.analysis_missing_modal_shown = True
    monkeypatch.setattr(
        app.stockfish_downloader, "take_result",
        lambda: ("/fake/path/to/stockfish", None),
    )
    stopped = []
    monkeypatch.setattr(app.analysis_worker, "stop_engine", lambda: stopped.append(True))
    set_paths = []
    monkeypatch.setattr(
        app.analysis_worker, "set_engine_path", lambda p: set_paths.append(p)
    )

    app._poll_stockfish_download()

    assert app.stockfish_download_status == "done"
    assert app.game.stockfish_path == "/fake/path/to/stockfish"
    assert stopped == [True]
    assert set_paths == ["/fake/path/to/stockfish"]
    assert app.game.analysis_missing_modal_shown is False


def test_poll_stockfish_download_success_does_not_update_bot_play_engine_path(app, monkeypatch):
    """Documents a known gap: a successful download updates
    analysis_worker's engine path but never calls set_engine_path on
    game.stockfish_bot_worker (the engine actually used to play bot
    moves when "Vs Bot" is set to Stockfish). A user who downloads
    Stockfish and immediately plays against it in the same session will
    still hit the old path on that worker.

    Documents current behaviour deliberately, same as the QUIT-handler
    test above — not an endorsement of leaving it unfixed.
    """
    monkeypatch.setattr(
        app.stockfish_downloader, "take_result",
        lambda: ("/fake/path/to/stockfish", None),
    )
    monkeypatch.setattr(app.analysis_worker, "stop_engine", lambda: None)
    monkeypatch.setattr(app.analysis_worker, "set_engine_path", lambda p: None)
    calls = []
    monkeypatch.setattr(
        app.game.stockfish_bot_worker, "set_engine_path",
        lambda p: calls.append(p),
    )

    app._poll_stockfish_download()

    assert calls == [], (
        "game.stockfish_bot_worker.set_engine_path() was called after a "
        "download — if this now passes with a call made, update this "
        "test to assert the (now fixed) propagation instead of its "
        "absence."
    )


# ── _frame() main-loop body ────────────────────────────────────────────────
#
# Previously entirely uncovered (app.py:496-532) — run() itself is an
# infinite loop and isn't directly unit-testable, but _frame() is a
# single iteration of its body and can be called directly.

def test_frame_runs_one_iteration_without_error(app, monkeypatch):
    """A smoke test that a single _frame() call completes cleanly from
    the menu screen with no queued events — covers the per-frame
    bookkeeping (drag safety-net, think-dots timer, bot/clock/analysis
    polling, flip animation, render, cursor update) end to end."""
    monkeypatch.setattr(pygame.event, "get", lambda: [])
    app._frame()  # must not raise
    assert app.game.state == GameState.MENU


def test_frame_clears_stale_drag_state_when_mouse_released(app, monkeypatch):
    """If drag_pending/drag_active is left set but the mouse button is no
    longer held (e.g. the mouseup was swallowed by an overlay), _frame's
    safety net must clear it so the next press starts cleanly."""
    app.drag_pending = True
    app.drag_active = True
    app.drag_sq = chess.E2
    monkeypatch.setattr(pygame.mouse, "get_pressed", lambda: (False, False, False))
    monkeypatch.setattr(pygame.event, "get", lambda: [])

    app._frame()

    assert app.drag_pending is False
    assert app.drag_active is False
