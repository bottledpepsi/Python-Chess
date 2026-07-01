"""Review-mode controller logic for stepping through past moves."""
from __future__ import annotations

import pygame

from chess_game.anim import AnimationState, AnimItem
from chess_game.layout import build_review_board, sq_to_screen


def enter_review(game, target_ply: int) -> None:
    """Enter review mode (or change target) and animate directly to target_ply."""
    assert game.adapter is not None
    if game.review.ply is None:
        game.review.ply = len(game.adapter.san_history)
        game.review.board = build_review_board(
            list(game.adapter.board.move_stack), game.review.ply
        )

    if target_ply == game.review.ply:
        return

    move_list = list(game.adapter.board.move_stack)
    items: list[AnimItem] = []
    now = pygame.time.get_ticks()

    if target_ply > game.review.ply:
        cur_board = game.review.board.copy()
        for i in range(game.review.ply, min(target_ply, len(move_list))):
            m = move_list[i]
            piece = cur_board.piece_at(m.from_square)
            img = game.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
            sx, sy = sq_to_screen(m.from_square, game.board_flipped)
            ex, ey = sq_to_screen(m.to_square, game.board_flipped)
            items.append(AnimItem(sx, sy, ex, ey, img, m.to_square))
            cur_board.push(m)
    else:
        cur_board = game.review.board.copy()
        for i in range(game.review.ply - 1, max(target_ply - 1, -1), -1):
            m = move_list[i]
            piece = cur_board.piece_at(m.to_square)
            img = game.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
            sx, sy = sq_to_screen(m.to_square, game.board_flipped)
            ex, ey = sq_to_screen(m.from_square, game.board_flipped)
            items.append(AnimItem(sx, sy, ex, ey, img, m.from_square))
            cur_board.pop()

    game.review.ply = target_ply
    game.review.board = build_review_board(move_list, target_ply)

    if items:
        game.anim = AnimationState(items=items, start_ms=now)


def exit_review(game) -> None:
    """Return immediately to the live position without animating."""
    game.review.reset()
    game.anim = None


def move_review(game, delta: int) -> None:
    """Step review mode by `delta` plies (arrow-key navigation)."""
    if game.adapter is None:
        return
    total_plies = len(game.adapter.san_history)
    if total_plies == 0:
        return

    if game.review.ply is None:
        if delta < 0:
            enter_review(game, total_plies - 1)
        elif delta > 0:
            enter_review(game, 1)
        return

    target = game.review.ply + delta
    target = max(0, min(total_plies, target))

    if target == total_plies:
        exit_review(game)
    elif target != game.review.ply:
        enter_review(game, target)
