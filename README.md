# Python Chess

A feature-rich desktop chess game built with Python and pygame, powered by the `python-chess` library for rules and move validation.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![pygame](https://img.shields.io/badge/pygame-2.0%2B-green) ![License](https://img.shields.io/badge/License-GPL--3.0-orange)

---

## Features

**Gameplay modes**
- **Player vs Player** — local two-player mode on the same screen
- **Player vs Bot** — face an AI opponent with 10 difficulty levels

**AI difficulty**
- 10-level slider ranging from *Novice* to *Grandmaster*, with tier labels and descriptions
- The bot runs on a background thread so the UI stays responsive while it thinks

**Board & UI**
- Smooth piece animation for moves and review stepping
- Move indicators (dots for empty squares, rings for captures)
- Last-move highlight, selected-square highlight, and check highlight
- Captured piece trays with material advantage display
- Scrollable move history panel with click-to-review navigation
- Arrow drawing on the board (right-click drag) with configurable colour themes
- Pawn promotion overlay strip with hover tooltips
- In-game menu overlay (save, quit, return to main menu)
- Game-over overlay with termination reason and result

**Customisation**
- Three board colour themes: Green, Blue, Red
- Five arrow colour themes: Blue, Yellow, Green, White, Black
- Preferences persist between sessions

**Review mode**
- Step through any game with the arrow keys or by clicking moves in the history panel
- Animated stepping forwards and backwards through the position tree

**Sound**
- Move and capture sound effects via pygame mixer

**Save & resume**
- Games (PvP and Bot) are auto-saved and can be resumed on next launch

---

## Requirements

- Python 3.10+
- `pygame >= 2.0.0`
- `chess >= 1.9.0`

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
PyInstaller --onefile --icon=icon.ico --add-data "data;data" --name "PythonChess" main.py
```

---

## Project Structure

```
Python-Chess/
├── main.py                  # Entry point — game loop, rendering, UI state machine
├── requirements.txt
├── icon.ico
└── data/
    ├── classes/
    │   └── ChessAdapter.py  # Wraps python-chess Board; tracks captures, SAN history
    ├── engine/
    │   └── bot.py           # Alpha-beta bot with quiescence search & transposition table
    ├── imgs/                # Piece PNG assets (w_king.png, b_pawn.png, …)
    └── sounds/              # move.ogg, capture.ogg
```

---

## Controls

| Action | Input |
|--------|-------|
| Select / move piece | Left-click |
| Draw arrow | Right-click drag |
| Clear arrows | Left-click (no drag) |
| Step review backward | ← arrow key |
| Step review forward | → arrow key |
| Open in-game menu | ≡ Menu button (bottom tray) |

---

## Architecture notes

`main.py` is a single-file with states: `menu → color_pick → difficulty → preferences → pvp / bot`. All rendering is done with pygame surfaces; the board is drawn onto a dedicated `board_surf` and blitted each frame. The `ChessAdapter` class wraps `chess.Board` and exposes a clean interface (turn, legal moves, SAN history, captured pieces) so the UI never touches `python-chess` internals directly. The bot runs in a `daemon` thread and communicates its result back via a shared variable protected by a `threading.Lock`.

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.
