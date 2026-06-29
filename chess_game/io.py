"""Atomic, versioned save/load and preferences persistence.

Covers:
  - saves live in platformdirs.user_data_dir, not the OS temp dir.
  - corrupt saves raise CorruptSaveError instead of being swallowed.
  - writes are atomic (tempfile + os.replace) and carry a schema version.
  - user_data_dir gets 0700 perms on POSIX "for free".
  - export_pgn() writes a standalone .pgn for sharing/analysis elsewhere,
    independent of the JSON save format above.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import chess
import chess.pgn
import platformdirs

from chess_game.log import get_logger

if TYPE_CHECKING:
    from chess_game.adapter import ChessAdapter

SCHEMA_VERSION = 2
# Oldest save-file version this build can still read. Version 1 predates
# time controls entirely; such saves load as untimed (time_control=None).
MIN_SUPPORTED_SCHEMA_VERSION = 1

SAVE_FILENAMES = {
    "pvp": "python-chess_pvp_game.json",
    "bot": "python-chess_bot_game.json",
}
# Old hand-rolled CSV save filenames, kept for one-time migration.
_LEGACY_SAVE_FILENAMES = {
    "pvp": "python-chess_pvp_game.txt",
    "bot": "python-chess_bot_game.txt",
}
PREF_FILENAME = "python-chess_preferences.json"
_LEGACY_PREF_FILENAME = "python-chess_preferences.txt"

# PGN exports live in their own subdirectory of the save dir, since unlike
# saves/preferences there can be many of them (one per exported game) and
# they're meant to be found and opened by the user, not just round-tripped
# by this app.
PGN_SUBDIR = "pgn"


class CorruptSaveError(Exception):
    """Raised when a save file exists but cannot be parsed/validated."""


class UserFacingError(Exception):
    """An error whose message is safe and meaningful to show in the UI."""


@dataclass
class SaveData:
    mode: str                       # "pvp" or "bot"
    moves: list[chess.Move] = field(default_factory=list)
    color: str = "white"            # player's colour, bot mode only
    level: int = 5                  # bot difficulty 1-10, bot mode only
    # PvP-only clock fields. time_control is the preset name (e.g. "3+2"),
    # or None for an untimed PvP game and always for bot games. The two
    # *_time_ms fields are the remaining time at save time; active_side is
    # whichever side's clock should resume ticking.
    time_control: str | None = None
    white_time_ms: int | None = None
    black_time_ms: int | None = None
    active_side: str | None = None


def get_save_dir() -> Path:
    """Return (creating if needed) the per-user save directory.

    Uses platformdirs.user_data_dir, which on POSIX creates the directory
    with 0700 permissions — fixing the world-readable /tmp issue for free.
    """
    path = Path(platformdirs.user_data_dir("python-chess", appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass  # best-effort on platforms without POSIX perms (e.g. Windows)
    return path


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically via tempfile + os.replace."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def write_preferences(board_theme: str, arrow_theme: str, reduced_motion: bool = False,
                      fullscreen: bool = False, stockfish_path: str = "",
                      bot_engine_pref: str = "native", bot_elo: int = 1500,
                      default_time_control: str = "none") -> None:
    """Persist preferences atomically."""
    logger = get_logger()
    path = get_save_dir() / PREF_FILENAME
    payload = {
        "version": SCHEMA_VERSION,
        "board_theme": board_theme,
        "arrow_theme": arrow_theme,
        "reduced_motion": reduced_motion,
        "fullscreen": fullscreen,
        "stockfish_path": stockfish_path,
        # Which engine backs "Vs Bot": "native" (chess_game.engine.bot)
        # or "stockfish" (external UCI binary, strength-limited by ELO).
        "bot_engine_pref": bot_engine_pref,
        "bot_elo": bot_elo,
        # The user's preferred PvP time control, e.g. "3+2", or "none" for
        # untimed. PvP-only: never read when starting a bot game.
        "default_time_control": default_time_control,
    }
    try:
        _atomic_write_json(path, payload)
        logger.info("Preferences saved -> %s", path)
    except OSError:
        logger.exception("Failed to save preferences")


def read_preferences() -> dict[str, Any]:
    """Read preferences, migrating the legacy key=value text format if present."""
    logger = get_logger()
    save_dir = get_save_dir()
    path = save_dir / PREF_FILENAME
    legacy_path = save_dir / _LEGACY_PREF_FILENAME

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            prefs = {
                "board_theme": payload.get("board_theme", ""),
                "arrow_theme": payload.get("arrow_theme", ""),
                # Old preference files predate this field, so default to False.
                "reduced_motion": bool(payload.get("reduced_motion", False)),
                "fullscreen": bool(payload.get("fullscreen", False)),
                # Old preference files predate this field too; "" means
                # "use PATH / default" (see AnalysisWorker).
                "stockfish_path": str(payload.get("stockfish_path", "")),
                # Old preference files predate these two as well, so
                # default to the native engine at a mid-range ELO —
                # matches StockfishBotWorker.DEFAULT_ELO without importing
                # that module here just for one constant.
                "bot_engine_pref": str(payload.get("bot_engine_pref", "native")),
                "bot_elo": int(payload.get("bot_elo", 1500)),
                # Old preference files predate this field too; "none" means
                # untimed, matching the default when no preference exists.
                "default_time_control": str(payload.get("default_time_control", "none")),
            }
            logger.info("Preferences loaded <- %s | %s", path, prefs)
            return prefs
        except (OSError, json.JSONDecodeError, AttributeError):
            logger.exception("Failed to load preferences from %s", path)
            return {}

    if legacy_path.exists():
        legacy_prefs: dict[str, str] = {}
        try:
            with open(legacy_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    legacy_prefs[key.strip()] = value.strip()
            logger.info("Legacy preferences migrated <- %s | %s", legacy_path, legacy_prefs)
            write_preferences(
                legacy_prefs.get("board_theme", "white_green"),
                legacy_prefs.get("arrow_theme", "blue"),
            )
            try:
                legacy_path.unlink()
            except OSError:
                pass
            return legacy_prefs
        except OSError:
            logger.exception("Failed to migrate legacy preferences from %s", legacy_path)
            return {}

    logger.info("No preferences file found at %s", path)
    return {}


def write_save(mode: str, moves: list[chess.Move], color: str = "white", level: int = 5,
               time_control: str | None = None, white_time_ms: int | None = None,
               black_time_ms: int | None = None, active_side: str | None = None) -> None:
    """Persist a game atomically as versioned JSON.

    The four clock parameters are PvP-only; bot saves never carry clock
    state regardless of what's passed (mirrors the `mode == "bot"` guard
    already used for color/level below).
    """
    logger = get_logger()
    filename = SAVE_FILENAMES.get(mode)
    if filename is None:
        logger.warning("write_save: unknown mode %r", mode)
        return
    path = get_save_dir() / filename
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "mode": mode,
        "moves": [m.uci() for m in moves],
    }
    if mode == "bot":
        payload["color"] = color
        payload["level"] = level
    else:
        payload["time_control"] = time_control
        payload["white_time_ms"] = white_time_ms
        payload["black_time_ms"] = black_time_ms
        payload["active_side"] = active_side
    try:
        _atomic_write_json(path, payload)
    except OSError:
        logger.exception("Failed to save game (%s)", mode)


def pgn_export_path() -> Path:
    """Return a fresh, timestamped path for the next PGN export.

    Lives in get_save_dir()/PGN_SUBDIR so exports don't clutter the same
    directory as the JSON saves, and each export gets its own filename
    (unlike write_save, which always overwrites the one save slot for a
    given mode) since the user may want to keep more than one.
    """
    save_dir = get_save_dir() / PGN_SUBDIR
    save_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return save_dir / f"python-chess_{stamp}.pgn"


def export_pgn(
    adapter: ChessAdapter,
    path: Path,
    mode: str = "pvp",
    color: str = "white",
    level: int = 5,
) -> None:
    """Write *adapter*'s move history to *path* as a standard PGN file.

    Moves are taken from adapter.board.move_stack (not adapter.san_history)
    and re-rendered to SAN by chess.pgn's own writer, so the export doesn't
    depend on two independent SAN implementations staying in agreement.

    `mode`/`color`/`level` mirror write_save()'s parameters: for bot games
    the side the human isn't playing gets "Bot" in White/Black, and a
    non-standard "Difficulty" tag records the level — PGN readers that
    don't recognise an extra tag pair simply ignore it.

    Raises
    ------
    OSError
        Propagated from the write itself; callers should catch this the
        same way write_save()'s callers do (see app.py).
    """
    white = "Bot" if mode == "bot" and color != "white" else "Player"
    black = "Bot" if mode == "bot" and color == "white" else "Player"

    game = chess.pgn.Game()
    game.headers["White"] = white
    game.headers["Black"] = black
    game.headers["Date"] = date.today().strftime("%Y.%m.%d")
    game.headers["Result"] = adapter.board.result(claim_draw=True)
    if mode == "bot":
        game.headers["Difficulty"] = str(level)

    node: chess.pgn.GameNode = game
    for move in adapter.board.move_stack:
        node = node.add_variation(move)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        print(game, file=f)


def _validate_moves(raw_moves: list[str]) -> list[chess.Move]:
    """Replay UCI moves against a fresh board, raising CorruptSaveError on
    any parse failure or illegal move — never silently truncate."""
    board = chess.Board()
    moves: list[chess.Move] = []
    for uci in raw_moves:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as exc:
            raise CorruptSaveError(f"Invalid move notation: {uci!r}") from exc
        if move not in board.legal_moves:
            raise CorruptSaveError(f"Illegal move in saved game: {uci!r}")
        board.push(move)
        moves.append(move)
    return moves


def _read_legacy_save(path: Path) -> SaveData:
    """Parse the old hand-rolled CSV save format, validating fully."""
    with open(path, encoding="utf-8") as f:
        lines = f.read().strip().split("\n")
    if not lines or not lines[0]:
        raise CorruptSaveError("Empty legacy save file")

    meta: dict[str, str] = {}
    for part in lines[0].split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            meta[k.strip()] = v.strip()

    raw_mode = meta.get("mode", "pvp")
    raw_moves = lines[1].split(",") if len(lines) > 1 else []
    raw_moves = [m for m in raw_moves if m.strip()]
    moves = _validate_moves(raw_moves)

    if raw_mode == "bot":
        if "level" in meta:
            level = int(meta["level"])
        elif "difficulty" in meta:
            level = int(meta["difficulty"])
        else:
            level = 5
        return SaveData(mode="bot", moves=moves, color=meta.get("color", "white"), level=level)
    return SaveData(mode="pvp", moves=moves)


def read_save(mode: str) -> SaveData | None:
    """Read and fully validate a save file.

    Returns None only if no save exists. Raises CorruptSaveError (and logs
    via logger.exception) if a save exists but is malformed — this is never
    silently treated as "no save".
    """
    logger = get_logger()
    save_dir = get_save_dir()
    filename = SAVE_FILENAMES.get(mode)
    legacy_filename = _LEGACY_SAVE_FILENAMES.get(mode)
    if filename is None:
        return None
    path = save_dir / filename
    legacy_path = save_dir / legacy_filename if legacy_filename else None

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.exception("Failed to read save (%s) at %s", mode, path)
            raise CorruptSaveError(f"Could not read save file: {exc}") from exc

        version = payload.get("version")
        if not isinstance(version, int) or not (MIN_SUPPORTED_SCHEMA_VERSION <= version <= SCHEMA_VERSION):
            logger.exception("Unsupported save schema version %r at %s", version, path)
            raise CorruptSaveError(f"Unsupported save schema version: {version!r}")

        try:
            moves = _validate_moves(payload.get("moves", []))
        except CorruptSaveError:
            logger.exception("Corrupt save (%s) at %s", mode, path)
            raise

        if mode == "bot":
            data = SaveData(
                mode=mode, moves=moves,
                color=payload.get("color", "white"),
                level=int(payload.get("level", 5)),
            )
        else:
            # version 1 predates time controls entirely, so payload.get()
            # naturally yields None for all four fields -> untimed PvP,
            # exactly like a v2 save written with time_control=None.
            data = SaveData(
                mode=mode, moves=moves,
                time_control=payload.get("time_control"),
                white_time_ms=payload.get("white_time_ms"),
                black_time_ms=payload.get("black_time_ms"),
                active_side=payload.get("active_side"),
            )
        logger.info("Game loaded (%s) <- %s | %d moves", mode, path, len(moves))
        return data

    if legacy_path is not None and legacy_path.exists():
        try:
            data = _read_legacy_save(legacy_path)
        except CorruptSaveError:
            logger.exception("Corrupt legacy save (%s) at %s", mode, legacy_path)
            raise
        logger.info("Legacy game migrated (%s) <- %s", mode, legacy_path)
        write_save(mode, data.moves, data.color, data.level)
        try:
            legacy_path.unlink()
        except OSError:
            pass
        return data

    logger.info("No save file found for (%s) at %s", mode, path)
    return None


def delete_save(mode: str) -> None:
    logger = get_logger()
    save_dir = get_save_dir()
    for filename in (SAVE_FILENAMES.get(mode), _LEGACY_SAVE_FILENAMES.get(mode)):
        if not filename:
            continue
        path = save_dir / filename
        try:
            path.unlink()
            logger.info("Save deleted (%s) - %s", mode, path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Failed to delete save (%s)", mode)
