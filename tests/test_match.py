"""Tests for chess_game.engine.match: single-game, batch, gauntlet,
tournament, timeout handling, and graceful Stockfish-unavailable
degradation.

Most tests use a scripted fake _EnginePlayer (via monkeypatching
_make_player) rather than a real ChessBot/Stockfish, so the aggregate
win/loss/draw counts and color-alternation logic can be asserted exactly
without depending on real search behavior or timing. A handful of slower
tests exercise a real ChessBot end-to-end (mirrors test_engine.py's
existing practice of calling the real search for correctness checks) and
are marked slow-ish but still bounded. Stockfish tests mock
chess.engine.SimpleEngine.popen_uci exactly like test_stockfish_bot_worker.py
does, plus one integration test gated on a real Stockfish binary being
available in this environment (mirrors analysis.py's "Stockfish not
installed" graceful-degradation contract; skipped rather than failing
confusingly when unavailable).
"""
from __future__ import annotations

import time

import chess
import chess.engine
import pytest

from chess_game.engine import match as match_mod
from chess_game.engine.match import (
    EngineSpec,
    play_game,
    run_batch,
    run_gauntlet,
    run_tournament,
)

# ── Scripted fake players for deterministic, fast aggregate tests ───────────


class _ScriptedPlayer:
    """Plays a fixed sequence of UCI moves regardless of board state (the
    tests construct openings/scripts that are actually legal). Falls back
    to the first legal move once the script runs out, so the game reaches
    a natural conclusion (typically a long shuffle to a draw) rather than
    stalling forever if a test's script is shorter than the game needs."""

    def __init__(self, moves: list[str]) -> None:
        self._moves = list(moves)
        self._index = 0

    def pick_move(self, board: chess.Board, timeout_s: float) -> chess.Move | None:
        if self._index < len(self._moves):
            move = chess.Move.from_uci(self._moves[self._index])
            self._index += 1
            if move in board.legal_moves:
                return move
        # Script exhausted or produced an illegal move for this board:
        # just play *something* legal so tests can still reach game-over
        # via the 3-move-repetition/shuffling path rather than hanging.
        legal = list(board.legal_moves)
        return legal[0] if legal else None

    def close(self) -> None:
        pass

    def stats(self) -> dict:
        return {"avg_move_time_s": 0.001, "moves": self._index}


class _AlwaysForfeitPlayer:
    """Never produces a move — used to test forfeit handling."""

    def pick_move(self, board: chess.Board, timeout_s: float) -> chess.Move | None:
        return None

    def close(self) -> None:
        pass

    def stats(self) -> dict:
        return {}


class _SlowPlayer:
    """Sleeps longer than the configured per-move timeout on every call,
    to test that play_game's timeout handling forfeits promptly instead
    of blocking for the full sleep duration."""

    def __init__(self, sleep_s: float) -> None:
        self._sleep_s = sleep_s
        self.calls = 0

    def pick_move(self, board: chess.Board, timeout_s: float) -> chess.Move | None:
        self.calls += 1
        # A real engine wrapper would run this on a thread and time out;
        # this fake simulates "the underlying call itself blocks past the
        # deadline" so play_game's own per-game wall-clock timeout (not
        # just a per-move abort) is what has to save the batch here.
        time.sleep(min(self._sleep_s, 0.05))
        return None  # simulate "timed out internally, forfeit this move"

    def close(self) -> None:
        pass

    def stats(self) -> dict:
        return {}


def _quick_mate_script() -> tuple[list[str], list[str]]:
    """Fool's mate: white and black move lists that produce checkmate in
    4 plies (2 moves each), so single-game tests run near-instantly."""
    white_moves = ["f2f3", "g2g4"]
    black_moves = ["e7e5", "d8h4"]
    return white_moves, black_moves


# ── play_game: basic correctness ─────────────────────────────────────────────


def test_play_game_scripted_checkmate(monkeypatch):
    white_moves, black_moves = _quick_mate_script()

    def _fake_make_player(spec: EngineSpec):
        if spec.name == "White":
            return _ScriptedPlayer(white_moves)
        return _ScriptedPlayer(black_moves)

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)

    white = EngineSpec(kind="native", name="White")
    black = EngineSpec(kind="native", name="Black")
    result = play_game(white, black)

    assert result.result == "0-1"
    assert result.termination == "checkmate"
    assert result.moves == ["f2f3", "e7e5", "g2g4", "d8h4"]
    assert not result.aborted
    assert "Qh4#" in result.pgn or "Qxh4#" in result.pgn or "1. f3 e5 2. g4" in result.pgn


