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
    # Time-control preset picker, reached from OPPONENT_PICK when the user
    # chooses to play a fresh PvP game (no existing save). Bot games never
    # pass through this screen - time controls are PvP-only.
    TIME_CONTROL_PICK = "time_control_pick"
    PVP = "pvp"
    BOT = "bot"
    # Engine-vs-engine setup screen: pick each side's engine (native depth
    # or Stockfish ELO) before starting a headless-style match rendered on
    # the normal board. Reached from OPPONENT_PICK's third card, mirroring
    # how COLOR_PICK/DIFFICULTY lead into BOT.
    ENGINE_SETUP = "engine_setup"
    ENGINE_MATCH = "engine_match"


# Allowed transitions: from_state -> set of to_states it may move to.
_ALLOWED: dict[GameState, set[GameState]] = {
    GameState.MENU: {GameState.OPPONENT_PICK, GameState.PREFERENCES},
    GameState.OPPONENT_PICK: {
        GameState.MENU, GameState.TIME_CONTROL_PICK, GameState.COLOR_PICK,
        GameState.ENGINE_SETUP,
    },
    GameState.TIME_CONTROL_PICK: {GameState.OPPONENT_PICK, GameState.PVP},
    GameState.COLOR_PICK: {
        GameState.MENU, GameState.OPPONENT_PICK,
        GameState.DIFFICULTY, GameState.STOCKFISH_DIFFICULTY,
    },
    GameState.DIFFICULTY: {GameState.COLOR_PICK, GameState.BOT},
    GameState.STOCKFISH_DIFFICULTY: {GameState.COLOR_PICK, GameState.BOT},
    GameState.ENGINE_SETUP: {GameState.OPPONENT_PICK, GameState.ENGINE_MATCH},
    # PREFERENCES is also reachable mid-game (from the in-game menu overlay,
    # see App._handle_main_menu_overlay_event) and returns to whichever of
    # PVP/BOT it was opened from, tracked out-of-band on
    # Game.preferences_return_state since the transition table itself has
    # no notion of "return to caller".
    GameState.PREFERENCES: {GameState.MENU, GameState.PVP, GameState.BOT},
    GameState.PVP: {GameState.MENU, GameState.PREFERENCES},
    GameState.BOT: {GameState.MENU, GameState.PREFERENCES},
    # No PREFERENCES mid-match: an engine-vs-engine game has no in-game menu
    # overlay (no save/resign/draw-offer semantics apply to it — see
    # App._handle_engine_match_event), so its only way out is to the menu.
    GameState.ENGINE_MATCH: {GameState.MENU},
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
