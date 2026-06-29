"""Save/load round-trip and corrupt-save tests."""
from __future__ import annotations

import json

import chess
import pytest

from chess_game import io as save_io


def test_write_read_roundtrip_pvp(isolated_save_dir):
    moves = [chess.Move.from_uci(m) for m in ["e2e4", "e7e5", "g1f3"]]
    save_io.write_save("pvp", moves)
    data = save_io.read_save("pvp")
    assert data is not None
    assert data.mode == "pvp"
    assert data.moves == moves


def test_write_read_roundtrip_bot(isolated_save_dir):
    moves = [chess.Move.from_uci(m) for m in ["d2d4", "d7d5"]]
    save_io.write_save("bot", moves, color="black", level=7)
    data = save_io.read_save("bot")
    assert data is not None
    assert data.mode == "bot"
    assert data.color == "black"
    assert data.level == 7
    assert data.moves == moves


def test_read_save_returns_none_when_missing(isolated_save_dir):
    assert save_io.read_save("pvp") is None


def test_corrupt_save_raises_not_silently_truncates(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    path = save_dir / save_io.SAVE_FILENAMES["pvp"]
    payload = {"version": 1, "mode": "pvp", "moves": ["e2e4", "not_a_real_move_xyz"]}
    with open(path, "w") as f:
        json.dump(payload, f)

    with pytest.raises(save_io.CorruptSaveError):
        save_io.read_save("pvp")

    # The corrupt file must be left untouched - never silently rewritten shorter.
    with open(path) as f:
        still_there = json.load(f)
    assert still_there["moves"] == ["e2e4", "not_a_real_move_xyz"]


def test_corrupt_save_illegal_move_in_otherwise_valid_sequence_raises(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    path = save_dir / save_io.SAVE_FILENAMES["pvp"]
    # e2e4 legal, then e2e4 again is illegal (no piece there anymore)
    payload = {"version": 1, "mode": "pvp", "moves": ["e2e4", "e2e4"]}
    with open(path, "w") as f:
        json.dump(payload, f)

    with pytest.raises(save_io.CorruptSaveError):
        save_io.read_save("pvp")


def test_write_is_atomic_no_tmp_file_left_behind(isolated_save_dir):
    moves = [chess.Move.from_uci("e2e4")]
    save_io.write_save("pvp", moves)
    save_dir = save_io.get_save_dir()
    leftover_tmp_files = list(save_dir.glob("*.tmp"))
    assert leftover_tmp_files == []


def test_preferences_roundtrip(isolated_save_dir):
    save_io.write_preferences("white_blue", "yellow")
    prefs = save_io.read_preferences()
    assert prefs["board_theme"] == "white_blue"
    assert prefs["arrow_theme"] == "yellow"


def test_preferences_roundtrip_includes_stockfish_path(isolated_save_dir):
    save_io.write_preferences("white_green", "blue", stockfish_path="/opt/homebrew/bin/stockfish")
    prefs = save_io.read_preferences()
    assert prefs["stockfish_path"] == "/opt/homebrew/bin/stockfish"


def test_preferences_missing_stockfish_path_defaults_to_empty_string(isolated_save_dir):
    """A preferences file written before stockfish_path existed must still
    load cleanly, with the new field defaulting to "" (use PATH)."""
    save_dir = save_io.get_save_dir()
    legacy_payload = {
        "version": 1,
        "board_theme": "white_green",
        "arrow_theme": "blue",
        "reduced_motion": False,
        "fullscreen": False,
    }
    (save_dir / save_io.PREF_FILENAME).write_text(json.dumps(legacy_payload))

    prefs = save_io.read_preferences()
    assert prefs["stockfish_path"] == ""
    assert prefs["board_theme"] == "white_green"


def test_legacy_csv_save_migration(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    legacy_path = save_dir / save_io._LEGACY_SAVE_FILENAMES["bot"]
    legacy_path.write_text("mode=bot,color=black,level=8\ne2e4,e7e5\n")

    data = save_io.read_save("bot")
    assert data is not None
    assert data.color == "black"
    assert data.level == 8
    assert data.moves == [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]

    # Migration should have written the new JSON format and removed the old file.
    assert not legacy_path.exists()
    new_path = save_dir / save_io.SAVE_FILENAMES["bot"]
    assert new_path.exists()


def test_legacy_save_with_old_difficulty_key(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    legacy_path = save_dir / save_io._LEGACY_SAVE_FILENAMES["bot"]
    legacy_path.write_text("mode=bot,color=white,difficulty=3\ne2e4\n")
    data = save_io.read_save("bot")
    assert data.level == 3


def test_get_save_dir_creates_directory_with_owner_only_perms():
    """Real platformdirs path, created with 0700 on POSIX."""
    import stat
    import sys

    path = save_io.get_save_dir()
    assert path.is_dir()
    if sys.platform != "win32":
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o700


def test_read_preferences_returns_empty_dict_when_nothing_saved(isolated_save_dir):
    assert save_io.read_preferences() == {}


def test_delete_save_removes_file(isolated_save_dir):
    moves = [chess.Move.from_uci("e2e4")]
    save_io.write_save("pvp", moves)
    assert save_io.read_save("pvp") is not None
    save_io.delete_save("pvp")
    assert save_io.read_save("pvp") is None


def test_delete_save_on_nonexistent_save_is_a_noop(isolated_save_dir):
    save_io.delete_save("pvp")  # should not raise


def test_read_save_unsupported_schema_version_raises(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    path = save_dir / save_io.SAVE_FILENAMES["pvp"]
    with open(path, "w") as f:
        json.dump({"version": 999, "mode": "pvp", "moves": []}, f)
    with pytest.raises(save_io.CorruptSaveError):
        save_io.read_save("pvp")


def test_write_save_unknown_mode_is_a_noop_not_a_crash(isolated_save_dir):
    save_io.write_save("not_a_real_mode", [])  # should not raise


def test_empty_legacy_save_file_raises_corrupt(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    legacy_path = save_dir / save_io._LEGACY_SAVE_FILENAMES["pvp"]
    legacy_path.write_text("")
    with pytest.raises(save_io.CorruptSaveError):
        save_io.read_save("pvp")


def test_legacy_preferences_migration(isolated_save_dir):
    save_dir = save_io.get_save_dir()
    legacy_path = save_dir / save_io._LEGACY_PREF_FILENAME
    legacy_path.write_text("board_theme=white_red\narrow_theme=green\n")
    prefs = save_io.read_preferences()
    assert prefs["board_theme"] == "white_red"
    assert prefs["arrow_theme"] == "green"
    assert not legacy_path.exists()
    new_path = save_dir / save_io.PREF_FILENAME
    assert new_path.exists()


def _adapter_with_moves(ucis):
    from chess_game.adapter import ChessAdapter

    adapter = ChessAdapter()
    for uci in ucis:
        adapter.apply_move(chess.Move.from_uci(uci))
    return adapter


def test_export_pgn_roundtrips_moves(isolated_save_dir, tmp_path):
    import chess.pgn

    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]
    adapter = _adapter_with_moves(moves)
    path = tmp_path / "game.pgn"

    save_io.export_pgn(adapter, path)

    with open(path, encoding="utf-8") as f:
        parsed = chess.pgn.read_game(f)
    assert parsed is not None
    assert list(parsed.mainline_moves()) == [chess.Move.from_uci(m) for m in moves]


def test_export_pgn_sets_bot_headers_and_difficulty(isolated_save_dir, tmp_path):
    import chess.pgn

    adapter = _adapter_with_moves(["d2d4", "d7d5"])
    path = tmp_path / "bot_game.pgn"

    save_io.export_pgn(adapter, path, mode="bot", color="black", level=8)

    with open(path, encoding="utf-8") as f:
        parsed = chess.pgn.read_game(f)
    assert parsed is not None
    # color="black" means the human played Black, so the bot is White.
    assert parsed.headers["White"] == "Bot"
    assert parsed.headers["Black"] == "Player"
    assert parsed.headers["Difficulty"] == "8"


def test_export_pgn_pvp_has_no_difficulty_header(isolated_save_dir, tmp_path):
    import chess.pgn

    adapter = _adapter_with_moves(["e2e4"])
    path = tmp_path / "pvp_game.pgn"

    save_io.export_pgn(adapter, path, mode="pvp")

    with open(path, encoding="utf-8") as f:
        parsed = chess.pgn.read_game(f)
    assert parsed is not None
    assert "Difficulty" not in parsed.headers
    assert parsed.headers["White"] == "Player"
    assert parsed.headers["Black"] == "Player"


def test_export_pgn_records_in_progress_result_as_unfinished(isolated_save_dir, tmp_path):
    import chess.pgn

    adapter = _adapter_with_moves(["e2e4", "e7e5"])
    path = tmp_path / "in_progress.pgn"

    save_io.export_pgn(adapter, path)

    with open(path, encoding="utf-8") as f:
        parsed = chess.pgn.read_game(f)
    assert parsed.headers["Result"] == "*"


def test_pgn_export_path_lands_under_save_dir_pgn_subdir(isolated_save_dir):
    path = save_io.pgn_export_path()
    assert path.parent == save_io.get_save_dir() / save_io.PGN_SUBDIR
    assert path.suffix == ".pgn"
    assert path.parent.is_dir()


def test_save_resume_roundtrips_clock_state(isolated_save_dir):
    moves = [chess.Move.from_uci(m) for m in ["e2e4", "e7e5", "g1f3"]]
    save_io.write_save(
        "pvp", moves,
        time_control="3+2", white_time_ms=174_500, black_time_ms=178_200,
        active_side="black",
    )
    data = save_io.read_save("pvp")
    assert data is not None
    assert data.mode == "pvp"
    assert data.moves == moves
    assert data.time_control == "3+2"
    assert data.white_time_ms == 174_500
    assert data.black_time_ms == 178_200
    assert data.active_side == "black"


def test_save_resume_untimed_pvp_roundtrips_as_untimed(isolated_save_dir):
    """An untimed PvP game writes time_control=None explicitly (not just
    omitted), and must load back as untimed, not crash on missing fields."""
    moves = [chess.Move.from_uci("e2e4")]
    save_io.write_save("pvp", moves)  # all clock kwargs default to None
    data = save_io.read_save("pvp")
    assert data is not None
    assert data.time_control is None
    assert data.white_time_ms is None
    assert data.black_time_ms is None
    assert data.active_side is None


def test_v1_save_loads_as_untimed(isolated_save_dir):
    """A version-1 save predates time controls entirely - no time_control
    key exists in the payload at all. It must load with a clock-less
    SaveData rather than raising, and must NOT be rejected by the version
    check (version 1 is still >= MIN_SUPPORTED_SCHEMA_VERSION)."""
    save_dir = save_io.get_save_dir()
    path = save_dir / save_io.SAVE_FILENAMES["pvp"]
    payload = {"version": 1, "mode": "pvp", "moves": ["e2e4", "e7e5"]}
    with open(path, "w") as f:
        json.dump(payload, f)

    data = save_io.read_save("pvp")
    assert data is not None
    assert data.mode == "pvp"
    assert data.moves == [chess.Move.from_uci("e2e4"), chess.Move.from_uci("e7e5")]
    assert data.time_control is None
    assert data.white_time_ms is None
    assert data.black_time_ms is None
    assert data.active_side is None


def test_v1_bot_save_still_loads_color_and_level(isolated_save_dir):
    """Bot saves never had clock fields to begin with; a v1 bot save's
    existing color/level fields must still load correctly post-migration."""
    save_dir = save_io.get_save_dir()
    path = save_dir / save_io.SAVE_FILENAMES["bot"]
    payload = {"version": 1, "mode": "bot", "moves": ["d2d4"], "color": "black", "level": 8}
    with open(path, "w") as f:
        json.dump(payload, f)

    data = save_io.read_save("bot")
    assert data is not None
    assert data.color == "black"
    assert data.level == 8
    assert data.time_control is None


def test_bot_save_never_persists_clock_fields_even_if_passed(isolated_save_dir):
    """write_save's clock kwargs are documented as PvP-only; a bot-mode
    call must not write them to disk even if a caller passes them."""
    save_io.write_save(
        "bot", [], color="white", level=5,
        time_control="3+2", white_time_ms=100_000, black_time_ms=100_000, active_side="white",
    )
    save_dir = save_io.get_save_dir()
    path = save_dir / save_io.SAVE_FILENAMES["bot"]
    with open(path) as f:
        payload = json.load(f)
    assert "time_control" not in payload
    assert "white_time_ms" not in payload
    assert "black_time_ms" not in payload
    assert "active_side" not in payload


def test_preferences_roundtrip_includes_default_time_control(isolated_save_dir):
    save_io.write_preferences("white_blue", "yellow", default_time_control="5+0")
    prefs = save_io.read_preferences()
    assert prefs["default_time_control"] == "5+0"


def test_preferences_missing_default_time_control_defaults_to_none(isolated_save_dir):
    """A preferences file written before time controls existed must still
    load cleanly, with the new field defaulting to "none" (untimed)."""
    save_dir = save_io.get_save_dir()
    legacy_payload = {
        "version": 1,
        "board_theme": "white_green",
        "arrow_theme": "blue",
        "reduced_motion": False,
        "fullscreen": False,
    }
    (save_dir / save_io.PREF_FILENAME).write_text(json.dumps(legacy_payload))

    prefs = save_io.read_preferences()
    assert prefs["default_time_control"] == "none"
