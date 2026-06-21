"""Widget tests: round-half-up slider snapping."""
from __future__ import annotations

from chess_game.widgets import Slider


def test_slider_value_from_x_round_half_up_not_banker():
    # 1-10 slider, 380px wide, matching draw_difficulty's geometry.
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    # t=0.5 exactly -> steps=9, 9*0.5=4.5 -> round-half-up means 5, + vmin(1) = 6
    midpoint_x = int(380 * 0.5)
    val = sl.value_from_x(midpoint_x)
    assert val == 6, f"expected round-half-up to give 6, got {val}"


def test_slider_value_from_x_clamped_to_range():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    assert sl.value_from_x(-100) == 1
    assert sl.value_from_x(10000) == 10
