"""Tests for keyboard access to the in-game action button row: Resign,
Offer Draw, Export PGN, the Analysis toggle, and Menu.

Before this, these five buttons — unlike every other screen in the app —
could only be clicked with a mouse, despite _focus_group_for_state's own
docstring calling out "PVP/BOT board" as the one place with no focusable
widgets. Tab now cycles this row (left to right, matching the on-screen
layout) and Enter/Space activates whichever one is focused, sharing the
exact same App._activate_ingame_action / InputHandler._activate_ingame_action
code path a mouse click already used — see test_app.py's existing
mouse-click tests for the same five buttons, which this file deliberately
does not duplicate, only extends with the keyboard path.
"""
from __future__ import annotations

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


def _key(app: App, key: int, mod: int = 0) -> None:
    app._handle_event(pygame.event.Event(pygame.KEYDOWN, key=key, mod=mod), 0, 0)


def _tab(app: App, shift: bool = False) -> None:
    _key(app, pygame.K_TAB, mod=pygame.KMOD_SHIFT if shift else 0)


def _focused_key(app: App):
    fg = app.game_focus
    if 0 <= fg.index < len(fg.widgets):
        return fg.widgets[fg.index].key
    return None


def test_tab_cycles_all_five_buttons_left_to_right(app):
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)  # populates the button rects and rebuilds game_focus

    expected_order = ['resign', 'draw', 'export', 'analysis', 'menu']
    seen = []
    for _ in expected_order:
        _tab(app)
        seen.append(_focused_key(app))
    assert seen == expected_order

    # One more Tab wraps back around to the first button.
    _tab(app)
    assert _focused_key(app) == 'resign'


def test_shift_tab_cycles_backwards(app):
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)

    _tab(app)  # resign
    _tab(app, shift=True)  # back to nothing focused... wraps to last
    assert _focused_key(app) == 'menu'


def test_enter_on_focused_menu_button_opens_main_menu_overlay(app):
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)

    for _ in range(5):  # cycle to 'menu' (last in the order)
        _tab(app)
    assert _focused_key(app) == 'menu'

    _key(app, pygame.K_RETURN)
    assert app.game.main_menu_overlay is True


def test_space_on_focused_analysis_button_toggles_analysis(app):
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)

    for _ in range(4):  # resign, draw, export, analysis
        _tab(app)
    assert _focused_key(app) == 'analysis'

    before = app.game.analysis_enabled
    _key(app, pygame.K_SPACE)
    assert app.game.analysis_enabled is not before


def test_enter_on_focused_resign_button_opens_confirm_dialog(app):
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.start_game()
    app._render(16)

    _tab(app)  # resign is first
    assert _focused_key(app) == 'resign'

    _key(app, pygame.K_RETURN)
    assert app.game.confirm_dialog is not None
    assert app.game.confirm_dialog['action'] == 'resign'
    assert app.game.game_over is False


def test_enter_on_focused_draw_button_opens_confirm_dialog(app):
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)

    _tab(app)  # resign
    _tab(app)  # draw
    assert _focused_key(app) == 'draw'

    _key(app, pygame.K_RETURN)
    assert app.game.confirm_dialog is not None
    assert app.game.confirm_dialog['action'] == 'draw'


def test_enter_on_focused_export_button_writes_pgn(app, tmp_path, monkeypatch):
    from chess_game import io as save_io

    app.game.state = GameState.PVP
    app.start_game()
    app.game.adapter.board.push(chess.Move.from_uci('e2e4'))
    app.game.adapter.san_history.append('e4')

    export_path = tmp_path / "exported.pgn"
    monkeypatch.setattr(save_io, "pgn_export_path", lambda: export_path)

    app._render(16)
    _tab(app)  # resign
    _tab(app)  # draw
    _tab(app)  # export
    assert _focused_key(app) == 'export'

    _key(app, pygame.K_RETURN)
    assert export_path.exists()
    assert "1. e4" in export_path.read_text()


def test_keyboard_and_mouse_activation_use_the_same_code_path(app):
    """Regression guard against the two input methods drifting apart:
    activating 'draw' via Tab+Enter must produce exactly the same
    confirm_dialog the existing mouse-click test (test_app.py) asserts
    for a direct click on the same button."""
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)

    from tests.test_app import _click
    pygame.display.quit()
    pygame.display.init()
    mouse_app = App()
    mouse_app.game.state = GameState.PVP
    mouse_app.start_game()
    mouse_app._render(16)
    _click(mouse_app, *mouse_app.draw_btn_ingame_rect.center)

    _tab(app)
    _tab(app)
    _key(app, pygame.K_RETURN)

    assert app.game.confirm_dialog == mouse_app.game.confirm_dialog


def test_focus_ring_only_drawn_for_the_focused_button(app):
    """Pixel-level check, not just index bookkeeping: after Tab, the
    FOCUS_RING colour must actually appear on the resign button's border
    and must not appear on the (unfocused) draw button's."""
    from chess_game.widgets import FOCUS_RING

    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)
    assert app.game_focus.index == -1  # nothing focused yet, no Tab pressed

    _tab(app)
    app._render(16)  # re-render with 'resign' now focused
    assert app.game_focus.widgets[app.game_focus.index].key == 'resign'

    resign_rect = app.resign_btn_ingame_rect
    draw_rect = app.draw_btn_ingame_rect
    resign_border_colors = {
        app.screen.get_at((x, y))[:3]
        for x in range(resign_rect.x, resign_rect.right)
        for y in (resign_rect.y, resign_rect.bottom - 1)
    }
    draw_border_colors = {
        app.screen.get_at((x, y))[:3]
        for x in range(draw_rect.x, draw_rect.right)
        for y in (draw_rect.y, draw_rect.bottom - 1)
    }
    assert FOCUS_RING in resign_border_colors
    assert FOCUS_RING not in draw_border_colors


def test_engine_match_has_no_game_focus_and_tab_is_a_no_op(app):
    """ENGINE_MATCH has no human player to resign/offer a draw for, so
    game_focus must be empty there, and Tab must not raise or focus a
    stale rect left over from a previous PVP/BOT game."""
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)
    _tab(app)
    assert _focused_key(app) == 'resign'

    app.game.state = GameState.ENGINE_MATCH
    app.start_game()
    app._render(16)

    assert app.game_focus.widgets == []
    assert app.game_focus.index == -1

    _tab(app)  # must not raise, and must not resurrect the old focus
    assert app.game_focus.widgets == []


def test_tab_then_enter_prefers_focused_button_over_board_cursor(app):
    """Enter/Space must activate a Tab-focused action button rather than
    being swallowed by the WASD board-cursor's own Enter/Space handling
    (see InputHandler._handle_kb_cursor_event) when both could plausibly
    claim the keypress."""
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)

    _key(app, pygame.K_w)  # arm the board cursor first
    assert app.game.kb_cursor_sq is not None

    _tab(app)  # then focus the first action button
    assert _focused_key(app) == 'resign'

    _key(app, pygame.K_RETURN)
    # The focused button's action fired, not a board move/selection.
    assert app.game.confirm_dialog is not None
    assert app.game.adapter.selected_square is None


def test_enter_still_drives_board_cursor_when_nothing_is_tab_focused(app):
    """The reverse of the above: with no Tab focus set, Enter must still
    reach the Change #1 keyboard board cursor exactly as before."""
    app.game.state = GameState.PVP
    app.start_game()
    app._render(16)
    assert app.game_focus.index == -1

    app.game.kb_cursor_sq = chess.E2
    _key(app, pygame.K_RETURN)
    assert app.game.adapter.selected_square == chess.E2
