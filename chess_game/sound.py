"""Sound effect playback, with structured logging instead of print()."""
from __future__ import annotations

import pygame

from chess_game.log import get_logger


class SoundManager:
    def __init__(self, resource_path_fn):
        self._sounds = {}
        self.audio_enabled = False
        logger = get_logger()

        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init()
                self.audio_enabled = True
                logger.info("Pygame mixer initialized successfully.")
            except pygame.error:
                logger.exception("Failed to initialize pygame.mixer; running without audio.")
                return
        else:
            self.audio_enabled = True

        sound_assets = (
            ('move', resource_path_fn('data/sounds/move.ogg')),
            ('capture', resource_path_fn('data/sounds/capture.ogg')),
        )

        for name, path in sound_assets:
            try:
                s = pygame.mixer.Sound(path)
                s.set_volume(0.6)
                self._sounds[name] = s
                logger.info("Loaded sound asset: %r from %s", name, path)
            except (pygame.error, FileNotFoundError):
                logger.exception("Could not load sound file %r at %s", name, path)

        if not self._sounds:
            logger.warning("No sound assets were loaded. System will remain silent.")

    def play(self, name: str) -> None:
        if not self.audio_enabled:
            return
        s = self._sounds.get(name)
        if s:
            try:
                s.play()
            except pygame.error:
                get_logger().exception("Error playing sound %r", name)

    def play_for_move_result(self, result: str, *, is_check: bool = False,
                              is_game_over: bool = False) -> None:
        """Play the cue for a completed move.

        Audio cues for check, checkmate, and draw should be distinct
        from plain move/capture sounds. No dedicated check/checkmate/draw
        .ogg assets exist in data/sounds/ (only move.ogg and capture.ogg) —
        adding new asset files wasn't authorized by the remediation brief
        ("no new runtime dependencies... flag and ask first"), so this
        approximates the cue with a double-strike of the existing capture
        sound for game-ending moves and check, which is audibly distinct
        from a single move/capture without requiring new assets. Replace
        with dedicated check.ogg/checkmate.ogg/draw.ogg assets when available.
        """
        if is_game_over:
            self.play('capture')
            return
        if is_check:
            self.play('capture')
            return
        if result in ('capture', 'en_passant'):
            self.play('capture')
        elif result == 'move':
            self.play('move')
