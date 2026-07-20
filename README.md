# Python Chess

A desktop chess game built with Python and pygame, powered by the `python-chess` library for rules and move validation.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![pygame](https://img.shields.io/badge/pygame-2.5%2B-green) ![License](https://img.shields.io/badge/License-GPL--3.0-orange) [![CI](https://github.com/bottledpepsi/Python-Chess/actions/workflows/ci.yml/badge.svg)](https://github.com/bottledpepsi/Python-Chess/actions/workflows/ci.yml)

---

## Features

**Gameplay modes**
- **Direct mode launcher**: start a friend game, computer game, engine match, or preferences directly from the home screen
- **Player vs Player**: local two-player mode on the same screen with automatic board flipping between turns
- **Player vs Bot**: face an AI opponent with 10 difficulty levels

**AI difficulty**
- 10-level slider ranging from *Novice* to *Grandmaster*, with tier labels and descriptions
- The bot runs on a background thread so the UI stays responsive while it thinks
- The bot thread is **cancellable**. Restart or quit mid-think and it stops within ~2 seconds
- The search uses **alpha-beta with Principal Variation Search**, a transposition table, killer moves, a per-instance history heuristic, quiescence search, MVV-LVA move ordering, and a Polyglot opening book
- **Null-move pruning** skips subtrees where even passing the turn is too good for the opponent to tolerate — adding roughly 2–4 ply of effective depth at the higher difficulty levels, while a non-pawn-material floor keeps it out of zugzwang-prone endgames where "passing" is illegally optimistic
- Optional **Stockfish** engine as an alternative to the native bot, with an ELO slider (1320–3190) instead of the 10-level difficulty picker; an in-app downloader fetches a platform-appropriate Stockfish binary on request, no manual install needed

**Analysis mode**
- Live Stockfish evaluation while playing or reviewing, toggled on/off from an in-game button
- An eval bar with frame-rate-independent exponential easing, so the fill animates smoothly rather than snapping between updates
- Best-move arrows drawn from the current principal variation
- Cancellable, epoch-guarded analysis worker (mirrors the bot's worker design) — restarting analysis on a new position never applies a stale result from the previous one
- Gracefully degrades when Stockfish isn't installed: analysis is simply unavailable, with a one-time explanatory modal rather than a silent failure

**PvP chess clock**
- Optional time control for local two-player games, chosen on a dedicated preset screen before the game starts: **None**, **1+0**, **3+2**, **5+0**, **10+0**, or **15+10** (minutes+increment)
- Clocks for both sides shown above the board, switching automatically on each move
- Low-time warning colour and a flag-fall that ends the game on time when a clock reaches zero
- Bot games are never timed — the clock is PvP-only
- Clock state is included in save/resume: closing and reopening the app part-way through a timed game restores both players' remaining time correctly, without crediting the gap between sessions to either side

**Board & UI**
- **Drag-and-drop piece movement** — pick up a piece and drop it on a target square
- **Animated board flipping** in PvP mode — the board rotates between turns with a smooth squash-and-stretch animation so each player sits at the bottom on their move
- Smooth piece animation for moves and review stepping, starting from the cursor release position when dragging
- Move indicators (dots for empty squares, rings for captures)
- Last-move highlight, selected-square highlight, and check highlight
- Captured piece trays with material advantage display, correct on board flip
- Scrollable move history panel with click-to-review navigation
- Arrow drawing on the board (right-click drag) with configurable colour themes
- Pawn promotion overlay strip with hover tooltips, keyboard-selectable (`Q/R/B/N`)
- In-game menu overlay: save & quit, or open Preferences without leaving the game
- Persistent in-game buttons (PvP/Bot only, next to Analysis/Menu): Resign, Offer Draw, and Export PGN — Resign/Offer Draw require a Yes/Cancel confirmation, since both are irreversible
- Hand-cursor hover feedback over every clickable button, card, and toggle
- Game-over overlay with termination reason and result, plus one-click **Rematch** (same colour/difficulty/time control, no need to go back through the pickers) and **Review Game**

**Customisation**
- Four board colour themes: Green, Blue, Red, and a colour-blind-safe option (deuteranopia-friendly)
- Five arrow colour themes: Blue, Yellow, Green, White, Black
- Redesigned preferences screen with card-based layout, high-contrast selected outlines, and pill-style reduced-motion / sound-effects toggles
- Preferences persist between sessions

**Review mode**
- Step through any game with the arrow keys or by clicking moves in the history panel
- Animated stepping forwards and backwards through the position tree

**Sound**
- Move and capture sound effects via pygame mixer
- Audio cues for check, checkmate, and draw using the existing sound assets
- Mute toggle in Preferences (In-game menu → Preferences, or Main Menu → Preferences)

**Save & resume**
- Games (PvP and Bot) are auto-saved and can be resumed on next launch
- Saves live in a per-user app-data directory and survive reboots
- Atomic, versioned JSON saves. A crash mid-write or a corrupt file can never silently erase your game
- Resuming a PvP game orients the board for whichever side is to move

**PGN export**
- Export the current game to a standard `.pgn` file at any time from the in-game menu
- Exports are timestamped and land in their own `pgn/` subdirectory of the save dir, so you can keep more than one
- Headers include `White`, `Black`, `Date`, `Result`, and (for bot games) a non-standard `Difficulty` tag with the level — PGN readers that don't recognise the extra tag simply ignore it
- Moves are re-rendered to SAN by `chess.pgn`'s own writer, so the export doesn't depend on two independent SAN implementations staying in agreement

**Accessibility**
- Full keyboard navigation: `Tab`/`Shift+Tab` to move focus, `Enter`/`Space` to activate, `Esc` to back out
- WCAG-AA-compliant text contrast across all UI
- F11 fullscreen toggle
- Reduced-motion preference for piece animations, board-flip animation, and the game-over fade
- Popup hover suppression — hover highlighting is disabled on elements behind modal overlays so they don't flicker as the cursor passes over them

---

## Requirements

- `python >= 3.10.0`
- `pygame >= 2.5.0`
- `chess >= 1.10.0`
- `platformdirs >= 4.2`

---

## Installation

### Option A: prebuilt binary (recommended)

Download the latest build for your platform from the [Releases page](https://github.com/bottledpepsi/Python-Chess/releases). Every release automatically produces standalone binaries for Linux, macOS, and Windows via GitHub Actions — no Python installation required.

- **Linux:** extract the `.tar.xz` and run `./PythonChess`
- **macOS:** see [Running the app on macOS](#running-the-app-on-macos) below for the one-time Gatekeeper bypass
- **Windows:** unzip and double-click `PythonChess.exe`

### Option B: from source

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
pyinstaller --onefile --add-data "data:data" --name "PythonChess" main.py
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
├── .github/workflows/
│   ├── ci.yml                   # ruff + mypy + pytest on push/PR (Linux, macOS, Windows)
│   └── release.yml              # Builds + uploads binaries on every tag push
└── chess_game/                  # The game itself
    ├── app.py                   # main() loop + state machine entry + flip/fullscreen + PGN export wiring
    ├── input_handler.py         # InputHandler: full event-dispatch tree, per-screen handlers, drag tracking
    ├── state.py                 # GameState (Enum) + transition table
    ├── game.py                  # @dataclass Game, owns all in-game state + flip animation + clock
    ├── clock.py                 # PvP chess clock: time controls, switch/tick/flag-fall, save/restore
    ├── io.py                    # Atomic, versioned JSON saves + preferences + export_pgn()
    ├── log.py                   # Rotating file logger
    ├── bot_worker.py            # Cancellable, epoch-guarded native bot worker
    ├── stockfish_bot_worker.py  # Cancellable, epoch-guarded Stockfish bot worker (ELO slider)
    ├── stockfish_download.py    # In-app Stockfish downloader, platform detection, path-traversal-safe extraction
    ├── analysis.py              # Cancellable, epoch-guarded live Stockfish analysis (eval bar, best-move arrows)
    ├── theme.py                 # Colours, fonts, board/arrow themes (AA-checked)
    ├── widgets.py                # Button, Slider (keyboard-navigable)
    ├── anim.py                  # dt-scaled animation + review state + FlipState
    ├── layout.py                # Pure coordinate math (unit-tested)
    ├── assets.py                # Image loading
    ├── sound.py                 # Sound manager
    ├── review.py                # Review-mode state
    ├── adapter.py               # Wraps python-chess Board; tracks captures, SAN history
    ├── engine/
    │   ├── bot.py               # Alpha-beta + PVS + null-move pruning + quiescence + TT + per-instance history + book
    │   └── piece_tables.py
    └── render/
        ├── board.py             # draw_board (cached surface) + label clearing on flip
        ├── clocks.py            # PvP clock rendering (active/low-time/flagged states)
        ├── trays.py             # Captured-piece trays
        ├── history.py           # Move-history panel
        ├── overlays.py          # Promotion, winner fade, modals
        ├── menus.py             # Main menu, opponent picker, color/time-control pick, difficulty, preferences, in-game overlay (Save & Quit / Preferences)
        └── arrows.py            # Right-click analysis arrows + best-move PV arrows
```

---

## Controls

| Action | Input |
|--------|-------|
| Select / move piece | Left-click (click-to-select then click-to-move) |
| Drag piece to move | Left-click and drag past 5px threshold, release on target |
| Draw arrow | Right-click drag |
| Clear arrows | Left-click on the board |
| Step review backward | `←` arrow key |
| Step review forward | `→` arrow key |
| Open in-game menu | `≡` Menu button (top-right of board) |
| Export current game to PGN | In-game menu → **Export PGN** |
| Open Preferences mid-game | In-game menu → **Preferences** (Back returns to the game, not the main menu) |
| Offer a draw | In-game menu → **Offer Draw** → confirm |
| Resign | In-game menu → **Resign** → confirm |
| Rematch with the same settings | Game-over overlay → **Rematch** |
| Review the game just played | Game-over overlay → **Review Game** |
| Toggle fullscreen | `F11` |
| Cancel / back out | `Esc` |
| Navigate UI focus | `Tab` / `Shift+Tab` |
| Activate focused item | `Enter` / `Space` |
| Choose promotion piece | `Q` / `R` / `B` / `N` |

---

## Architecture notes

The game is structured as a `chess_game/` package, with `main.py` as a thin launcher guarded by `if __name__ == "__main__"`. A `@dataclass Game` owns all in-game state (adapter, animation, review, winner, bot worker, flip state, optional `Clock`). There are no module-level mutable globals. Rendering functions in `chess_game/render/` are pure: they take a surface and the `Game`, and write nothing back. `App` (`chess_game/app.py`) owns bootstrap, the frame loop, and rendering; `InputHandler` (`chess_game/input_handler.py`) owns the full event-dispatch tree — translating pygame events into `Game`/`App` state transitions — and is constructed once per `App` and held for its lifetime rather than owning its own copy of the transient UI state that rendering also reads each frame.

The `ChessAdapter` class (in `chess_game/adapter.py`) wraps `chess.Board` and exposes a clean interface (turn, legal moves, SAN history, captured pieces), so the UI never touches `python-chess` internals directly.

The bot runs in a background `BotWorker` thread that is **cancellable** (`threading.Event` abort) and **epoch-guarded**. Restarting mid-think joins the prior thread, and any stale result is dropped by epoch mismatch rather than applied to the new game. The transposition table and history heuristic are only cleared after the worker has joined. `StockfishBotWorker` follows the same cancellable, epoch-guarded shape for the optional Stockfish backend.

The search itself is alpha-beta with Principal Variation Search, backed by a transposition table (exact / lower / upper bound entries), a two-slot-per-depth killer-move heuristic, a **per-instance** history heuristic (so two `ChessBot` objects never share move-ordering state), MVV-LVA capture ordering, quiescence search at the leaves, and **null-move pruning** gated by a non-pawn-material floor to avoid zugzwang. A Polyglot opening book (`data/book/gm2001.bin`) supplies weighted-random opening moves until the human deviates from the book.

Live analysis (`chess_game/analysis.py`) mirrors `BotWorker`'s cancellable, epoch-guarded design, but python-chess's blocking `analyse()` call has no cooperative-cancel hook — so `AnalysisWorker` instead opens the non-blocking `analysis()` stream and pumps it in a loop, checking the abort signal between iterations. The eval bar's fill ratio is derived from the centipawn score via a logistic curve and eased exponentially frame-to-frame rather than snapping, so rapid evaluation swings read as motion instead of flicker.

The PvP `Clock` (`chess_game/clock.py`) is ticked once per frame from the main loop rather than running on its own thread, deliberately — it shares the same frame timeline as the move-slide and board-flip animations, and a separate timer thread would reintroduce exactly the kind of race those animations' state machines were built to avoid. Clock state (remaining time per side, the active side, and the configured time control) round-trips through save/resume, with elapsed real time between sessions excluded so reopening a save doesn't silently burn a player's clock.

Saves are written as versioned JSON to a per-user app-data directory (`platformdirs.user_data_dir`) via an atomic `tempfile` + `os.replace` write. A corrupt save raises a user-facing error modal rather than silently starting a fresh game. PGN exports are written separately into a `pgn/` subdirectory of the same app-data dir, one timestamped file per export.

---

### Logging

Diagnostics go to a rotating log file in `platformdirs.user_log_dir("python-chess")` (1 MB, 3 backups). Under a PyInstaller `--windowed` build where stdout is discarded, the log file is the only place to find errors. Check there first if something goes wrong.

---

### Development

```bash
pip install -e ".[dev]"          # pytest, pytest-cov, ruff, mypy, pyinstaller
ruff check .                     # lint
mypy chess_game                  # type-check
pytest --cov=chess_game          # tests (275 passing, 84% overall coverage)
```

A GitHub Actions workflow (`.github/workflows/ci.yml`) runs ruff + mypy + pytest on every push and pull request for Linux, macOS, and Windows, across Python 3.10, 3.11, 3.12, and 3.13.

A second workflow (`.github/workflows/release.yml`) triggers on every `v*` tag push, runs the test suite, builds standalone PyInstaller binaries for all three platforms, and uploads them to the GitHub release — so every release ships with ready-to-run downloads.

---


### Running the app on macOS

Because I'm not paying Apple $99/year for a developer certificate, macOS will throw a security warning on launch. Here's how to bypass it.

**Option A: System Settings (recommended)**

1. Double-click **PythonChess.app**. macOS will say it "cannot be opened because it is from an unidentified developer." Click **OK** to dismiss.
2. Open **System Settings → Privacy & Security** and scroll down to the Security section. You'll see a message saying the app was blocked. Click **Open Anyway**.
3. A final confirmation dialog will appear. Click **Open** and the app will launch. macOS remembers this choice, so you only need to do this once.

**Option B: Terminal**

Open Terminal and run:
```bash
xattr -cr PythonChess.app
```
Then double-click the app as normal. This strips the quarantine flag macOS sets on downloaded files.

---

### Finding the log file

If something goes wrong, the rotating log is at:
- **Linux:** `~/.local/state/python-chess/log/python-chess.log` (or `$XDG_STATE_HOME`)
- **macOS:** `~/Library/Logs/python-chess/python-chess.log`
- **Windows:** `%LOCALAPPDATA%\python-chess\Logs\python-chess.log`

### Finding exported PGN files

Exported games land in a `pgn/` subdirectory of the save dir:
- **Linux:** `~/.local/share/python-chess/pgn/`
- **macOS:** `~/Library/Application Support/python-chess/pgn/`
- **Windows:** `%APPDATA%\python-chess\pgn\`

Each export is named `python-chess_YYYYMMDD_HHMMSS.pgn`, so you can keep more than one without overwriting.

---

## License

GNU General Public License v3.0. See [LICENSE](LICENSE) for details.