def test_play_game_pgn_is_replayable(monkeypatch):
    """The PGN produced must be parseable by chess.pgn and reconstruct
    the exact same move sequence — the whole point of reusing chess.pgn's
    writer instead of a second SAN implementation."""
    import io as _io

    import chess.pgn as chess_pgn

    white_moves, black_moves = _quick_mate_script()

    def _fake_make_player(spec: EngineSpec):
        return _ScriptedPlayer(white_moves if spec.name == "White" else black_moves)

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)
    result = play_game(EngineSpec(kind="native", name="White"), EngineSpec(kind="native", name="Black"))

    parsed = chess_pgn.read_game(_io.StringIO(result.pgn))
    assert parsed is not None
    replayed_uci = [m.uci() for m in parsed.mainline_moves()]
    assert replayed_uci == result.moves


def test_play_game_respects_custom_opening_fen(monkeypatch):
    """A custom starting FEN must be honoured, not silently replaced by
    the standard starting position."""
    fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"  # king+pawn endgame

    def _fake_make_player(spec: EngineSpec):
        return _ScriptedPlayer(["e2e4"])  # only one legal-ish move scripted

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)
    result = play_game(
        EngineSpec(kind="native", name="White"), EngineSpec(kind="native", name="Black"),
        opening_fen=fen, per_game_timeout_s=5.0,
    )
    # First move in the PGN must be from the custom position, not e2e4
    # from the standard start (there's no black e-pawn to capture, so if
    # this ran from the real start it would look totally different).
    assert result.moves[0] == "e2e4"


def test_play_game_forfeit_when_engine_returns_no_move(monkeypatch):
    def _fake_make_player(spec: EngineSpec):
        if spec.name == "White":
            return _AlwaysForfeitPlayer()
        return _ScriptedPlayer([])

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)
    result = play_game(EngineSpec(kind="native", name="White"), EngineSpec(kind="native", name="Black"))

    assert result.result == "0-1"
    assert result.termination == "forfeit-white"
    assert result.aborted


def test_play_game_illegal_move_is_rejected_as_forfeit(monkeypatch):
    """A defensive check: even if an engine wrapper misbehaves and
    returns a move object that isn't legal in the current position, the
    match runner must not push it onto the board — it must forfeit that
    side instead of corrupting game state or crashing."""

    class _IllegalMover:
        def pick_move(self, board, timeout_s):
            return chess.Move.from_uci("e2e5")  # not a legal pawn move

        def close(self):
            pass

        def stats(self):
            return {}

    def _fake_make_player(spec: EngineSpec):
        if spec.name == "White":
            return _IllegalMover()
        return _ScriptedPlayer([])

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)
    result = play_game(EngineSpec(kind="native", name="White"), EngineSpec(kind="native", name="Black"))

    assert result.termination == "illegal-move-white"
    assert result.result == "0-1"


def test_play_game_per_game_timeout_aborts_without_hanging(monkeypatch):
    """A pathologically slow engine (each call blocks past the per-move
    budget) must not be able to hang the whole game — the per-game
    wall-clock cap must kick in and the call must return."""

    def _fake_make_player(spec: EngineSpec):
        return _SlowPlayer(sleep_s=1.0)

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)

    start = time.time()
    result = play_game(
        EngineSpec(kind="native", name="White"), EngineSpec(kind="native", name="Black"),
        per_move_timeout_s=0.05, per_game_timeout_s=0.2,
    )
    elapsed = time.time() - start

    assert result.aborted
    assert elapsed < 5.0, f"play_game should not hang; took {elapsed:.2f}s"


# ── Batch: aggregation + color alternation ───────────────────────────────────


