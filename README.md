# Python Chess

A desktop chess game built with Python and pygame, powered by the `python-chess` library for rules and move validation.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![pygame](https://img.shields.io/badge/pygame-2.5%2B-green) ![License](https://img.shields.io/badge/License-GPL--3.0-orange) ![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)

---

## Features

**Gameplay modes**
- **Player vs Player**: local two-player mode on the same screen
- **Player vs Bot**: face an AI opponent with 10 difficulty levels

**AI difficulty**
- 10-level slider ranging from *Novice* to *Grandmaster*, with tier labels and descriptions
- The bot runs on a background thread so the UI stays responsive while it thinks
- The bot thread is **cancellable**. Restart or quit mid-think and it stops within ~2 seconds

**Board & UI**
- Smooth piece animation for moves and review stepping
- Move indicators (dots for empty squares, rings for captures)
- Last-move highlight, selected-square highlight, and check highlight
- Captured piece trays with material advantage display, correct on board flip
- Scrollable move history panel with click-to-review navigation
- Arrow drawing on the board (right-click drag) with configurable colour themes
- Pawn promotion overlay strip with hover tooltips, keyboard-selectable (`Q/R/B/N`)
- In-game menu overlay (save, quit, return to main menu)
- Game-over overlay with termination reason and result

**Customisation**
- Three board colour themes: Green, Blue, Red
- A colour-blind-safe default theme (deuteranopia-friendly)
- Five arrow colour themes: Blue, Yellow, Green, White, Black
- Preferences persist between sessions

**Review mode**
- Step through any game with the arrow keys or by clicking moves in the history panel
- Animated stepping forwards and backwards through the position tree

**Sound**
- Move and capture sound effects via pygame mixer
- Audio cues for check, checkmate, and draw using the existing sound assets

**Save & resume**
- Games (PvP and Bot) are auto-saved and can be resumed on next launch
- Saves live in a per-user app-data directory and survive reboots
- Atomic, versioned JSON saves. A crash mid-write or a corrupt file can never silently erase your game

**Accessibility**
- Full keyboard navigation: `Tab`/`Shift+Tab` to move focus, `Enter`/`Space` to activate, `Esc` to back out
- WCAG-AA-compliant text contrast across all UI
- Resizable window with integer-scaled rendering and vsync
- Reduced-motion preference for piece animations and the game-over fade

---

## Requirements

- `python >= 3.10.0`
- `pygame >= 2.5.0`
- `chess >= 1.10.0`
- `platformdirs >= 4.2`

---

## Installation

```bash
# Clone the repository
git clone https://github.com/bottledpepsi/Python-Chess.git
cd Python-Chess

# Install dependencies
pip install -r requirements.txt

# Run the game
python main.py
```

---

## Building a Standalone Executable

To compile the game into a single executable using [PyInstaller](https://pyinstaller.org/):

```bash
pip install pyinstaller
```

**Linux:**
```bash
PyInstaller --onefile --icon=icon.ico --add-data "data:data" --name "PythonChess" main.py
```

**macOS:**
```bash
PyInstaller --onedir --windowed --icon=icon.ico --add-data "data:data" --name "PythonChess" main.py
```

**Windows:**
```bash
PyInstaller --onefile --windowed --icon=icon.ico --add-data "data;data" --name "PythonChess" main.py
```

---

## Project Structure

```
Python-Chess/
├── main.py                      # Thin launcher
├── pyproject.toml               # Project metadata, pinned deps, ruff/mypy/pytest config
├── requirements.txt             # Pinned runtime deps
├── icon.ico
├── data/                        # Assets only (no Python code)
│   ├── imgs/                    # Piece PNG assets
│   ├── sounds/                  # move.ogg, capture.ogg
│   └── book/gm2001.bin          # Polyglot opening book
└── chess_game/                  # The game itself
    ├── app.py                   # main() loop + state machine entry
    ├── state.py                 # GameState (Enum) + transition table
    ├── game.py                  # @dataclass Game, owns all in-game state
    ├── io.py                    # Atomic, versioned JSON saves + preferences
    ├── log.py                   # Rotating file logger
    ├── bot_worker.py             # Cancellable, epoch-guarded bot worker
    ├── theme.py                  # Colours, fonts, board/arrow themes (AA-checked)
    ├── widgets.py                # Button, Slider (keyboard-navigable)
    ├── anim.py                  # dt-scaled animation + review state
    ├── layout.py                # Pure coordinate math (unit-tested)
    ├── assets.py                # Image loading
    ├── sound.py                 # Sound manager
    ├── review.py                # Review-mode state
    ├── adapter.py               # Wraps python-chess Board; tracks captures, SAN history
    ├── engine/
    │   ├── bot.py               # Alpha-beta bot with quiescence, TT, and abort support
    │   └── piece_tables.py
    └── render/
        ├── board.py             # draw_board (cached surface)
        ├── trays.py             # Captured-piece trays
        ├── history.py           # Move-history panel
        ├── overlays.py          # Promotion, winner fade, modals
        ├── menus.py             # Main menu, color pick, difficulty, preferences
        └── arrows.py            # Right-click analysis arrows
```

---

## Controls

| Action | Input |
|--------|-------|
| Select / move piece | Left-click |
| Draw arrow | Right-click drag |
| Clear arrows | Left-click on the board |
| Step review backward | `←` arrow key |
| Step review forward | `→` arrow key |
| Open in-game menu | `≡` Menu button (bottom tray) |
| Cancel / back out | `Esc` |
| Navigate UI focus | `Tab` / `Shift+Tab` |
| Activate focused item | `Enter` / `Space` |
| Choose promotion piece | `Q` / `R` / `B` / `N` |

---

## Architecture notes

The game is structured as a `chess_game/` package, with `main.py` as a thin launcher guarded by `if __name__ == "__main__"`. A `@dataclass Game` owns all in-game state (adapter, animation, review, winner, bot worker). There are no module-level mutable globals. Rendering functions in `chess_game/render/` are pure: they take a surface and the `Game`, and write nothing back.

The `ChessAdapter` class (in `chess_game/adapter.py`) wraps `chess.Board` and exposes a clean interface (turn, legal moves, SAN history, captured pieces), so the UI never touches `python-chess` internals directly.

The bot runs in a background `BotWorker` thread that is **cancellable** (`threading.Event` abort) and **epoch-guarded**. Restarting mid-think joins the prior thread, and any stale result is dropped by epoch mismatch rather than applied to the new game. The transposition table is only cleared after the worker has joined.

Saves are written as versioned JSON to a per-user app-data directory (`platformdirs.user_data_dir`) via an atomic `tempfile` + `os.replace` write. A corrupt save raises a user-facing error modal rather than silently starting a fresh game.

### Logging

Diagnostics go to a rotating log file in `platformdirs.user_log_dir("python-chess")` (1 MB, 3 backups). Under a PyInstaller `--windowed` build where stdout is discarded, the log file is the only place to find errors. Check there first if something goes wrong.

### Development

```bash
pip install -e ".[dev]"          # pytest, pytest-cov, ruff, mypy, pyinstaller
ruff check .                     # lint
mypy chess_game                  # type-check
pytest --cov=chess_game          # tests (≥70% coverage on pure-logic modules)
```

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs ruff + mypy + pytest on every push and pull request for Linux, macOS, and Windows.

---

## License

GNU General Public License v3.0. See [LICENSE](LICENSE) for details.
