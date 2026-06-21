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
    MENU_ACCENT_BRIGHT,
    MENU_BG,
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
        Button((cx - bw // 2, y0, bw, bh), 'Local Play', 'Play on this device'),
        Button((cx - bw // 2, y0 + bh + gap, bw, bh), 'Online Play', 'Coming soon', disabled=True),
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


def draw_opponent_picker(screen, fonts, king_imgs):
    """The 'Select Opponent' screen shown after clicking Local Play.

    Deliberately styled to look distinct from the color picker (which uses
    two side-by-side square cards with king portraits). This screen uses a
    vertical stack of wide horizontal cards, each with a circular icon
    badge on the left, a bold title, and a descriptive subtitle —
    closer in spirit to a settings/list screen than a chooser.

    Returns (rects_by_key, back_rect) where rects_by_key is
    {'player': rect, 'bot': rect}.
    """
    screen.fill(MENU_BG)
    cx = WIN_W // 2

    # Distinct header style: a small kicker label above a larger title,
    # rather than the color picker's single centred heading.
    kicker = fonts.pick_s.render('LOCAL PLAY', True, MENU_ACCENT)
    screen.blit(kicker, kicker.get_rect(center=(cx, 90)))
    title = fonts.pick.render('Choose your opponent', True, MENU_TEXT)
    screen.blit(title, title.get_rect(center=(cx, 122)))

    mx, my = pygame.mouse.get_pos()
    # Wide horizontal cards stacked vertically — visually nothing like the
    # color picker's two side-by-side squares.
    card_w, card_h = 520, 120
    card_x = cx - card_w // 2
    gap = 22
    total_h = card_h * 2 + gap
    y0 = WIN_H // 2 - total_h // 2 + 30

    # Each card: (key, icon_img, icon_bg, title, subtitle, accent_color)
    # Subtitles kept short to fit comfortably within the card width.
    cards = [
        ('player', king_imgs['white'], (60, 90, 60), 'Player',
         'Two people, one screen. Pass the keyboard between moves.',
         (120, 180, 100)),
        ('bot', king_imgs['black'], (90, 60, 90), 'Bot',
         'Challenge the computer. Pick a side and difficulty.',
         (180, 120, 200)),
    ]

    # Pre-scale the king portraits down to fit inside the circular badge.
    badge_r = 38
    badge_inner = 60
    scaled_icons = {
        'player': pygame.transform.smoothscale(king_imgs['white'], (badge_inner, badge_inner)),
        'bot': pygame.transform.smoothscale(king_imgs['black'], (badge_inner, badge_inner)),
    }

    rects = {}
    for i, (key, _icon, icon_bg, label, sublabel, accent) in enumerate(cards):
        rect = pygame.Rect(card_x, y0 + i * (card_h + gap), card_w, card_h)
        hov = rect.collidepoint(mx, my)

        # Card background: subtle two-tone fill on hover for a lift effect.
        bg = (42, 42, 48) if hov else (30, 30, 34)
        pygame.draw.rect(screen, bg, rect, border_radius=14)
        # Border (accent on hover, neutral otherwise).
        border_col = accent if hov else (62, 62, 68)
        pygame.draw.rect(screen, border_col, rect, 2 if hov else 1, border_radius=14)

        # Circular icon badge on the left, holding the (scaled) king portrait.
        badge_cx = rect.x + 64
        badge_cy = rect.centery
        pygame.draw.circle(screen, icon_bg, (badge_cx, badge_cy), badge_r)
        pygame.draw.circle(screen, accent, (badge_cx, badge_cy), badge_r, 2)
        screen.blit(scaled_icons[key], scaled_icons[key].get_rect(center=(badge_cx, badge_cy)))

        # Title + subtitle to the right of the badge.
        text_x = badge_cx + badge_r + 22
        lbl = fonts.btn.render(label, True, MENU_TEXT)
        screen.blit(lbl, (text_x, rect.y + 32))
        sub = fonts.btn_sub.render(sublabel, True, MENU_TEXT_SUB)
        screen.blit(sub, (text_x, rect.y + 64))

        # Right-side chevron hint that the card is clickable.
        chevron = '\u203a'  # ›
        ch = fonts.pick.render(chevron, True, accent if hov else (90, 90, 90))
        screen.blit(ch, ch.get_rect(midright=(rect.right - 22, rect.centery)))

        rects[key] = rect

    # Footer hint.
    hint = fonts.pick_s.render('Press Esc to go back', True, (90, 90, 90))
    screen.blit(hint, hint.get_rect(center=(cx, WIN_H - 28)))

    back_s = fonts.pick_s.render('\u2190 Back', True, MENU_TEXT_SUB)
    screen.blit(back_s, (18, 18))
    return rects, pygame.Rect(0, 0, 80, 36)


def draw_color_picker(screen, fonts, king_imgs):
    """Returns (rects_by_color, back_rect).

    In the refactored flow this screen is reached from the OPPONENT_PICK
    screen (after choosing Bot), so the Back button returns there rather
    than to the main menu.
    """
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
    """Returns (back_rect, board_rects, arrow_rects, motion_rect).

    Redesigned with a clean card-based layout: each preference group sits
    in its own rounded card with a heading, a one-line description, and a
    row of large swatches. The reduced-motion toggle is a proper pill
    switch rather than a checkbox.
    """
    screen.fill(MENU_BG)
    cx = WIN_W // 2

    # ── Header ─────────────────────────────────────────────────────────
    title_s = fonts.pick.render('Preferences', True, MENU_TEXT)
    screen.blit(title_s, title_s.get_rect(center=(cx, 56)))
    sub_s = fonts.pick_s.render('Customise the look and feel of your board', True, MENU_TEXT_SUB)
    screen.blit(sub_s, sub_s.get_rect(center=(cx, 86)))

    mx, my = pygame.mouse.get_pos()

    # ── Helper: draw a section card (rounded panel with a heading) ─────
    def _section_card(y, h, heading, description):
        rect = pygame.Rect(cx - 280, y, 560, h)
        pygame.draw.rect(screen, (26, 26, 30), rect, border_radius=12)
        pygame.draw.rect(screen, (52, 52, 58), rect, 1, border_radius=12)
        h_s = fonts.diff_l.render(heading, True, MENU_TEXT)
        screen.blit(h_s, (rect.x + 20, rect.y + 14))
        d_s = fonts.btn_sub.render(description, True, MENU_TEXT_SUB)
        screen.blit(d_s, (rect.x + 20, rect.y + 36))
        return rect

    # ── Board Theme card ───────────────────────────────────────────────
    board_card = _section_card(120, 155, 'Board Theme', 'Choose the colour scheme for the squares.')
    board_rects = {}
    swatch_w, swatch_h = 110, 56
    swatch_gap = 12
    total_sw = swatch_w * len(_BOARD_THEME_CHOICES) + swatch_gap * (len(_BOARD_THEME_CHOICES) - 1)
    sw_x0 = board_card.centerx - total_sw // 2
    for i, theme_name in enumerate(_BOARD_THEME_CHOICES):
        theme = BOARD_THEMES[theme_name]
        if theme_name == 'colorblind_safe':
            label = 'Colourblind'
        else:
            parts = theme_name.split('_')
            label = parts[0].capitalize() + ' & ' + parts[1].capitalize()

        rect = pygame.Rect(sw_x0 + i * (swatch_w + swatch_gap), board_card.y + 60, swatch_w, swatch_h)
        hov = rect.collidepoint(mx, my)
        selected = (current_board_theme == theme_name)

        # Preview: two side-by-side squares showing the light/dark colours.
        half_w = (swatch_w - 4) // 2
        pygame.draw.rect(screen, theme['light'], (rect.x + 2, rect.y + 2, half_w, swatch_h - 4), border_top_left_radius=8, border_bottom_left_radius=8)
        pygame.draw.rect(screen, theme['dark'], (rect.x + 2 + half_w, rect.y + 2, swatch_w - 4 - half_w, swatch_h - 4), border_top_right_radius=8, border_bottom_right_radius=8)

        border_col = MENU_ACCENT_BRIGHT if selected else ((90, 90, 96) if hov else (60, 60, 66))
        border_width = 3 if selected else 2
        pygame.draw.rect(screen, border_col, rect, border_width, border_radius=10)

        lbl_col = MENU_TEXT if selected else MENU_TEXT_SUB
        lbl = fonts.btn_sub.render(label, True, lbl_col)
        screen.blit(lbl, lbl.get_rect(center=(rect.centerx, rect.bottom + 12)))

        board_rects[theme_name] = rect

    # ── Arrow Theme card ───────────────────────────────────────────────
    arrow_card = _section_card(295, 155, 'Arrow Theme', 'Colour used for right-click annotation arrows.')
    arrow_rects = {}
    n_arrows = len(_ARROW_THEME_CHOICES)
    a_w, a_h = 90, 56
    a_gap = 14
    total_aw = a_w * n_arrows + a_gap * (n_arrows - 1)
    aw_x0 = arrow_card.centerx - total_aw // 2
    for i, theme_name in enumerate(_ARROW_THEME_CHOICES):
        color = ARROW_THEMES[theme_name]
        display_color = color[:3]
        label = theme_name.capitalize()

        rect = pygame.Rect(aw_x0 + i * (a_w + a_gap), arrow_card.y + 60, a_w, a_h)
        hov = rect.collidepoint(mx, my)
        selected = (current_arrow_theme == theme_name)

        # Preview: a centred filled circle in the arrow colour.
        pygame.draw.circle(screen, display_color, (rect.centerx, rect.centery - 4), 20)
        pygame.draw.circle(screen, (30, 30, 30), (rect.centerx, rect.centery - 4), 20, 1)

        border_col = MENU_ACCENT_BRIGHT if selected else ((90, 90, 96) if hov else (60, 60, 66))
        border_width = 3 if selected else 2
        pygame.draw.rect(screen, border_col, rect, border_width, border_radius=10)

        lbl_col = MENU_TEXT if selected else MENU_TEXT_SUB
        lbl = fonts.btn_sub.render(label, True, lbl_col)
        screen.blit(lbl, lbl.get_rect(center=(rect.centerx, rect.bottom + 12)))

        arrow_rects[theme_name] = rect

    # ── Reduced Motion card ────────────────────────────────────────────
    motion_card = _section_card(470, 110, 'Reduced Motion', 'Skip piece-slide and board-flip animations.')
    # Pill-style toggle switch on the right side of the card.
    pill_w, pill_h = 64, 30
    motion_rect = pygame.Rect(motion_card.right - pill_w - 24, motion_card.y + 50, pill_w, pill_h)
    hov = motion_rect.collidepoint(mx, my)
    # Track background: bright accent when on, neutral when off.
    track_col = MENU_ACCENT_BRIGHT if reduced_motion else ((70, 70, 76) if hov else (50, 50, 56))
    pygame.draw.rect(screen, track_col, motion_rect, border_radius=pill_h // 2)
    # Knob: slides right when on, left when off.
    knob_r = pill_h // 2 - 4
    knob_x = motion_rect.right - knob_r - 4 if reduced_motion else motion_rect.x + knob_r + 4
    pygame.draw.circle(screen, (235, 235, 235), (knob_x, motion_rect.centery), knob_r)
    # Status label to the left of the pill.
    status = 'On' if reduced_motion else 'Off'
    status_col = MENU_TEXT if reduced_motion else MENU_TEXT_SUB
    status_s = fonts.btn.render(status, True, status_col)
    screen.blit(status_s, status_s.get_rect(midright=(motion_rect.x - 12, motion_rect.centery)))

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
