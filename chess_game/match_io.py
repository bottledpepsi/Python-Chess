"""Versioned, atomic persistence for engine-match-framework results.

Deliberately a separate file and a separate schema-version counter from
chess_game.io's SAVE_FILENAMES/SCHEMA_VERSION — match results are not
game saves and must never be confused with them (see 06's Affected
Systems: "own file, versioned, not mixed into game saves"). The
underlying atomic-write mechanics (_atomic_write_json, get_save_dir) are
imported and reused rather than re-implemented, so both stores share the
same crash-safety guarantees without duplicating that logic.

Layout on disk: get_save_dir() / "match_results" / <kind>_<timestamp>.json
one file per run, mirroring how io.pgn_export_path() gives each PGN
export its own timestamped file rather than overwriting a single slot —
match/gauntlet/tournament results are historical records 09 needs to read
back for trend tracking, not a single "current" save.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from chess_game import io as _save_io
from chess_game.log import get_logger

MATCH_SCHEMA_VERSION = 1
MIN_SUPPORTED_MATCH_SCHEMA_VERSION = 1

_RESULTS_SUBDIR = "match_results"


class CorruptMatchResultError(Exception):
    """Raised when a persisted match-result file exists but can't be
    parsed or carries an unsupported schema version. Mirrors
    io.CorruptSaveError's contract: never silently treated as absent."""


def _results_dir() -> Path:
    path = _save_io.get_save_dir() / _RESULTS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamped_path(kind: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return _results_dir() / f"{kind}_{stamp}.json"


def _write_result(kind: str, payload: dict[str, Any]) -> Path:
    logger = get_logger()
    path = _timestamped_path(kind)
    full_payload = {"version": MATCH_SCHEMA_VERSION, "kind": kind, **payload}
    try:
        _save_io._atomic_write_json(path, full_payload)
        logger.info("Match result saved (%s) -> %s", kind, path)
    except OSError:
        logger.exception("Failed to save match result (%s)", kind)
    return path


def write_game_result(result: Any) -> Path:
    """Persist a single GameResult (chess_game.engine.match.GameResult)."""
    return _write_result("game", asdict(result))


def write_batch_result(result: Any) -> Path:
    """Persist a BatchResult, including its per-game GameResults."""
    payload = asdict(result)
    return _write_result("batch", payload)


def write_gauntlet_result(result: Any) -> Path:
    """Persist a GauntletResult (a primary engine's per-opponent batches)."""
    payload = asdict(result)
    return _write_result("gauntlet", payload)


def write_tournament_result(result: Any) -> Path:
    """Persist a TournamentResult (round-robin standings + pairings)."""
    payload = asdict(result)
    return _write_result("tournament", payload)


def read_match_history(kind: str | None = None) -> list[dict[str, Any]]:
    """Read back all persisted results (optionally filtered to one
    `kind`: "game" | "batch" | "gauntlet" | "tournament"), sorted oldest
    to newest by filename timestamp, for trend tracking (this is what
    09_ELO_BENCHMARKING.md reads from).

    Raises CorruptMatchResultError for a file that exists but can't be
    parsed or carries an unsupported version — never silently skipped,
    matching io.read_save's "corruption is never treated as absence"
    contract. A missing directory (no results have ever been written) is
    not corruption and returns an empty list.
    """
    logger = get_logger()
    results_dir = _save_io.get_save_dir() / _RESULTS_SUBDIR
    if not results_dir.is_dir():
        return []

    history: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.exception("Failed to read match result at %s", path)
            raise CorruptMatchResultError(f"Could not read match result file: {exc}") from exc

        version = payload.get("version")
        if not isinstance(version, int) or not (
            MIN_SUPPORTED_MATCH_SCHEMA_VERSION <= version <= MATCH_SCHEMA_VERSION
        ):
            logger.exception("Unsupported match-result schema version %r at %s", version, path)
            raise CorruptMatchResultError(f"Unsupported match-result schema version: {version!r}")

        if kind is not None and payload.get("kind") != kind:
            continue
        history.append(payload)

    return history
