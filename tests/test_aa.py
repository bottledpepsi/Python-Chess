"""Tests for render/aa.py's anti-aliasing primitives.

Beyond the usual "does it run" smoke coverage, this focuses on the one
property the rest of the app actually depends on: aa_rounded_rect and
aa_circle must reproduce a caller's exact requested colour wherever
coverage is meant to be 100%, not just approximately - because several
existing tests (test_ingame_focus.py's focus-ring check,
test_render_smoke.py's bot-engine segment check) read theme colours back
from rendered pixels. See render/aa.py's module docstring for why this
isn't automatic with a naive supersample-then-smoothscale.
"""
from __future__ import annotations

import pygame
import pytest

from chess_game.render.aa import (
    aa_button_backdrop,
    aa_circle,
    aa_polygon,
    aa_rounded_rect,
    blit_button_backdrop,
)

# (width, height, border_radius, outline_width) combinations drawn from
# the project's real call sites: the in-game focus ring (62x18, r8, w3),
# the preferences bot-engine segment (150x36, r8, fill), a large section
# card (512x88, r14, fill), a slider handle sized circle-ish square
# (24x24, r12, fill), a small history-row highlight (28x18, r4, w1), a
# clock pill (96x32, r10, w2), a modal-sized panel (200x100, r24, w6),
# and a square badge (36x36, r18, fill).
_REAL_WORLD_RECTS = [
    (62, 18, 8, 3),
    (150, 36, 8, 0),
    (512, 88, 14, 0),
    (24, 24, 12, 0),
    (28, 18, 4, 1),
    (96, 32, 10, 2),
    (200, 100, 24, 6),
    (36, 36, 18, 0),
]


