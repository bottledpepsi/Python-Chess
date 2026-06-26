"""Enum state machine + transition table."""
from __future__ import annotations

import enum


class GameState(enum.Enum):
    MENU = "menu"
    OPPONENT_PICK = "opponent_pick"
    COLOR_PICK = "color_pick"
    DIFFICULTY = "difficulty"
    # Stockfish-specific ELO-slider sub-menu, reached instead of DIFFICULTY
    # when the user's bot engine preference is "stockfish" (see
    # Game.bot_engine_pref / App._handle_color_pick_event).
    STOCKFISH_DIFFICULTY = "stockfish_difficulty"
    PREFERENCES = "preferences"
    PVP = "pvp"
    BOT = "bot"


# Allowed transitions: from_state -> set of to_states it may move to.
_ALLOWED: dict[GameState, set[GameState]] = {
    GameState.MENU: {GameState.OPPONENT_PICK, GameState.PREFERENCES},
    GameState.OPPONENT_PICK: {GameState.MENU, GameState.PVP, GameState.COLOR_PICK},
    GameState.COLOR_PICK: {
        GameState.MENU, GameState.OPPONENT_PICK,
        GameState.DIFFICULTY, GameState.STOCKFISH_DIFFICULTY,
    },
    GameState.DIFFICULTY: {GameState.COLOR_PICK, GameState.BOT},
    GameState.STOCKFISH_DIFFICULTY: {GameState.COLOR_PICK, GameState.BOT},
    GameState.PREFERENCES: {GameState.MENU},
    GameState.PVP: {GameState.MENU},
    GameState.BOT: {GameState.MENU},
}


def can_transition(from_state: GameState, to_state: GameState) -> bool:
    return to_state in _ALLOWED.get(from_state, set())


def transition(game, new_state: GameState) -> None:
    """Move `game` to new_state.

    `game` is a chess_game.game.Game instance. Disallowed transitions are
    logged but not blocked outright, since some legitimate flows (e.g.
    same-state re-entry) aren't worth special-casing in the table.
    """
    if not can_transition(game.state, new_state):
        from chess_game.log import get_logger
        get_logger().warning(
            "Disallowed transition %s -> %s (proceeding anyway)",
            game.state, new_state
        )
    game.state = new_state
