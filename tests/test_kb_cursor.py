"""Headless tests for keyboard-only board navigation.

These verify that:
  - The keyboard cursor is unset until the first WASD press (mouse-only
    players never see it).
  - WASD moves the cursor by one square, clamped to the board edges.
  - Enter/Space activates the cursor's square exactly like a mouse click
    (select, then move) would.
  - Board flips invert which screen direction each key moves toward, so
    "toward the top of the screen" stays constant regardless of
    orientation.
  - The cursor is ignored while it isn't the keyboard-owning side's turn
    in a BOT game, mirroring the existing mouse-click guard.
  - The cursor doesn't act while animating, reviewing, or mid-flip.
"""
from __future__ import annotations

import chess
import pygame
import pytest

from chess_game.app import App
from chess_game.review import enter_review
from chess_game.state import GameState


@pytest.fixture
def app(isolated_save_dir):
    pygame.display.quit()
    pygame.display.init()
    return App()


def _key(app: App, key: int) -> None:
    app._handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0), 0, 0)


def _finish_animation(app: App) -> None:
    if app.game.anim is not None:
        app.game.anim.start_ms = -10_000


def test_cursor_unset_until_first_keypress(app):
    app.game.state = GameState.PVP
    app.start_game()
    assert app.game.kb_cursor_sq is None


def test_w_moves_cursor_toward_top_of_screen(app):
    """From the White king's default starting square, 'w' should move the
    cursor toward the top of the screen (higher rank on-screen), matching
    the un-flipped board's normal White-at-bottom orientation."""
    app.game.state = GameState.PVP
    app.start_game()

    _key(app, pygame.K_w)
    first_sq = app.game.kb_cursor_sq
    assert first_sq is not None  # first press only initialises the cursor

    _key(app, pygame.K_w)
    second_sq = app.game.kb_cursor_sq
    assert chess.square_rank(second_sq) == chess.square_rank(first_sq) + 1
    assert chess.square_file(second_sq) == chess.square_file(first_sq)


def test_cursor_clamped_to_board_edges(app):
    app.game.state = GameState.PVP
    app.start_game()
    app.game.kb_cursor_sq = chess.A1

    _key(app, pygame.K_a)  # off the left edge
    assert chess.square_file(app.game.kb_cursor_sq) == 0
    _key(app, pygame.K_s)  # off the bottom edge
    assert chess.square_rank(app.game.kb_cursor_sq) == 0


def test_flipped_board_inverts_key_direction(app):
    """With the board flipped, 'w' must still move the cursor toward the
    top of the screen — which is now the opposite file/rank delta from the
    un-flipped case."""
    app.game.state = GameState.PVP
    app.start_game()
    app.game.board_flipped = True
    app.game.kb_cursor_sq = chess.D4

    _key(app, pygame.K_w)
    # Flipped: 'w' (screen-up) decreases the rank instead of increasing it.
    assert app.game.kb_cursor_sq == chess.D3


def test_enter_selects_then_moves_like_a_click(app):
    app.game.state = GameState.PVP
    app.start_game()

    app.game.kb_cursor_sq = chess.E2
    _key(app, pygame.K_RETURN)
    assert app.game.adapter.selected_square == chess.E2

    app.game.kb_cursor_sq = chess.E4
    _key(app, pygame.K_SPACE)

    assert app.game.adapter.san_history == ['e4']
    assert chess.Move.from_uci('e2e4') in app.game.adapter.board.move_stack


def test_enter_does_nothing_with_no_cursor(app):
    """Enter/Space before any WASD press must be a no-op, not a crash or an
    accidental move on some default square."""
    app.game.state = GameState.PVP
    app.start_game()
    assert app.game.kb_cursor_sq is None

    _key(app, pygame.K_RETURN)

    assert app.game.adapter.san_history == []
    assert app.game.kb_cursor_sq is None


def test_cursor_ignored_when_not_players_turn_in_bot_game(app):
    """Mirrors the existing bot_to_move guard on mouse clicks: pressing
    Enter on a square shouldn't select/move anything while the bot is
    about to move or thinking."""
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()
    # Force it to be Black's (the bot's) turn.
    app.game.adapter.board.push(chess.Move.from_uci('e2e4'))
    app.game.adapter.san_history.append('e4')

    app.game.kb_cursor_sq = chess.E7
    _key(app, pygame.K_RETURN)

    assert app.game.adapter.selected_square is None
    assert app.game.adapter.san_history == ['e4']


def test_cursor_ignored_during_review(app):
    app.game.state = GameState.PVP
    app.start_game()
    app.game.adapter.board.push(chess.Move.from_uci('e2e4'))
    app.game.adapter.san_history.append('e4')
    enter_review(app.game, 0)
    _finish_animation(app)

    _key(app, pygame.K_w)
    assert app.game.kb_cursor_sq is None


def test_left_right_still_scrub_review_and_are_not_claimed_by_cursor(app):
    """Left/Right must keep doing move-history scrubbing exactly as
    before; the new WASD handling must not intercept them."""
    app.game.state = GameState.PVP
    app.start_game()
    app.game.adapter.board.push(chess.Move.from_uci('e2e4'))
    app.game.adapter.san_history.append('e4')

    _key(app, pygame.K_LEFT)

    assert app.game.review.active
    assert app.game.kb_cursor_sq is None
