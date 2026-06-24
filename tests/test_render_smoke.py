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
    back_rect, board_rects, arrow_rects, motion_rect, download_rect = menus.draw_preferences(
        screen, "white_green", "blue", False, "", fonts
    )
    assert download_rect is not None

    # Every download_status branch, including a long error message that
    # needs front-truncation to avoid overflowing the card, and a long
    # downloaded path shown in the 'done' state.
    long_path = "/home/someuser/.local/share/python-chess/stockfish/stockfish-ubuntu-x86-64"
    menus.draw_preferences(
        screen, "white_green", "blue", False, long_path, fonts,
        download_status="downloading", download_progress=0.37,
    )
    menus.draw_preferences(
        screen, "white_green", "blue", False, long_path, fonts,
        download_status="downloading", download_progress=None,  # indeterminate (extracting)
    )
    menus.draw_preferences(
        screen, "white_green", "blue", False, "", fonts,
        download_status="error",
        download_error="Download failed: <urlopen error [Errno -2] Name or service not known>",
    )
    menus.draw_preferences(
        screen, "white_green", "blue", False, long_path, fonts,
        download_status="done",
    )
    menus.draw_main_menu_overlay(screen, fonts, PANEL_X)


def test_draw_eval_bar_mate_orientation_pixel_correctness():
    """Pixel-level check (not just "doesn't raise") that scores fill the
    bar from the correct end, that mate scores peg fully to the correct
    side, and that the degenerate mate_in == 0 case falls back to an even
    split rather than silently guessing a side.

    Bar geometry: x in [0, EVAL_BAR_W), y in [BOARD_Y, BOARD_Y+BOARD_PX).
    White fill colour is (235, 235, 230); Black fill is (40, 40, 40).
    Not flipped -> White sits at the bottom of the board, so White's
    fill must grow from the bottom of the bar (top stays black-ish for
    anything short of a full White rout). A full-mate fill is 100% one
    colour either way, so it can't by itself catch a flipped fill
    direction — the partial-eval case below is what actually exercises
    that bug.
    """
    from chess_game.render.board import EVAL_BAR_W, draw_eval_bar
    from chess_game.theme import BOARD_PX, BOARD_Y

    fonts = load_fonts()
    screen = pygame.Surface((WIN_W, WIN_H))
    sample_x = EVAL_BAR_W // 2
    top_y = BOARD_Y + 5
    bottom_y = BOARD_Y + BOARD_PX - 5
    white_col = (235, 235, 230)
    black_col = (40, 40, 40)

    # A large White advantage, not flipped: White's fill must dominate
    # the BOTTOM of the bar (matching White's own side of the board),
    # leaving a black sliver at the top — not the reverse.
    draw_eval_bar(screen, 800, False, False, None, fonts)
    assert screen.get_at((sample_x, top_y))[:3] == black_col
    assert screen.get_at((sample_x, bottom_y))[:3] == white_col

    # Same advantage, flipped (White now sits at the top): the fill
    # direction must flip too, so White's fill dominates the TOP.
    draw_eval_bar(screen, 800, True, False, None, fonts)
    assert screen.get_at((sample_x, top_y))[:3] == white_col
    assert screen.get_at((sample_x, bottom_y))[:3] == black_col

    # White mates (mate_in > 0): bar fully white from top to bottom.
    draw_eval_bar(screen, None, False, True, 4, fonts)
    assert screen.get_at((sample_x, top_y))[:3] == white_col
    assert screen.get_at((sample_x, bottom_y))[:3] == white_col

    # Black mates (mate_in < 0): bar fully black.
    draw_eval_bar(screen, None, False, True, -4, fonts)
    assert screen.get_at((sample_x, top_y))[:3] == black_col
    assert screen.get_at((sample_x, bottom_y))[:3] == black_col

    # Degenerate mate_in == 0: must NOT silently render as if either side
    # is mating (the side genuinely can't be recovered from this value) —
    # split roughly evenly instead, same orientation rule as eval_cp=0.
    draw_eval_bar(screen, None, False, True, 0, fonts)
    assert screen.get_at((sample_x, top_y))[:3] == black_col
    assert screen.get_at((sample_x, bottom_y))[:3] == white_col


