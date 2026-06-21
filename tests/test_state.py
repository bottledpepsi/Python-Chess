"""State-machine transition table tests."""
from __future__ import annotations

from chess_game.state import GameState, can_transition


def test_menu_can_go_to_color_pick():
    assert can_transition(GameState.MENU, GameState.COLOR_PICK)


def test_menu_can_go_to_pvp():
    assert can_transition(GameState.MENU, GameState.PVP)


def test_menu_cannot_go_directly_to_bot():
    assert not can_transition(GameState.MENU, GameState.BOT)


def test_difficulty_can_go_to_bot():
    assert can_transition(GameState.DIFFICULTY, GameState.BOT)


def test_pvp_can_return_to_menu():
    assert can_transition(GameState.PVP, GameState.MENU)


def test_bot_cannot_go_to_pvp_directly():
    assert not can_transition(GameState.BOT, GameState.PVP)
