"""Shared pytest fixtures.

Ensures pygame runs headless (dummy SDL drivers) for every test, and
redirects platformdirs save locations to a temp dir so tests never touch
a real user's save files.
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import pytest


@pytest.fixture(autouse=True, scope="session")
def _pygame_session():
    pygame.init()
    pygame.display.set_mode((10, 10))
    pygame.font.init()
    yield
    pygame.quit()


@pytest.fixture
def isolated_save_dir(tmp_path, monkeypatch):
    """Redirect chess_game.io.get_save_dir() to a per-test tmp directory."""
    from chess_game import io as save_io

    def _fake_get_save_dir():
        d = tmp_path / "saves"
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr(save_io, "get_save_dir", _fake_get_save_dir)
    return tmp_path / "saves"
