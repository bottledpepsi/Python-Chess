"""Tests for PvP auto-flip between turns and the refactored menu flow.

Verifies:
  - After a PvP move, pending_pvp_flip is set and the board flips once the
    animation completes.
  - The board does NOT flip during the animation.
  - The board does NOT flip on game-over (no next turn to orient for).
  - The board does NOT flip in BOT mode.
  - Resuming a saved PvP game orients the board for the side to move.
"""
from __future__ import annotations

import chess
import pygame
import pytest

from chess_game.app import App
from chess_game.layout import sq_to_screen
from chess_game.state import GameState


@pytest.fixture
def app(isolated_save_dir):
    pygame.display.quit()
    pygame.display.init()
    return App()


def _click(app, x, y):
    app._handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x, y)), x, y)
    app._handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x, y)), x, y)


def _finish_animation(app):
    if app.game.anim is not None:
        app.game.anim.start_ms = -10_000


def _sq(sq, flipped=False):
    return sq_to_screen(sq, flipped)


# ── pending_pvp_flip is set after a PvP move ────────────────────────────────

def test_pvp_move_sets_pending_flip(app):
    """A completed PvP move must set pending_pvp_flip so the board will
    rotate for the next player once the animation finishes."""
    app.game.state = GameState.PVP
    app.start_game()
    assert app.game.pending_pvp_flip is False

    _click(app, *_sq(chess.E2))
    _click(app, *_sq(chess.E4))

    assert app.game.adapter.san_history == ['e4']
    assert app.game.pending_pvp_flip is True


def test_pvp_flip_applied_after_animation_completes(app):
    """After the move slide finishes, the flip animation is armed and runs
    to completion, ending with the board flipped."""
    from chess_game.anim import FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()

    _click(app, *_sq(chess.E2))
    _click(app, *_sq(chess.E4))
    assert app.game.board_flipped is False  # still unflipped during move slide

    # Finish the move slide, then arm the flip.
    _finish_animation(app)
    now = pygame.time.get_ticks()
    app._maybe_arm_pvp_flip(now)
    assert app.game.flip is not None  # flip animation armed
    assert app.game.pending_pvp_flip is False

    # Advance time past the flip duration and let update_flip complete it.
    app.game.update_flip(now + FLIP_MS + 10)

    assert app.game.board_flipped is True
    assert app.game.flip is None  # flip animation cleaned up


def test_pvp_flip_not_applied_during_animation(app):
    """The flip must wait until the move slide completes — otherwise the
    piece would rotate mid-slide."""
    app.game.state = GameState.PVP
    app.start_game()

    _click(app, *_sq(chess.E2))
    _click(app, *_sq(chess.E4))
    # Move slide is fresh (start_ms ≈ now), so _maybe_arm_pvp_flip must not
    # arm a flip yet.
    app._maybe_arm_pvp_flip(pygame.time.get_ticks())

    assert app.game.flip is None
    assert app.game.board_flipped is False
    assert app.game.pending_pvp_flip is True


def test_pvp_flip_alternates_each_move(app):
    """After white's move the board flips to black's view; after black's
    move it flips back to white's view."""
    from chess_game.anim import FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()

    def _complete_flip():
        """Finish the move slide, arm the flip, then run it to completion."""
        _finish_animation(app)
        now = pygame.time.get_ticks()
        app._maybe_arm_pvp_flip(now)
        if app.game.flip is not None:
            app.game.update_flip(now + FLIP_MS + 10)

    # White plays e4
    _click(app, *_sq(chess.E2))
    _click(app, *_sq(chess.E4))
    _complete_flip()
    assert app.game.board_flipped is True  # now black's perspective

    # Black plays e5 — coordinates must use the flipped orientation
    _click(app, *_sq(chess.E7, flipped=True))
    _click(app, *_sq(chess.E5, flipped=True))
    _complete_flip()
    assert app.game.board_flipped is False  # back to white's perspective

    assert app.game.adapter.san_history == ['e4', 'e5']


# ── No flip on game-over ────────────────────────────────────────────────────

