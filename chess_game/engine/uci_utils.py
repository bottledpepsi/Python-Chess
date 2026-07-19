"""Shared UCI subprocess helpers for anything that spawns an external
engine (Stockfish or another UCI-speaking binary).

_popen_uci was previously duplicated verbatim in analysis.py and
stockfish_bot_worker.py. Both now import it from here; the engine match
framework (chess_game.engine.match) is a third consumer, which is what
made the duplication worth consolidating rather than tripling.
"""
from __future__ import annotations

import subprocess
import sys

import chess.engine

# On Windows, suppress the extra console window a frozen (PyInstaller
# --windowed) build would otherwise pop up when spawning a UCI subprocess,
# since there's no parent console for it to inherit. getattr() avoids an
# attribute error on non-Windows platforms, where this is simply unused
# (CREATE_NO_WINDOW doesn't exist there).
_WINDOWS_CREATIONFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else None


def popen_uci(engine_path: str) -> chess.engine.SimpleEngine:
    """popen_uci wrapper that suppresses the blank console window a frozen
    Windows build would otherwise spawn alongside a UCI engine process."""
    if _WINDOWS_CREATIONFLAGS is not None:
        return chess.engine.SimpleEngine.popen_uci(
            engine_path, creationflags=_WINDOWS_CREATIONFLAGS
        )
    return chess.engine.SimpleEngine.popen_uci(engine_path)