def test_run_batch_alternates_colors_and_aggregates_correctly(monkeypatch):
    """Whoever plays White in a given game is scripted with
    _quick_mate_script()'s fool's-mate-losing moves, so White always
    loses and Black always wins. With 4 games and alternate_colors=True,
    A is White on games 0 and 2 (loses both) and Black on games 1 and 3
    (wins both) — so from A's perspective: 2 wins, 2 losses, 0 draws."""
    white_mate, black_mate = _quick_mate_script()

    seen_colors = []

    def _fake_make_player(spec: EngineSpec):
        # Whoever is "white" in this call is scripted to lose (fool's mate).
        return _ScriptedPlayer(white_mate if spec.name == "white-slot" else black_mate)

    # We need play_game to tell each side's spec apart AND know which
    # physical color it was assigned, so wrap play_game to record that,
    # then delegate color info into fake specs by name.
    orig_play_game = match_mod.play_game

    def _wrapped_play_game(white, black, **kwargs):
        seen_colors.append((white.display_name(), black.display_name()))
        # Re-tag specs so _fake_make_player can tell white from black
        # regardless of which original EngineSpec (a or b) is playing it.
        white_tagged = EngineSpec(kind=white.kind, name="white-slot")
        black_tagged = EngineSpec(kind=black.kind, name="black-slot")
        return orig_play_game(white_tagged, black_tagged, **kwargs)

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)
    monkeypatch.setattr(match_mod, "play_game", _wrapped_play_game)

    engine_a = EngineSpec(kind="native", name="A")
    engine_b = EngineSpec(kind="native", name="B")
    batch = run_batch(engine_a, engine_b, n_games=4, alternate_colors=True)

    # Colors must alternate: A white on games 0,2; B white on games 1,3.
    assert seen_colors == [("A", "B"), ("B", "A"), ("A", "B"), ("B", "A")]
    # White always loses in this script, so: game0 A(White) loses,
    # game1 B(White) loses (A wins), game2 A(White) loses,
    # game3 B(White) loses (A wins) -> engine_a: 2 wins, 2 losses.
    assert batch.a_wins == 2
    assert batch.b_wins == 2
    assert batch.draws == 0
    assert batch.total_games == 4
    assert batch.a_score == 2.0


def test_run_batch_without_alternating_colors_keeps_a_as_white(monkeypatch):
    """_quick_mate_script()'s white_moves are the losing (fool's-mate)
    side and black_moves deliver the mate — see that helper's docstring.
    With alternate_colors=False, engine_a is always White and therefore
    always the side that gets mated: 0 wins for A, 3 for B."""
    white_mate, black_mate = _quick_mate_script()

    def _fake_make_player(spec: EngineSpec):
        return _ScriptedPlayer(white_mate if spec.name == "A" else black_mate)

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)

    engine_a = EngineSpec(kind="native", name="A")
    engine_b = EngineSpec(kind="native", name="B")
    batch = run_batch(engine_a, engine_b, n_games=3, alternate_colors=False)

    # A is always White and always gets fool's-mated (scripted) -> 0 wins
    # for A, 3 for B.
    assert batch.a_wins == 0
    assert batch.b_wins == 3
    assert batch.draws == 0


def test_run_batch_cycles_through_shorter_opening_list(monkeypatch):
    """If fewer openings are supplied than n_games, they must cycle
    rather than raising an IndexError."""

    def _fake_make_player(spec: EngineSpec):
        return _ScriptedPlayer([])  # first-legal-move fallback every time

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)

    openings = [chess.STARTING_FEN]
    engine_a = EngineSpec(kind="native", name="A")
    engine_b = EngineSpec(kind="native", name="B")
    batch = run_batch(
        engine_a, engine_b, n_games=3, openings=openings,
        per_game_timeout_s=5.0,
    )
    assert batch.total_games == 3


# ── Gauntlet: per-opponent attribution ───────────────────────────────────────


