"""AnalysisWorker tests: engine-availability handling, epoch guarding, and
the pure eval-bar sigmoid helper.

Stockfish is not installed in CI, so every test mocks
chess.engine.SimpleEngine.popen_uci to return a small fake engine instead
of launching a real subprocess. The fake engine's .analysis() returns a
context-manager-compatible fake analysis stream whose .next() yields a
caller-supplied sequence of info dicts and then None (mirroring how the
real SimpleAnalysisResult.next() returns None once the search completes
or is stopped).
"""
from __future__ import annotations

import threading
import time

import chess
import chess.engine
import pytest

from chess_game.analysis import AnalysisWorker, _eval_to_ratio


class _FakeAnalysisResult:
    """Stands in for chess.engine.SimpleAnalysisResult.

    next() pops info dicts off a queue one at a time; once the queue is
    exhausted it blocks until either stop() is called (then returns None,
    like the real implementation does once AnalysisComplete fires) or a
    short timeout elapses (treated as "depth limit reached naturally").
    """

    def __init__(self, infos: list[dict], block_after: bool = False) -> None:
        self._infos = list(infos)
        self._stopped = threading.Event()
        self._block_after = block_after

    def next(self) -> dict | None:
        if self._infos:
            return self._infos.pop(0)
        if self._block_after:
            # Simulate a search that keeps running until stop() is called.
            self._stopped.wait(timeout=5.0)
            return None
        return None

    def stop(self) -> None:
        self._stopped.set()

    def __enter__(self) -> _FakeAnalysisResult:
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()


class _FakeEngine:
    """Stands in for chess.engine.SimpleEngine."""

    def __init__(self, infos: list[dict], block_after: bool = False) -> None:
        self._infos = infos
        self._block_after = block_after
        self.quit_called = False

    def analysis(self, board, limit, **kwargs) -> _FakeAnalysisResult:
        return _FakeAnalysisResult(self._infos, block_after=self._block_after)

    def quit(self) -> None:
        self.quit_called = True


def _patch_popen_uci(monkeypatch, engine_or_exc):
    """Patch SimpleEngine.popen_uci to return engine_or_exc if it's an
    engine, or raise it if it's an exception instance."""

    def _fake_popen_uci(command, **kwargs):
        if isinstance(engine_or_exc, BaseException):
            raise engine_or_exc
        return engine_or_exc

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))


# ── Engine-unavailable handling ─────────────────────────────────────────────

def test_engine_unavailable_sets_flag_and_reason(monkeypatch):
    _patch_popen_uci(monkeypatch, FileNotFoundError("[Errno 2] No such file or directory: 'stockfish'"))
    worker = AnalysisWorker()

    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    assert worker.engine_available is False
    assert "stockfish" in worker.missing_reason.lower() or "No such file" in worker.missing_reason
    # start() still hands back a usable epoch so callers can store it
    # uniformly, but no result is ever produced under it.
    assert isinstance(epoch, int)
    assert worker.take(epoch) is None


def test_engine_unavailable_does_not_retry_popen_every_start(monkeypatch):
    """A missing Stockfish shouldn't spawn a failing subprocess attempt on
    every single move; popen_uci should only be tried once."""
    call_count = {"n": 0}

    def _fake_popen_uci(command, **kwargs):
        call_count["n"] += 1
        raise FileNotFoundError("not found")

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))
    worker = AnalysisWorker()

    board = chess.Board()
    for _ in range(5):
        epoch = worker.start(board)
        worker.join(timeout=2.0)
        assert worker.take(epoch) is None

    assert call_count["n"] == 1


def test_engine_path_pointing_at_wrong_binary_does_not_crash(monkeypatch):
    """TimeoutError is itself a subclass of OSError (Python 3.10+) — this
    is a regression test for an ordering bug where an `except OSError`
    clause listed before `except TimeoutError` would silently swallow the
    timeout with the wrong (often empty) missing_reason. Real-world
    trigger: stockfish_path pointing at some other, non-UCI-speaking but
    perfectly executable program.
    """
    _patch_popen_uci(monkeypatch, TimeoutError())
    worker = AnalysisWorker("/usr/bin/not-actually-stockfish")

    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    assert worker.engine_available is False
    # The message must be informative even though TimeoutError() carries
    # no text of its own (str(TimeoutError()) == "") — falling back to
    # str(exc) here would silently produce an empty missing_reason.
    assert worker.missing_reason != ""
    assert "not-actually-stockfish" in worker.missing_reason
    assert worker.take(epoch) is None


def test_engine_error_with_empty_message_still_sets_a_useful_reason(monkeypatch):
    """Mirrors the TimeoutError case above for chess.engine.EngineError:
    an exception instance with no message must still produce a
    non-empty, identifiable missing_reason."""
    _patch_popen_uci(monkeypatch, chess.engine.EngineError())
    worker = AnalysisWorker("/opt/weird-engine")

    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    assert worker.engine_available is False
    assert worker.missing_reason != ""
    assert worker.take(epoch) is None


# ── Successful analysis result ──────────────────────────────────────────────

def test_take_returns_eval_and_pv_for_matching_epoch(monkeypatch):
    move = chess.Move.from_uci("e2e4")
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(120), chess.WHITE),
        "pv": [move],
    }
    fake_engine = _FakeEngine(infos=[info])
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = AnalysisWorker()
    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    result = worker.take(epoch)
    assert result is not None
    eval_cp, pv, is_mate, mate_in = result
    assert eval_cp == 120
    assert pv == [move]
    assert is_mate is False
    assert mate_in is None