class TestExactColorReproduction:
    """aa_rounded_rect/aa_circle must return the caller's exact colour
    wherever a pixel is unambiguously fully inside the shape - not an
    off-by-a-few-values approximation."""

    @pytest.mark.parametrize("w,h,radius,width", _REAL_WORLD_RECTS)
    def test_rect_center_pixel_is_exact(self, w, h, radius, width):
        color = (118, 150, 86)
        surf = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
        rect = pygame.Rect(2, 2, w, h)
        aa_rounded_rect(surf, color, rect, radius, width=width)
        cx, cy = rect.centerx, rect.centery
        if width > 0:
            # For an outline, the geometric center is inside the hollow
            # middle for anything but a very thick stroke - sample a
            # point that's unambiguously on the stroke band regardless
            # of thickness: the top-left corner region just past the
            # curve, offset in from the edge by less than `width`.
            cx, cy = rect.x + radius, rect.y + max(0, width - 1)
        assert tuple(surf.get_at((cx, cy)))[:3] == color

    @pytest.mark.parametrize("w,h,radius,width", _REAL_WORLD_RECTS)
    def test_rect_no_high_alpha_pixel_deviates(self, w, h, radius, width):
        """Exhaustively check every pixel of the shape: any pixel at
        alpha>=250 (i.e. visually solid, not a partial-coverage edge
        pixel) must be exactly the requested colour. This is the
        property the erosion-based alpha fix in aa.py depends on; a
        regression here would be invisible in a quick screenshot check
        (see the module docstring's account of the corner-touching bug
        an earlier version of this fix had)."""
        color = (140, 190, 250)
        surf = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
        rect = pygame.Rect(2, 2, w, h)
        aa_rounded_rect(surf, color, rect, radius, width=width)
        for x in range(rect.x, rect.right):
            for y in range(rect.y, rect.bottom):
                px = surf.get_at((x, y))
                if px[3] >= 250:
                    assert tuple(px)[:3] == color, f"deviated at ({x},{y}): {tuple(px)}"

    def test_circle_center_pixel_is_exact(self):
        color = (200, 100, 50)
        surf = pygame.Surface((60, 60), pygame.SRCALPHA)
        aa_circle(surf, color, (30, 30), 20)
        assert tuple(surf.get_at((30, 30)))[:3] == color

    def test_circle_no_high_alpha_pixel_deviates(self):
        color = (60, 60, 200)
        surf = pygame.Surface((70, 70), pygame.SRCALPHA)
        aa_circle(surf, color, (35, 35), 25, width=4)
        for x in range(70):
            for y in range(70):
                px = surf.get_at((x, y))
                if px[3] >= 250:
                    assert tuple(px)[:3] == color

    def test_pure_black_and_white_extremes(self):
        """The MIN-blend technique's one theoretical failure mode is a
        colour channel already at 255 combined with downward alpha/RGB
        drift at that exact pixel - check both extremes explicitly."""
        for color in [(0, 0, 0), (255, 255, 255)]:
            surf = pygame.Surface((100, 100), pygame.SRCALPHA)
            aa_rounded_rect(surf, color, pygame.Rect(10, 10, 60, 60), 16)
            assert tuple(surf.get_at((40, 40)))[:3] == color

    def test_per_corner_radius_matches_pygame_semantics(self):
        """A per-corner override (e.g. only rounding the left two
        corners, used by render/menus.py's board-theme swatch preview)
        should round only that corner at the given radius while the
        others keep following `border_radius`, mirroring
        pygame.draw.rect's own border_top_left_radius=-1-means-fallback
        behaviour."""
        color = (200, 100, 50)
        surf = pygame.Surface((100, 100), pygame.SRCALPHA)
        aa_rounded_rect(surf, color, pygame.Rect(0, 0, 100, 100), 20,
                         border_top_left_radius=4)
        # Top-left: tightly rounded (radius 4) - a pixel safely past that
        # small curve, e.g. (5,5), should already be inside the shape.
        assert surf.get_at((5, 5))[3] >= 250
        # Top-right: still governed by border_radius=20 - pixel (98,1)
        # should still be outside the (much larger) curve there.
        assert surf.get_at((98, 1))[3] == 0

    def test_project_focus_ring_scenario_exact(self):
        """Reproduces test_ingame_focus.py's real assertion: scanning
        every x across the top/bottom edge of a focus-ring rect must
        find at least one exact FOCUS_RING pixel, at the project's
        actual rect position/size."""
        from chess_game.widgets import FOCUS_RING

        for test_x, test_y in [(0, 0), (513, 2), (400, 100)]:
            surf = pygame.Surface((800, 700))
            surf.fill((20, 20, 20))
            rect = pygame.Rect(test_x, test_y, 62, 18)
            aa_rounded_rect(surf, FOCUS_RING, rect, 8, width=3)
            colors = {
                surf.get_at((x, y))[:3]
                for x in range(rect.x, rect.right)
                for y in (rect.y, rect.bottom - 1)
            }
            assert FOCUS_RING in colors

    def test_translucent_color_scales_coverage_not_flattens_it(self):
        """render/board.py's move-indicator dot/ring pass a translucent
        colour (alpha 80/85) rather than opaque. Every pixel's
        translucent alpha should equal the same pixel's fully-opaque
        alpha scaled by the requested alpha - not just the interior
        fill value with a hard-edged cutoff at the boundary, which is
        what an early debugging session briefly suspected was
        happening. That suspicion turned out to be a sampling mistake
        (checking row y=15 of a 30x30 surface, which is the exact
        vertical midline through a radius-12 circle centred at
        (15, 15) - every pixel on that row is legitimately 100%
        covered, so there was no edge on that row to show a ramp, opaque
        or not). This test checks a row that actually crosses the
        circle's boundary, so a future regression - accidental or
        otherwise - would show up here rather than needing a repeat of
        that debugging session."""
        surf_opaque = pygame.Surface((30, 30), pygame.SRCALPHA)
        aa_circle(surf_opaque, (0, 0, 0, 255), (15, 15), 12)
        surf_translucent = pygame.Surface((30, 30), pygame.SRCALPHA)
        aa_circle(surf_translucent, (0, 0, 0, 80), (15, 15), 12)

        for x in range(30):
            for y in range(30):
                opaque_a = surf_opaque.get_at((x, y))[3]
                trans_a = surf_translucent.get_at((x, y))[3]
                expected = round(opaque_a * 80 / 255)
                assert abs(trans_a - expected) <= 2, (
                    f"({x},{y}): opaque_a={opaque_a} trans_a={trans_a} expected~={expected}"
                )
        # And there must be genuine partial-coverage pixels present (not
        # just interior-80/exterior-0 with a hard step), i.e. the AA
        # edge survived the translucency scaling. Row y=4 crosses the
        # circle's top edge, unlike y=15 (the trap described above).
        edge_alphas = {surf_translucent.get_at((x, 4))[3] for x in range(30)}
        assert edge_alphas - {0, 80}, "no partial-coverage alpha values found near the AA edge"

    def test_translucent_polygon_scales_coverage_not_flattens_it(self):
        """Same property as the aa_circle case above, checked for
        aa_polygon: every ARROW_THEMES colour (theme.py) carries alpha
        180, so this path runs on every arrow drawn in the actual game,
        not just a hypothetical caller."""
        pts = [(10, 10), (50, 15), (30, 45)]
        surf_opaque = pygame.Surface((70, 70), pygame.SRCALPHA)
        aa_polygon(surf_opaque, (0, 180, 255, 255), pts)
        surf_translucent = pygame.Surface((70, 70), pygame.SRCALPHA)
        aa_polygon(surf_translucent, (0, 180, 255, 180), pts)

        deviations = 0
        for x in range(70):
            for y in range(70):
                opaque_a = surf_opaque.get_at((x, y))[3]
                trans_a = surf_translucent.get_at((x, y))[3]
                expected = round(opaque_a * 180 / 255)
                if abs(trans_a - expected) > 2:
                    deviations += 1
        assert deviations == 0

    def test_circle_thick_outline_erosion_still_locks_alpha(self):
        """Covers the width>0-and-still-positive-after-erosion branch
        of aa_circle's safe-interior mask (a thin outline, eroded by
        _SAFE_ERODE_PX on each side, can vanish entirely - this checks
        the case where it doesn't): a thick ring's mid-stroke pixel
        should be exactly the requested colour at full alpha, the same
        property test_rect_no_high_alpha_pixel_deviates checks for
        rects."""
        color = (90, 150, 220)
        surf = pygame.Surface((80, 80), pygame.SRCALPHA)
        aa_circle(surf, color, (40, 40), 30, width=10)
        # Mid-stroke on the flat right side of the ring, well clear of
        # both the outer and inner curve.
        assert tuple(surf.get_at((68, 40))) == (*color, 255)