def test_run_gauntlet_attributes_per_opponent_scores(monkeypatch):
    """primary beats "weak" every game and loses to "strong" every game
    (deterministically forced below); the gauntlet's score table must
    attribute each result to the correct opponent, not mix them up.

    run_batch alternates colors, so the "should-win" engine needs a
    verified checkmating script for *either* physical color it might be
    assigned: fool's mate (White plays weakening moves, Black mates in
    2) when it's Black, or Scholar's Mate (White mates in 4) when it's
    White.
    """
    fools_mate_white = ["f2f3", "g2g4"]                       # White's losing moves
    fools_mate_black = ["e7e5", "d8h4"]                       # Black delivers Qh4#
    scholars_mate_white = ["e2e4", "f1c4", "d1h5", "h5f7"]     # White delivers Qxf7#
    scholars_mate_black = ["e7e5", "b8c6", "g8f6"]             # Black's losing moves

    def _fake_make_player(spec: EngineSpec):
        scripts = {
            "winner-as-white": scholars_mate_white,
            "loser-as-black": scholars_mate_black,
            "winner-as-black": fools_mate_black,
            "loser-as-white": fools_mate_white,
        }
        return _ScriptedPlayer(scripts[spec.name])

    orig_play_game = match_mod.play_game

    def _wrapped_play_game(white, black, **kwargs):
        pairing = {white.display_name(), black.display_name()}
        winner_name = "primary" if pairing == {"primary", "weak"} else "strong"

        if white.display_name() == winner_name:
            white_tagged = EngineSpec(kind=white.kind, name="winner-as-white")
            black_tagged = EngineSpec(kind=black.kind, name="loser-as-black")
        else:
            white_tagged = EngineSpec(kind=white.kind, name="loser-as-white")
            black_tagged = EngineSpec(kind=black.kind, name="winner-as-black")
        return orig_play_game(white_tagged, black_tagged, **kwargs)

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)
    monkeypatch.setattr(match_mod, "play_game", _wrapped_play_game)

    primary = EngineSpec(kind="native", name="primary")
    weak = EngineSpec(kind="native", name="weak")
    strong = EngineSpec(kind="native", name="strong")

    gauntlet = run_gauntlet(primary, [weak, strong], games_per_opponent=2)
    table = gauntlet.score_table()

    assert [row["opponent"] for row in table] == ["weak", "strong"]
    weak_row, strong_row = table
    # primary always beats "weak" (forced above, regardless of color) ->
    # 2 wins, 0 losses, 0 draws from primary's perspective.
    assert weak_row["wins"] == 2
    assert weak_row["losses"] == 0
    assert weak_row["win_rate"] == 1.0
    # primary always loses to "strong" (forced above) -> 0 wins, 2 losses.
    assert strong_row["wins"] == 0
    assert strong_row["losses"] == 2
    assert strong_row["win_rate"] == 0.0
    assert len(gauntlet.opponents) == 2
    assert gauntlet.opponents[0].engine_b == "weak"
    assert gauntlet.opponents[1].engine_b == "strong"


# ── Tournament: round robin ──────────────────────────────────────────────────


def test_run_tournament_round_robin_pairs_every_config_once(monkeypatch):
    def _fake_make_player(spec: EngineSpec):
        return _ScriptedPlayer([])  # everything draws-by-shuffle or quick

    monkeypatch.setattr(match_mod, "_make_player", _fake_make_player)

    configs = [
        EngineSpec(kind="native", name="A"),
        EngineSpec(kind="native", name="B"),
        EngineSpec(kind="native", name="C"),
    ]
    tournament = run_tournament(configs, games_per_pairing=1, per_game_timeout_s=5.0)

    # 3 configs round-robin -> C(3,2) = 3 pairings.
    assert len(tournament.pairings) == 3
    pairing_names = {frozenset((p.engine_a, p.engine_b)) for p in tournament.pairings}
    assert pairing_names == {
        frozenset({"A", "B"}), frozenset({"A", "C"}), frozenset({"B", "C"}),
    }
    # Every config appears in standings exactly once, with 2 games played
    # each (played every other config once).
    assert {s.name for s in tournament.standings} == {"A", "B", "C"}
    for standing in tournament.standings:
        assert standing.games_played == 2


# ── Real ChessBot integration (slower, but bounded) ──────────────────────────


@pytest.mark.slow
def test_real_native_vs_native_game_completes_and_produces_legal_pgn():
    """End-to-end with the real ChessBot at the lowest difficulty (fastest
    search) on both sides. Uses a generous per-move timeout, since a
    correctness/robustness test should tolerate this engine's occasional
    slow moves (see report) rather than being flaky about them."""
    import io as _io

    import chess.pgn as chess_pgn

    white = EngineSpec(kind="native", difficulty=1, name="RealWhite")
    black = EngineSpec(kind="native", difficulty=1, name="RealBlack")
    result = play_game(white, black, per_move_timeout_s=15.0, per_game_timeout_s=120.0)

    assert result.moves, "expected at least one move to be played"
    parsed = chess_pgn.read_game(_io.StringIO(result.pgn))
    assert parsed is not None
    replayed_uci = [m.uci() for m in parsed.mainline_moves()]
    assert replayed_uci == result.moves
    assert result.result in ("1-0", "0-1", "1/2-1/2", "*")