def test_pvp_no_flip_on_game_over(app):
    """If a move ends the game, the board must NOT queue a flip — there's
    no next player to orient for, and the winner overlay should show from
    the final position's perspective."""
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # Set up fool's mate position one move before the end.
    for uci in ('f2f3', 'e7e5', 'g2g4'):
        g.adapter.apply_move(chess.Move.from_uci(uci))

    # Black plays Qh4# via the click UI. The board is unflipped (white's
    # perspective, black to move). d8 is at top, h4 is mid-board.
    _click(app, *_sq(chess.D8))
    _click(app, *_sq(chess.H4))

    assert g.adapter.is_game_over
    assert g.pending_pvp_flip is False, "must not queue a flip when the game is over"


# ── No flip in BOT mode ─────────────────────────────────────────────────────

def test_bot_mode_does_not_set_pending_flip(app):
    """BOT mode must never set pending_pvp_flip — the board orientation is
    fixed to the player's color for the whole game."""
    app.game.state = GameState.BOT
    app.game.player_color = 'white'
    app.game.board_flipped = False
    app.start_game()

    _click(app, *_sq(chess.E2))
    _click(app, *_sq(chess.E4))

    assert app.game.adapter.san_history == ['e4']
    assert app.game.pending_pvp_flip is False


# ── Resuming a saved PvP game orients for the side to move ──────────────────

def test_continue_saved_pvp_orients_for_side_to_move(app, isolated_save_dir):
    """When resuming a PvP game where it's Black's turn, the board must be
    flipped so Black sits at the bottom."""
    from chess_game import io as save_io

    # One white move played → Black to move.
    moves = [chess.Move.from_uci('e2e4')]
    save_io.write_save('pvp', moves, 'white', 5)  # color/level ignored for pvp
    save = save_io.read_save('pvp')

    app.continue_saved_game(save, GameState.PVP)

    assert app.game.state == GameState.PVP
    assert app.game.adapter.turn == 'black'
    assert app.game.board_flipped is True  # black to move → flipped


def test_continue_saved_pvp_white_to_move_not_flipped(app, isolated_save_dir):
    """When resuming a PvP game where it's White's turn (even number of
    moves played), the board must NOT be flipped."""
    from chess_game import io as save_io

    # Two moves played → White to move.
    moves = [chess.Move.from_uci('e2e4'), chess.Move.from_uci('e7e5')]
    save_io.write_save('pvp', moves, 'white', 5)
    save = save_io.read_save('pvp')

    app.continue_saved_game(save, GameState.PVP)

    assert app.game.adapter.turn == 'white'
    assert app.game.board_flipped is False


# ── No pending flip after starting a fresh PvP game ─────────────────────────

def test_fresh_pvp_game_starts_with_no_pending_flip(app):
    app.game.state = GameState.PVP
    app.start_game()
    assert app.game.pending_pvp_flip is False
    assert app.game.board_flipped is False  # white to move first


# ── Flip animation behaviour ────────────────────────────────────────────────

def test_flip_animation_has_delay_before_squashing(app):
    """During the pre-flip delay, the board must still be at full width
    (progress == 1.0) and in the old orientation."""
    from chess_game.anim import FLIP_DELAY_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    g.start_flip(0, target_flipped=True)  # arm flip at t=0
    assert g.flip is not None
    assert g.flip.target_flipped is True
    assert g.flip.is_delaying(0) is True
    assert g.flip.is_delaying(FLIP_DELAY_MS - 1) is True
    # During the delay, progress is 1.0 (full width, old orientation).
    assert g.flip.progress(0) == 1.0
    assert g.flip.progress(FLIP_DELAY_MS - 1) == 1.0
    # Orientation has NOT swapped yet.
    assert g.board_flipped is False


