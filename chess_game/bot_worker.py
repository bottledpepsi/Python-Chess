"""Cancellable, epoch-guarded bot move computation.

Restarting a game while the bot is thinking must never apply a stale move
to the fresh board. BotWorker guarantees this via:
  - an abort Event passed into the search, checked at every search node
  - an epoch counter: results are only accepted if the epoch they were
    computed under still matches the current epoch at take()-time
  - start() always cancels and joins any prior thread before spawning a new
    one, so at most one worker thread is ever alive
"""
from __future__ import annotations

import threading

import chess

from chess_game.engine.bot import ChessBot, SearchAborted
from chess_game.log import get_logger


class BotWorker:
    """Owns a single background search thread for one ChessBot instance."""

    def __init__(self, bot: ChessBot) -> None:
        self._bot = bot
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._epoch = 0
        self._lock = threading.Lock()
        self._result: chess.Move | None = None
        self._result_epoch: int | None = None
        self._thinking = False

    @property
    def thinking(self) -> bool:
        return self._thinking

    def start(self, board: chess.Board, color: str, level: int) -> int:
        """Cancel any in-flight search, then start a new one.

        Returns the epoch assigned to this search; pass it to take() later
        to retrieve the result only if it's still current.
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

        def _run() -> None:
            try:
                move = self._bot.get_move(board_copy, color, level, abort=cancel_event)
            except SearchAborted:
                logger.debug("Bot search aborted (epoch %d)", epoch)
                with self._lock:
                    self._thinking = False
                return
            with self._lock:
                self._result = move
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
        self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
