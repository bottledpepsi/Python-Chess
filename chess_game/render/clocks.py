"""PvP chess clock rendering. Pure: surface + data in, nothing out.

Placement
---------
The clocks render as small digital displays inside the existing
captured-piece trays, anchored to each tray's right edge (the trays' left
side is used by draw_tray for capture icons, and draw_tray's "lead" badge
and "Bot is thinking..." text both stop well short of the right edge —
see render/trays.py).

The top tray is NOT free real estate at the top, though: App._render_game
draws the in-game "Menu" button and the analysis-mode toggle ('A') in
that same right-aligned corner, at y=2..20 — spanning roughly
panel_x-116..panel_x, or panel_x-364..panel_x in PVP/BOT once the
Resign/Offer Draw/Export PGN buttons are included (see _render_game;
those three are absent in ENGINE_MATCH, which uses Pause/Step instead at
a similar total width). A clock vertically centred in the full tray
height sits right on top of those buttons. To avoid that, the top clock
is pinned to the *bottom* of the top tray instead of centred, clearing
the button row entirely; the bottom clock has no such conflict (nothing
else occupies the bottom tray's right edge) and stays vertically centred.

This keeps the clocks visually attached to the player they belong to
without needing any new layout constants in theme.py: whichever side's
captures are shown in the top tray gets the top clock, and likewise for
the bottom tray, exactly mirroring render/trays.draw_trays's own
board_flipped-aware top/bottom swap. A side-of-tray placement (rather
than a separate free-standing widget elsewhere on screen) was chosen so
the existing tray bar doesn't need to be resized or gain new chrome.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.theme import MENU_ACCENT_BRIGHT, TRAY_H

_CLOCK_W = 96
_CLOCK_H = 32
_CLOCK_MARGIN_RIGHT = 10
_CLOCK_MARGIN_BOTTOM = 4
# The in-game Menu button + analysis toggle occupy y=2..20 in the top
# tray's top-right corner (see App._render_game). The top clock starts
# below that with a small gap, rather than being vertically centred.
_TOP_CLOCK_MARGIN_TOP = 24
_LOW_TIME_MS = 10_000
_LOW_TIME_COLOR = (220, 80, 80)
_INACTIVE_DIM = (130, 130, 130)


def _draw_one_clock(surface, rect, label_text, is_active, is_low, is_flagged, fonts):
    """Draw a single digital clock readout inside `rect`."""
    if is_flagged:
        bg = (50, 26, 26)
        border_col = _LOW_TIME_COLOR
        text_col = _LOW_TIME_COLOR
    elif is_active:
        bg = (40, 40, 38)
        border_col = MENU_ACCENT_BRIGHT
        text_col = _LOW_TIME_COLOR if is_low else (235, 235, 225)
    else:
        bg = (32, 32, 32)
        border_col = (60, 60, 60)
        text_col = _INACTIVE_DIM

    surface.fill(bg, rect)
    pygame.draw.rect(surface, border_col, rect, 2 if is_active else 1, border_radius=6)

    digits = fonts.diff_n.render(label_text, True, text_col)
    surface.blit(digits, digits.get_rect(center=rect.center))


def draw_clocks(surface, panel_x, bottom_y, game, fonts, board_flipped):
    """Draw both PvP clocks onto `surface`, right-aligned inside the top
    and bottom capture trays. No-op when the game is untimed
    (game.clock is None) — covers both untimed PvP and all bot games.

    `panel_x` and `bottom_y` mirror render.trays.draw_trays's own
    parameters exactly (the tray's right edge and the bottom tray's y0),
    since the clocks are drawn inside those same tray bars.
    """
    clock = game.clock
    if clock is None:
        return

    # Mirrors render/trays.draw_trays exactly: top tray shows whichever
    # colour sits on top of the board given the current flip state.
    top_color = chess.WHITE if board_flipped else chess.BLACK
    bottom_color = chess.BLACK if board_flipped else chess.WHITE

    rect_x = panel_x - _CLOCK_W - _CLOCK_MARGIN_RIGHT
    # Pinned below the Menu/analysis buttons (see module docstring), not
    # vertically centred in the tray.
    top_rect = pygame.Rect(rect_x, _TOP_CLOCK_MARGIN_TOP, _CLOCK_W, _CLOCK_H)
    # The bottom tray has no competing UI, so its clock stays bottom-aligned
    # with a small margin, mirroring the top clock's margin-from-edge feel.
    bottom_rect = pygame.Rect(
        rect_x, bottom_y + TRAY_H - _CLOCK_H - _CLOCK_MARGIN_BOTTOM, _CLOCK_W, _CLOCK_H,
    )

    flagged = clock.flagged()
    for color, rect in ((top_color, top_rect), (bottom_color, bottom_rect)):
        is_flagged = flagged == color
        label_text = "0:00" if is_flagged else clock.format(color)
        is_low = clock.remaining(color) <= _LOW_TIME_MS
        is_active = (clock.active == color) and flagged is None
        _draw_one_clock(surface, rect, label_text, is_active, is_low, is_flagged, fonts)
