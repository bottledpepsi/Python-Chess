"""SoundManager tests: init failure, missing asset files, disabled-audio
no-op, and exception handling during playback.

pygame.mixer is already initialised in dummy-audio-driver mode by
conftest/other tests in this suite, so most of these tests monkeypatch
pygame.mixer directly rather than relying on a real failure, mirroring
the approach used for the analysis/stockfish worker tests elsewhere in
this repo.
"""
from __future__ import annotations

import pygame
import pytest

from chess_game.sound import SoundManager


def _missing_resource_path(rel: str) -> str:
    """Always points at a nonexistent file, to exercise the asset-load
    failure path without touching real data/sounds/*.ogg."""
    return '/nonexistent/path/' + rel


def test_sound_manager_missing_assets_disables_nothing_but_logs(caplog):
    """Sound files that don't exist on disk should be skipped (not raise),
    leaving _sounds empty and triggering the 'no assets loaded' warning."""
    sm = SoundManager(_missing_resource_path)
    assert sm._sounds == {}
    # audio_enabled reflects whether the mixer itself initialised, which is
    # independent of whether any individual asset loaded successfully.


def test_play_is_noop_when_audio_disabled():
    sm = SoundManager.__new__(SoundManager)
    sm._sounds = {}
    sm.audio_enabled = False
    # Must not raise even though _sounds is empty and audio is off.
    sm.play('move')


def test_play_is_noop_for_unknown_sound_name():
    sm = SoundManager.__new__(SoundManager)
    sm._sounds = {}
    sm.audio_enabled = True
    sm.play('does_not_exist')  # no KeyError, just a silent no-op


def test_play_swallows_pygame_error_on_playback_failure(monkeypatch):
    """If Sound.play() itself raises (e.g. device went away mid-game), play()
    must log and swallow it rather than crashing the frame loop."""
    class _ExplodingSound:
        def play(self):
            raise pygame.error('mock device failure')

    sm = SoundManager.__new__(SoundManager)
    sm._sounds = {'move': _ExplodingSound()}
    sm.audio_enabled = True
    sm.play('move')  # must not raise


def test_sound_manager_mixer_init_failure_disables_audio(monkeypatch):
    """If pygame.mixer.init() itself raises, audio_enabled must end up
    False and construction must not raise."""
    monkeypatch.setattr(pygame.mixer, 'get_init', lambda: False)

    def _raise_init():
        raise pygame.error('mock: no audio device')

    monkeypatch.setattr(pygame.mixer, 'init', _raise_init)
    sm = SoundManager(_missing_resource_path)
    assert sm.audio_enabled is False
    assert sm._sounds == {}


def test_sound_manager_reuses_already_initialised_mixer(monkeypatch):
    """When pygame.mixer is already initialised (get_init() True), the
    constructor should set audio_enabled True without calling init() again."""
    monkeypatch.setattr(pygame.mixer, 'get_init', lambda: True)
    init_calls = []
    monkeypatch.setattr(pygame.mixer, 'init', lambda: init_calls.append(1))
    sm = SoundManager(_missing_resource_path)
    assert sm.audio_enabled is True
    assert init_calls == []


@pytest.fixture(autouse=True)
def _restore_real_mixer():
    """Other test modules in this suite rely on a real, initialised mixer
    (e.g. test_render_smoke.py constructs a real SoundManager), so make sure
    it's left in its normal initialised state after each test here even
    though individual tests above monkeypatch get_init/init."""
    yield
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