def test_flip_orientation_sets_at_midpoint(app):
    """The board_flipped flag must be SET to the target exactly once during
    the flip, at the midpoint when the board is at minimum width."""
    from chess_game.anim import FLIP_DELAY_MS, FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    g.start_flip(0, target_flipped=True)
    assert g.board_flipped is False

    # First half of the flip phase: board squashing, no swap yet.
    flip_phase_mid = FLIP_DELAY_MS + (FLIP_MS - FLIP_DELAY_MS) // 2
    g.update_flip(flip_phase_mid - 5)
    assert g.board_flipped is False  # still old orientation
    assert g.flip_swapped is False

    # Just past midpoint: SET to target fires.
    g.update_flip(flip_phase_mid + 1)
    assert g.board_flipped is True
    assert g.flip_swapped is True

    # Further updates during the second half must NOT swap again.
    g.update_flip(flip_phase_mid + 50)
    assert g.board_flipped is True
    assert g.flip_swapped is True


def test_flip_cleans_up_after_completion(app):
    """After the flip duration elapses, update_flip must clear the FlipState,
    reset the swapped latch, and ensure the board is at the target."""
    from chess_game.anim import FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    g.start_flip(0, target_flipped=True)
    g.update_flip(FLIP_MS + 10)

    assert g.flip is None
    assert g.flip_swapped is False
    assert g.board_flipped is True  # SET to target


def test_flip_respects_reduced_motion(app):
    """When reduced_motion is enabled, start_flip must SET the orientation
    to the target instantly with no animation (flip state stays None)."""
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game
    g.reduced_motion = True

    g.start_flip(0, target_flipped=True)
    assert g.flip is None  # no animation armed
    assert g.board_flipped is True  # orientation SET to target instantly


def test_flip_progress_is_zero_at_midpoint(app):
    """At the flip midpoint (the orientation swap moment) the horizontal
    scale must reach its minimum (FLIP_MIN_SCALE, not 0 — a full squash to
    zero was nauseating and is no longer used)."""
    from chess_game.anim import FLIP_DELAY_MS, FLIP_MIN_SCALE, FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    g.start_flip(0, target_flipped=True)
    mid = FLIP_DELAY_MS + (FLIP_MS - FLIP_DELAY_MS) // 2
    assert abs(g.flip.progress(mid) - FLIP_MIN_SCALE) < 1e-6
    # And it's back to 1.0 at the end.
    assert g.flip.progress(FLIP_MS) == 1.0


# ── Rapid-move race-condition tests ─────────────────────────────────────────

def test_rapid_moves_always_correct_orientation(app):
    """Making rapid moves (queuing flips while a flip is in-flight) must
    always leave the board in the correct orientation for the side to move.

    This is the core race-condition regression test: previously the flip
    used a relative toggle, so rapid moves could leave the board showing
    the wrong player at the bottom. The absolute-target fix + the
    _enforce_pvp_orientation safety net guarantee correctness.
    """
    from chess_game.anim import FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # White moves e4. This arms a flip (target: Black to move → flipped).
    _click(app, *_sq(chess.E2))
    _click(app, *_sq(chess.E4))
    _finish_animation(app)
    now = pygame.time.get_ticks()
    app._maybe_arm_pvp_flip(now)
    assert g.flip is not None
    assert g.flip.target_flipped is True  # Black to move → flipped

    # While the flip is in-flight, the board_flipped flag hasn't changed
    # yet (it changes at the midpoint). So the player is still seeing the
    # OLD (unflipped) orientation. To play Black's move, they click using
    # the unflipped coordinates — which is what the real game would do
    # because the flip animation hides the orientation change.
    # We'll bypass the click UI and apply the move directly, then verify
    # the second flip has the correct target.
    g.update_flip(now + 50)  # flip still in-flight, board still unflipped
    # Apply Black's move directly (simulating a click that lands correctly).
    g.adapter.apply_move(chess.Move.from_uci('e7e5'))
    g.pending_pvp_flip = True
    _finish_animation(app)
    # Now it's White's turn again — the new flip target should be NOT flipped.
    app._maybe_arm_pvp_flip(now + 60)
    assert g.flip is not None
    assert g.flip.target_flipped is False  # White to move → not flipped

    # Let the flip complete.
    g.update_flip(now + 60 + FLIP_MS + 10)
    assert g.board_flipped is False  # correct: White to move
    # Safety net should also agree.
    app._enforce_pvp_orientation(now + 60 + FLIP_MS + 20)
    assert g.board_flipped is False


