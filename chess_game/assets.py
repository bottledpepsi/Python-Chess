"""Image asset loading: piece sprites, promotion icons, king portraits.

Must run after pygame.display.set_mode() (convert_alpha needs a display
surface), so callers invoke load_images() from bootstrap(), never at
import time.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import chess
import pygame

from chess_game.log import get_logger
from chess_game.theme import PIECE_SIZE

_PIECE_NAMES = {
    chess.PAWN: 'pawn', chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop', chess.ROOK: 'rook',
    chess.QUEEN: 'queen', chess.KING: 'king',
}

# Standard one-letter glyphs used on the placeholder surface when a real
# piece PNG can't be loaded (so a missing asset degrades to a labelled
# square rather than crashing a windowed build with no visible error).
_PLACEHOLDER_LETTER = {
    'pawn': 'P', 'knight': 'N', 'bishop': 'B',
    'rook': 'R', 'queen': 'Q', 'king': 'K',
}


@dataclass
class Assets:
    piece_imgs: dict = field(default_factory=dict)       # (piece_type, color) -> Surface
    tray_imgs: dict = field(default_factory=dict)         # "w_pawn" -> Surface (30px)
    promo_imgs: dict = field(default_factory=dict)        # "w_queen" -> Surface (78px)
    promo_imgs_small: dict = field(default_factory=dict)  # "w_queen" -> Surface (54px)
    king_imgs: dict = field(default_factory=dict)         # "white"/"black" -> Surface (100px)


def load_images(resource_path_fn: Callable[[str], str]) -> Assets:
    """Load and scale every piece image used across the board, trays,
    promotion picker, and color-picker screens.

    A missing or unreadable PNG degrades to a labelled placeholder surface
    (solid square + piece letter + red border) rather than raising, so a
    PyInstaller bundling failure in a --windowed build surfaces as visibly
    wrong pieces instead of the app silently disappearing on startup.
    """
    logger = get_logger()

    def _placeholder(name: str, color_char: str, size: int) -> pygame.Surface:
        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        is_white = color_char == 'w'
        bg = (235, 235, 230) if is_white else (45, 45, 45)
        fg = (30, 30, 30) if is_white else (235, 235, 235)
        surf.fill(bg)
        letter = _PLACEHOLDER_LETTER.get(name, '?')
        try:
            font = pygame.font.Font(None, max(8, int(size * 0.8)))
            text = font.render(letter, True, fg)
            surf.blit(text, text.get_rect(center=surf.get_rect().center))
        except pygame.error:
            pass  # font unavailable; the red border still signals the fallback
        pygame.draw.rect(surf, (200, 50, 50), surf.get_rect(), 2)
        return surf

    def _load(name: str, color_char: str, size: int) -> pygame.Surface:
        path = resource_path_fn('data/imgs/' + color_char + '_' + name + '.png')
        try:
            img = pygame.image.load(path).convert_alpha()
            return pygame.transform.smoothscale(img, (size, size))
        except (pygame.error, FileNotFoundError):
            logger.exception(
                "Could not load piece image %r at %s; using a placeholder.", name, path
            )
            return _placeholder(name, color_char, size)

    assets = Assets()
    for ct, pchar in ((chess.WHITE, 'w'), (chess.BLACK, 'b')):
        for ptype, pname in _PIECE_NAMES.items():
            assets.piece_imgs[(ptype, ct)] = _load(pname, pchar, PIECE_SIZE)
            assets.tray_imgs[pchar + '_' + pname] = _load(pname, pchar, 30)
        for pname in ('queen', 'rook', 'bishop', 'knight'):
            assets.promo_imgs[pchar + '_' + pname] = _load(pname, pchar, 78)
            assets.promo_imgs_small[pchar + '_' + pname] = _load(pname, pchar, 54)

    assets.king_imgs['white'] = _load('king', 'w', 100)
    assets.king_imgs['black'] = _load('king', 'b', 100)
    return assets
