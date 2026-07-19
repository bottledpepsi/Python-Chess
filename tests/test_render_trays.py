"""Targeted coverage for chess_game/render/trays.py beyond the single
generic call in test_render_smoke.py: the 'thinking' dots branch, capture
icon rendering with and without a count badge, the lead (+N) display, and
the row-overflow break in draw_tray's icon loop.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.render import trays
from chess_game.theme import PANEL_X, TRAY_H, WIN_H, WIN_W, load_fonts


def _capture(notation: str, color: str) -> dict:
    return {'notation': notation, 'color': color}


def test_group_captures_orders_queen_to_pawn_white_before_black():
    pieces = [
        _capture(' ', 'white'),   # pawn
        _capture('Q', 'black'),
        _capture('Q', 'white'),
        _capture('N', 'white'),
    ]
    grouped = trays.group_captures(pieces)
    # Queen entries should come before knight, which comes before pawn;
    # white before black within the same piece type.
    kinds = [(pt, color) for pt, color, _ in grouped]
    assert kinds.index((chess.QUEEN, 'white')) < kinds.index((chess.QUEEN, 'black'))
    assert kinds.index((chess.QUEEN, 'white')) < kinds.index((chess.KNIGHT, 'white'))
    assert kinds.index((chess.KNIGHT, 'white')) < kinds.index((chess.PAWN, 'white'))


def test_group_captures_counts_duplicates():
    pieces = [_capture(' ', 'white'), _capture(' ', 'white'), _capture(' ', 'white')]
    grouped = trays.group_captures(pieces)
    assert grouped == [(chess.PAWN, 'white', 3)]


def test_draw_tray_with_thinking_dots():
    surf = pygame.Surface((WIN_W, TRAY_H))
    fonts = load_fonts()
    # thinking=True with each think_dots value exercises the '.', '..', '...'
    # cycle (1 + think_dots % 3).
    for dots in (0, 1, 2, 3, 4):
        trays.draw_tray(surf, PANEL_X, 0, [], 'White', fonts, {},
                         thinking=True, think_dots=dots)


def test_draw_tray_with_captures_and_count_badge():
    """A single-count capture exercises the icon-blit branch; 2+ of the same
    type exercises the count badge ('x2') branch."""
    surf = pygame.Surface((WIN_W, TRAY_H))
    fonts = load_fonts()
    pieces = [
        _capture('Q', 'black'),               # single queen
        _capture(' ', 'black'),
        _capture(' ', 'black'),                # 2x pawns -> count badge
    ]
    # tray_imgs deliberately empty (mirrors a missing/incomplete asset map):
    # exercises the `if img:` False branch without crashing.
    trays.draw_tray(surf, PANEL_X, 0, pieces, 'Black', fonts, {})


def test_draw_tray_with_lead_display():
    surf = pygame.Surface((WIN_W, TRAY_H))
    fonts = load_fonts()
    trays.draw_tray(surf, PANEL_X, 0, [], 'White', fonts, {}, lead=5)


def test_draw_tray_overflow_breaks_icon_loop():
    """Enough distinct captured piece types to overflow the row should hit
    the `if cx + icon_w > w - 100: break` branch rather than drawing past
    the tray's usable width."""
    surf = pygame.Surface((200, TRAY_H))  # narrow surface forces overflow fast
    fonts = load_fonts()
    pieces = [
        _capture('Q', 'white'), _capture('R', 'white'), _capture('B', 'white'),
        _capture('N', 'white'), _capture(' ', 'white'), _capture(' ', 'white'),
        _capture(' ', 'white'),
    ]
    # panel_x narrower than the natural icon run -> loop must break cleanly,
    # not raise or draw off-surface.
    trays.draw_tray(surf, 150, 0, pieces, 'White', fonts, {})


def test_draw_trays_both_orientations_with_captures():
    """draw_trays (the two-tray wrapper) with real captured-piece data and
    both board_flipped states, matching the label-vs-data fix this module's
    docstring documents."""
    class _FakeAdapter:
        captured_pieces = {
            'white': [_capture('Q', 'black')],
            'black': [_capture('N', 'white'), _capture('N', 'white')],
        }

        def material_advantage(self):
            return (3, 0)

    fonts = load_fonts()
    surf = pygame.Surface((WIN_W, WIN_H))
    for flipped in (False, True):
        trays.draw_trays(surf, PANEL_X, WIN_H - TRAY_H, _FakeAdapter(), flipped,
                          fonts, {}, top_thinking=False, bottom_thinking=True, think_dots=2)


class _FakeAdapterNoCaptures:
    captured_pieces = {'white': [], 'black': []}

    def material_advantage(self):
        return (0, 0)


