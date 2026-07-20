"""Tests for GameState.ENGINE_SETUP / ENGINE_MATCH — the engine-vs-engine
local play option added alongside Player and Bot.

Mirrors tests/test_app.py's fixtures and helpers (same `app` fixture
workaround for pygame's SCALED display mode under the dummy SDL driver,
same _click/_finish_animation/_square_center helpers) since this is
testing the same App class, just a new mode within it.
"""
from __future__ import annotations

import time

import chess
import pygame
import pytest

from chess_game.app import App
from chess_game.state import GameState


@pytest.fixture
def app(isolated_save_dir):
    pygame.display.quit()
    pygame.display.init()
    return App()


def _click(app, x, y, button=1):
    app._handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=(x, y)), x, y)


def _key(app, key, mod=0):
    app._handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod), 0, 0)


def _finish_animation(app):
    if app.game.anim is not None:
        app.game.anim.start_ms = -10_000


def _run_frames(app, max_moves=6, timeout_s=30.0):
    """Poll _apply_engine_match_move in a loop, actually waiting real
    wall-clock time between polls, until at least max_moves have been
    played, the game ends, or timeout_s elapses.

    A tight no-sleep loop doesn't work here: even with the artificial
    ~1.0s floor disabled for engine matches (see
    Game.launch_engine_match_move), the real search itself still takes
    real wall-clock time to finish on a background thread, so the test
    needs to actually wait, not just iterate many times instantly.
    """
    g = app.game
    start = time.time()
    while time.time() - start < timeout_s:
        _finish_animation(app)
        app._apply_engine_match_move()
        if len(g.adapter.board.move_stack) >= max_moves or g.game_over:
            return
        time.sleep(0.05)


# ── Home launcher routing ────────────────────────────────────────────────────

def test_home_engine_match_goes_to_engine_setup(app):
    rect = app.menu_buttons[2].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.ENGINE_SETUP


