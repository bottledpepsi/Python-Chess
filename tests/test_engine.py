"""Engine-internals regression tests: history-heuristic isolation and
null-move pruning performance.

These exercise chess_game.engine.bot's module-level search functions
directly (not through ChessBot.get_move, which enforces a 1.0s floor that
would swamp any timing signal).
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import chess

from chess_game.engine import bot as bot_mod
from chess_game.engine.bot import ChessBot

# A quiet, closed-ish QGD-style middlegame: both sides are fully developed
# with no immediate tactics, so there are many plausible "do nothing
# useful" quiet moves at every node. This is exactly the kind of position
# where null-move pruning earns its keep — tactical or near-opening
# positions are dominated by forcing lines the TT/quiescence search
# already prune well, and don't show a reliable gap.
_QUIET_MIDDLEGAME_MOVES = [
    "d2d4", "d7d5", "c2c4", "e7e6", "g1f3", "g8f6", "b1c3", "f8e7",
    "e2e3", "b8d7", "f1d3", "c7c6", "e1g1", "e8g8", "b2b3",
]


def _quiet_middlegame_board() -> chess.Board:
    board = chess.Board()
    for uci in _QUIET_MIDDLEGAME_MOVES:
        board.push(chess.Move.from_uci(uci))
    return board


def test_history_table_is_per_instance_not_shared():
    """Two ChessBot instances must not share move-ordering state.

    Before the fix, _HISTORY was a single module-level dict, so cutoffs
    recorded while searching with bot_a would silently bias move ordering
    for bot_b. Each bot's _history must be its own dict.
    """
    bot_a = ChessBot(book_path=None)
    bot_b = ChessBot(book_path=None)
    assert bot_a._history is not bot_b._history

    board = _quiet_middlegame_board()
    bot_a._search_top_n(board, "white", depth=3, n=1)
    assert bot_a._history, "expected bot_a's search to populate its own history table"
    assert bot_b._history == {}, "bot_b's history must stay empty after bot_a's search"


def test_clear_tt_also_clears_history():
    """clear_tt() must wipe history alongside the transposition table —
    this is the actual cross-game leak the fix addresses."""
    bot = ChessBot(book_path=None)
    board = _quiet_middlegame_board()
    bot._search_top_n(board, "white", depth=3, n=1)
    assert bot._history, "search should have populated history before clear_tt"

    bot.clear_tt()
    assert bot._tt == {}
    assert bot._history == {}


# The timing harness below deliberately shells out to a fresh, uninstrumented
# interpreter rather than calling _alphabeta in-process. pytest-cov's line
# tracer adds enough per-call overhead to a hot recursive function like
# _alphabeta (~4x in measurements) that it swamps the actual signal being
# tested, making the comparison meaningless under `pytest --cov` (which is
# this project's default invocation). Shelling out measures the real
# behaviour the feature is meant to improve.
_TIMING_SCRIPT = textwrap.dedent("""
    import time
    import chess
    from chess_game.engine import bot as bot_mod

    board = chess.Board()
    for uci in {moves!r}:
        board.push(chess.Move.from_uci(uci))

    depth = {depth}
    bot_mod._NULL_MOVE_MIN_DEPTH = {min_depth}
    killers = [[None, None] for _ in range(depth + 1)]
    t0 = time.perf_counter()
    bot_mod._alphabeta(
        board, depth, -bot_mod.INF, bot_mod.INF,
        True, chess.WHITE, killers, {{}}, {{}}, root=True,
    )
    print(time.perf_counter() - t0)
