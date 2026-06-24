"""Promotion picker, winner fade, and continue/new-game overlays.

All functions here are pure: they take a surface plus explicit data and
return hit-test rects, instead of reading/writing module globals as the
original main.py did.

Each of these allocates a per-call SRCALPHA surface, same as
the original. That allocation is cheap relative to the per-frame board
surface (which IS cached in app.py); these overlays are not drawn every
frame of normal play (only while the relevant modal is open), so caching
them would add complexity for little benefit. The dropped per-frame
.convert_alpha() call is the actual perf/robustness fix that matters
here and IS applied below.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.theme import (
    BOARD_PX,
    MENU_ACCENT,
    PROMO_BG_C,
    PROMO_BRD,
    PROMO_HOV,
    PROMO_NORM,
)

PROMO_OPTIONS = [
    ('Queen', chess.QUEEN, 'queen'),
    ('Rook', chess.ROOK, 'rook'),
    ('Bishop', chess.BISHOP, 'bishop'),
    ('Knight', chess.KNIGHT, 'knight'),
]


def draw_promotion_overlay(screen, board_x, board_y, turn_color, fonts,
                            promo_imgs_small):
    """Draw the promotion picker. Returns [(absolute_rect, piece_type), ...]
    for hit-testing in the input layer.

    No redundant convert_alpha() call on the already-SRCALPHA
    overlay, and no bare except Exception: pass masking failures.
    """
    overlay = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 155))
    color_char = 'w' if turn_color == 'white' else 'b'

    icon, gap, pad = 54, 6, 10
    n = len(PROMO_OPTIONS)
    box_w = n * icon + (n - 1) * gap + pad * 2
    box_h = icon + pad * 2
    box_x = board_x + (BOARD_PX - box_w) // 2
    box_y = board_y + (BOARD_PX - box_h) // 2
    lbl_h = 18

    panel = pygame.Rect(box_x - 2 - board_x, box_y - lbl_h - 6 - board_y,
                         box_w + 4, box_h + lbl_h + 10)
    pygame.draw.rect(overlay, PROMO_BG_C, panel, border_radius=10)
    pygame.draw.rect(overlay, PROMO_BRD, panel, 1, border_radius=10)
    title = fonts.label.render('PROMOTE TO', True, (140, 140, 140))
    overlay.blit(title, (box_x + (box_w - title.get_width()) // 2 - board_x,
                          box_y - lbl_h - 2 - board_y))

    mx, my = pygame.mouse.get_pos()
    rects = []
    for i, (label, pt, pname) in enumerate(PROMO_OPTIONS):
        ix = box_x + pad + i * (icon + gap)
        iy = box_y + pad
        rect = pygame.Rect(ix - 3, iy - 3, icon + 6, icon + 6)
        hov = rect.collidepoint(mx, my)
        rect_local = pygame.Rect(rect.x - board_x, rect.y - board_y,
                                  rect.width, rect.height)
        pygame.draw.rect(overlay, PROMO_HOV if hov else PROMO_NORM,
                          rect_local, border_radius=7)
        if hov:
            pygame.draw.rect(overlay, (150, 150, 150), rect_local, 1, border_radius=7)
            tip = fonts.label.render(label, True, (220, 220, 220))
            tip_w = tip.get_width() + 10
            tip_x = rect.centerx - tip_w // 2
            tip_y = rect.top - 22
            tip_bg = pygame.Rect(tip_x - 2 - board_x, tip_y - board_y, tip_w + 4, 18)
            pygame.draw.rect(overlay, (55, 55, 55), tip_bg, border_radius=4)
            overlay.blit(tip, (tip_x + 3 - board_x, tip_y + 2 - board_y))
        img = promo_imgs_small.get(color_char + '_' + pname)
        if img:
            img_rect = img.get_rect(center=rect.center)
            overlay.blit(img, img_rect.move(-board_x, -board_y))
        rects.append((rect, pt))

    screen.blit(overlay, (board_x, board_y))
    return rects


def draw_winner(screen, win_w, win_h, panel_x, result, alpha, fonts):
    """Draw the winner fade-in overlay. Returns the 'Main Menu' button rect,
    or None if the button isn't visible yet (alpha is dt-scaled by
    the caller, not incremented per-frame here)."""
    headline, subtitle = result
    ov = pygame.Surface((win_w, win_h), pygame.SRCALPHA)
    ov.fill((0, 0, 0, min(int(alpha), 175)))
    screen.blit(ov, (0, 0))

    menu_btn_rect = None
    if alpha > 80:
        a = min(255, (alpha - 80) * 5)
        cx = panel_x // 2
        cy = win_h // 2

        head_col = (255, 215, 0) if 'Wins' in headline else (180, 180, 220)
        ws = fonts.win.render(headline, True, head_col)
        ws.set_alpha(int(a))
        screen.blit(ws, ws.get_rect(center=(cx, cy - 44)))
        if subtitle:
            ss = fonts.win_s.render(subtitle, True, (200, 200, 200))
            ss.set_alpha(int(a))
            screen.blit(ss, ss.get_rect(center=(cx, cy + 8)))
        if a > 200:
            bw, bh = 180, 42
            btn = pygame.Rect(cx - bw // 2, cy + 44, bw, bh)
            mx_, my_ = pygame.mouse.get_pos()
            hov = btn.collidepoint(mx_, my_)
            bg = pygame.Surface((bw, bh), pygame.SRCALPHA)
            bg.fill((60, 60, 60, 210) if hov else (40, 40, 40, 190))
            screen.blit(bg, btn.topleft)
            border_col = (160, 160, 160) if hov else (90, 90, 90)
            pygame.draw.rect(screen, border_col, btn, 1, border_radius=8)
            lbl = fonts.btn.render('Main Menu', True, (220, 220, 220) if hov else (170, 170, 170))
            lbl.set_alpha(int(a))
            screen.blit(lbl, lbl.get_rect(center=btn.center))
            menu_btn_rect = btn

    return menu_btn_rect


def draw_continue_new_overlay(screen, win_w, win_h, fonts):
    """Draw the 'Continue saved game / New game' choice overlay.
    Returns (continue_btn_rect, new_btn_rect)."""
    ov = pygame.Surface((win_w, win_h), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 175))
    screen.blit(ov, (0, 0))

    box_w, box_h = 360, 190
    box = pygame.Rect((win_w - box_w) // 2, (win_h - box_h) // 2, box_w, box_h)
    pygame.draw.rect(screen, (32, 32, 32), box, border_radius=12)
    pygame.draw.rect(screen, (70, 70, 70), box, 1, border_radius=12)

    title = fonts.ov_title.render('Saved game found', True, (220, 220, 220))
    screen.blit(title, title.get_rect(center=(box.centerx, box.y + 36)))
    sub = fonts.ov_sub.render('Continue where you left off?', True, (160, 160, 160))
    screen.blit(sub, sub.get_rect(center=(box.centerx, box.y + 62)))

    mx, my = pygame.mouse.get_pos()
    btn_w, btn_h, gap = 150, 44, 16
    cont_btn = pygame.Rect(box.centerx - btn_w - gap // 2, box.y + 110, btn_w, btn_h)
    new_btn = pygame.Rect(box.centerx + gap // 2, box.y + 110, btn_w, btn_h)

    for rect, label, accent in ((cont_btn, 'Continue', True), (new_btn, 'New Game', False)):
        hov = rect.collidepoint(mx, my)
        bg = MENU_ACCENT if (accent and hov) else ((55, 55, 55) if hov else (42, 42, 42))
        pygame.draw.rect(screen, bg, rect, border_radius=8)
        pygame.draw.rect(screen, (90, 90, 90), rect, 1, border_radius=8)
        lbl = fonts.ov_btn.render(label, True, (230, 230, 230))
        screen.blit(lbl, lbl.get_rect(center=rect.center))

    return cont_btn, new_btn


def draw_info_modal(screen, win_w, win_h, title_text, message, fonts):
    """Draw a generic informational modal with a custom title. Returns the
    OK button rect.

    Distinct from draw_error_modal (which hardcodes a "Could not load
    save" title and red/error styling) — this is for non-error notices
    like "Stockfish was not found", using neutral styling so it doesn't
    read as something having gone catastrophically wrong.
    """
    ov = pygame.Surface((win_w, win_h), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 185))
    screen.blit(ov, (0, 0))

    box_w, box_h = 420, 200
    box = pygame.Rect((win_w - box_w) // 2, (win_h - box_h) // 2, box_w, box_h)
    pygame.draw.rect(screen, (30, 30, 30), box, border_radius=12)
    pygame.draw.rect(screen, (66, 66, 66), box, 1, border_radius=12)

    title = fonts.ov_title.render(title_text, True, (220, 220, 220))
    screen.blit(title, title.get_rect(center=(box.centerx, box.y + 34)))

    words = message.split(' ')
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if fonts.ov_sub.size(trial)[0] > box_w - 40:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines[:3]):
        ls = fonts.ov_sub.render(line, True, (180, 180, 180))
        screen.blit(ls, ls.get_rect(center=(box.centerx, box.y + 70 + i * 18)))

    mx, my = pygame.mouse.get_pos()
    ok_btn = pygame.Rect(box.centerx - 70, box.bottom - 56, 140, 38)
    hov = ok_btn.collidepoint(mx, my)
    pygame.draw.rect(screen, (55, 55, 55) if hov else (42, 42, 42), ok_btn, border_radius=8)
    pygame.draw.rect(screen, (90, 90, 90), ok_btn, 1, border_radius=8)
    lbl = fonts.ov_btn.render('OK', True, (220, 220, 220))
    screen.blit(lbl, lbl.get_rect(center=ok_btn.center))
    return ok_btn


def draw_error_modal(screen, win_w, win_h, message, fonts):
    """Draw a generic user-facing error modal. Returns the OK button rect."""
    ov = pygame.Surface((win_w, win_h), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 185))
    screen.blit(ov, (0, 0))

    box_w, box_h = 420, 200
    box = pygame.Rect((win_w - box_w) // 2, (win_h - box_h) // 2, box_w, box_h)
    pygame.draw.rect(screen, (40, 28, 28), box, border_radius=12)
    pygame.draw.rect(screen, (140, 70, 70), box, 1, border_radius=12)

    title = fonts.ov_title.render('Could not load save', True, (235, 200, 200))
    screen.blit(title, title.get_rect(center=(box.centerx, box.y + 34)))

    words = message.split(' ')
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if fonts.ov_sub.size(trial)[0] > box_w - 40:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines[:3]):
        ls = fonts.ov_sub.render(line, True, (200, 180, 180))
        screen.blit(ls, ls.get_rect(center=(box.centerx, box.y + 70 + i * 18)))

    mx, my = pygame.mouse.get_pos()
    ok_btn = pygame.Rect(box.centerx - 70, box.bottom - 56, 140, 38)
    hov = ok_btn.collidepoint(mx, my)
    pygame.draw.rect(screen, (70, 45, 45) if hov else (55, 38, 38), ok_btn, border_radius=8)
    pygame.draw.rect(screen, (140, 70, 70), ok_btn, 1, border_radius=8)
    lbl = fonts.ov_btn.render('OK', True, (230, 210, 210))
    screen.blit(lbl, lbl.get_rect(center=ok_btn.center))
    return ok_btn
