"""StockfishBotWorker tests: engine-availability handling, epoch guarding,
and UCI_LimitStrength/UCI_Elo configuration (including clamping).

Stockfish is not installed in CI, so every test mocks
chess.engine.SimpleEngine.popen_uci to return a small fake engine instead
of launching a real subprocess — mirrors tests/test_analysis.py's
_FakeEngine pattern exactly, just with a play() method instead of
analysis(), and a configure() that records what was sent so tests can
assert on the exact UCI_Elo value without needing a real engine to
verify it against.
"""
from __future__ import annotations

import threading
import time

import chess
import chess.engine

from chess_game.stockfish_bot_worker import MAX_ELO, MIN_ELO, StockfishBotWorker


class _FakePlayResult:
    def __init__(self, move: chess.Move) -> None:
        self.move = move


class _FakeEngine:
    """Stands in for chess.engine.SimpleEngine. Records every configure()
    call (a list of the option dicts passed in, in order) so tests can
    assert exactly what UCI_Elo was sent, and supports a block_after flag
    so cancellation/restart races can be exercised the same way
    test_analysis.py does for AnalysisWorker."""

    def __init__(self, move: chess.Move | None = None, block_after: bool = False) -> None:
        self._move = move if move is not None else chess.Move.from_uci("e2e4")
        self._block_after = block_after
        self._stopped = threading.Event()
        self.configure_calls: list[dict] = []
        self.quit_called = False

    def configure(self, options: dict) -> None:
        self.configure_calls.append(dict(options))

    def play(self, board, limit, **kwargs) -> _FakePlayResult:
        if self._block_after:
            self._stopped.wait(timeout=5.0)
        return _FakePlayResult(self._move)

    def quit(self) -> None:
        self.quit_called = True


def _patch_popen_uci(monkeypatch, engine_or_exc):
    def _fake_popen_uci(command, **kwargs):
        if isinstance(engine_or_exc, BaseException):
            raise engine_or_exc
        return engine_or_exc

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))


# ── Engine-unavailable handling ─────────────────────────────────────────────


def test_engine_unavailable_sets_flag_and_reason(monkeypatch):
    _patch_popen_uci(monkeypatch, FileNotFoundError("no such file"))
    worker = StockfishBotWorker("/nonexistent/stockfish")
    epoch = worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    assert worker.engine_available is False
    assert worker.missing_reason
    assert worker.take(epoch) is None


def test_engine_unavailable_does_not_retry_popen_every_start(monkeypatch):
    calls = {"n": 0}

    def _fake_popen_uci(command, **kwargs):
        calls["n"] += 1
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))
    worker = StockfishBotWorker("/nonexistent/stockfish")
    worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    assert calls["n"] == 1


def test_preload_opens_engine_before_the_first_search(monkeypatch):
    fake_engine = _FakeEngine()
    opened = threading.Event()

    def _fake_popen_uci(command, **kwargs):
        opened.set()
        return fake_engine

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))
    worker = StockfishBotWorker("/fake/stockfish")

    worker.preload()

    assert opened.wait(timeout=1.0)
    deadline = time.monotonic() + 1.0
    while worker._engine is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert worker._engine is fake_engine
    assert worker.thinking is False


def test_first_engine_handshake_does_not_block_start(monkeypatch):
    """A slow cold UCI handshake must run on the worker thread, not UI thread."""
    handshake_started = threading.Event()
    release_handshake = threading.Event()
    fake_engine = _FakeEngine()

    def _slow_popen_uci(command, **kwargs):
        handshake_started.set()
        release_handshake.wait(timeout=2.0)
        return fake_engine

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_slow_popen_uci))
    worker = StockfishBotWorker("/fake/stockfish")

    started_at = time.monotonic()
    epoch = worker.start(chess.Board(), "white", elo=1500)
    elapsed = time.monotonic() - started_at

    assert elapsed < 0.1
    assert handshake_started.wait(timeout=1.0)
    assert worker.thinking is True
    release_handshake.set()
    worker.join(timeout=2.0)
    assert worker.take(epoch) == chess.Move.from_uci("e2e4")


