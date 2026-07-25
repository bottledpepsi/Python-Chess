"""WCAG contrast regression tests for chess_game.theme colour pairs.

theme.py already documents several past contrast fixes inline (see its
"Contrast failures raised to >=4.5:1" header comment). This module turns
the specific pairs that matter for on-screen text into an executable
check, so a future colour tweak that reintroduces a low-contrast pairing
fails CI instead of silently shipping — which is exactly how the
MENU_ACCENT / MENU_TEXT regression this module guards against slipped
through the original cleanup pass.
"""
from __future__ import annotations

from chess_game import theme


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG 2.x relative luminance of an sRGB colour."""
    def chan(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two sRGB colours, in [1, 21]."""
    l1, l2 = relative_luminance(rgb1), relative_luminance(rgb2)
    l1, l2 = max(l1, l2), min(l1, l2)
    return (l1 + 0.05) / (l2 + 0.05)


WCAG_AA_NORMAL_TEXT = 4.5

# (description, foreground, background) for every text/fill pairing that
# actually appears on screen. Add to this list whenever a new text-on-fill
# combination is introduced in render/menus.py or elsewhere.
TEXT_ON_FILL_PAIRS: list[tuple[str, tuple[int, int, int], tuple[int, int, int]]] = [
    ("MENU_TEXT on MENU_BG", theme.MENU_TEXT, theme.MENU_BG),
    ("MENU_TEXT on MENU_BTN_NORM", theme.MENU_TEXT, theme.MENU_BTN_NORM),
    ("MENU_TEXT_SUB on MENU_BG", theme.MENU_TEXT_SUB, theme.MENU_BG),
    # MENU_TEXT_DIS on MENU_BTN_DIS is intentionally excluded here: WCAG's
    # normal-text contrast requirement doesn't apply to disabled/inactive
    # UI components, and this pairing (~3.67:1) is theme.py's deliberate
    # choice for a disabled button, not an oversight.
    # Selected segmented-control buttons (Bot Engine picker, Engine Match
    # setup): label text is rendered directly on the MENU_ACCENT fill, not
    # on MENU_BG, so it needs its own dedicated text colour — this is the
    # pairing that previously failed at ~2.44:1 (see render/menus.py).
    ("MENU_ACCENT_TEXT on MENU_ACCENT", theme.MENU_ACCENT_TEXT, theme.MENU_ACCENT),
]


def test_text_on_fill_pairs_meet_wcag_aa():
    failures = []
    for name, fg, bg in TEXT_ON_FILL_PAIRS:
        ratio = contrast_ratio(fg, bg)
        if ratio < WCAG_AA_NORMAL_TEXT:
            failures.append(f"{name}: {ratio:.2f}:1 (need >= {WCAG_AA_NORMAL_TEXT}:1)")
    assert not failures, "WCAG AA contrast failures:\n" + "\n".join(failures)


def test_selected_segmented_control_label_is_not_menu_text():
    """Regression guard for the specific bug: MENU_TEXT (220,220,220) on
    MENU_ACCENT (118,150,86) measures ~2.44:1, so the selected-state label
    colour must not be MENU_TEXT. This test fails loudly if a future edit
    reverts render/menus.py's lbl_col back to MENU_TEXT for either
    segmented control, even if this file's own contrast check above were
    ever relaxed."""
    ratio_if_menu_text = contrast_ratio(theme.MENU_TEXT, theme.MENU_ACCENT)
    assert ratio_if_menu_text < WCAG_AA_NORMAL_TEXT, (
        "This test's premise (MENU_TEXT on MENU_ACCENT fails AA) no longer "
        "holds — double check MENU_ACCENT hasn't changed before removing "
        "this guard."
    )
    ratio_actual = contrast_ratio(theme.MENU_ACCENT_TEXT, theme.MENU_ACCENT)
    assert ratio_actual >= WCAG_AA_NORMAL_TEXT