def test_take_reports_mate_scores(monkeypatch):
    info = {
        "score": chess.engine.PovScore(chess.engine.Mate(3), chess.WHITE),
        "pv": [chess.Move.from_uci("d1h5")],
    }
    fake_engine = _FakeEngine(infos=[info])
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = AnalysisWorker()
    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    result = worker.take(epoch)
    assert result is not None
    eval_cp, pv, is_mate, mate_in = result
    assert is_mate is True
    assert mate_in == 3
    assert eval_cp is None


def test_take_handles_missing_score_and_pv_gracefully(monkeypatch):
    """An info dict with no 'score'/'pv' keys (e.g. the very first partial
    update from a fresh search) shouldn't crash the worker thread."""
    fake_engine = _FakeEngine(infos=[{}])
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = AnalysisWorker()
    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    result = worker.take(epoch)
    assert result is not None
    eval_cp, pv, is_mate, mate_in = result
    assert eval_cp is None
    assert pv == []
    assert is_mate is False


def test_engine_terminating_mid_search_does_not_crash(monkeypatch):
    """If the Stockfish subprocess dies unexpectedly while a search is in
    flight (analysis.next() raises EngineTerminatedError), the worker
    thread must absorb it rather than letting it propagate and kill a
    daemon thread silently or, worse, surface as a crash somewhere the
    user can see."""

    class _DyingAnalysisResult:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def next(self):
            raise chess.engine.EngineTerminatedError("engine process exited unexpectedly")

        def stop(self):
            pass

    class _DyingEngine:
        def analysis(self, board, limit, **kwargs):
            return _DyingAnalysisResult()

        def quit(self):
            pass

    _patch_popen_uci(monkeypatch, _DyingEngine())
    worker = AnalysisWorker()
    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)

    assert worker.thinking is False
    assert worker.take(epoch) is None


# ── Epoch guarding ───────────────────────────────────────────────────────────

def test_take_with_stale_epoch_returns_none(monkeypatch):
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(50), chess.WHITE),
        "pv": [],
    }
    fake_engine = _FakeEngine(infos=[info])
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = AnalysisWorker()
    board = chess.Board()
    old_epoch = worker.start(board)
    worker.join(timeout=2.0)

    # Bump the epoch via a second start() before ever taking the first
    # result — exactly the "position changed before we read the old
    # search" race BotWorker's epoch guard exists to prevent.
    fake_engine_2 = _FakeEngine(infos=[info])
    _patch_popen_uci(monkeypatch, fake_engine_2)
    new_epoch = worker.start(board)
    worker.join(timeout=2.0)

    assert new_epoch != old_epoch
    assert worker.take(old_epoch) is None
    assert worker.take(new_epoch) is not None


def test_start_cancels_in_flight_search_before_spawning_new_one(monkeypatch):
    """A start() while a previous search is still running must cancel and
    join it first, mirroring BotWorker.start()'s contract, so at most one
    worker thread is ever alive.

    Both start() calls share a single fake engine (rather than swapping
    the popen_uci mock between them) because AnalysisWorker deliberately
    keeps its UCI subprocess open across calls instead of relaunching it
    every search — only the first start() actually opens anything.
    """
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(10), chess.WHITE),
        "pv": [],
    }
    fake_engine = _FakeEngine(infos=[info], block_after=True)
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = AnalysisWorker()
    board = chess.Board()
    epoch1 = worker.start(board)
    time.sleep(0.05)
    assert worker.thinking is True

    # Reconfigure the same fake engine to hand back a real result for the
    # second search (the first search would otherwise block forever).
    fake_engine._block_after = False
    fake_engine._infos = [info]
    epoch2 = worker.start(board)
    worker.join(timeout=2.0)

    assert epoch2 != epoch1
    assert worker.take(epoch1) is None
    assert worker.take(epoch2) is not None


# ── stop_engine ──────────────────────────────────────────────────────────────

def test_stop_engine_is_idempotent_when_never_opened():
    worker = AnalysisWorker()
    worker.stop_engine()
    worker.stop_engine()  # must not raise


def test_stop_engine_quits_the_underlying_engine(monkeypatch):
    info = {
        "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE),
        "pv": [],
    }
    fake_engine = _FakeEngine(infos=[info])
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = AnalysisWorker()
    board = chess.Board()
    epoch = worker.start(board)
    worker.join(timeout=2.0)
    worker.take(epoch)

    worker.stop_engine()
    assert fake_engine.quit_called is True
    worker.stop_engine()  # idempotent even after a real close


# ── Pure eval-bar helper ─────────────────────────────────────────────────────

def test_eval_to_ratio_even_position_is_half():
    assert _eval_to_ratio(0) == pytest.approx(0.5)


def test_eval_to_ratio_positive_above_half():
    assert _eval_to_ratio(150) > 0.5


def test_eval_to_ratio_negative_below_half():
    assert _eval_to_ratio(-150) < 0.5


def test_eval_to_ratio_symmetric():
    assert _eval_to_ratio(300) == pytest.approx(1.0 - _eval_to_ratio(-300))


def test_eval_to_ratio_handles_large_values_without_overflow():
    # Mate-adjacent or absurdly lopsided centipawn scores must not raise
    # OverflowError and must stay within the valid (0, 1) open interval.
    for v in (10_000, -10_000, 1_000_000, -1_000_000):
        ratio = _eval_to_ratio(v)
        assert 0.0 <= ratio <= 1.0
