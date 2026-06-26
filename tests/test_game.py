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


def test_launch_bot_move_dispatches_to_stockfish_worker_when_preferred(monkeypatch):
    """When bot_engine_pref == 'stockfish', launch_bot_move/poll_bot_move
    must go through stockfish_bot_worker, not the native bot_worker —
    mocked the same way tests/test_stockfish_bot_worker.py mocks
    SimpleEngine.popen_uci, so no real Stockfish binary is needed."""
    import chess.engine

    from chess_game.stockfish_bot_worker import StockfishBotWorker

    class _FakePlayResult:
        def __init__(self, move):
            self.move = move

    class _FakeEngine:
        def configure(self, options):
            pass

        def play(self, board, limit, **kwargs):
            return _FakePlayResult(chess.Move.from_uci("e2e4"))

        def quit(self):
            pass

    monkeypatch.setattr(
        chess.engine.SimpleEngine, "popen_uci",
        staticmethod(lambda command, **kwargs: _FakeEngine()),
    )

    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    sf_worker = StockfishBotWorker("/fake/stockfish")
    g = Game(bot=bot, bot_worker=worker, stockfish_bot_worker=sf_worker)
    g.start_game()
    g.bot_engine_pref = "stockfish"
    g.bot_elo = 2000
    g.player_color = "white"

    g.launch_bot_move()
    sf_worker.join(timeout=2.0)

    # The native worker must never have been asked to think.
    assert worker.thinking is False
    move = g.poll_bot_move()
    assert move == chess.Move.from_uci("e2e4")


# ── Eval bar smoothing ───────────────────────────────────────────────────────


def test_eval_bar_snaps_to_first_result_instead_of_easing_from_default():
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    g = Game(bot=bot, bot_worker=worker)
    g.analysis_enabled = True
    g.analysis_eval = 500  # +5.00 for White
    assert g.eval_bar_display_ratio is None
    g.update_eval_bar_smoothing(dt_ms=16)
    assert g.eval_bar_display_ratio is not None
    from chess_game.render.board import eval_target_ratio
    target = eval_target_ratio(500, False, None)
    assert g.eval_bar_display_ratio == target


def test_eval_bar_eases_toward_target_without_overshoot():
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)
    g = Game(bot=bot, bot_worker=worker)
    g.analysis_enabled = True

    g.analysis_eval = 0
    g.update_eval_bar_smoothing(dt_ms=16)  # snaps to ~0.5
    start_ratio = g.eval_bar_display_ratio

    g.analysis_eval = 900  # big swing toward White
    from chess_game.render.board import eval_target_ratio
    target = eval_target_ratio(900, False, None)

    prev = start_ratio
    for _ in range(200):
        g.update_eval_bar_smoothing(dt_ms=16)
        # Monotonic approach: each step moves closer to the target and
        # never overshoots past it.
        assert prev <= g.eval_bar_display_ratio <= target + 1e-9
        prev = g.eval_bar_display_ratio

    # After ~3.2 seconds of frames it should have essentially converged.
    assert abs(g.eval_bar_display_ratio - target) < 1e-3


def test_eval_bar_smoothing_is_frame_rate_independent():
    """Stepping with many small dt's vs one big dt covering the same
    total elapsed time should converge to (almost) the same ratio."""
    bot = ChessBot(book_path=None)
    worker = BotWorker(bot)

    g_fast = Game(bot=bot, bot_worker=worker)
    g_fast.analysis_enabled = True
    g_fast.analysis_eval = 0
    g_fast.update_eval_bar_smoothing(dt_ms=16)
    g_fast.analysis_eval = 800

    g_slow = Game(bot=bot, bot_worker=worker)
    g_slow.analysis_enabled = True
    g_slow.analysis_eval = 0
    g_slow.update_eval_bar_smoothing(dt_ms=16)
    g_slow.analysis_eval = 800

    total_ms = 500
    # 60fps-equivalent: many small steps.
    steps = total_ms // 16
    for _ in range(steps):
        g_fast.update_eval_bar_smoothing(dt_ms=16)
    # One single big step covering the same wall-clock time.
    g_slow.update_eval_bar_smoothing(dt_ms=steps * 16)

    assert abs(g_fast.eval_bar_display_ratio - g_slow.eval_bar_display_ratio) < 0.01