class TestDegenerateInputs:
    """Zero/negative sizes and tiny shapes must not raise."""

    def test_zero_size_rect(self):
        surf = pygame.Surface((10, 10))
        aa_rounded_rect(surf, (255, 0, 0), pygame.Rect(0, 0, 0, 0), 5)

    def test_zero_radius_rect(self):
        surf = pygame.Surface((10, 10))
        aa_rounded_rect(surf, (255, 0, 0), pygame.Rect(0, 0, 8, 8), 0)

    def test_zero_radius_circle(self):
        surf = pygame.Surface((10, 10))
        aa_circle(surf, (255, 0, 0), (5, 5), 0)

    def test_tiny_shapes(self):
        surf = pygame.Surface((10, 10), pygame.SRCALPHA)
        aa_rounded_rect(surf, (200, 100, 50), pygame.Rect(1, 1, 1, 1), 0)
        aa_rounded_rect(surf, (200, 100, 50), pygame.Rect(1, 1, 4, 4), 2, width=1)
        aa_circle(surf, (200, 100, 50), (5, 5), 1)

    def test_empty_polygon(self):
        surf = pygame.Surface((10, 10))
        aa_polygon(surf, (255, 0, 0), [])
        aa_polygon(surf, (255, 0, 0), [(0, 0), (1, 1)])

    def test_thin_polygon(self):
        surf = pygame.Surface((100, 100), pygame.SRCALPHA)
        aa_polygon(surf, (0, 180, 255), [(5, 5), (5, 50), (50, 27)])

    def test_colinear_points_do_not_crash(self):
        """Three colinear points (zero-area triangle) still produce a
        positive-size mask - aa_polygon's margin (at least 2px on every
        side) keeps w/h >= 4 regardless of how degenerate the points
        are, so this exercises that margin rather than a w<=0 guard."""
        surf = pygame.Surface((100, 100), pygame.SRCALPHA)
        aa_polygon(surf, (0, 180, 255), [(5, 20), (30, 20), (60, 20)])


class TestButtonBackdropCache:
    def test_identical_args_return_same_surface(self):
        aa_button_backdrop.cache_clear()
        b1 = aa_button_backdrop((100, 40), 8, (50, 50, 50), (90, 90, 90), 1)
        b2 = aa_button_backdrop((100, 40), 8, (50, 50, 50), (90, 90, 90), 1)
        assert b1 is b2

    def test_different_args_return_different_surfaces(self):
        aa_button_backdrop.cache_clear()
        b1 = aa_button_backdrop((100, 40), 8, (50, 50, 50), (90, 90, 90), 1)
        b2 = aa_button_backdrop((100, 40), 8, (51, 50, 50), (90, 90, 90), 1)
        assert b1 is not b2

    def test_no_border_color_is_valid(self):
        aa_button_backdrop.cache_clear()
        aa_button_backdrop((80, 30), 6, (40, 40, 40), None, 1)

    def test_blit_button_backdrop_runs(self):
        surf = pygame.Surface((200, 200))
        blit_button_backdrop(surf, pygame.Rect(10, 10, 80, 30), 8, (60, 60, 60), (100, 100, 100), 1)

    def test_blit_button_backdrop_zero_size_noop(self):
        surf = pygame.Surface((200, 200))
        blit_button_backdrop(surf, pygame.Rect(10, 10, 0, 30), 8, (60, 60, 60))