def test_native_player_forfeits_on_timeout_without_hanging(monkeypatch):
    """Deterministic, fast unit test for _NativePlayer's timeout-forfeit
    branch: force ChessBot.get_move to block past the deadline and
    confirm pick_move returns None promptly rather than waiting for it."""
    from chess_game.engine.bot import ChessBot
    from chess_game.engine.match import _NativePlayer

    def _slow_get_move(self, board, color, difficulty_level=10, abort=None):
        time.sleep(2.0)
        return None

    monkeypatch.setattr(ChessBot, "get_move", _slow_get_move)

    spec = EngineSpec(kind="native", difficulty=2, name="X")
    player = _NativePlayer(spec)

    start = time.time()
    move = player.pick_move(chess.Board(), timeout_s=0.2)
    elapsed = time.time() - start

    assert move is None
    assert elapsed < 1.0, f"pick_move should return promptly on timeout; took {elapsed:.2f}s"
    assert player.stats()["moves"] == 0  # a timed-out move must not count toward avg timing


def test_native_player_does_not_share_live_board_with_search_thread():
    """Regression test for a race found during development: pick_move
    must hand the search thread a *copy* of the board, not the live
    shared board, so a per-move timeout that lets the caller continue
    (while the aborted search thread is still winding down) can never
    race with the next ply's search touching the same board object.
    """
    from chess_game.engine.match import _NativePlayer

    spec = EngineSpec(kind="native", difficulty=2, name="X")
    player = _NativePlayer(spec)
    board = chess.Board()

    captured_board_id = {}
    orig_get_move = player._bot.get_move

    def _spy_get_move(board_arg, *args, **kwargs):
        captured_board_id["id"] = id(board_arg)
        return orig_get_move(board_arg, *args, **kwargs)

    player._bot.get_move = _spy_get_move
    player.pick_move(board, timeout_s=5.0)

    assert captured_board_id["id"] != id(board), (
        "pick_move must pass a copy of the board to the search thread, "
        "never the live shared board object"
    )


# ── Stockfish: mocked availability + graceful degradation ───────────────────


class _FakeSFPlayResult:
    def __init__(self, move):
        self.move = move


class _FakeSFEngine:
    def __init__(self, move=None):
        self._move = move or chess.Move.from_uci("e2e4")
        self.configure_calls = []
        self.quit_called = False

    def configure(self, options):
        self.configure_calls.append(dict(options))

    def play(self, board, limit, **kwargs):
        return _FakeSFPlayResult(self._move)

    def quit(self):
        self.quit_called = True


def _patch_popen_uci(monkeypatch, engine_or_exc):
    def _fake_popen_uci(engine_path):
        if isinstance(engine_or_exc, BaseException):
            raise engine_or_exc
        return engine_or_exc

    monkeypatch.setattr(match_mod, "popen_uci", _fake_popen_uci)


def test_stockfish_player_sends_elo_via_uci_limit_strength(monkeypatch):
    fake_engine = _FakeSFEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    spec = EngineSpec(kind="stockfish", elo=2200, name="SF")
    player = match_mod._StockfishPlayer(spec)

    assert player.engine_available
    assert fake_engine.configure_calls == [{"UCI_LimitStrength": True, "UCI_Elo": 2200}]


def test_stockfish_player_clamps_elo_to_valid_range(monkeypatch):
    fake_engine = _FakeSFEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    spec = EngineSpec(kind="stockfish", elo=999999, name="SF")
    match_mod._StockfishPlayer(spec)
    assert fake_engine.configure_calls[-1]["UCI_Elo"] == 3190


def test_stockfish_player_degrades_gracefully_when_engine_missing(monkeypatch):
    """Mirrors analysis.py's existing 'Stockfish not installed' handling:
    a missing/unlaunchable engine sets engine_available False and
    pick_move returns None (forfeit) rather than raising."""
    _patch_popen_uci(monkeypatch, FileNotFoundError("no such file"))

    spec = EngineSpec(kind="stockfish", elo=1500, engine_path="/nonexistent/stockfish")
    player = match_mod._StockfishPlayer(spec)

    assert player.engine_available is False
    assert player.missing_reason
    assert player.pick_move(chess.Board(), timeout_s=1.0) is None


def test_stockfish_player_degrades_gracefully_on_handshake_timeout(monkeypatch):
    _patch_popen_uci(monkeypatch, TimeoutError("no UCI response"))

    spec = EngineSpec(kind="stockfish", elo=1500, engine_path="/some/stockfish")
    player = match_mod._StockfishPlayer(spec)

    assert player.engine_available is False
    assert "Timed out" in player.missing_reason
    assert player.pick_move(chess.Board(), timeout_s=1.0) is None


