"""Smoke tests for render/ modules - confirm every draw function runs
without raising, across both board orientations and representative state
combinations. These are not pixel-perfect assertions (that needs a human
eye on a real display) but they catch crashes, signature drift, and
KeyErrors from missing asset/theme keys.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.adapter import ChessAdapter
from chess_game.assets import load_images
from chess_game.render import arrows, board, history, menus, overlays, trays
from chess_game.sound import SoundManager
from chess_game.theme import (
    BOARD_PX,
    BOARD_X,
    BOARD_Y,
    PANEL_W,
    PANEL_X,
    WIN_H,
    WIN_W,
    load_fonts,
)


def _resource_path(rel):
    import os
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), rel)


def test_draw_board_both_orientations():
    surf = pygame.Surface((BOARD_PX, BOARD_PX))
    chess_board = chess.Board()
    for flipped in (False, True):
        board.draw_board(surf, chess_board, {}, "white_green", flipped,
                          None, None, None, set(), None)
        board.draw_labels(pygame.Surface((WIN_W, WIN_H)), flipped, load_fonts())


def test_draw_board_with_check_and_selection():
    surf = pygame.Surface((BOARD_PX, BOARD_PX))
    chess_board = chess.Board()
    board.draw_board(surf, chess_board, {}, "colorblind_safe", False,
                      chess.E1, chess.Move.from_uci("e2e4"), chess.E2,
                      {chess.E3, chess.E4}, {chess.E4})


def test_draw_trays_and_history_and_arrows():
    adapter = ChessAdapter()
    adapter._push(chess.Move.from_uci("e2e4"))
    fonts = load_fonts()
    screen = pygame.Surface((WIN_W, WIN_H))
    trays.draw_trays(screen, PANEL_X, WIN_H - 70, adapter, False, fonts, {}, False, False, 0)
    rects, live_rect, scroll = history.draw_history_panel(
        screen, PANEL_X, PANEL_W, WIN_W, WIN_H, adapter.san_history, None, 0, fonts
    )
    assert isinstance(rects, list)
    arrows.draw_board_arrow_overlay(screen, [(chess.E2, chess.E4)], "blue", False)
    arrows.draw_board_arrow_overlay(screen, [], "blue", False)


def test_draw_overlays():
    fonts = load_fonts()
    screen = pygame.Surface((WIN_W, WIN_H))
    rects = overlays.draw_promotion_overlay(screen, BOARD_X, BOARD_Y, "white", fonts, {})
    assert len(rects) == 4
    btn = overlays.draw_winner(screen, WIN_W, WIN_H, PANEL_X, ("White Wins!", "by Checkmate"), 255, fonts)
    assert btn is not None
    none_btn = overlays.draw_winner(screen, WIN_W, WIN_H, PANEL_X, ("Draw", ""), 10, fonts)
    assert none_btn is None
    overlays.draw_continue_new_overlay(screen, WIN_W, WIN_H, fonts)
    overlays.draw_error_modal(screen, WIN_W, WIN_H, "Your saved game could not be read.", fonts)


def test_draw_menus():
    fonts = load_fonts()
    screen = pygame.Surface((WIN_W, WIN_H))
    btns = menus.make_menu_buttons()
    menus.draw_menu(screen, btns, fonts)
    king_imgs = {
        "white": pygame.Surface((100, 100), pygame.SRCALPHA),
        "black": pygame.Surface((100, 100), pygame.SRCALPHA),
    }
    menus.draw_color_picker(screen, fonts, king_imgs)
    for level in range(1, 11):
        menus.draw_difficulty(screen, level, fonts)
    menus.draw_preferences(screen, "white_green", "blue", False, fonts)
    menus.draw_main_menu_overlay(screen, fonts, PANEL_X)


def test_load_images_and_sound_with_real_assets():
    assets = load_images(_resource_path)
    assert len(assets.piece_imgs) == 12
    assert len(assets.king_imgs) == 2
    sm = SoundManager(_resource_path)
    sm.play_for_move_result("move")
    sm.play_for_move_result("capture")
    sm.play_for_move_result("move", is_check=True)
    sm.play_for_move_result("move", is_game_over=True)
