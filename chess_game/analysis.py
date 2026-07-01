"""Cancellable, epoch-guarded Stockfish analysis.

Mirrors chess_game.bot_worker.BotWorker exactly: an abort Event, an epoch
counter so a stale result is never applied to a fresh board, and
join-before-spawn so at most one worker thread is ever alive.

The one real difference from BotWorker is *how* the abort is delivered.
python-chess's blocking SimpleEngine.analyse() has no cooperative-cancel
parameter — its `game` argument is an opaque cache key for the engine
protocol, not a cancellation signal. The cancellable primitive the library
actually provides is the non-blocking SimpleEngine.analysis() iterator,
which returns a SimpleAnalysisResult with a .stop() method. AnalysisWorker
therefore opens an analysis() stream and pumps it with .next() in a loop,
checking the abort Event between iterations and calling .stop() the moment
it's set, instead of blocking forever inside a single analyse() call.

Stockfish is treated as optional: if it can't be launched, engine_available
is False and every other method becomes a safe no-op. The caller (App)
checks engine_available before offering analysis mode at all.
"""
from __future__ import annotations

import subprocess
import sys
import threading

import chess
import chess.engine

from chess_game.log import get_logger

# On Windows, a windowed (console-less) PyInstaller build has no console for
# a spawned child process to inherit, so CreateProcess allocates a brand new
# one -- the blank terminal window users see when Stockfish launches. Passing
# CREATE_NO_WINDOW suppresses that. getattr() avoids a mypy attr-defined
# error on non-Windows platforms, where the constant doesn't exist at all.
_WINDOWS_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else None


def _popen_uci(engine_path: str) -> chess.engine.SimpleEngine:
    """popen_uci wrapper that suppresses the blank console window a frozen
    Windows build would otherwise spawn alongside the Stockfish process."""
    if _WINDOWS_CREATIONFLAGS is not None:
        return chess.engine.SimpleEngine.popen_uci(
            engine_path, creationflags=_WINDOWS_CREATIONFLAGS
        )
    return chess.engine.SimpleEngine.popen_uci(engine_path)

# Default search depth for a single analysis pass. Deep enough to be a
# useful "what's best here" signal, shallow enough to return in well under
# a second on a modern machine for any position.
DEFAULT_DEPTH = 18


def _eval_to_ratio(eval_cp: float) -> float:
    """Map a centipawn score (White's POV) to a 0..1 fill ratio for the
    eval bar, via a standard WDL-style logistic curve.

    0 cp -> 0.5 (an even bar). Large positive/negative scores asymptote
    towards 1.0/0.0 without ever pegging exactly, so the function never
    overflows or divides by zero regardless of how lopsided eval_cp is.
    """
    # 400 is the same scaling constant Lichess/many engines use for their
    # win-probability sigmoid; it makes +/-100cp (a modest edge) noticeably
    # move the bar while +/-800cp (a won position) sits close to the cap
    # without literally touching it.
    # Clamp the exponent before exponentiating rather than after, so huge
    # |eval_cp| values (mate-adjacent scores, or any caller-supplied
    # garbage) can't overflow float exponentiation. +/-50 as an exponent
    # already saturates the ratio to (effectively) 0.0/1.0, so clamping
    # there changes nothing about the curve's shape, just its domain.
    exponent = max(-50.0, min(50.0, -eval_cp / 400.0))
    return float(1.0 / (1.0 + 10.0 ** exponent))


