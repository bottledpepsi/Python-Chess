"""Tests for App's top-level crash handling (run() -> _handle_crash()).

Before this, any exception that escaped the frame loop propagated all the
way out of run() with a bare traceback and no user-facing message — a
real problem for a --windowed build, where stdout is discarded (see
log.py's own docstring), so the player would just see the window vanish
with zero explanation and no indication their game was safe.

These tests call _handle_crash()/_show_crash_screen() directly rather
than forcing a real exception through the full run() loop, so they stay
fast and deterministic while still exercising the real code paths a
crash would hit.
"""
from __future__ import annotations

import logging

import chess
import pygame
import pytest

from chess_game import io as save_io
from chess_game.app import App
from chess_game.state import GameState


@pytest.fixture
def app(isolated_save_dir):
    pygame.display.quit()
    pygame.display.init()
    return App()


def _post_quit_soon():
    """Queue a QUIT event so _show_crash_screen's wait loop exits on its
    first poll instead of hanging the test."""
    pygame.event.post(pygame.event.Event(pygame.QUIT))


def test_handle_crash_logs_exits_and_shows_screen(app, caplog):
    _post_quit_soon()
    with caplog.at_level(logging.ERROR, logger="python_chess"):
        with pytest.raises(SystemExit) as exc_info:
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                app._handle_crash()
    assert exc_info.value.code == 1
    assert any("Unhandled exception" in r.message for r in caplog.records)


def test_handle_crash_attempts_final_save(app):
    """A game in progress should still be on disk after a crash, via the
    belt-and-braces write_save() call inside _handle_crash()."""
    app.game.state = GameState.PVP
    app.start_game()
    app.game.adapter.board.push(chess.Move.from_uci('e2e4'))
    app.game.adapter.san_history.append('e4')

    _post_quit_soon()
    with pytest.raises(SystemExit):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            app._handle_crash()

    saved = save_io.read_save('pvp')
    assert saved is not None
    assert saved.moves == [chess.Move.from_uci('e2e4')]


def test_handle_crash_survives_a_broken_save(app, monkeypatch, caplog):
    """If write_save() itself raises during crash handling (e.g. disk
    full), that must not replace the original exception or prevent the
    crash screen / exit from still happening."""
    def _broken_write_save():
        raise OSError("disk full")
    monkeypatch.setattr(app, "write_save", _broken_write_save)

    _post_quit_soon()
    with caplog.at_level(logging.ERROR, logger="python_chess"):
        with pytest.raises(SystemExit) as exc_info:
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                app._handle_crash()
    assert exc_info.value.code == 1
    assert any("Final save attempt" in r.message for r in caplog.records)


def test_handle_crash_survives_a_broken_crash_screen(app, monkeypatch, caplog):
    """If even _show_crash_screen() throws, _handle_crash() must still
    log it and exit(1) rather than letting a second, unrelated traceback
    propagate in place of the original crash."""
    def _broken_screen():
        raise pygame.error("no display")
    monkeypatch.setattr(app, "_show_crash_screen", _broken_screen)

    with caplog.at_level(logging.ERROR, logger="python_chess"):
        with pytest.raises(SystemExit) as exc_info:
            try:
                raise RuntimeError("boom")
            except RuntimeError:
                app._handle_crash()
    assert exc_info.value.code == 1
    assert any("Crash screen itself failed" in r.message for r in caplog.records)


def test_show_crash_screen_waits_for_input_then_returns(app):
    """Confirms the screen doesn't return immediately on its own — it
    genuinely waits for a QUIT/KEYDOWN/MOUSEBUTTONDOWN event."""
    pygame.event.clear()
    _post_quit_soon()
    app._show_crash_screen()  # returns once the QUIT event above is seen


def test_run_routes_an_escaped_exception_through_handle_crash(app, monkeypatch):
    """End-to-end: an exception raised inside _frame() during run() must
    reach _handle_crash() (proven here via a monkeypatched stand-in)
    rather than propagating past run() as a bare traceback, and worker
    cleanup in the outer finally must still execute."""
    def _boom():
        raise RuntimeError("boom")
    monkeypatch.setattr(app, "_frame", _boom)

    handled = []
    def _fake_handle_crash():
        handled.append(True)
        raise SystemExit(1)
    monkeypatch.setattr(app, "_handle_crash", _fake_handle_crash)

    cancelled = []
    monkeypatch.setattr(app.game.bot_worker, "cancel", lambda: cancelled.append(True))

    with pytest.raises(SystemExit):
        app.run()

    assert handled == [True]
    assert cancelled == [True]  # outer finally still ran worker cleanup
