"""Animation state for piece moves and the winner fade, dt-scaled."""
from __future__ import annotations

from dataclasses import dataclass, field

import chess

ANIM_MS = 120


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


def ease_out(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1.0 - (1.0 - t) ** 2


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