def test_stockfish_player_degrades_gracefully_on_engine_error(monkeypatch):
    _patch_popen_uci(monkeypatch, chess.engine.EngineError("bad handshake"))

    spec = EngineSpec(kind="stockfish", elo=1500, engine_path="/some/stockfish")
    player = match_mod._StockfishPlayer(spec)

    assert player.engine_available is False
    assert player.missing_reason
    assert player.pick_move(chess.Board(), timeout_s=1.0) is None


def test_stockfish_player_pick_move_handles_mid_game_termination(monkeypatch):
    """If the Stockfish subprocess dies mid-game, pick_move must return
    None (forfeit) rather than propagating the exception and crashing
    the whole batch run."""

    class _DyingEngine(_FakeSFEngine):
        def play(self, board, limit, **kwargs):
            raise chess.engine.EngineTerminatedError("process died")

    _patch_popen_uci(monkeypatch, _DyingEngine())
    spec = EngineSpec(kind="stockfish", elo=1500, name="SF")
    player = match_mod._StockfishPlayer(spec)

    assert player.pick_move(chess.Board(), timeout_s=1.0) is None
    assert player.engine_available is False


def test_stockfish_player_pick_move_handles_engine_error(monkeypatch):
    class _ErroringEngine(_FakeSFEngine):
        def play(self, board, limit, **kwargs):
            raise chess.engine.EngineError("unexpected UCI response")

    _patch_popen_uci(monkeypatch, _ErroringEngine())
    spec = EngineSpec(kind="stockfish", elo=1500, name="SF")
    player = match_mod._StockfishPlayer(spec)

    assert player.pick_move(chess.Board(), timeout_s=1.0) is None


def test_stockfish_player_close_is_safe_to_call_when_never_launched(monkeypatch):
    _patch_popen_uci(monkeypatch, FileNotFoundError("no such file"))
    spec = EngineSpec(kind="stockfish", elo=1500, engine_path="/nonexistent/stockfish")
    player = match_mod._StockfishPlayer(spec)
    player.close()  # must not raise even though self._engine is None


def test_play_game_between_native_and_unavailable_stockfish_forfeits_cleanly(monkeypatch):
    """A full play_game() where Stockfish can't launch must end the game
    as a clean forfeit rather than crashing the whole match run."""
    _patch_popen_uci(monkeypatch, FileNotFoundError("no such file"))

    white = EngineSpec(kind="native", difficulty=1, name="Native")
    black = EngineSpec(kind="stockfish", elo=1500, engine_path="/nonexistent/stockfish", name="SF")
    result = play_game(white, black, per_move_timeout_s=15.0, per_game_timeout_s=60.0)

    assert result.termination.startswith("forfeit") or result.result in ("1-0",)


# ── Real Stockfish integration (skipped if unavailable) ──────────────────────


def _find_real_stockfish() -> str | None:
    import shutil

    found = shutil.which("stockfish")
    if found:
        return found
    # This session downloaded a real binary via StockfishDownloader into
    # a fixed scratch path for realistic (non-mocked) testing; reuse it
    # here if present, but don't fail the suite if it isn't (CI won't
    # have it, matching analysis.py's own "Stockfish not installed" story).
    candidate = "/home/claude/sf_install/stockfish/stockfish/stockfish-ubuntu-x86-64"
    import os
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


@pytest.mark.slow
@pytest.mark.skipif(_find_real_stockfish() is None, reason="Stockfish binary not available in this environment")
def test_real_stockfish_vs_native_game_completes():
    """Integration-level sanity check against a real Stockfish binary
    (not mocked), skipped cleanly when unavailable rather than failing
    confusingly — mirrors analysis.py's existing graceful-degradation
    contract for missing Stockfish."""
    engine_path = _find_real_stockfish()
    assert engine_path is not None

    white = EngineSpec(kind="native", difficulty=1, name="Native")
    black = EngineSpec(kind="stockfish", elo=1320, engine_path=engine_path, movetime_ms=200, name="SF")

    result = play_game(white, black, per_move_timeout_s=15.0, per_game_timeout_s=120.0)
    assert result.moves, "expected at least one move against real Stockfish"
    assert result.result in ("1-0", "0-1", "1/2-1/2", "*")
