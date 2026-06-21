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

from chess_game.theme import PIECE_SIZE

_PIECE_NAMES = {
    chess.PAWN: 'pawn', chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop', chess.ROOK: 'rook',
    chess.QUEEN: 'queen', chess.KING: 'king',
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
    promotion picker, and color-picker screens."""

    def _load(name: str, color_char: str, size: int) -> pygame.Surface:
        img = pygame.image.load(
            resource_path_fn('data/imgs/' + color_char + '_' + name + '.png')
        ).convert_alpha()
        return pygame.transform.smoothscale(img, (size, size))

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
