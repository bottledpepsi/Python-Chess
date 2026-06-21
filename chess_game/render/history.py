"""Move-history side panel rendering.

Made pure: instead of mutating module globals
(history_ply_rects, live_btn_rect, panel_scroll), draw_history_panel
takes the current panel_scroll value and returns the new panel_scroll
plus hit-test rects, leaving the caller (app.py) to write them back
into the Game object. No behavioural change from the original other
than this data-flow direction.
"""
from __future__ import annotations

import pygame

from chess_game.theme import (
    HIST_FOOT_H,
    HIST_HDR_H,
    HIST_MOV_COL,
    HIST_MOV_W,
    HIST_NUM_COL,
    HIST_NUM_W,
    HIST_PAD,
    HIST_ROW_H,
    HIST_ROW_HOV,
    HIST_SEL_BG,
    HIST_SEL_FG,
    LIVE_BG_ACT,
    LIVE_BG_HOV,
    LIVE_BG_OFF,
    PANEL_BDR,
    PANEL_BG,
    PANEL_HDR_BG,
)


def draw_history_panel(screen, panel_x, panel_w, win_w, win_h,
                        san_history, review_ply, panel_scroll, fonts):
    """Draw the move-history panel.

    Returns (ply_rects, live_btn_rect, new_panel_scroll) where ply_rects
    is a list of (rect, ply_number) for click hit-testing.
    """
    pygame.draw.rect(screen, PANEL_BG, (panel_x, 0, panel_w, win_h))
    pygame.draw.line(screen, PANEL_BDR, (panel_x, 0), (panel_x, win_h), 1)

    pygame.draw.rect(screen, PANEL_HDR_BG, (panel_x, 0, panel_w, HIST_HDR_H))
    pygame.draw.line(screen, PANEL_BDR, (panel_x, HIST_HDR_H), (win_w, HIST_HDR_H), 1)
    hdr_s = fonts.hist_hdr.render('MOVE HISTORY', True, (88, 88, 88))
    screen.blit(hdr_s, hdr_s.get_rect(midleft=(panel_x + HIST_PAD, HIST_HDR_H // 2)))
    if review_ply is not None:
        rv_s = fonts.hist_hdr.render('\u25cf REVIEW', True, (110, 180, 100))
        screen.blit(rv_s, rv_s.get_rect(midright=(win_w - HIST_PAD, HIST_HDR_H // 2)))

    foot_y = win_h - HIST_FOOT_H
    pygame.draw.line(screen, PANEL_BDR, (panel_x, foot_y), (win_w, foot_y), 1)
    btn_m = 6
    live_btn_rect = pygame.Rect(panel_x + btn_m, foot_y + btn_m,
                                 panel_w - btn_m * 2, HIST_FOOT_H - btn_m * 2)
    mx_, my_ = pygame.mouse.get_pos()
    is_live_now = review_ply is None
    live_hov = live_btn_rect.collidepoint(mx_, my_) and not is_live_now
    live_bg = LIVE_BG_OFF if is_live_now else (LIVE_BG_HOV if live_hov else LIVE_BG_ACT)
    pygame.draw.rect(screen, live_bg, live_btn_rect, border_radius=6)
    live_brd = (50, 50, 50) if is_live_now else (80, 155, 80)
    pygame.draw.rect(screen, live_brd, live_btn_rect, 1, border_radius=6)
    live_label = '\u25cf LIVE' if is_live_now else 'Live'
    live_col = (55, 55, 55) if is_live_now else (190, 238, 190)
    live_s = fonts.live_btn.render(live_label, True, live_col)
    screen.blit(live_s, live_s.get_rect(center=live_btn_rect.center))

    if san_history is None:
        return [], live_btn_rect, panel_scroll

    total_plies = len(san_history)
    n_rows = (total_plies + 1) // 2

    cur_ply = review_ply if review_ply is not None else total_plies

    list_top_y = HIST_HDR_H
    list_bot_y = foot_y
    list_h = list_bot_y - list_top_y

    if cur_ply > 0:
        cur_row = (cur_ply - 1) // 2
    else:
        cur_row = 0
    max_scroll = max(0, n_rows * HIST_ROW_H - list_h)
    row_y_abs = cur_row * HIST_ROW_H
    new_scroll = panel_scroll
    if row_y_abs < new_scroll:
        new_scroll = row_y_abs
    elif row_y_abs + HIST_ROW_H > new_scroll + list_h:
        new_scroll = row_y_abs + HIST_ROW_H - list_h
    new_scroll = max(0, min(max_scroll, new_scroll))

    screen.set_clip(pygame.Rect(panel_x, list_top_y, panel_w, list_h))
    ply_rects = []

    for row_i in range(n_rows):
        w_idx = row_i * 2
        b_idx = row_i * 2 + 1
        row_y = list_top_y + row_i * HIST_ROW_H - new_scroll

        if row_y + HIST_ROW_H < list_top_y or row_y > list_bot_y:
            continue

        row_bg = (30, 30, 30) if row_i % 2 == 0 else PANEL_BG
        pygame.draw.rect(screen, row_bg, (panel_x, row_y, panel_w, HIST_ROW_H))

        num_s = fonts.hist_num.render(str(row_i + 1) + '.', True, HIST_NUM_COL)
        screen.blit(num_s, (panel_x + HIST_PAD,
                            row_y + (HIST_ROW_H - num_s.get_height()) // 2))

        w_ply = w_idx + 1
        if w_idx < total_plies:
            wx = panel_x + HIST_PAD + HIST_NUM_W
            w_rect = pygame.Rect(wx, row_y, HIST_MOV_W, HIST_ROW_H)
            w_sel = (cur_ply == w_ply)
            w_hov = w_rect.collidepoint(mx_, my_)
            if w_sel:
                pygame.draw.rect(screen, HIST_SEL_BG, w_rect, border_radius=3)
            elif w_hov:
                pygame.draw.rect(screen, HIST_ROW_HOV, w_rect, border_radius=3)
            w_col = HIST_SEL_FG if w_sel else HIST_MOV_COL
            w_s = fonts.hist_mov.render(san_history[w_idx], True, w_col)
            screen.blit(w_s, (wx + 4, row_y + (HIST_ROW_H - w_s.get_height()) // 2))
            ply_rects.append((w_rect, w_ply))

        b_ply = b_idx + 1
        if b_idx < total_plies:
            bx = panel_x + HIST_PAD + HIST_NUM_W + HIST_MOV_W
            b_rect = pygame.Rect(bx, row_y, HIST_MOV_W, HIST_ROW_H)
            b_sel = (cur_ply == b_ply)
            b_hov = b_rect.collidepoint(mx_, my_)
            if b_sel:
                pygame.draw.rect(screen, HIST_SEL_BG, b_rect, border_radius=3)
            elif b_hov:
                pygame.draw.rect(screen, HIST_ROW_HOV, b_rect, border_radius=3)
            b_col = HIST_SEL_FG if b_sel else HIST_MOV_COL
            b_s = fonts.hist_mov.render(san_history[b_idx], True, b_col)
            screen.blit(b_s, (bx + 4, row_y + (HIST_ROW_H - b_s.get_height()) // 2))
            ply_rects.append((b_rect, b_ply))

    screen.set_clip(None)

    if n_rows > 0 and n_rows * HIST_ROW_H > list_h:
        sb_ratio = new_scroll / max(1, n_rows * HIST_ROW_H)
        sb_size = max(20, int(list_h * list_h / max(1, n_rows * HIST_ROW_H)))
        sb_y = list_top_y + int((list_h - sb_size) * sb_ratio)
        pygame.draw.rect(screen, (58, 58, 58), (win_w - 5, sb_y, 4, sb_size), border_radius=2)

    return ply_rects, live_btn_rect, new_scroll