def test_draw_trays_engine_notes_relabels_both_trays(monkeypatch):
    """When engine_notes is given (ENGINE_MATCH mode), each tray's label
    becomes "<Color> \u00b7 <note>" instead of the default
    "<Color>'s captures", and its thinking message names that engine —
    verified for both board orientations, since the note must follow the
    *color*, not the screen position."""
    calls = []
    original_draw_tray = trays.draw_tray

    def _spy_draw_tray(surface, panel_x, y0, pieces, label, fonts, tray_imgs,
                        lead=0, thinking=False, think_dots=0, thinking_label='Bot is thinking'):
        calls.append((label, thinking_label))
        return original_draw_tray(surface, panel_x, y0, pieces, label, fonts, tray_imgs,
                                   lead=lead, thinking=thinking, think_dots=think_dots,
                                   thinking_label=thinking_label)

    monkeypatch.setattr(trays, 'draw_tray', _spy_draw_tray)

    fonts = load_fonts()
    surf = pygame.Surface((WIN_W, WIN_H))
    notes = {'white': 'Native (depth 4)', 'black': 'Stockfish (ELO 2200)'}

    for flipped in (False, True):
        calls.clear()
        trays.draw_trays(surf, PANEL_X, WIN_H - TRAY_H, _FakeAdapterNoCaptures(), flipped,
                          fonts, {}, top_thinking=True, bottom_thinking=True, think_dots=0,
                          engine_notes=notes)
        labels = {label for label, _ in calls}
        thinking_labels = {t for _, t in calls}
        assert "White \u00b7 Native (depth 4)" in labels
        assert "Black \u00b7 Stockfish (ELO 2200)" in labels
        assert any('Native (depth 4)' in t for t in thinking_labels)
        assert any('Stockfish (ELO 2200)' in t for t in thinking_labels)


def test_draw_trays_without_engine_notes_uses_default_labels(monkeypatch):
    """PVP/BOT never pass engine_notes; confirms the default labels are
    completely unchanged by this feature."""
    calls = []
    original_draw_tray = trays.draw_tray

    def _spy_draw_tray(surface, panel_x, y0, pieces, label, fonts, tray_imgs,
                        lead=0, thinking=False, think_dots=0, thinking_label='Bot is thinking'):
        calls.append((label, thinking_label))
        return original_draw_tray(surface, panel_x, y0, pieces, label, fonts, tray_imgs,
                                   lead=lead, thinking=thinking, think_dots=think_dots,
                                   thinking_label=thinking_label)

    monkeypatch.setattr(trays, 'draw_tray', _spy_draw_tray)

    fonts = load_fonts()
    surf = pygame.Surface((WIN_W, WIN_H))
    trays.draw_trays(surf, PANEL_X, WIN_H - TRAY_H, _FakeAdapterNoCaptures(), False,
                      fonts, {}, top_thinking=True, bottom_thinking=True, think_dots=0)

    labels = {label for label, _ in calls}
    thinking_labels = {t for _, t in calls}
    assert "White's captures" in labels
    assert "Black's captures" in labels
    assert thinking_labels == {'Bot is thinking'}


def test_draw_tray_engine_note_label_and_thinking_text():
    """draw_tray itself accepts an explicit thinking_label override —
    this is the piece draw_trays' engine_notes wiring depends on, tested
    directly so a regression here is caught even if draw_trays' own
    internal label-selection logic changes shape later."""
    surf = pygame.Surface((WIN_W, TRAY_H))
    fonts = load_fonts()
    trays.draw_tray(
        surf, PANEL_X, 0, [], "White \u00b7 Native (depth 5)", fonts, {},
        thinking=True, think_dots=1, thinking_label="Native (depth 5) is thinking",
    )


def test_draw_tray_default_thinking_label_is_unchanged():
    """Regression guard: omitting thinking_label must still say "Bot is
    thinking" exactly as before this parameter existed, so PVP/BOT (which
    never pass it) render identically to pre-engine-match behaviour."""
    surf = pygame.Surface((WIN_W, TRAY_H))
    fonts = load_fonts()
    # No assertion beyond "doesn't raise" is possible without pixel
    # inspection, but the default argument value itself
    # (thinking_label='Bot is thinking') is the actual regression
    # surface — confirmed directly via the function signature default.
    import inspect
    sig = inspect.signature(trays.draw_tray)
    assert sig.parameters['thinking_label'].default == 'Bot is thinking'
    trays.draw_tray(surf, PANEL_X, 0, [], 'White', fonts, {}, thinking=True, think_dots=0)
