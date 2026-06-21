"""Headless tests for the drag-and-drop piece movement feature.

These tests verify that:
  - A mousedown+mouseup below the drag threshold behaves as a pure click
    (backward-compatible with the existing click-to-select/click-to-move flow).
  - A mousedown + motion beyond the threshold + mouseup on a valid target
    applies the move (drag-and-drop).
  - A drag that releases on an invalid square leaves the piece selected
    (forgiving behaviour).
  - A drag that releases outside the board leaves the piece selected.
  - Promotion via drag still triggers the promotion overlay.
  - Escape cancels an in-flight drag.
"""
from __future__ import annotations

import chess
import pygame
import pytest

from chess_game.app import DRAG_THRESHOLD_PX, App
from chess_game.layout import sq_to_screen
from chess_game.state import GameState


@pytest.fixture
def app(isolated_save_dir):
    """A fresh App with no save files on disk (mirrors the fixture in
    test_app.py — duplicated here so this test module is self-contained
    without modifying conftest.py)."""
    pygame.display.quit()
    pygame.display.init()
    return App()


def _click(app: App, x: int, y: int, button: int = 1) -> None:
    """A pure mousedown+mouseup pair at the same screen coordinate — simulates
    a click without any mouse motion in between."""
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=(x, y)), x, y
    )
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=button, pos=(x, y)), x, y
    )


def _finish_animation(app: App) -> None:
    """Force any in-flight piece-slide animation to be considered finished,
    so the next synthetic event isn't swallowed by the is_animating guard
    (mirrors the helper in test_app.py)."""
    if app.game.anim is not None:
        app.game.anim.start_ms = -10_000


def _drag(app: App, x1: int, y1: int, x2: int, y2: int) -> None:
    """Simulate a drag: mousedown at (x1,y1), motion to (x2,y2) crossing the
    drag threshold, mouseup at (x2,y2). The motion is broken into small steps
    so the threshold check in _update_drag_motion fires correctly."""
    _finish_animation(app)
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(x1, y1)), x1, y1
    )
    # Step the cursor well past the threshold (DRAG_THRESHOLD_PX + buffer) so
    # _update_drag_motion promotes the pending drag to active.
    step_x = x1 + (DRAG_THRESHOLD_PX + 5)
    step_y = y1
    app._handle_event(
        pygame.event.Event(pygame.MOUSEMOTION, pos=(step_x, step_y), rel=(step_x - x1, 0)),
        step_x, step_y,
    )
    assert app.drag_active, "drag should have been promoted to active after threshold motion"
    # Continue to the final drop position.
    app._handle_event(
        pygame.event.Event(pygame.MOUSEMOTION, pos=(x2, y2), rel=(x2 - step_x, y2 - step_y)),
        x2, y2,
    )
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x2, y2)), x2, y2
    )


def _square_center(sq: int, board_flipped: bool = False) -> tuple[int, int]:
    return sq_to_screen(sq, board_flipped)


# ── Backward-compat: pure click still works ─────────────────────────────────

def test_click_to_select_then_click_to_move_still_works(app):
    """The existing click-to-select + click-to-move flow must be unchanged."""
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    to_x, to_y = _square_center(chess.E4)
    _click(app, from_x, from_y)
    _click(app, to_x, to_y)

    assert app.game.adapter.san_history == ['e4']
    assert chess.Move.from_uci('e2e4') in app.game.adapter.board.move_stack


def test_click_below_threshold_is_not_a_drag(app):
    """A mousedown+mouseup at the same coordinate should not lift the piece
    off the board (drag_active must remain False)."""
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    # Press only (no motion, no release yet).
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(from_x, from_y)),
        from_x, from_y,
    )
    # drag_pending should be armed (mousedown selected the piece) but drag_active
    # must stay False because the cursor hasn't moved past the threshold.
    assert app.drag_pending is True
    assert app.drag_active is False
    assert app.drag_sq == chess.E2


# ── Drag-and-drop applies moves ─────────────────────────────────────────────

def test_drag_piece_to_valid_target_applies_move(app):
    """Dragging a piece from its square to a valid target square should
    apply the move, exactly as if the user had clicked both squares."""
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    to_x, to_y = _square_center(chess.E4)
    _drag(app, from_x, from_y, to_x, to_y)

    assert app.game.adapter.san_history == ['e4']
    assert chess.Move.from_uci('e2e4') in app.game.adapter.board.move_stack
    # Drag state must be fully cleared after a successful drop.
    assert app.drag_active is False
    assert app.drag_pending is False
    assert app.drag_sq is None


def test_drag_capture_updates_san_history(app):
    """A drag that captures an enemy piece records the capture in SAN
    history, just like the click flow."""
    app.game.state = GameState.PVP
    app.start_game()

    # Walk into a position where white can capture en passant... or just play
    # a simple capturing line. 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Bxc6 dxc6
    setup = [
        (chess.E2, chess.E4),
        (chess.E7, chess.E5),
        (chess.G1, chess.F3),
        (chess.B8, chess.C6),
        (chess.F1, chess.B5),
        (chess.A7, chess.A6),
    ]
    for from_sq, to_sq in setup:
        _drag(app, *_square_center(from_sq), *_square_center(to_sq))

    # White Bishop takes Knight on c6 — a capture.
    _drag(app, *_square_center(chess.B5), *_square_center(chess.C6))

    assert app.game.adapter.san_history[-1] == 'Bxc6'
    assert len(app.game.adapter.san_history) == 7


