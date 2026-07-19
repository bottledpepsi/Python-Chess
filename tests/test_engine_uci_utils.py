"""Tests for chess_game.engine.uci_utils.popen_uci — the consolidated
helper that replaces the byte-for-byte-duplicated _popen_uci previously
defined separately in analysis.py and stockfish_bot_worker.py.

These focus on the consolidation itself: both call sites now share one
implementation, and its Windows-console-suppression behavior matches what
both originals did. The existing test_analysis.py / test_stockfish_bot_worker.py
suites already cover the higher-level worker behavior end-to-end (via
monkeypatched chess.engine.SimpleEngine.popen_uci) and continue to pass
unmodified, which is itself a regression check that the consolidation
didn't change behavior.
"""
from __future__ import annotations

import subprocess
import sys

import chess.engine
import pytest

from chess_game.engine import uci_utils


def test_analysis_and_stockfish_bot_worker_share_the_same_helper():
    """The whole point of consolidating: both modules must now import the
    exact same function object, not their own copies."""
    from chess_game import analysis, stockfish_bot_worker

    assert analysis._popen_uci is uci_utils.popen_uci
    assert stockfish_bot_worker._popen_uci is uci_utils.popen_uci


def test_popen_uci_passes_creationflags_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(uci_utils, "_WINDOWS_CREATIONFLAGS", 0x08000000)

    captured = {}

    def _fake_popen_uci(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return "fake-engine"

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))

    result = uci_utils.popen_uci("/path/to/stockfish")
    assert result == "fake-engine"
    assert captured["command"] == "/path/to/stockfish"
    assert captured["kwargs"] == {"creationflags": 0x08000000}


def test_popen_uci_omits_creationflags_off_windows(monkeypatch):
    monkeypatch.setattr(uci_utils, "_WINDOWS_CREATIONFLAGS", None)

    captured = {}

    def _fake_popen_uci(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return "fake-engine"

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", staticmethod(_fake_popen_uci))

    result = uci_utils.popen_uci("/path/to/stockfish")
    assert result == "fake-engine"
    assert captured["kwargs"] == {}


def test_module_level_creationflags_is_none_on_non_windows():
    """On the actual platform running this test suite (Linux/macOS in
    CI), CREATE_NO_WINDOW doesn't exist and the module must not raise
    just from being imported."""
    if sys.platform == "win32":
        pytest.skip("this checks the non-Windows branch specifically")
    assert uci_utils._WINDOWS_CREATIONFLAGS is None
    assert not hasattr(subprocess, "CREATE_NO_WINDOW")
