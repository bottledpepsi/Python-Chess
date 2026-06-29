"""Per-side chess clock with increment.

PvP-only. No timer thread: the clock is advanced by calling `tick()` once
per frame from App._frame, using pygame.time.get_ticks() as the time
source. This deliberately avoids spawning a background thread, which
would race against the main loop's animation/flip state machine.
"""
from __future__ import annotations

import chess

# (label, initial_seconds, increment_seconds). "none" is handled separately
# by callers (no Clock is constructed at all) and is not listed here.
TIME_CONTROL_PRESETS: dict[str, tuple[int, int]] = {
    "1+0": (60, 0),
    "3+2": (180, 2),
    "5+0": (300, 0),
    "10+0": (600, 0),
    "15+10": (900, 10),
}


class Clock:
    """Per-side chess clock with increment. No thread - tick from the main loop."""

    def __init__(self, initial_ms: int, increment_ms: int = 0) -> None:
        self.times: dict[chess.Color, int] = {
            chess.WHITE: initial_ms,
            chess.BLACK: initial_ms,
        }
        self.increment_ms = increment_ms
        self.active: chess.Color = chess.WHITE
        self._last_tick_ms: int | None = None
        self._flagged: chess.Color | None = None

    def tick(self, now_ms: int) -> None:
        """Subtract elapsed time from the active side's clock. Call once per frame."""
        if self._flagged is not None:
            return
        if self._last_tick_ms is None:
            self._last_tick_ms = now_ms
            return
        elapsed = now_ms - self._last_tick_ms
        self._last_tick_ms = now_ms
        self.times[self.active] -= elapsed
        if self.times[self.active] <= 0:
            self.times[self.active] = 0
            self._flagged = self.active

    def switch(self) -> None:
        """Switch the active side and add increment to the side that just moved."""
        if self._flagged is not None:
            return
        just_moved = self.active
        self.times[just_moved] += self.increment_ms
        self.active = not just_moved
        self._last_tick_ms = None  # reset so the next tick doesn't subtract the gap

    def flagged(self) -> chess.Color | None:
        return self._flagged

    def remaining(self, color: chess.Color) -> int:
        return max(0, self.times[color])

    def format(self, color: chess.Color) -> str:
        """Render remaining time for `color`.

        - Above 1 hour: H:MM:SS
        - Above 10 seconds: M:SS
        - At or below 10 seconds: SS.d (tenths shown so the player can see
          they're flagging)
        """
        ms = self.remaining(color)
        total_seconds = ms / 1000.0

        if total_seconds > 10:
            total_seconds_int = int(total_seconds)
            hours, rem = divmod(total_seconds_int, 3600)
            minutes, seconds = divmod(rem, 60)
            if hours > 0:
                return f"{hours}:{minutes:02d}:{seconds:02d}"
            return f"{minutes}:{seconds:02d}"

        # Low time: show tenths of a second.
        tenths_total = int(ms // 100)  # truncate, don't round up past 0
        whole_seconds, tenth = divmod(tenths_total, 10)
        return f"{whole_seconds}.{tenth}"

    @classmethod
    def from_preset(cls, preset: str) -> Clock | None:
        """Construct a Clock from a preset name (e.g. "3+2"), or None for
        "none" / any unrecognised preset (treated as untimed)."""
        spec = TIME_CONTROL_PRESETS.get(preset)
        if spec is None:
            return None
        initial_s, increment_s = spec
        return cls(initial_s * 1000, increment_s * 1000)
