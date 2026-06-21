"""BotWorker epoch/cancel tests, including the exact restart-mid-think
race scenario described in the remediation brief."""
from __future__ import annotations

import threading
import time

import chess
import pytest

from chess_game.bot_worker import BotWorker
from chess_game.engine.bot import ChessBot, SearchAborted


def _slow_bot():
    return ChessBot(book_path=None)


def test_restart_mid_think_never_applies_stale_move():
    bot = _slow_bot()
    worker = BotWorker(bot)

    board1 = chess.Board()
    epoch1 = worker.start(board1, "white", level=10)
    time.sleep(0.05)

    board2 = chess.Board()
    epoch2 = worker.start(board2, "white", level=1)
    worker.join(timeout=3.0)

    assert worker.take(epoch1) is None, "stale epoch result leaked"
    fresh = worker.take(epoch2)
    assert fresh is not None
    assert fresh in board2.legal_moves


def test_take_with_wrong_epoch_returns_none():
    bot = _slow_bot()
    worker = BotWorker(bot)
    board = chess.Board()
    epoch = worker.start(board, "white", level=1)
    worker.join(timeout=3.0)
    assert worker.take(epoch + 999) is None


def test_take_consumes_result_once():
    bot = _slow_bot()
    worker = BotWorker(bot)
    board = chess.Board()
    epoch = worker.start(board, "white", level=1)
    worker.join(timeout=3.0)
    first = worker.take(epoch)
    assert first is not None
    second = worker.take(epoch)
    assert second is None


def test_bot_get_move_raises_search_aborted_when_preset():
    bot = ChessBot(book_path=None)
    board = chess.Board()
    abort = threading.Event()
    abort.set()
    try:
        bot.get_move(board, "white", difficulty_level=8, abort=abort)
    except SearchAborted:
        return
    pytest.fail("expected SearchAborted")


def test_bot_get_move_aborts_mid_search():
    bot = ChessBot(book_path=None)
    board = chess.Board()
    abort = threading.Event()

    def trigger():
        time.sleep(0.05)
        abort.set()

    threading.Thread(target=trigger).start()
    start = time.time()
    raised = False
    try:
        bot.get_move(board, "white", difficulty_level=10, abort=abort)
    except SearchAborted:
        raised = True
    elapsed = time.time() - start
    assert raised
    assert elapsed < 0.9, "abort should interrupt the search promptly, not wait out the 1s floor"


def test_worker_thinking_flag_clears_after_completion():
    bot = _slow_bot()
    worker = BotWorker(bot)
    board = chess.Board()
    worker.start(board, "white", level=1)
    worker.join(timeout=3.0)
    assert worker.thinking is False
