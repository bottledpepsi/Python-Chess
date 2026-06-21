"""Animation state for piece moves and the winner fade, dt-scaled."""
from __future__ import annotations

from dataclasses import dataclass, field

import chess

ANIM_MS = 120
FLIP_MS = 600  # Board-flip animation duration (ms), including the pre-flip delay.
FLIP_DELAY_MS = 300  # Pause after the move slide before the flip begins.
# Minimum horizontal scale during the flip — the board never fully squashes
# to zero (which was nauseating); it just dips to this fraction of full width
# while the orientation swaps, then eases back out.
FLIP_MIN_SCALE = 0.78


@dataclass
class AnimItem:
    sx: float
    sy: float
    ex: float
    ey: float
    img: object  # pygame.Surface | None
    suppress_sq: int | None


@dataclass
class AnimationState:
    """A batch of simultaneously-animating piece slides."""
    items: list[AnimItem] = field(default_factory=list)
    start_ms: int = 0

    def is_animating(self, now_ms: int) -> bool:
        return bool(self.items) and (now_ms - self.start_ms) < ANIM_MS


@dataclass
class FlipState:
    """Tracks an in-flight board-flip animation.

    The flip plays in two phases:
      1. DELAY (FLIP_DELAY_MS): a brief pause after the move slide so the
         player sees the piece land before the board starts rotating.
      2. FLIP (FLIP_MS - FLIP_DELAY_MS): the board squashes horizontally
         to zero width (first half) then expands back from the opposite
         side (second half). `board_flipped` is SET to `target_flipped` at
         the midpoint so the orientation swap is hidden by the
         zero-width moment.

    `target_flipped` is the ABSOLUTE orientation the board should have
    after the flip (not a relative toggle). This prevents race conditions
    where rapid moves could leave the board in the wrong orientation —
    no matter how many flips queue up, the final orientation is always
    the correct one for the current turn.

    `start_ms` is set when the flip is armed (immediately after the move
    is applied). The caller checks `is_delaying` / `is_flipping` /
    `is_active` to decide what to render.
    """
    start_ms: int = 0
    target_flipped: bool = False

    def is_delaying(self, now_ms: int) -> bool:
        """True during the pre-flip pause (board still in old orientation)."""
        elapsed = now_ms - self.start_ms
        return elapsed < FLIP_DELAY_MS

    def is_flipping(self, now_ms: int) -> bool:
        """True during the actual squash/stretch (board visually rotating)."""
        elapsed = now_ms - self.start_ms
        return FLIP_DELAY_MS <= elapsed < FLIP_MS

    def is_active(self, now_ms: int) -> bool:
        """True for the entire flip lifecycle (delay + flip)."""
        return (now_ms - self.start_ms) < FLIP_MS

    def progress(self, now_ms: int) -> float:
        """Horizontal scale factor in [FLIP_MIN_SCALE, 1] during the flip.

        Returns 1.0 during the delay (board at full size in old orientation)
        and 1.0 after the flip completes (board at full size in new
        orientation). During the flip phase it traces a smooth dip down to
        FLIP_MIN_SCALE at the midpoint (the orientation swap moment) and
        back up to 1.0 — a gentle "settle" rather than a violent squash.

        The board never goes to zero width (which was nauseating); it just
        narrows slightly while the orientation swaps, which reads as a calm
        card-flip rather than a violent crush.
        """
        elapsed = now_ms - self.start_ms
        if elapsed < FLIP_DELAY_MS:
            return 1.0
        if elapsed >= FLIP_MS:
            return 1.0
        t = (elapsed - FLIP_DELAY_MS) / (FLIP_MS - FLIP_DELAY_MS)
        # Smooth triangle dip: 1 → FLIP_MIN_SCALE at t=0.5 → 1. We use a
        # sine-based smoothstep on each half so the scale decelerates into
        # the midpoint and accelerates out of it (ease-in-out feel) rather
        # than the linear triangle that felt abrupt.
        if t < 0.5:
            # First half: 1.0 → FLIP_MIN_SCALE, ease-in.
            half_t = t * 2.0  # 0 → 1 over the first half
            eased = ease_in_out(half_t)
            return 1.0 - (1.0 - FLIP_MIN_SCALE) * eased
        # Second half: FLIP_MIN_SCALE → 1.0, ease-out.
        half_t = (t - 0.5) * 2.0  # 0 → 1 over the second half
        eased = ease_in_out(half_t)
        return FLIP_MIN_SCALE + (1.0 - FLIP_MIN_SCALE) * eased

    def should_swap_orientation(self, now_ms: int) -> bool:
        """True at the flip midpoint — the moment the board is at zero width
        and the orientation should be toggled. Returns False at all other
        times."""
        if not self.is_flipping(now_ms):
            return False
        elapsed = now_ms - self.start_ms
        t = (elapsed - FLIP_DELAY_MS) / (FLIP_MS - FLIP_DELAY_MS)
        # Swap once, at the midpoint. We can't detect a single frame exactly
        # at t=0.5, so swap during the second half (t >= 0.5). The caller
        # gates this with a `swapped` flag so it only fires once.
        return t >= 0.5


def ease_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 2


def ease_in_out(t: float) -> float:
    """Smoothstep-style ease-in-out: slow start, fast middle, slow end.
    Used for the board-flip scale animation so the dip into the midpoint
    and the rise back out both feel gentle rather than abrupt."""
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass
class ReviewState:
    """Tracks move-history review-mode position.

    `target`/`going_live` from the original implementation were dead state
    (target was only ever assigned None) and have been removed
    entirely rather than ported forward.
    """
    ply: int | None = None          # None = live; int = ply index
    board: chess.Board | None = None

    @property
    def active(self) -> bool:
        return self.ply is not None

    def reset(self) -> None:
        self.ply = None
        self.board = None
