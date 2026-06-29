"""Unit tests for chess_game.clock.Clock - no pygame, no App, pure logic."""
from __future__ import annotations

import chess
import pytest

from chess_game.clock import Clock


def test_clock_ticks_down_for_active_side():
    c = Clock(60_000)
    c.tick(0)  # first tick only establishes the baseline, no time subtracted
    assert c.remaining(chess.WHITE) == 60_000
    c.tick(500)
    assert c.remaining(chess.WHITE) == 59_500
    c.tick(1500)
    assert c.remaining(chess.WHITE) == 58_500
    # The inactive side is untouched.
    assert c.remaining(chess.BLACK) == 60_000


def test_clock_switch_adds_increment():
    c = Clock(60_000, increment_ms=2_000)
    c.switch()
    assert c.remaining(chess.WHITE) == 62_000
    assert c.active == chess.BLACK


def test_clock_flags_at_zero():
    c = Clock(1_000)
    c.tick(0)
    c.tick(1_500)
    assert c.flagged() == chess.WHITE
    assert c.remaining(chess.WHITE) == 0


def test_clock_does_not_tick_after_flag():
    c = Clock(1_000)
    c.tick(0)
    c.tick(1_500)
    assert c.flagged() == chess.WHITE
    # Further ticks are no-ops: remaining time stays clamped at 0 and the
    # flagged side doesn't change.
    c.tick(10_000)
    assert c.remaining(chess.WHITE) == 0
    assert c.flagged() == chess.WHITE


def test_clock_format_high_time():
    c = Clock(3 * 60_000 + 42_000)  # 3:42
    assert c.format(chess.WHITE) == "3:42"


def test_clock_format_exactly_ten_seconds_uses_low_format():
    # The boundary is deliberately inclusive on the low-time side: at
    # exactly 10.0s the player should already see tenths, since the next
    # tick could drop them under 10s and showing "0:10" right up to the
    # wire would hide that they're about to enter the danger zone.
    c = Clock(10_000)
    assert c.format(chess.WHITE) == "10.0"


def test_clock_format_just_above_ten_seconds_uses_high_format():
    c = Clock(10_100)
    assert c.format(chess.WHITE) == "0:10"


def test_clock_format_low_time():
    c = Clock(8_300)
    assert c.format(chess.WHITE) == "8.3"


def test_clock_format_very_low_time():
    c = Clock(400)
    assert c.format(chess.WHITE) == "0.4"


def test_clock_format_over_an_hour():
    c = Clock(((1 * 3600) + (5 * 60) + 9) * 1000)  # 1:05:09
    assert c.format(chess.WHITE) == "1:05:09"


def test_clock_switch_resets_last_tick():
    c = Clock(60_000)
    c.tick(1_000)          # baseline
    c.tick(1_500)          # 500ms elapsed, subtracted from White
    assert c.remaining(chess.WHITE) == 59_500
    c.switch()              # now Black is active; _last_tick_ms reset to None
    c.tick(50_000)          # huge wall-clock gap since the last real tick,
                             # but switch() reset the baseline so this tick
                             # establishes a new baseline instead of
                             # subtracting the 48.5s gap from Black
    assert c.remaining(chess.BLACK) == 60_000
    c.tick(50_200)
    assert c.remaining(chess.BLACK) == 59_800


def test_clock_switch_is_noop_once_flagged():
    c = Clock(1_000)
    c.tick(0)
    c.tick(2_000)
    assert c.flagged() == chess.WHITE
    c.switch()
    # switch() must not un-flag the clock or change the active side once
    # a flag-fall has already happened.
    assert c.active == chess.WHITE
    assert c.flagged() == chess.WHITE


def test_clock_remaining_never_negative():
    c = Clock(500)
    c.tick(0)
    c.tick(10_000)
    assert c.remaining(chess.WHITE) == 0


@pytest.mark.parametrize("preset,expected_initial_ms,expected_increment_ms", [
    ("1+0", 60_000, 0),
    ("3+2", 180_000, 2_000),
    ("5+0", 300_000, 0),
    ("10+0", 600_000, 0),
    ("15+10", 900_000, 10_000),
])
def test_clock_from_preset(preset, expected_initial_ms, expected_increment_ms):
    c = Clock.from_preset(preset)
    assert c is not None
    assert c.remaining(chess.WHITE) == expected_initial_ms
    assert c.remaining(chess.BLACK) == expected_initial_ms
    assert c.increment_ms == expected_increment_ms


def test_clock_from_preset_none_is_untimed():
    assert Clock.from_preset("none") is None


def test_clock_from_preset_unknown_is_untimed():
    assert Clock.from_preset("not-a-real-preset") is None