# ── Move retrieval / epoch guarding ─────────────────────────────────────────


def test_take_returns_move_for_matching_epoch(monkeypatch):
    fake_engine = _FakeEngine(move=chess.Move.from_uci("g1f3"))
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    epoch = worker.start(chess.Board(), "black", elo=1800)
    worker.join(timeout=2.0)

    move = worker.take(epoch)
    assert move == chess.Move.from_uci("g1f3")
    # Consumed once — a second take() under the same epoch returns None.
    assert worker.take(epoch) is None


def test_take_with_wrong_epoch_returns_none(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    epoch = worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    assert worker.take(epoch + 999) is None


def test_restart_mid_think_never_applies_stale_move(monkeypatch):
    """Mirrors test_bot_worker.py's restart-mid-think race test: a second
    start() before the first search finishes must invalidate the first
    search's epoch, even though python-chess's play() offers no
    cooperative early-cancel (see StockfishBotWorker.cancel's docstring)."""
    fake_engine = _FakeEngine(move=chess.Move.from_uci("e2e4"), block_after=True)
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    epoch1 = worker.start(chess.Board(), "white", elo=1500)
    time.sleep(0.05)

    # Let the first (blocked) search's underlying play() return now, but
    # under the *old* epoch — it should be discarded once epoch2 exists.
    fake_engine._stopped.set()
    fake_engine._block_after = False

    epoch2 = worker.start(chess.Board(), "white", elo=2000)
    worker.join(timeout=2.0)

    assert worker.take(epoch1) is None, "stale epoch result leaked"
    fresh = worker.take(epoch2)
    assert fresh is not None


def test_worker_thinking_flag_clears_after_completion(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)
    worker = StockfishBotWorker("/fake/stockfish")
    worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    assert worker.thinking is False


# ── UCI_LimitStrength / UCI_Elo configuration ───────────────────────────────


def test_elo_is_sent_via_uci_limit_strength_and_uci_elo(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    worker.start(chess.Board(), "white", elo=2200)
    worker.join(timeout=2.0)

    assert fake_engine.configure_calls == [{"UCI_LimitStrength": True, "UCI_Elo": 2200}]


def test_elo_above_max_is_clamped(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    worker.start(chess.Board(), "white", elo=999999)
    worker.join(timeout=2.0)

    assert fake_engine.configure_calls[-1]["UCI_Elo"] == MAX_ELO


def test_elo_below_min_is_clamped(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    worker.start(chess.Board(), "white", elo=-50)
    worker.join(timeout=2.0)

    assert fake_engine.configure_calls[-1]["UCI_Elo"] == MIN_ELO


def test_unchanged_elo_is_not_resent(monkeypatch):
    """configure() should only be called again if the ELO actually
    changed since the last search, to avoid spamming setoption on every
    single move at a fixed difficulty."""
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    e1 = worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    worker.take(e1)

    e2 = worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    worker.take(e2)

    assert len(fake_engine.configure_calls) == 1


def test_elo_change_between_searches_is_resent(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    e1 = worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    worker.take(e1)

    e2 = worker.start(chess.Board(), "white", elo=2500)
    worker.join(timeout=2.0)
    worker.take(e2)

    assert [c["UCI_Elo"] for c in fake_engine.configure_calls] == [1500, 2500]


# ── stop_engine ──────────────────────────────────────────────────────────────


def test_stop_engine_is_idempotent_when_never_opened():
    worker = StockfishBotWorker("/fake/stockfish")
    worker.stop_engine()
    worker.stop_engine()  # must not raise


def test_stop_engine_quits_the_underlying_engine(monkeypatch):
    fake_engine = _FakeEngine()
    _patch_popen_uci(monkeypatch, fake_engine)

    worker = StockfishBotWorker("/fake/stockfish")
    worker.start(chess.Board(), "white", elo=1500)
    worker.join(timeout=2.0)
    worker.stop_engine()

    assert fake_engine.quit_called is True