def test_enforce_pvp_orientation_corrects_wrong_state(app):
    """_enforce_pvp_orientation must force-correct the board if it's in the
    wrong orientation when no flip/anim is in-flight."""
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # White to move, but board is wrongly flipped.
    g.board_flipped = True
    g.flip = None
    g.pending_pvp_flip = False
    app._enforce_pvp_orientation(0)
    assert g.board_flipped is False  # corrected to match White's turn


def test_enforce_pvp_orientation_does_not_correct_during_flip(app):
    """_enforce_pvp_orientation must NOT interfere while a flip is in-flight."""
    from chess_game.anim import FLIP_DELAY_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    g.start_flip(0, target_flipped=True)
    app._enforce_pvp_orientation(FLIP_DELAY_MS + 10)
    # The in-flight flip is still there, board hasn't been force-corrected.
    assert g.flip is not None
    assert g.board_flipped is False  # still pre-swap


# ── Piece interaction blocked during flip ───────────────────────────────────

def test_piece_interaction_blocked_during_flip(app):
    """While the board-flip animation is in-flight, clicking on a piece must
    NOT select it. All piece interaction is blocked until the flip completes.
    """
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # Arm a flip at the current time so is_active(now) returns True.
    now = pygame.time.get_ticks()
    g.start_flip(now, target_flipped=True)
    assert g.flip is not None

    # While the flip is in-flight, click on a pawn (e2). This must NOT
    # select the piece.
    e2_x, e2_y = _sq(chess.E2)
    _click(app, e2_x, e2_y)
    assert g.adapter.selected_square is None  # piece was NOT selected

    # Even after the delay phase (during the squash/stretch), clicks are blocked.
    _click(app, e2_x, e2_y)
    assert g.adapter.selected_square is None


def test_piece_interaction_allowed_after_flip_completes(app):
    """After the flip animation completes, piece interaction works normally."""
    from chess_game.anim import FLIP_MS
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # Arm and complete a flip (target: flipped for Black's perspective).
    g.start_flip(0, target_flipped=True)
    g.update_flip(FLIP_MS + 10)
    assert g.flip is None  # flip completed
    assert g.board_flipped is True  # now showing Black's perspective

    # Now a click on e2 (using flipped coordinates) should select the piece.
    # After the flip, e2 is at a different screen position, so we use
    # the flipped coordinate helper.
    e2_x, e2_y = _sq(chess.E2, flipped=True)
    _click(app, e2_x, e2_y)
    assert g.adapter.selected_square == chess.E2


def test_drag_blocked_during_flip(app):
    """A drag started before the flip must not complete (drop the piece)
    while the flip is in-flight."""
    from chess_game.app import DRAG_THRESHOLD_PX
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # Select the e2 pawn and arm a drag.
    e2_x, e2_y = _sq(chess.E2)
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(e2_x, e2_y)),
        e2_x, e2_y,
    )
    assert g.adapter.selected_square == chess.E2
    # Arm the drag by moving past the threshold.
    step_x = e2_x + DRAG_THRESHOLD_PX + 5
    app._handle_event(
        pygame.event.Event(pygame.MOUSEMOTION, pos=(step_x, e2_y), rel=(step_x - e2_x, 0)),
        step_x, e2_y,
    )
    assert app.drag_active is True

    # Now a flip starts at the current time so is_active(now) returns True.
    now = pygame.time.get_ticks()
    g.start_flip(now, target_flipped=True)

    # Try to drop on e4 — must NOT apply the move while the flip is in-flight.
    e4_x, e4_y = _sq(chess.E4)
    app._handle_event(
        pygame.event.Event(pygame.MOUSEMOTION, pos=(e4_x, e4_y), rel=(e4_x - step_x, e4_y - e2_y)),
        e4_x, e4_y,
    )
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(e4_x, e4_y)),
        e4_x, e4_y,
    )
    # The move was NOT applied — the pawn is still on e2.
    assert g.adapter.board.piece_at(chess.E2) is not None
    assert g.adapter.san_history == []  # no move was recorded
