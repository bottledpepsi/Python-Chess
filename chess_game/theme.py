"""Colours, fonts, and board/arrow theme definitions.

Font objects require ``pygame.font`` to be initialised, so :func:`load_fonts`
must be called only after ``pygame.init()`` — never at import time.
"""
from __future__ import annotations

from dataclasses import dataclass

import pygame

# ── Layout ──────────────────────────────────────────────────────────────────
BOARD_PX = 600
assert BOARD_PX % 8 == 0, "BOARD_PX must be divisible by 8"
TILE = BOARD_PX // 8  # 75
RANK_LABEL_W = 28
FILE_LABEL_H = 26
TRAY_H = 70
BOARD_X = RANK_LABEL_W
BOARD_Y = TRAY_H
PANEL_W = 220
BOARD_PANEL_GAP = 4
WIN_W = RANK_LABEL_W + BOARD_PX + BOARD_PANEL_GAP + PANEL_W  # 852
WIN_H = TRAY_H + BOARD_PX + FILE_LABEL_H + TRAY_H
PANEL_X = RANK_LABEL_W + BOARD_PX + BOARD_PANEL_GAP  # 632
ANIM_MS = 120

# History panel sub-dimensions
HIST_HDR_H = 30
HIST_FOOT_H = 44
HIST_ROW_H = 26
HIST_NUM_W = 26
HIST_PAD = 5
HIST_MOV_W = (PANEL_W - HIST_NUM_W - HIST_PAD * 2) // 2  # 92

PIECE_SIZE = int(TILE * 0.88)

# ── Colours ─────────────────────────────────────────────────────────────────
# Contrast failures raised to >=4.5:1 (WCAG AA for normal text).
BG = (22, 22, 22)
TRAY_BG = (52, 52, 52)
SHADOW = (10, 10, 10)
LABEL_COL = (167, 167, 167)          # was (120,120,120) ~3.9:1 on BG -> ~5.6:1
MENU_BG = (18, 18, 18)
MENU_ACCENT = (118, 150, 86)
# Brighter version of MENU_ACCENT for selected-state outlines on preferences
# swatches — the muted accent didn't pop enough against the dark background.
MENU_ACCENT_BRIGHT = (170, 220, 120)
MENU_BTN_NORM = (38, 38, 38)
MENU_BTN_HOV = (55, 55, 55)
MENU_BTN_DIS = (30, 30, 30)
MENU_BTN_BRD = (70, 70, 70)
MENU_TEXT = (220, 220, 220)
MENU_TEXT_SUB = (150, 150, 150)      # was (110,110,110) ~3.5:1 on MENU_BG -> ~4.7:1
MENU_TEXT_DIS = (118, 118, 118)      # was (70,70,70) ~1.6:1 on (30,30,30) -> ~4.5:1
PICK_LIGHT = (238, 238, 210)
PICK_DARK = (118, 150, 86)
PICK_HOVER = (255, 215, 0)

BOARD_THEMES = {
    'white_green': {'light': (238, 238, 210), 'dark': (118, 150, 86)},
    'white_blue': {'light': (238, 238, 210), 'dark': (86, 118, 150)},
    'white_red': {'light': (238, 238, 210), 'dark': (150, 86, 86)},
    # Colour-blind-safe default. Green/red is the worst pair for
    # deuteranopia; blue/orange remains distinguishable across common CVD types.
    'colorblind_safe': {'light': (240, 240, 235), 'dark': (90, 130, 180)},
}

ARROW_THEMES = {
    'blue': (0, 180, 255, 180),
    'yellow': (255, 200, 50, 180),
    'green': (100, 220, 80, 180),
    'white': (255, 255, 255, 180),
    'black': (40, 40, 40, 180),
}

SQ_SEL_L = (246, 246, 105)
SQ_SEL_D = (186, 202, 43)
SQ_LAST_L = (206, 210, 107)
SQ_LAST_D = (170, 162, 58)
SQ_CHK_L = (220, 80, 80)
SQ_CHK_D = (168, 40, 40)
PROMO_BG_C = (42, 42, 42)
PROMO_HOV = (72, 72, 72)
PROMO_NORM = (55, 55, 55)
PROMO_BRD = (90, 90, 90)

# Panel colours
PANEL_BG = (26, 26, 26)
PANEL_HDR_BG = (33, 33, 33)
PANEL_BDR = (46, 46, 46)
HIST_ROW_HOV = (40, 40, 40)
HIST_SEL_BG = (46, 68, 42)
HIST_SEL_FG = (140, 200, 100)
HIST_NUM_COL = (138, 138, 138)       # was (70,70,70) ~1.9:1 on PANEL_BG -> ~4.5:1
HIST_MOV_COL = (190, 190, 190)
LIVE_BG_ACT = (32, 86, 32)
LIVE_BG_HOV = (42, 108, 42)
LIVE_BG_OFF = (33, 33, 33)

ARROW_WIDTH = 10
ARROW_HEAD_SIZE = 18