# ── Forgiving cancellation ──────────────────────────────────────────────────

def test_drag_released_on_invalid_square_keeps_piece_selected(app):
    """Dropping a piece on a non-target square should cancel the drag but
    leave the piece selected, so the user can click a target next."""
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    # A1 is clearly not a legal target for the e2 pawn (pawns can only move
    # forward to e3/e4, or capture diagonally to d3/f3 — both empty here).
    invalid_x, invalid_y = _square_center(chess.A1)
    _drag(app, from_x, from_y, invalid_x, invalid_y)

    # The pawn must still be on e2 and still be selected.
    assert app.game.adapter.board.piece_at(chess.E2) is not None
    assert app.game.adapter.selected_square == chess.E2
    # Drag state cleared.
    assert app.drag_active is False
    assert app.drag_pending is False


def test_drag_released_outside_board_keeps_piece_selected(app):
    """Dropping a piece outside the board area should cancel the drag but
    leave the piece selected."""
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    # Drop somewhere well off the board (e.g. the panel area).
    _drag(app, from_x, from_y, 700, 400)

    assert app.game.adapter.board.piece_at(chess.E2) is not None
    assert app.game.adapter.selected_square == chess.E2
    assert app.drag_active is False
    assert app.drag_pending is False


# ── Promotion via drag ──────────────────────────────────────────────────────

def test_drag_promotion_triggers_promotion_overlay(app):
    """Dragging a pawn to the promotion rank should set promotion_pending
    (the user then picks a piece via the existing flow)."""
    app.game.state = GameState.PVP
    app.start_game()
    g = app.game

    # Walk a white pawn to a7 via two captures, with filler moves to pass
    # the turn back to white. a8 is still black's rook, so the promotion
    # move is the diagonal capture a7xb8.
    setup_moves = [
        'a2a4', 'b7b5', 'a4b5', 'a7a6', 'b5a6',
        'd7d5', 'a6a7', 'd5d4',
    ]
    for uci in setup_moves:
        g.adapter.apply_move(chess.Move.from_uci(uci))
    assert g.adapter.turn == 'white'

    from_x, from_y = _square_center(chess.A7, g.board_flipped)
    to_x, to_y = _square_center(chess.B8, g.board_flipped)
    _drag(app, from_x, from_y, to_x, to_y)

    # The drag should have set promotion_pending; the user picks a piece next.
    assert g.adapter.promotion_pending is not None
    # Drag state is cleared regardless — the promotion flow takes over.
    assert app.drag_active is False
    assert app.drag_pending is False


# ── Drag animation starts from cursor position ─────────────────────────────

def test_drag_animation_starts_from_cursor_release_position(app):
    """When a drag completes, the slide animation must begin from the cursor's
    release position — NOT the origin square's centre. Otherwise the piece
    visually snaps back to its origin before sliding to the destination.
    """
    app.game.state = GameState.PVP
    app.start_game()
    app.game.reduced_motion = False  # ensure the animation is actually created

    from_x, from_y = _square_center(chess.E2)
    to_x, to_y = _square_center(chess.E4)
    # Drop slightly off the destination centre so the release position is
    # distinguishable from both the origin and the destination centres.
    drop_x, drop_y = to_x + 12, to_y + 8
    _drag(app, from_x, from_y, drop_x, drop_y)

    anim = app.game.anim
    assert anim is not None
    assert len(anim.items) == 1
    item = anim.items[0]
    # The animation start must be the cursor release position…
    assert (item.sx, item.sy) == (drop_x, drop_y)
    # …and the end must be the destination square's centre.
    assert (item.ex, item.ey) == (to_x, to_y)
    # Sanity: the start must NOT be the origin square's centre.
    assert (item.sx, item.sy) != (from_x, from_y)


def test_click_animation_unchanged_uses_origin_square(app):
    """The existing click-to-move flow must NOT pass a start_pos override —
    the animation should still begin from the origin square's centre."""
    app.game.state = GameState.PVP
    app.start_game()
    app.game.reduced_motion = False

    from_x, from_y = _square_center(chess.E2)
    to_x, to_y = _square_center(chess.E4)
    _click(app, from_x, from_y)
    _click(app, to_x, to_y)

    anim = app.game.anim
    assert anim is not None
    item = anim.items[0]
    # Click path: animation starts at the origin square centre.
    assert (item.sx, item.sy) == (from_x, from_y)
    assert (item.ex, item.ey) == (to_x, to_y)


# ── Escape cancels drag ─────────────────────────────────────────────────────

def test_escape_cancels_in_flight_drag(app):
    """Pressing Escape mid-drag should reset the drag state (the overlay
    would otherwise swallow the subsequent mouseup)."""
    app.game.state = GameState.PVP
    app.start_game()

    from_x, from_y = _square_center(chess.E2)
    # Press to arm the drag.
    app._handle_event(
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(from_x, from_y)),
        from_x, from_y,
    )
    # Move past the threshold to promote to active drag.
    step_x = from_x + DRAG_THRESHOLD_PX + 5
    app._handle_event(
        pygame.event.Event(pygame.MOUSEMOTION, pos=(step_x, from_y), rel=(step_x - from_x, 0)),
        step_x, from_y,
    )
    assert app.drag_active is True

    # Press Escape — should open the main menu overlay and reset drag.
    app._handle_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0),
        step_x, from_y,
    )
    assert app.game.main_menu_overlay is True
    assert app.drag_active is False
    assert app.drag_pending is False
    assert app.drag_sq is None
