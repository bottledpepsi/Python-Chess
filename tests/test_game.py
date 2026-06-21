"""Game lifecycle tests, especially the join-before-clear_tt ordering."""
from __future__ import annotations

import time

import chess

from chess_game.bot_worker import BotWorker
from chess_game.engine.bot import ChessBot
from chess_game.game import Game


def test_start_game_resets_state():
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    g = Game(bot=bot, bot_worker=worker)
    g.start_game()
    assert g.adapter is not None
    assert g.game_over is False
    assert g.winner_result is None
    assert g.review.ply is None
    assert g.bot_epoch is None


def test_start_game_joins_worker_before_clearing_tt_no_stale_move():
    """Regression test: start_game() must cancel+join the bot
    worker BEFORE calling bot.clear_tt(), or a still-running search could
    read/write the TT dict concurrently with it being cleared."""
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    g = Game(bot=bot, bot_worker=worker)
    g.start_game()
    g.player_color = "white"
    g.bot_level = 10
    g.launch_bot_move()
    stale_epoch = g.bot_epoch
    time.sleep(0.05)

    g.start_game()  # restart mid-think

    stale_result = worker.take(stale_epoch)
    assert stale_result is None, "stale bot move leaked across a restart"
    assert len(g.adapter.board.move_stack) == 0


def test_launch_bot_move_uses_opposite_color():
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    g = Game(bot=bot, bot_worker=worker)
    g.start_game()
    g.player_color = "white"
    g.launch_bot_move()
    worker.join(timeout=3.0)
    move = worker.take(g.bot_epoch)
    assert move is not None
    # Black's first reply must be a legal black move on the starting board.
    assert move in chess.Board().legal_moves
