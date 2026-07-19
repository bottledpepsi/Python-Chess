"""Captured-piece tray rendering. Pure: surface + data in, nothing out.

Board-flip tray fix
-------------------
The original main.py always drew adapter.captured_pieces['black'] in the
top tray and captured_pieces['white'] in the bottom tray, regardless of
board_flipped - only the *label* text branched on board_flipped, so one
of the two label branches was always wrong (the data didn't change to
match the label).

captured_pieces[color] holds the pieces captured BY `color` (i.e. the
opponent's material losses). Which colour's captures belong in the top
tray depends on which colour's pieces sit on the top row of the board:
when not flipped, black sits on top, so the top tray shows black's own
captures (of white's pieces); when flipped, white sits on top.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.theme import LABEL_COL, MENU_ACCENT, TRAY_BG, TRAY_H

_PIECE_NAMES = {
    chess.PAWN: 'pawn', chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop', chess.ROOK: 'rook',
    chess.QUEEN: 'queen', chess.KING: 'king',
}
_NOTATION_TO_PT = {
    ' ': chess.PAWN, 'N': chess.KNIGHT, 'B': chess.BISHOP,
    'R': chess.ROOK, 'Q': chess.QUEEN, 'K': chess.KING,
}
_TRAY_ORDER = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]


def group_captures(pieces):
    """Group raw captured-piece dicts into (piece_type, color, count) tuples,
    ordered queen -> rook -> bishop -> knight -> pawn, white before black."""
    counts = {}
    for info in pieces:
        pt = _NOTATION_TO_PT.get(info['notation'], chess.PAWN)
        color = info['color']
        key = (pt, color)
        counts[key] = counts.get(key, 0) + 1
    result = []
    for pt in _TRAY_ORDER:
        for color in ('white', 'black'):
            k = (pt, color)
            if k in counts:
                result.append((pt, color, counts[k]))
    return result


def draw_tray(surface, panel_x, y0, pieces, label, fonts, tray_imgs,
              lead=0, thinking=False, think_dots=0, thinking_label='Bot is thinking'):
    """Draw one capture tray onto `surface`. Pure - no globals.

    thinking_label lets callers other than BOT mode (namely
    ENGINE_MATCH, where either side could be "the bot") supply a message
    that actually names which engine is thinking, e.g. "Native (depth 5)
    is thinking" or "Stockfish (ELO 1800) is thinking" — see
    draw_trays' engine_notes parameter, which builds this string from
    Game.engine_match_label so the tray never just says the generic
    "Bot" for a mode where both sides could be any engine.
    """
    w = panel_x  # tray only spans the board area, not the side panel
    pygame.draw.rect(surface, TRAY_BG, (0, y0, w, TRAY_H))
    pygame.draw.line(surface, (62, 62, 62), (0, y0), (w, y0))
    lbl = fonts.label.render(label, True, LABEL_COL)
    surface.blit(lbl, (6, y0 + 4))

    if thinking:
        dots = '.' * (1 + think_dots % 3)
        ts = fonts.think.render(thinking_label + dots, True, MENU_ACCENT)
        surface.blit(ts, ts.get_rect(midright=(w - 90, y0 + TRAY_H // 2)))

    grouped = group_captures(pieces)
    icon_w = 28
    cx = 6
    cy_icon = y0 + 20
    for pt, color, count in grouped:
        key = color[0] + '_' + _PIECE_NAMES.get(pt, 'pawn')
        img = tray_imgs.get(key)
        if img:
            surface.blit(img, (cx, cy_icon))
        if count > 1:
            badge = fonts.count.render('x' + str(count), True, (220, 220, 220))
            surface.blit(badge, (cx + icon_w - badge.get_width(), cy_icon + icon_w - 2))
        cx += icon_w + (6 if count > 1 else 2)
        if cx + icon_w > w - 100:
            break
    if lead > 0:
        lead_s = fonts.lead.render('+' + str(lead), True, (180, 220, 130))
        surface.blit(lead_s, (cx + 6, cy_icon + 6))


def draw_trays(surface, panel_x, bottom_y, adapter, board_flipped,
                fonts, tray_imgs, top_thinking, bottom_thinking, think_dots,
                engine_notes=None):
    """Draw both trays with the label correctly matched to the data.

    engine_notes, when given, is {'white': str, 'black': str} — each
    side's engine name/strength (see Game.engine_match_label). When
    present, a tray's label becomes "White \u00b7 Native (depth 5)" instead
    of the default "White's captures", and its thinking message names
    that same engine instead of the generic "Bot is thinking". Only
    ENGINE_MATCH passes this; PVP/BOT leave it None and get the
    unchanged original behaviour.
    """
    white_lead, black_lead = adapter.material_advantage()
    top_color = 'white' if board_flipped else 'black'
    bottom_color = 'black' if board_flipped else 'white'
    top_lead = white_lead if top_color == 'white' else black_lead
    bottom_lead = white_lead if bottom_color == 'white' else black_lead

    def _label_and_thinking_text(color: str) -> tuple[str, str]:
        if engine_notes is not None:
            note = engine_notes.get(color, '')
            base = f"{color.capitalize()} \u00b7 {note}" if note else color.capitalize() + "'s captures"
            return base, f'{note} is thinking' if note else 'Engine is thinking'
        return color.capitalize() + "'s captures", 'Bot is thinking'

    top_label, top_thinking_label = _label_and_thinking_text(top_color)
    bottom_label, bottom_thinking_label = _label_and_thinking_text(bottom_color)

    draw_tray(
        surface, panel_x, 0,
        adapter.captured_pieces[top_color],
        top_label,
        fonts, tray_imgs,
        lead=top_lead, thinking=top_thinking, think_dots=think_dots,
        thinking_label=top_thinking_label,
    )
    draw_tray(
        surface, panel_x, bottom_y,
        adapter.captured_pieces[bottom_color],
        bottom_label,
        fonts, tray_imgs,
        lead=bottom_lead, thinking=bottom_thinking, think_dots=think_dots,
        thinking_label=bottom_thinking_label,
    )