class AnalysisWorker:
    """Owns a single background Stockfish analysis stream.

    Unlike BotWorker (one ChessBot, reused across searches), each
    AnalysisWorker owns its own UCI engine subprocess, opened lazily on
    first use and kept alive across positions until stop_engine() closes
    it (normally only on app shutdown).
    """

    def __init__(self, engine_path: str = "") -> None:
        # "" means "rely on PATH", matching the stockfish_path preference's
        # empty-string default.
        self._engine_path = engine_path or "stockfish"
        self._engine: chess.engine.SimpleEngine | None = None
        self.engine_available = True
        self.missing_reason: str = ""
        self._tried_open = False

        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._epoch = 0
        self._lock = threading.Lock()
        # (eval_cp, pv_moves, is_mate, mate_in) — eval_cp is None for mate
        # scores, mate_in is None for non-mate scores.
        self._result: tuple[int | None, list[chess.Move], bool, int | None] | None = None
        self._result_epoch: int | None = None
        self._thinking = False

    @property
    def thinking(self) -> bool:
        return self._thinking

    def set_engine_path(self, path: str) -> None:
        """Update the configured engine path. Takes effect the next time
        the engine is (re-)opened, e.g. after stop_engine() or on next
        start() if it was never successfully opened."""
        self._engine_path = path or "stockfish"

    def _ensure_engine(self) -> bool:
        """Lazily open the UCI engine. Returns True if usable.

        Only attempts popen_uci once per (path) — repeated calls to start()
        while Stockfish is missing don't spawn repeated failing subprocess
        attempts every move.
        """
        if self._engine is not None:
            return True
        if self._tried_open and not self.engine_available:
            return False
        self._tried_open = True
        logger = get_logger()
        try:
            self._engine = _popen_uci(self._engine_path)
        except TimeoutError as exc:
            # Caught before the broader `except OSError` below because
            # TimeoutError is itself a subclass of OSError in Python 3.10+
            # — an except OSError clause listed first would silently
            # swallow this case with the wrong (often empty) message.
            # This fires when the configured path points at a real,
            # executable program that simply never responds to the UCI
            # handshake within popen_uci's internal timeout — e.g.
            # stockfish_path was set to some unrelated binary. Verified
            # against a real non-engine executable: this is the actual
            # exception python-chess raises here, not chess.engine.
            # EngineError, so it has to be caught explicitly or a bad
            # (but executable) path crashes the app on the next analysis
            # start instead of just disabling analysis mode.
            self.engine_available = False
            self.missing_reason = (
                f"Timed out waiting for a UCI response from '{self._engine_path}' "
                "(is this actually a chess engine?)"
            )
            logger.warning("Stockfish handshake timed out (%s): %s", self._engine_path, exc)
            return False
        except OSError as exc:
            # Covers FileNotFoundError (binary not on PATH / bad path) and
            # PermissionError (path exists but isn't executable) — there is
            # no dedicated "engine not found" exception type to catch here.
            self.engine_available = False
            self.missing_reason = str(exc) or f"Could not launch '{self._engine_path}'"
            logger.warning("Stockfish unavailable (%s): %s", self._engine_path, exc)
            return False
        except chess.engine.EngineError as exc:
            # The process launched but errored out during the UCI
            # handshake (e.g. it does speak UCI but rejected something).
            self.engine_available = False
            self.missing_reason = str(exc) or f"'{self._engine_path}' did not initialise correctly"
            logger.warning("Stockfish did not initialise (%s): %s", self._engine_path, exc)
            return False
        self.engine_available = True
        self.missing_reason = ""
        return True

    def start(self, board: chess.Board, depth: int = DEFAULT_DEPTH) -> int:
        """Cancel any in-flight analysis, then start a new one.

        Returns the epoch assigned to this search; pass it to take() later
        to retrieve the result only if it's still current. If the engine
        is unavailable, this still bumps and returns a fresh epoch (so
        callers can store it uniformly) but never produces a result.
        """
        logger = get_logger()
        self.cancel()
        self.join(timeout=2.0)

        self._epoch += 1
        epoch = self._epoch
        self._cancel = threading.Event()
        cancel_event = self._cancel
        board_copy = board.copy()  # never share the live board with the thread
        self._thinking = True

        if not self._ensure_engine():
            self._thinking = False
            return epoch

        engine = self._engine
        assert engine is not None

        def _run() -> None:
            try:
                with engine.analysis(board_copy, chess.engine.Limit(depth=depth)) as analysis:
                    # .next() blocks until the engine pushes its next info
                    # update, so the abort Event can't be polled between
                    # calls — by the time control returns to this loop the
                    # wait is already over. Instead, a small watcher thread
                    # calls analysis.stop() the moment cancel_event fires,
                    # which makes the in-flight (or next) .next() call
                    # return None promptly, exactly like calling .stop()
                    # from the main thread would, just without blocking it.
                    def _watch_cancel() -> None:
                        # Waits on whichever of (cancel, done) fires first,
                        # so this thread always exits promptly instead of
                        # leaking for the worker's lifetime when a search
                        # finishes naturally (depth limit reached) without
                        # ever being aborted.
                        while not cancel_event.is_set() and not done.is_set():
                            cancel_event.wait(timeout=0.05)
                        if cancel_event.is_set():
                            analysis.stop()

                    done = threading.Event()
                    watcher = threading.Thread(target=_watch_cancel, daemon=True)
                    watcher.start()

                    info: chess.engine.InfoDict = {}
                    try:
                        while True:
                            next_info = analysis.next()
                            if next_info is None:
                                # Either the depth limit was reached, or
                                # cancel_event fired and the watcher called
                                # stop() — either way, this is the last
                                # update.
                                break
                            info = next_info
                    finally:
                        done.set()
                        watcher.join(timeout=1.0)

                if cancel_event.is_set():
                    logger.debug("Analysis aborted (epoch %d)", epoch)
                    with self._lock:
                        self._thinking = False
                    return
            except chess.engine.EngineTerminatedError:
                logger.warning("Stockfish process terminated during analysis")
                with self._lock:
                    self._thinking = False
                return

            score = info.get("score")
            eval_cp: int | None = None
            is_mate = False
            mate_in: int | None = None
            if score is not None:
                white_score = score.white()
                if white_score.is_mate():
                    is_mate = True
                    mate_in = white_score.mate()
                else:
                    eval_cp = white_score.score()
            pv = list(info.get("pv", []))

            with self._lock:
                self._result = (eval_cp, pv, is_mate, mate_in)
                self._result_epoch = epoch
                self._thinking = False

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return epoch

    def take(self, expected_epoch: int) -> tuple[int | None, list[chess.Move], bool, int | None] | None:
        """Return (eval_cp, pv_moves, is_mate, mate_in) only if it matches
        expected_epoch, else None.

        eval_cp is None when is_mate is True (and vice versa) — callers
        should branch on is_mate rather than treating eval_cp is None as
        an error.
        """
        with self._lock:
            if self._result is not None and self._result_epoch == expected_epoch:
                result = self._result
                self._result = None
                self._result_epoch = None
                return result
            return None

    def current_epoch(self) -> int:
        return self._epoch

    def cancel(self) -> None:
        self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def stop_engine(self) -> None:
        """Close the UCI engine subprocess. Idempotent; safe to call even
        if the engine was never successfully opened."""
        self.cancel()
        self.join(timeout=2.0)
        if self._engine is not None:
            try:
                self._engine.quit()
            except chess.engine.EngineError:
                pass
            self._engine = None
        # Allow a fresh popen_uci attempt next time analysis is enabled
        # (e.g. after the user fixes the path in preferences).
        self._tried_open = False