def test_engine_setup_back_returns_to_home(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['back']
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.MENU


# ── Setup screen interaction ─────────────────────────────────────────────────

def test_engine_setup_toggle_switches_side_to_stockfish(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['white_engine']['stockfish']
    _click(app, rect.centerx, rect.centery)
    assert app.game.em_white_kind == 'stockfish'
    # Black's kind must be untouched by a click on White's toggle.
    assert app.game.em_black_kind == 'native'


def test_engine_setup_sides_are_independent(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    white_rect = app.em_setup_rects['white_engine']['stockfish']
    _click(app, white_rect.centerx, white_rect.centery)
    app._render(16)
    black_rect = app.em_setup_rects['black_engine']['native']
    _click(app, black_rect.centerx, black_rect.centery)

    assert app.game.em_white_kind == 'stockfish'
    assert app.game.em_black_kind == 'native'


def test_engine_setup_slider_click_sets_native_level(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    slider = app.em_setup_rects['white_slider']
    sl_x, sl_w, sl_y = app.em_setup_slider_info['white']
    # Click near the right edge of the slider track -> a high level.
    _click(app, sl_x + sl_w - 2, slider.centery)
    assert app.game.em_white_level >= 9


def test_engine_setup_confirm_starts_match(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    assert app.game.state == GameState.ENGINE_MATCH
    assert app.game.board_flipped is False
    assert app.game.em_white_epoch is not None
    # Not asserting engine_match_thinking('white') here: with the
    # artificial 1s floor disabled for engine matches (see
    # Game.launch_engine_match_move), a fast/shallow search can finish
    # before this very next line runs, making "still thinking right
    # after launch" a race rather than a reliable fact. em_white_epoch
    # being set is the synchronous, non-racy signal that a search was
    # actually launched.


def test_engine_setup_is_fully_keyboard_navigable(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)

    # Back, white Native, white Stockfish, white slider.
    for _ in range(4):
        _key(app, pygame.K_TAB)
    assert app.em_setup_focus.widgets[app.em_setup_focus.index].key == ('slider', 'white')
    original_level = app.game.em_white_level
    _key(app, pygame.K_RIGHT)
    assert app.game.em_white_level == original_level + 1

    # Black Native, Black Stockfish: select Stockfish with Enter.
    _key(app, pygame.K_TAB)
    _key(app, pygame.K_TAB)
    _key(app, pygame.K_RETURN)
    assert app.game.em_black_kind == 'stockfish'

    # Its slider changes in predictable 10-ELO steps.
    _key(app, pygame.K_TAB)
    original_elo = app.game.em_black_elo
    _key(app, pygame.K_RIGHT)
    assert app.game.em_black_elo == original_elo + 10


def test_engine_setup_keyboard_confirm_starts_match(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    for _ in range(8):
        _key(app, pygame.K_TAB)
    assert app.em_setup_focus.widgets[app.em_setup_focus.index].key == ('confirm',)
    _key(app, pygame.K_RETURN)
    assert app.game.state == GameState.ENGINE_MATCH


# ── Auto-play ─────────────────────────────────────────────────────────────────

def test_engine_match_plays_moves_automatically_without_input(app):
    """The whole point of this mode: once started, moves apply themselves
    frame by frame with no clicks at all."""
    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_level = 1
    app.game.em_black_level = 1
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    _run_frames(app, max_moves=2)
    assert len(app.game.adapter.board.move_stack) >= 2


def test_engine_match_board_clicks_never_select_or_move_a_piece(app):
    """Confirms there is genuinely no click-to-move path in this mode —
    a left click on the board must be a no-op (no piece selected, no
    move applied), unlike PVP/BOT."""
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    board_before = list(app.game.adapter.board.move_stack)
    from chess_game.layout import sq_to_screen
    x, y = sq_to_screen(chess.E2, False)
    _click(app, x, y)
    assert app.game.adapter.board.move_stack == board_before
    assert app.game.adapter.selected_square is None


# ── Forfeit handling ──────────────────────────────────────────────────────────

def test_engine_match_forfeits_cleanly_when_stockfish_unavailable(app, monkeypatch):
    """If a side is configured as Stockfish and the binary can't launch,
    the match must end as a clean forfeit rather than hang forever
    waiting for a move that will never come."""
    def _raise_missing(engine_path):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr("chess_game.stockfish_bot_worker._popen_uci", _raise_missing)

    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_kind = 'stockfish'
    app.game.em_white_elo = 1500
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    _run_frames(app, max_moves=1, timeout_s=10.0)

    assert app.game.game_over is True
    assert app.game.winner_result is not None
    assert 'Forfeit' in app.game.winner_result[1]


# ── PGN export ────────────────────────────────────────────────────────────────

def test_export_engine_match_pgn_labels_both_engines_correctly(app, tmp_path, monkeypatch):
    """Exercises the PGN header-labeling logic specifically (both engines
    correctly named, not "Player"/"Bot"), independent of whether a real
    Stockfish binary is available in this environment — White is native
    so the match actually produces a move to export, while Black is
    configured as Stockfish purely to verify its label is correct
    without requiring gameplay from it."""
    from chess_game import io as save_io

    monkeypatch.setattr(save_io, "get_save_dir", lambda: tmp_path)

    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_kind = 'native'
    app.game.em_white_level = 7
    app.game.em_black_kind = 'stockfish'
    app.game.em_black_elo = 1900
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)
    _run_frames(app, max_moves=1)  # White's first move only

    app.export_engine_match_pgn()

    pgn_dir = tmp_path / "pgn"
    files = list(pgn_dir.glob("*.pgn"))
    assert len(files) == 1
    content = files[0].read_text()
    assert 'Native (depth 7)' in content
    assert 'Stockfish (ELO 1900)' in content
    assert '[Event "Engine Match"]' in content


# ── Menu overlay / quit ──────────────────────────────────────────────────────

def test_escape_opens_reduced_overlay_in_engine_match(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    app._handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE), 0, 0)
    assert app.game.main_menu_overlay is True


def test_engine_match_overlay_quit_stops_workers_and_returns_to_menu(app, monkeypatch):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    calls = []
    monkeypatch.setattr(app.game.em_white_native_worker, "cancel", lambda: calls.append("white_cancel"))
    monkeypatch.setattr(app.game.em_black_native_worker, "cancel", lambda: calls.append("black_cancel"))

    app.game.main_menu_overlay = True
    app._render(16)
    rect = app.em_overlay_quit_btn
    _click(app, rect.centerx, rect.centery)

    assert "white_cancel" in calls
    assert "black_cancel" in calls
    assert app.game.state == GameState.MENU
    assert app.game.main_menu_overlay is False


def test_quit_event_cancels_engine_match_workers(app, monkeypatch):
    """Mirrors test_app.py's test_quit_event_cancels_native_bot_worker_
    and_stops_analysis_engine, extended to the four new engine-match
    workers this feature introduces."""
    calls = []
    for worker_name in ("em_white_native_worker", "em_black_native_worker"):
        worker = getattr(app.game, worker_name)
        monkeypatch.setattr(worker, "cancel", lambda n=worker_name: calls.append(f"{n}_cancel"))
        monkeypatch.setattr(worker, "join", lambda timeout=None, n=worker_name: calls.append(f"{n}_join"))
    for worker_name in ("em_white_stockfish_worker", "em_black_stockfish_worker"):
        worker = getattr(app.game, worker_name)
        monkeypatch.setattr(worker, "cancel", lambda n=worker_name: calls.append(f"{n}_cancel"))
    monkeypatch.setattr(pygame, "quit", lambda: calls.append("pygame_quit"))
    monkeypatch.setattr("sys.exit", lambda *a: (_ for _ in ()).throw(SystemExit))

    with pytest.raises(SystemExit):
        app._handle_event(pygame.event.Event(pygame.QUIT), 0, 0)

    assert "em_white_native_worker_cancel" in calls
    assert "em_black_native_worker_cancel" in calls
    assert "em_white_stockfish_worker_cancel" in calls
    assert "em_black_stockfish_worker_cancel" in calls


# ── Pause / Step / Resume ─────────────────────────────────────────────────────

def test_pause_halts_further_moves(app):
    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_level = 3
    app.game.em_black_level = 3
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)
    _run_frames(app, max_moves=2)
    moves_at_pause = len(app.game.adapter.board.move_stack)

    app.game.em_paused = True
    _run_frames(app, max_moves=moves_at_pause + 1, timeout_s=3.0)

    assert len(app.game.adapter.board.move_stack) == moves_at_pause


def test_step_advances_exactly_one_move_then_halts_again(app):
    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_level = 3
    app.game.em_black_level = 3
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)
    _run_frames(app, max_moves=2)
    moves_before = len(app.game.adapter.board.move_stack)

    app.game.em_paused = True
    _run_frames(app, max_moves=moves_before + 1, timeout_s=3.0)
    assert len(app.game.adapter.board.move_stack) == moves_before

    app.game.em_step_requested = True
    _run_frames(app, max_moves=moves_before + 1, timeout_s=15.0)
    assert len(app.game.adapter.board.move_stack) == moves_before + 1
    # The step must be consumed, not sticky — waiting again afterward
    # must not produce a second move.
    _run_frames(app, max_moves=moves_before + 2, timeout_s=3.0)
    assert len(app.game.adapter.board.move_stack) == moves_before + 1
    assert app.game.em_step_requested is False


def test_resume_continues_play_after_pause(app):
    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_level = 3
    app.game.em_black_level = 3
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)
    _run_frames(app, max_moves=2)
    moves_before = len(app.game.adapter.board.move_stack)

    app.game.em_paused = True
    _run_frames(app, max_moves=moves_before + 1, timeout_s=3.0)
    assert len(app.game.adapter.board.move_stack) == moves_before

    app.game.em_paused = False
    _run_frames(app, max_moves=moves_before + 2, timeout_s=15.0)
    assert len(app.game.adapter.board.move_stack) >= moves_before + 2


def test_pause_button_click_toggles_em_paused(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    app._render(16)
    pause_rect = app.em_pause_btn_rect
    assert pause_rect is not None
    _click(app, pause_rect.centerx, pause_rect.centery)
    assert app.game.em_paused is True

    app._render(16)
    pause_rect = app.em_pause_btn_rect
    _click(app, pause_rect.centerx, pause_rect.centery)
    assert app.game.em_paused is False


def test_step_button_click_sets_step_requested_only_while_paused(app):
    app.game.state = GameState.ENGINE_SETUP
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    # Not paused yet: clicking Step must do nothing (it's drawn dimmed
    # and non-interactive in this state — see App._render_game).
    app._render(16)
    step_rect = app.em_step_btn_rect
    assert step_rect is not None
    _click(app, step_rect.centerx, step_rect.centery)
    assert app.game.em_step_requested is False

    app.game.em_paused = True
    app._render(16)
    step_rect = app.em_step_btn_rect
    _click(app, step_rect.centerx, step_rect.centery)
    assert app.game.em_step_requested is True


def test_pause_step_buttons_absent_outside_engine_match(app):
    """The pause/step controls must not appear (or be clickable) in
    PVP/BOT — they're only meaningful when both sides are engines."""
    rect = app.menu_buttons[1].rect
    _click(app, rect.centerx, rect.centery)
    assert app.game.state == GameState.COLOR_PICK
    app._render(16)
    assert app.em_pause_btn_rect is None
    assert app.em_step_btn_rect is None


# ── Artificial think-time floor disabled for engine matches ─────────────────

def test_engine_match_native_move_has_no_artificial_minimum_delay(app):
    """The ~1.0s pacing floor in ChessBot.get_move exists for human-vs-bot
    play and must not apply here — a low-depth native engine playing
    itself should be able to produce several moves in well under the
    ~1.0s-per-move that floor would otherwise force."""
    app.game.state = GameState.ENGINE_SETUP
    app.game.em_white_level = 1
    app.game.em_black_level = 1
    app._render(16)
    rect = app.em_setup_rects['confirm']
    _click(app, rect.centerx, rect.centery)

    start = time.time()
    _run_frames(app, max_moves=4, timeout_s=10.0)
    elapsed = time.time() - start

    assert len(app.game.adapter.board.move_stack) >= 4
    # With the floor still active this would take >= 4.0s; comfortably
    # asserting well under that without being flaky on a slow CI box.
    assert elapsed < 3.0, f"expected fast play with no artificial floor, took {elapsed:.2f}s"


def test_bot_mode_still_has_the_artificial_minimum_delay(app):
    """Regression guard: the fix for engine-match must not have removed
    the pacing floor for ordinary human-vs-bot play, where it's still
    wanted (see ChessBot.get_move's default min_think_time_s=1.0)."""
    from chess_game.engine.bot import ChessBot

    bot = ChessBot(max_depth=1, book_path=None)
    board = chess.Board()
    start = time.time()
    bot.get_move(board, 'white', 1)
    elapsed = time.time() - start
    assert elapsed >= 0.95


# ── Engine note display ───────────────────────────────────────────────────────
# See tests/test_render_trays.py for draw_trays' engine_notes coverage —
# that file already has the right fixtures (_FakeAdapter, real fonts) for
# testing chess_game.render.trays directly.

def test_engine_match_label_formats_native_and_stockfish(app):
    g = app.game
    g.em_white_kind = 'native'
    g.em_white_level = 7
    g.em_black_kind = 'stockfish'
    g.em_black_elo = 1800
    assert g.engine_match_label('white') == 'Native (depth 7)'
    assert g.engine_match_label('black') == 'Stockfish (ELO 1800)'
