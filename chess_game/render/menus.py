"""Main menu, color picker, difficulty slider, and preferences screens.

Ported from main.py with module-level rect globals converted to return
values, and self-contained Button widgets replaced with chess_game.widgets.
"""
from __future__ import annotations

import pygame

from chess_game.engine.bot import DIFFICULTY_CONFIG
from chess_game.theme import (
    ARROW_THEMES,
    BOARD_THEMES,
    DIFF_DESC,
    DIFF_TIER,
    MENU_ACCENT,
    MENU_BG,
    MENU_BTN_HOV,
    MENU_BTN_NORM,
    MENU_TEXT,
    MENU_TEXT_SUB,
    PICK_DARK,
    PICK_HOVER,
    PICK_LIGHT,
    WIN_H,
    WIN_W,
    difficulty_color,
)


def make_menu_buttons():
    from chess_game.widgets import Button
    cx, bw, bh, gap = WIN_W // 2, 280, 68, 18
    y0 = WIN_H // 2 + 30
    return [
        Button((cx - bw // 2, y0, bw, bh), 'Play vs Friend', 'Local 2-player'),
        Button((cx - bw // 2, y0 + bh + gap, bw, bh), 'Play vs Bot', 'AI opponent'),
        Button((cx - bw // 2, y0 + 2 * (bh + gap), bw, bh), 'Preferences', 'Board & Arrow themes'),
    ]


def draw_menu(screen, menu_buttons, fonts):
    screen.fill(MENU_BG)
    tile = 36
    for col in range(WIN_W // tile + 1):
        c = (32, 32, 32) if col % 2 == 0 else (26, 26, 26)
        pygame.draw.rect(screen, c, (col * tile, 0, tile, tile * 2))
    pygame.draw.line(screen, (40, 40, 40), (0, tile * 2), (WIN_W, tile * 2), 1)
    cx = WIN_W // 2
    title = fonts.title.render('Python Chess', True, MENU_ACCENT)
    screen.blit(title, title.get_rect(center=(cx, WIN_H // 2 - 70)))
    tw = title.get_width()
    pygame.draw.line(screen, MENU_ACCENT,
                      (cx - tw // 2, WIN_H // 2 - 40), (cx + tw // 2, WIN_H // 2 - 40), 2)
    for btn in menu_buttons:
        btn.draw(screen, fonts)
    foot = fonts.subtitle.render('Built with Python & pygame', True, (55, 55, 55))
    screen.blit(foot, foot.get_rect(center=(cx, WIN_H - 22)))


def draw_color_picker(screen, fonts, king_imgs):
    """Returns (rects_by_color, back_rect)."""
    screen.fill(MENU_BG)
    cx = WIN_W // 2
    s = fonts.pick.render('Choose your colour', True, MENU_TEXT)
    screen.blit(s, s.get_rect(center=(cx, 120)))
    s = fonts.pick_s.render('Click the side you want to play', True, MENU_TEXT_SUB)
    screen.blit(s, s.get_rect(center=(cx, 158)))

    mx, my = pygame.mouse.get_pos()
    bw, bh = 200, 220
    x0 = cx - (bw * 2 + 40) // 2
    rects = {}
    for color, label, bg, fg, bx in (
        ('white', 'White', PICK_LIGHT, (50, 50, 50), x0),
        ('black', 'Black', PICK_DARK, (200, 200, 200), x0 + bw + 40),
    ):
        by_ = WIN_H // 2 - bh // 2
        rect = pygame.Rect(bx, by_, bw, bh)
        hov = rect.collidepoint(mx, my)
        pygame.draw.rect(screen, bg, rect, border_radius=12)
        pygame.draw.rect(screen, PICK_HOVER if hov else (90, 90, 90), rect, 3, border_radius=12)
        img = king_imgs[color]
        screen.blit(img, img.get_rect(center=(bx + bw // 2, by_ + bh // 2 - 15)))
        lbl = fonts.btn.render(label, True, fg)
        screen.blit(lbl, lbl.get_rect(center=(bx + bw // 2, by_ + bh - 28)))
        rects[color] = rect
    s = fonts.pick_s.render('\u2190 Back', True, MENU_TEXT_SUB)
    screen.blit(s, (18, 18))
    return rects, pygame.Rect(0, 0, 80, 36)


def _draw_slider_track(screen, value, vmin, vmax, sl_x, sl_w, sl_y, color, fonts):
    t = (value - vmin) / (vmax - vmin)
    pygame.draw.rect(screen, (48, 48, 48), (sl_x, sl_y - 4, sl_w, 8), border_radius=4)
    fill_w = max(8, int(sl_w * t))
    pygame.draw.rect(screen, color, (sl_x, sl_y - 4, fill_w, 8), border_radius=4)
    steps = vmax - vmin
    for i in range(steps + 1):
        tx = sl_x + int(sl_w * i / steps)
        pygame.draw.line(screen, (70, 70, 70), (tx, sl_y - 8), (tx, sl_y + 8), 1)
        if i in (0, steps // 2, steps):
            t_s = fonts.count.render(str(vmin + i), True, (100, 100, 100))
            screen.blit(t_s, t_s.get_rect(center=(tx, sl_y + 20)))
    hx = sl_x + int(sl_w * t)
    pygame.draw.circle(screen, (30, 30, 30), (hx, sl_y), 12)
    pygame.draw.circle(screen, color, (hx, sl_y), 12, 3)


def draw_difficulty(screen, level, fonts):
    """Single-slider difficulty selector.

    Returns (back_rect, confirm_rect, slider_rect, slider_info) where
    slider_info = (sl_x, sl_w, sl_y) for pixel-to-value conversion.
    """
    screen.fill(MENU_BG)
    cx = WIN_W // 2
    sl_x = cx - 190
    sl_w = 380

    col = difficulty_color(level)
    tier = DIFF_TIER[level]
    desc = DIFF_DESC[level]
    cfg = DIFFICULTY_CONFIG[level]
    depth = cfg['depth']
    blunder = int(cfg['blunder_prob'] * 100)

    title_s = fonts.pick.render('Bot Difficulty', True, MENU_TEXT)
    screen.blit(title_s, title_s.get_rect(center=(cx, 72)))

    num_s = fonts.win.render(str(level), True, col)
    screen.blit(num_s, num_s.get_rect(center=(cx, 148)))

    tier_s = fonts.diff_l.render(tier.upper(), True, col)
    screen.blit(tier_s, tier_s.get_rect(center=(cx, 190)))

    if blunder == 0:
        info_txt = 'Searches ' + str(depth) + ' moves ahead  \u00b7  Perfect play (0% blunder)'
    else:
        plural = 's' if depth != 1 else ''
        info_txt = 'Searches ' + str(depth) + ' move' + plural + ' ahead  \u00b7  ' + str(blunder) + '% blunder chance'
    info_s = fonts.diff_s.render(info_txt, True, MENU_TEXT_SUB)
    screen.blit(info_s, info_s.get_rect(center=(cx, 214)))

    pygame.draw.line(screen, (44, 44, 44), (sl_x, 238), (sl_x + sl_w, 238), 1)

    sl_y = 272
    _draw_slider_track(screen, level, 1, 10, sl_x, sl_w, sl_y, col, fonts)
    slider_rect = pygame.Rect(sl_x - 14, sl_y - 18, sl_w + 28, 36)

    tier_lbl = fonts.diff_l.render(tier, True, col)
    screen.blit(tier_lbl, tier_lbl.get_rect(center=(cx, 316)))

    desc_s = fonts.diff_s.render(desc, True, (155, 155, 155))
    screen.blit(desc_s, desc_s.get_rect(center=(cx, 336)))

    pygame.draw.line(screen, (44, 44, 44), (sl_x, 360), (sl_x + sl_w, 360), 1)

    bw, bh = 200, 48
    btn = pygame.Rect(cx - bw // 2, 384, bw, bh)
    mx_, my_ = pygame.mouse.get_pos()
    hov = btn.collidepoint(mx_, my_)
    bg_col = tuple(min(255, int(c * (0.38 if hov else 0.22))) for c in col)
    pygame.draw.rect(screen, bg_col, btn, border_radius=10)
    brd_col = col if hov else tuple(int(c * 0.55) for c in col)
    pygame.draw.rect(screen, brd_col, btn, 2 if hov else 1, border_radius=10)
    btn_lbl = fonts.btn.render('Start Game', True, MENU_TEXT)
    screen.blit(btn_lbl, btn_lbl.get_rect(center=btn.center))

    back_s = fonts.pick_s.render('\u2190 Back', True, MENU_TEXT_SUB)
    screen.blit(back_s, (18, 18))

    return (
        pygame.Rect(0, 0, 80, 36),
        btn,
        slider_rect,
        (sl_x, sl_w, sl_y),
    )


# colorblind_safe added as a selectable board theme option.
_BOARD_THEME_CHOICES = ['white_green', 'white_blue', 'white_red', 'colorblind_safe']
_ARROW_THEME_CHOICES = ['blue', 'yellow', 'green', 'white', 'black']


def draw_preferences(screen, current_board_theme, current_arrow_theme, reduced_motion, fonts):
    """Returns (back_rect, board_rects, arrow_rects, motion_rect)."""
    screen.fill(MENU_BG)
    cx = WIN_W // 2

    title_s = fonts.pick.render('Preferences', True, MENU_TEXT)
    screen.blit(title_s, title_s.get_rect(center=(cx, 50)))

    board_label = fonts.diff_l.render('Board Theme', True, MENU_TEXT)
    screen.blit(board_label, (cx - 120, 110))

    board_rects = {}
    board_y = 150
    for i, theme_name in enumerate(_BOARD_THEME_CHOICES):
        theme = BOARD_THEMES[theme_name]
        if theme_name == 'colorblind_safe':
            label = 'Colourblind safe'
        else:
            parts = theme_name.split('_')
            label = parts[0].capitalize() + ' & ' + parts[1].capitalize()

        rect_x = cx - 120 + i * 100
        rect = pygame.Rect(rect_x, board_y, 80, 60)

        mx_, my_ = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx_, my_)
        selected = (current_board_theme == theme_name)

        pygame.draw.rect(screen, theme['light'], (rect.x + 2, rect.y + 2, 35, 35))
        pygame.draw.rect(screen, theme['dark'], (rect.x + 37, rect.y + 2, 35, 35))

        border_col = MENU_ACCENT if selected else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
        border_width = 3 if selected else 2
        pygame.draw.rect(screen, border_col, rect, border_width, border_radius=8)

        lbl = fonts.btn_sub.render(label, True, MENU_TEXT if selected else MENU_TEXT_SUB)
        screen.blit(lbl, lbl.get_rect(center=(rect.centerx, rect.bottom + 12)))

        board_rects[theme_name] = rect

    arrow_label = fonts.diff_l.render('Arrow Theme', True, MENU_TEXT)
    screen.blit(arrow_label, (cx - 120, 270))

    arrow_rects = {}
    arrow_y = 310
    for i, theme_name in enumerate(_ARROW_THEME_CHOICES):
        color = ARROW_THEMES[theme_name]
        display_color = color[:3]
        label = theme_name.capitalize()

        rect_x = cx - 120 + i * 100
        rect = pygame.Rect(rect_x, arrow_y, 80, 60)

        mx_, my_ = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx_, my_)
        selected = (current_arrow_theme == theme_name)

        pygame.draw.circle(screen, display_color, (rect.centerx, rect.centery - 10), 20)
        pygame.draw.circle(screen, (80, 80, 80), (rect.centerx, rect.centery - 10), 20, 2)

        border_col = MENU_ACCENT if selected else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
        border_width = 3 if selected else 2
        pygame.draw.rect(screen, border_col, rect, border_width, border_radius=8)

        lbl = fonts.btn_sub.render(label, True, MENU_TEXT if selected else MENU_TEXT_SUB)
        screen.blit(lbl, lbl.get_rect(center=(rect.centerx, rect.bottom - 12)))

        arrow_rects[theme_name] = rect

    motion_label = fonts.diff_l.render('Reduced Motion', True, MENU_TEXT)
    screen.blit(motion_label, (cx - 120, 400))

    motion_rect = pygame.Rect(cx - 120, 432, 240, 40)
    mx_, my_ = pygame.mouse.get_pos()
    hov = motion_rect.collidepoint(mx_, my_)
    border_col = MENU_ACCENT if reduced_motion else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
    pygame.draw.rect(screen, border_col, motion_rect, 2, border_radius=8)

    box_rect = pygame.Rect(motion_rect.x + 10, motion_rect.y + 10, 20, 20)
    pygame.draw.rect(screen, MENU_ACCENT if reduced_motion else MENU_BTN_NORM, box_rect, border_radius=4)
    if reduced_motion:
        pygame.draw.line(screen, MENU_TEXT, (box_rect.x + 4, box_rect.centery),
                          (box_rect.centerx - 1, box_rect.bottom - 5), 2)
        pygame.draw.line(screen, MENU_TEXT, (box_rect.centerx - 1, box_rect.bottom - 5),
                          (box_rect.right - 3, box_rect.y + 4), 2)
    motion_status = 'On — skip animations' if reduced_motion else 'Off — normal animations'
    motion_s = fonts.btn_sub.render(motion_status, True, MENU_TEXT)
    screen.blit(motion_s, (box_rect.right + 12, motion_rect.y + 11))

    back_s = fonts.pick_s.render('\u2190 Back', True, MENU_TEXT_SUB)
    screen.blit(back_s, (18, 18))

    return pygame.Rect(0, 0, 80, 36), board_rects, arrow_rects, motion_rect


def draw_main_menu_overlay(screen, fonts, panel_x):
    """In-game 'main menu' confirm overlay. Returns (save_btn, quit_btn)."""
    ov = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 200))
    screen.blit(ov, (0, 0))

    cx = panel_x // 2
    cy = WIN_H // 2
    bw, bh = 310, 210
    box = pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh)
    pygame.draw.rect(screen, (30, 30, 30), box, border_radius=14)
    pygame.draw.rect(screen, (66, 66, 66), box, 2, border_radius=14)

    t_s = fonts.ov_title.render('Main Menu', True, MENU_TEXT)
    screen.blit(t_s, t_s.get_rect(center=(cx, cy - 66)))
    s_s = fonts.ov_sub.render('What would you like to do?', True, MENU_TEXT_SUB)
    screen.blit(s_s, s_s.get_rect(center=(cx, cy - 40)))

    mx_, my_ = pygame.mouse.get_pos()
    bw2 = 210
    save_btn = pygame.Rect(cx - bw2 // 2, cy - 12, bw2, 42)
    quit_btn = pygame.Rect(cx - bw2 // 2, cy + 40, bw2, 42)
    for btn, label, font, accent in (
        (save_btn, 'Save & Quit', fonts.ov_btn, (65, 115, 65)),
        (quit_btn, 'Quit Without Saving', fonts.ov_btn_sm, (130, 65, 55)),
    ):
        hov = btn.collidepoint(mx_, my_)
        bg = tuple(min(255, int(c * (0.48 if hov else 0.28))) for c in accent)
        pygame.draw.rect(screen, bg, btn, border_radius=8)
        brd = accent if hov else tuple(int(c * 0.58) for c in accent)
        pygame.draw.rect(screen, brd, btn, 1, border_radius=8)
        l_s = font.render(label, True, MENU_TEXT)
        screen.blit(l_s, l_s.get_rect(center=btn.center))

    return save_btn, quit_btn
