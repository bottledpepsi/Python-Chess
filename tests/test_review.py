"""Review-mode controller tests (dead review_target code dropped)."""
from __future__ import annotations

import chess

from chess_game.bot_worker import BotWorker
from chess_game.engine.bot import ChessBot
from chess_game.game import Game
from chess_game.review import enter_review, exit_review, move_review


def _make_game():
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    g = Game(bot=bot, bot_worker=worker)
    g.start_game()
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6"]:
        g.adapter._push(chess.Move.from_uci(uci))
    return g


def test_move_review_backward_from_live_enters_at_last_ply():
    g = _make_game()
    move_review(g, -1)
    assert g.review.ply == 3


def test_move_review_forward_from_live_enters_at_ply_one():
    g = _make_game()
    move_review(g, 1)
    assert g.review.ply == 1


def test_move_review_clamped_at_zero():
    g = _make_game()
    enter_review(g, 0)
    move_review(g, -5)
    assert g.review.ply == 0


def test_move_review_exits_at_total_plies():
    g = _make_game()
    enter_review(g, 2)
    move_review(g, 100)
    assert g.review.ply is None


def test_exit_review_clears_anim():
    g = _make_game()
    enter_review(g, 1)
    exit_review(g)
    assert g.review.ply is None
    assert g.review.board is None
    assert g.anim is None


def test_enter_review_builds_correct_board():
    g = _make_game()
    enter_review(g, 2)
    expected = list(g.adapter.board.move_stack)[:2]
    assert g.review.board.move_stack == expected