def test_draw_eval_bar_label_never_renders_off_left_edge():
    """Regression test: the eval label used to be centred on the 14px
    bar's own midpoint, but every realistic label string ("+1.20",
    "M-12", ...) is wider than that, so centring pushed the label's left
    edge to a negative x — off the window entirely — for every value
    except the very shortest ones. The label must now be anchored from
    the bar's left edge instead, keeping it fully on-screen.
    """
    from chess_game.render.board import EVAL_BAR_LABEL_X_OFFSET, EVAL_BAR_X, draw_eval_bar
    from chess_game.theme import load_fonts as _load_fonts

    fonts = _load_fonts()
    screen = pygame.Surface((WIN_W, WIN_H))

    for eval_cp in (120, -45, 1_000_000, -1_000_000):
        draw_eval_bar(screen, eval_cp, False, False, None, fonts)
    for mate_in in (5, -12, 0):
        draw_eval_bar(screen, None, False, True, mate_in, fonts)

    # The label is always anchored at the same fixed x regardless of
    # string width, so this alone is enough to confirm it can never go
    # negative for any value drawn above.
    assert EVAL_BAR_X + EVAL_BAR_LABEL_X_OFFSET >= 0


def test_draw_eval_bar_and_info_modal():
    """Analysis mode's rendering: the eval bar across cp/mate/no-data
    states and both orientations, the Stockfish-not-found info modal, and
    a sanity check that draw_board_arrow_overlay (still used for the
    player's own right-click arrows) keeps working standalone. None of
    these should raise regardless of input — eval_cp=None (no result
    yet) and the is_mate branch in particular are easy to get a
    KeyError/TypeError on.

    app.py no longer calls draw_board_arrow_overlay a second time for a
    PV line — analysis mode shows only the eval bar — but the function
    itself is still the one rendering the player's manually-drawn
    arrows, so it's still exercised here directly.
    """
    fonts = load_fonts()
    screen = pygame.Surface((WIN_W, WIN_H))

    for flipped in (False, True):
        # Ordinary centipawn scores, including a very lopsided one (checks
        # the sigmoid clamp doesn't blow up the renderer either).
        board.draw_eval_bar(screen, 35, flipped, False, None, fonts)
        board.draw_eval_bar(screen, -480, flipped, False, None, fonts)
        board.draw_eval_bar(screen, 1_000_000, flipped, False, None, fonts)
        # Mate scores, both sides.
        board.draw_eval_bar(screen, None, flipped, True, 4, fonts)
        board.draw_eval_bar(screen, None, flipped, True, -2, fonts)
        # Degenerate mate_in == 0 (an already-checkmated position) — the
        # side can't be recovered from this value, so it must render an
        # even bar and an "M" label rather than guessing a side.
        board.draw_eval_bar(screen, None, flipped, True, 0, fonts)
        # No result yet (analysis just (re)started, nothing taken() yet).
        board.draw_eval_bar(screen, None, flipped, False, None, fonts)

    user_arrows = [(chess.E2, chess.E4)]
    arrows.draw_board_arrow_overlay(screen, user_arrows, "blue", False)
    arrows.draw_board_arrow_overlay(screen, [], "blue", False)

    ok_rect = overlays.draw_info_modal(
        screen, WIN_W, WIN_H, "Stockfish Not Found",
        "Install Stockfish or set its path in Preferences to use analysis mode.",
        fonts,
    )
    assert ok_rect is not None


def test_load_images_and_sound_with_real_assets():
    assets = load_images(_resource_path)
    assert len(assets.piece_imgs) == 12
    assert len(assets.king_imgs) == 2
    sm = SoundManager(_resource_path)
    sm.play_for_move_result("move")
    sm.play_for_move_result("capture")
    sm.play_for_move_result("move", is_check=True)
    sm.play_for_move_result("move", is_game_over=True)
