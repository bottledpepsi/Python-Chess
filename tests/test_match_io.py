"""Round-trip and corruption tests for chess_game.match_io — the
versioned results-storage module for match/batch/gauntlet/tournament
results, independent of chess_game.io's game-save schema."""
from __future__ import annotations

import json

import pytest

from chess_game import match_io
from chess_game.engine.match import (
    BatchResult,
    GameResult,
    GauntletResult,
    Standing,
    TournamentResult,
)


def test_write_read_game_result_roundtrip(isolated_save_dir):
    gr = GameResult(
        white="Native(d5)", black="Stockfish(1500)",
        moves=["e2e4", "e7e5"], result="1/2-1/2", termination="draw",
        pgn="(pgn text)",
    )
    match_io.write_game_result(gr)
    history = match_io.read_match_history(kind="game")

    assert len(history) == 1
    assert history[0]["white"] == "Native(d5)"
    assert history[0]["moves"] == ["e2e4", "e7e5"]
    assert history[0]["version"] == match_io.MATCH_SCHEMA_VERSION
    assert history[0]["kind"] == "game"


def test_write_read_batch_result_roundtrip(isolated_save_dir):
    batch = BatchResult(engine_a="A", engine_b="B", a_wins=2, b_wins=1, draws=1)
    match_io.write_batch_result(batch)
    history = match_io.read_match_history(kind="batch")

    assert len(history) == 1
    assert history[0]["a_wins"] == 2
    assert history[0]["b_wins"] == 1
    assert history[0]["draws"] == 1


def test_write_read_gauntlet_result_roundtrip(isolated_save_dir):
    inner_batch = BatchResult(engine_a="primary", engine_b="opp1", a_wins=1, b_wins=0, draws=0)
    gauntlet = GauntletResult(primary="primary", opponents=[inner_batch])
    match_io.write_gauntlet_result(gauntlet)
    history = match_io.read_match_history(kind="gauntlet")

    assert len(history) == 1
    assert history[0]["primary"] == "primary"
    assert history[0]["opponents"][0]["engine_b"] == "opp1"


def test_write_read_tournament_result_roundtrip(isolated_save_dir):
    standing = Standing(name="A", points=2.5, games_played=4, wins=2, losses=1, draws=1)
    tournament = TournamentResult(standings=[standing], pairings=[])
    match_io.write_tournament_result(tournament)
    history = match_io.read_match_history(kind="tournament")

    assert len(history) == 1
    assert history[0]["standings"][0]["name"] == "A"
    assert history[0]["standings"][0]["points"] == 2.5


def test_read_match_history_returns_empty_list_when_nothing_written(isolated_save_dir):
    assert match_io.read_match_history() == []


def test_read_match_history_filters_by_kind(isolated_save_dir):
    match_io.write_game_result(GameResult(white="A", black="B"))
    match_io.write_batch_result(BatchResult(engine_a="A", engine_b="B"))

    assert len(match_io.read_match_history(kind="game")) == 1
    assert len(match_io.read_match_history(kind="batch")) == 1
    assert len(match_io.read_match_history()) == 2


def test_read_match_history_sorted_oldest_to_newest(isolated_save_dir):
    match_io.write_game_result(GameResult(white="first", black="B"))
    match_io.write_game_result(GameResult(white="second", black="B"))
    match_io.write_game_result(GameResult(white="third", black="B"))

    history = match_io.read_match_history(kind="game")
    assert [h["white"] for h in history] == ["first", "second", "third"]


def test_corrupt_match_result_raises_not_silently_skipped(isolated_save_dir):
    from chess_game import io as save_io

    results_dir = save_io.get_save_dir() / "match_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "game_corrupt.json"
    with open(path, "w") as f:
        f.write("{not valid json")

    with pytest.raises(match_io.CorruptMatchResultError):
        match_io.read_match_history()


def test_unsupported_schema_version_raises(isolated_save_dir):
    from chess_game import io as save_io

    results_dir = save_io.get_save_dir() / "match_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "game_future.json"
    with open(path, "w") as f:
        json.dump({"version": 999, "kind": "game", "white": "A", "black": "B"}, f)

    with pytest.raises(match_io.CorruptMatchResultError):
        match_io.read_match_history()


def test_results_are_never_written_into_the_game_save_directory_directly(isolated_save_dir):
    """Match results must live in their own subdirectory/schema, never
    mixed into the same files chess_game.io uses for game saves (06's
    Affected Systems: 'own file, versioned, not mixed into game saves')."""
    from chess_game import io as save_io

    match_io.write_game_result(GameResult(white="A", black="B"))

    save_dir = save_io.get_save_dir()
    top_level_files = [p.name for p in save_dir.iterdir() if p.is_file()]
    # No match-result file should ever land directly in the save
    # directory root next to pvp.json/bot.json/etc — it must be under
    # the match_results subdirectory.
    assert not any(name.startswith(("game_", "batch_", "gauntlet_", "tournament_")) for name in top_level_files)
    assert (save_dir / "match_results").is_dir()
