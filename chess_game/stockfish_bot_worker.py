"""Cancellable Stockfish worker for playing bot moves at a target ELO.

This worker is separate from AnalysisWorker so playing and evaluation
can be toggled independently without sharing the same subprocess.
"""
from __future__ import annotations

import subprocess
import sys
import threading

import chess
import chess.engine

from chess_game.log import get_logger

# See analysis.py's identical helper for the full explanation: without this,
# a windowed PyInstaller build on Windows pops a blank console window
# whenever the Stockfish subprocess is spawned, because there's no parent
# console for it to inherit. No-op on non-Windows platforms.
_WINDOWS_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else None


def _popen_uci(engine_path: str) -> chess.engine.SimpleEngine:
    """popen_uci wrapper that suppresses the blank console window a frozen
    Windows build would otherwise spawn alongside the Stockfish process."""
    if _WINDOWS_CREATIONFLAGS is not None:
        return chess.engine.SimpleEngine.popen_uci(
            engine_path, creationflags=_WINDOWS_CREATIONFLAGS
        )
    return chess.engine.SimpleEngine.popen_uci(engine_path)

# Stockfish only accepts UCI_Elo within this range once UCI_LimitStrength is
# enabled. Values are clamped to this window before being sent, so a caller
# passing an out-of-range slider value (e.g. from a stale UI state) can never
# produce a UCI protocol error.
MIN_ELO = 1320
MAX_ELO = 3190
DEFAULT_ELO = 1500

# Capped low so a low-ELO bot still "feels" fast; UCI_LimitStrength already
# does most of the work of making it play worse, not slower.
DEFAULT_MOVETIME_MS = 1000


class StockfishBotWorker:
    """Owns a single background Stockfish subprocess used to generate the
    bot's moves (as opposed to AnalysisWorker, which only ever evaluates).

    Like AnalysisWorker, Stockfish is treated as optional: if it can't be
    launched, engine_available is False and get_move()/start() become
    safe no-ops that never produce a result. Callers should fall back to
    the native ChessBot (via BotWorker) when this is the case — App is
    responsible for surfacing that fallback to the user.
    """

    def __init__(self, engine_path: str = "") -> None:
        self._engine_path = engine_path or "stockfish"
        self._engine: chess.engine.SimpleEngine | None = None
        self.engine_available = True
        self.missing_reason: str = ""
        self._tried_open = False

        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._epoch = 0
        self._lock = threading.Lock()
        self._result: chess.Move | None = None
        self._result_epoch: int | None = None
        self._thinking = False

        # The ELO + movetime currently configured on the live subprocess,
        # so _ensure_engine() can skip resending setoption when nothing
        # has changed since the last search.
        self._configured_elo: int | None = None

    @property
    def thinking(self) -> bool:
        return self._thinking

    def set_engine_path(self, path: str) -> None:
        """Update the configured engine path for the next engine spawn."""
        self._engine_path = path or "stockfish"

    def _ensure_engine(self) -> bool:
        """Lazily open the UCI engine and return whether it is usable."""
        if self._engine is not None:
            return True
        if self._tried_open and not self.engine_available:
            return False
        self._tried_open = True
        logger = get_logger()
        try:
            self._engine = _popen_uci(self._engine_path)
        except TimeoutError as exc:
            self.engine_available = False
            self.missing_reason = (
                f"Timed out waiting for a UCI response from '{self._engine_path}' "
                "(is this actually a chess engine?)"
            )
            logger.warning("Stockfish handshake timed out (%s): %s", self._engine_path, exc)
            return False
        except OSError as exc:
            self.engine_available = False
            self.missing_reason = str(exc) or f"Could not launch '{self._engine_path}'"
            logger.warning("Stockfish unavailable (%s): %s", self._engine_path, exc)
            return False
        except chess.engine.EngineError as exc:
            self.engine_available = False
            self.missing_reason = str(exc) or f"'{self._engine_path}' did not initialise correctly"
            logger.warning("Stockfish did not initialise (%s): %s", self._engine_path, exc)
            return False
        self.engine_available = True
        self.missing_reason = ""
        self._configured_elo = None  # force a fresh setoption on the new process
        return True

    def _configure_strength(self, elo: int) -> None:
        """Send UCI_LimitStrength + UCI_Elo if they differ from what's
        already configured on the live subprocess. Clamped to
        [MIN_ELO, MAX_ELO] so a stale or out-of-range slider value can
        never reach the engine as a protocol error."""
        assert self._engine is not None
        elo = max(MIN_ELO, min(MAX_ELO, int(elo)))
        if elo == self._configured_elo:
            return
        self._engine.configure({
            "UCI_LimitStrength": True,
            "UCI_Elo": elo,
        })
        self._configured_elo = elo

    def start(self, board: chess.Board, color: str, elo: int = DEFAULT_ELO,
              movetime_ms: int = DEFAULT_MOVETIME_MS) -> int:
        """Cancel any in-flight search, then start a new one in the
        background. Returns the epoch assigned to this search; pass it
        to take() later to retrieve the result only if it's still
        current.

        `color` is accepted (and unused beyond bookkeeping symmetry with
        BotWorker.start()'s signature) since python-chess's engine.play
        infers whose move it is directly from `board.turn` rather than
        needing it passed explicitly.
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
                self._configure_strength(elo)
                limit = chess.engine.Limit(time=movetime_ms / 1000.0)
                result = engine.play(board_copy, limit)
            except chess.engine.EngineTerminatedError:
                logger.warning("Stockfish process terminated during play")
                with self._lock:
                    self._thinking = False
                return
            except chess.engine.EngineError as exc:
                logger.warning("Stockfish play() error (epoch %d): %s", epoch, exc)
                with self._lock:
                    self._thinking = False
                return

            if cancel_event.is_set():
                # The move finished computing, but a newer search has
                # already been requested (e.g. the game was restarted
                # mid-think) — discard it rather than risk it being
                # take()n under a now-stale epoch later.
                logger.debug("Stockfish search aborted (epoch %d)", epoch)
                with self._lock:
                    self._thinking = False
                return

            with self._lock:
                self._result = result.move
                self._result_epoch = epoch
                self._thinking = False

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        return epoch

    def take(self, expected_epoch: int) -> chess.Move | None:
        """Return the computed move only if it matches expected_epoch.

        Stale results (computed under an old epoch) are dropped, never
        applied — this is what makes restart-while-thinking safe.
        """
        with self._lock:
            if self._result is not None and self._result_epoch == expected_epoch:
                move = self._result
                self._result = None
                self._result_epoch = None
                return move
            return None

    def current_epoch(self) -> int:
        return self._epoch

    def cancel(self) -> None:
        # NOTE: unlike AnalysisWorker's analysis() stream, engine.play()
        # offers no cooperative-cancel hook — once dispatched, the
        # underlying `go` command runs to completion (bounded by
        # movetime_ms) inside python-chess's blocking call. Setting this
        # Event therefore can't interrupt an in-flight search early; it
        # only marks the *result* as stale so a late-arriving move from a
        # cancelled search is discarded in _run() / take() rather than
        # ever being applied to a board it no longer matches. Bounding
        # movetime_ms keeps "how late" bounded to roughly one search.
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
        self._tried_open = False
        self._configured_elo = None