""")


def _time_search(depth: int, min_depth: int) -> float:
    script = _TIMING_SCRIPT.format(
        moves=_QUIET_MIDDLEGAME_MOVES, depth=depth, min_depth=min_depth,
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return float(result.stdout.strip())


def test_null_move_pruning_speeds_up_deep_search():
    """A depth-5 search on a quiet middlegame must complete measurably
    faster with null-move pruning enabled than with it disabled.

    Toggling _NULL_MOVE_MIN_DEPTH above the search depth is the cleanest
    way to disable the feature without duplicating _alphabeta.  A 1.25x
    margin is used (not 1.0x) so the assertion isn't sensitive to normal
    run-to-run scheduling noise, while still failing if pruning stops
    providing any real benefit.
    """
    depth = 5
    without_null_move = _time_search(depth, min_depth=depth + 1)  # disabled
    with_null_move = _time_search(depth, min_depth=3)             # enabled

    assert with_null_move * 1.25 < without_null_move, (
        f"expected null-move pruning to give a meaningful speedup, got "
        f"{with_null_move:.2f}s (enabled) vs {without_null_move:.2f}s (disabled)"
    )


def test_null_move_pruning_skipped_under_material_floor():
    """A bare-kings-and-pawns endgame must not attempt null-move pruning —
    this is the zugzwang guard. We verify it by checking the position
    fails the gate condition directly, rather than asserting on search
    timing (king-and-pawn endgames are cheap to search either way, so a
    timing-based assertion would be too noisy to be meaningful)."""
    board = chess.Board(fen="8/4k3/8/4P3/8/4K3/8/8 w - - 0 1")
    assert bot_mod._non_pawn_material(board, chess.WHITE) < bot_mod._NULL_MOVE_MATERIAL_FLOOR
    assert bot_mod._non_pawn_material(board, chess.BLACK) < bot_mod._NULL_MOVE_MATERIAL_FLOOR


# ── Tapered evaluation ────────────────────────────────────────────────────────


def test_king_endgame_centralised_scores_higher():
    """In a low-phase (bare-kings-plus-a-pawn) position, a centralised
    king must score higher for its own side than the same king tucked in
    the corner — this is exactly what the endgame PST taper is for."""
    centre_fen = "8/8/8/3k4/8/3K4/4P3/8 w - - 0 1"
    corner_fen = "8/8/8/3k4/8/8/4P3/6K1 w - - 0 1"

    centre_board = chess.Board(fen=centre_fen)
    corner_board = chess.Board(fen=corner_fen)

    # Both positions have identical material (one pawn, two kings) and an
    # identical black king square, so the only difference is where the
    # white king sits — and both are deep endgames (phase == 0), so the
    # taper is fully weighted toward KING_END in each case.
    assert bot_mod._phase(centre_board) == 0
    assert bot_mod._phase(corner_board) == 0

    centre_score = bot_mod._evaluate(centre_board, chess.WHITE)
    corner_score = bot_mod._evaluate(corner_board, chess.WHITE)

    assert centre_score > corner_score, (
        f"expected a centralised king ({centre_score}) to score higher than "
        f"a cornered king ({corner_score}) in the endgame"
    )


def test_phase_is_max_at_start():
    """The starting position has every piece on the board, so the phase
    must read the maximum value (24 = fully midgame/opening)."""
    board = chess.Board()
    assert bot_mod._phase(board) == 24


def test_phase_is_min_in_bare_kings():
    """A board with only the two kings left has phase 0 (pure endgame)."""
    board = chess.Board(fen="8/4k3/8/8/8/8/4K3/8 w - - 0 1")
    assert bot_mod._phase(board) == 0


def test_evaluation_is_symmetric():
    """_evaluate must be antisymmetric in bot_color: flipping whose
    perspective we score from should exactly negate the result. This is
    the cheapest way to catch a sign error introduced by the taper math
    (e.g. accidentally tapering material, or swapping phase/inv_phase)."""
    positions = [
        chess.Board(),  # start position, phase == 24
        _quiet_middlegame_board(),  # mixed phase
        chess.Board(fen="8/4k3/8/4P3/8/4K3/8/8 w - - 0 1"),  # near-bare endgame
        chess.Board(fen="8/8/8/3k4/8/3K4/4P3/8 w - - 0 1"),  # bare kings + a pawn
    ]
    for board in positions:
        white_score = bot_mod._evaluate(board, chess.WHITE)
        black_score = bot_mod._evaluate(board, chess.BLACK)
        assert white_score == -black_score, (
            f"expected _evaluate to be antisymmetric, got white={white_score} "
            f"black={black_score} for fen={board.fen()}"
        )