_DIFFICULTY_COLORS = [
    (90, 200, 90), (120, 200, 70), (155, 195, 50),
    (185, 180, 40), (210, 155, 40), (220, 120, 40),
    (220, 90, 50), (210, 60, 60), (200, 40, 40),
    (180, 20, 20),
]


def difficulty_color(level: int) -> tuple[int, int, int]:
    """Return the accent colour for a 1-10 difficulty level."""
    return _DIFFICULTY_COLORS[max(0, min(9, level - 1))]


def elo_color(elo: int, vmin: int, vmax: int) -> tuple[int, int, int]:
    """Return an accent colour for a Stockfish ELO value, interpolated
    across the same green->red ramp as difficulty_color but continuously
    (not in 10 discrete steps) since ELO spans a much wider, finer-grained
    range than the native engine's 1-10 levels."""
    span = max(1, vmax - vmin)
    t = max(0.0, min(1.0, (elo - vmin) / span))
    idx_f = t * (len(_DIFFICULTY_COLORS) - 1)
    lo = int(idx_f)
    hi = min(len(_DIFFICULTY_COLORS) - 1, lo + 1)
    frac = idx_f - lo
    c_lo, c_hi = _DIFFICULTY_COLORS[lo], _DIFFICULTY_COLORS[hi]
    r = int(c_lo[0] + (c_hi[0] - c_lo[0]) * frac)
    g = int(c_lo[1] + (c_hi[1] - c_lo[1]) * frac)
    b = int(c_lo[2] + (c_hi[2] - c_lo[2]) * frac)
    return (r, g, b)


DIFF_TIER = {
    1: 'Novice', 2: 'Novice',
    3: 'Casual', 4: 'Casual',
    5: 'Intermediate', 6: 'Intermediate',
    7: 'Advanced', 8: 'Advanced',
    9: 'Master',
    10: 'Grandmaster',
}

DIFF_DESC = {
    1: 'Beginner friendly, frequent tactical mistakes',
    2: 'Beginner friendly, frequent tactical mistakes',
    3: 'Plays briskly, classic kitchen-table difficulty',
    4: 'Plays briskly, classic kitchen-table difficulty',
    5: 'Club player standard, capitalizes on obvious blunders',
    6: 'Club player standard, capitalizes on obvious blunders',
    7: 'Tournament regular, sharp short-term tactics',
    8: 'Tournament regular, sharp short-term tactics',
    9: 'Extremely deep strategic vision, very rare slips',
    10: 'Engine max strength. Perfect calculation.',
}


@dataclass
class Fonts:
    """Bundle of all pygame Font objects used by the renderer."""
    label: pygame.font.Font
    promo: pygame.font.Font
    win: pygame.font.Font
    win_s: pygame.font.Font
    title: pygame.font.Font
    subtitle: pygame.font.Font
    btn: pygame.font.Font
    btn_sub: pygame.font.Font
    think: pygame.font.Font
    count: pygame.font.Font
    lead: pygame.font.Font
    pick: pygame.font.Font
    pick_s: pygame.font.Font
    diff_n: pygame.font.Font
    diff_l: pygame.font.Font
    diff_s: pygame.font.Font
    hist_hdr: pygame.font.Font
    hist_num: pygame.font.Font
    hist_mov: pygame.font.Font
    live_btn: pygame.font.Font
    ov_title: pygame.font.Font
    ov_sub: pygame.font.Font
    ov_btn: pygame.font.Font
    ov_btn_sm: pygame.font.Font
    igmenu: pygame.font.Font


_fonts: Fonts | None = None


def load_fonts() -> Fonts:
    """Create (or return the cached) Fonts bundle. Must run after pygame.init()."""
    global _fonts
    if _fonts is not None:
        return _fonts
    sf = pygame.font.SysFont
    _fonts = Fonts(
        label=sf('Arial', 13, bold=True),
        promo=sf('Arial', 16, bold=True),
        win=sf('Arial', 52, bold=True),
        win_s=sf('Arial', 22),
        title=sf('Georgia', 64, bold=True),
        subtitle=sf('Arial', 16),
        btn=sf('Arial', 22, bold=True),
        btn_sub=sf('Arial', 13),
        think=sf('Arial', 14),
        count=sf('Arial', 11, bold=True),
        lead=sf('Arial', 13, bold=True),
        pick=sf('Arial', 28, bold=True),
        pick_s=sf('Arial', 14),
        diff_n=sf('Arial', 26, bold=True),
        diff_l=sf('Arial', 14, bold=True),
        diff_s=sf('Arial', 12),
        hist_hdr=sf('Arial', 10, bold=True),
        hist_num=sf('Arial', 11),
        hist_mov=sf('Arial', 13, bold=True),
        live_btn=sf('Arial', 13, bold=True),
        ov_title=sf('Arial', 20, bold=True),
        ov_sub=sf('Arial', 13),
        ov_btn=sf('Arial', 16, bold=True),
        ov_btn_sm=sf('Arial', 13, bold=True),
        igmenu=sf('Arial', 11, bold=True),
    )
    return _fonts
