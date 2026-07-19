"""Headless, scriptable engine-vs-engine match framework.

Nothing in this module imports pygame or requires a display — it is safe
to import and run from a plain script, a test, or a future menu action
without a pygame event loop (verified: `python -c "import chess_game.engine.match"`
never touches pygame.display).

Building blocks
---------------
Every match participant is described by an EngineSpec (native ChessBot at
a difficulty level, or Stockfish at an ELO), turned into a uniform
_EnginePlayer that exposes a single synchronous call:

    player.pick_move(board, timeout_s) -> chess.Move | None

None means "this side failed to produce a legal move in time" (timeout,
crash, or no legal moves) and the game is scored as a forfeit for that
side rather than hanging the batch.

This deliberately does not reuse BotWorker / StockfishBotWorker: those are
async, poll-based UI workers (start()/take() across frames). A headless
batch runner needs a blocking call-and-return per move instead, so this
module talks to ChessBot and chess.engine.SimpleEngine directly, reusing
StockfishDownloader for provisioning and the shared uci_utils.popen_uci
helper for spawning — the same pieces the UI workers use under the hood.

Public entry points (menu-callable; no board/UI state required):
    play_game(white, black, ...)   -> GameResult
    run_batch(engine_a, engine_b, n_games, ...) -> BatchResult
    run_gauntlet(primary, opponents, games_per_opponent, ...) -> GauntletResult
    run_tournament(configs, games_per_pairing, ...) -> TournamentResult
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from datetime import date

import chess
import chess.engine
import chess.pgn

from chess_game.engine.bot import ChessBot, SearchAborted
from chess_game.engine.uci_utils import popen_uci
from chess_game.log import get_logger

_LOGGER = get_logger()

DEFAULT_PER_MOVE_TIMEOUT_S = 10.0
DEFAULT_PER_GAME_TIMEOUT_S = 300.0


# ── Engine configuration ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class EngineSpec:
    """Describes one match participant, before it's turned into a live
    engine process/instance.

    kind="native": a ChessBot at `difficulty` (1-10, see
      engine.bot.DIFFICULTY_CONFIG), optionally with a book_path.
    kind="stockfish": an external UCI engine at `elo` (clamped to
      StockfishBotWorker's [MIN_ELO, MAX_ELO] the same way live play is),
      using `engine_path` ("" = rely on PATH, matching the rest of the app).
    """

    kind: str  # "native" | "stockfish"
    name: str = ""
    difficulty: int = 10
    book_path: str | None = None
    elo: int = 1500
    engine_path: str = ""
    movetime_ms: int = 1000

    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.kind == "native":
            return f"Native(d{self.difficulty})"
        return f"Stockfish({self.elo})"


# ── Uniform synchronous player interface ─────────────────────────────────────


class _EnginePlayer:
    """Base interface: pick_move() blocks until a move is ready, the
    timeout elapses, or the game is over. close() releases any resources
    (subprocess, thread) and must be safe to call more than once."""

    def pick_move(self, board: chess.Board, timeout_s: float) -> chess.Move | None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    def stats(self) -> dict:
        """Best-effort per-engine stats collected across the game so far
        (e.g. average move time). Node counts are only available for the
        native engine; Stockfish via SimpleEngine.play() doesn't expose
        them without switching to analyse(), which is out of scope here."""
        return {}


class _NativePlayer(_EnginePlayer):
    """Wraps a single ChessBot instance for the lifetime of one game, so
    its transposition table and history heuristic persist move-to-move
    exactly as they do in live UI play (BotWorker also reuses one
    ChessBot across a game). A per-move timeout is enforced by running
    get_move() in a background thread and setting its cooperative abort
    Event if the timeout elapses — the same SearchAborted mechanism
    BotWorker relies on for cancellation."""

    def __init__(self, spec: EngineSpec) -> None:
        self._spec = spec
        self._bot = ChessBot(max_depth=spec.difficulty, book_path=spec.book_path)
        self._move_times: list[float] = []

    def pick_move(self, board: chess.Board, timeout_s: float) -> chess.Move | None:
        abort = threading.Event()
        result: dict[str, chess.Move | None] = {"move": None}
        # Never hand the live, shared board to a background thread: the
        # search mutates it in place via push()/pop() at every node, so if
        # a timeout lets this call return while the thread is still
        # winding down, the caller's next pick_move() (on the same board,
        # from the main thread) would race with it. BotWorker and
        # StockfishBotWorker both copy for exactly this reason; match play
        # is no different just because it's synchronous from the caller's
        # point of view.
        board_copy = board.copy()
        turn_color = "white" if board.turn == chess.WHITE else "black"

        def _run() -> None:
            try:
                result["move"] = self._bot.get_move(
                    board_copy, turn_color, self._spec.difficulty, abort=abort,
                )
            except SearchAborted:
                result["move"] = None

        start = time.time()
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout_s)
        elapsed = time.time() - start

        if thread.is_alive():
            # Timed out: signal abort so the search thread winds down on
            # its own (SearchAborted is checked at every search node), but
            # don't block the caller waiting for that — a daemon thread
            # left running is abandoned exactly the way BotWorker already

            # tolerates a cancelled-but-not-yet-joined search (see
            # stockfish_bot_worker.py's cancel() docstring for the same
            # "cancel means stale, not literally killed" contract).
            abort.set()
            _LOGGER.warning(
                "Native engine (%s) exceeded per-move timeout %.1fs — forfeiting move",
                self._spec.display_name(), timeout_s,
            )
            return None

        self._move_times.append(elapsed)
        return result["move"]

    def close(self) -> None:
        pass  # no subprocess/socket to release

    def stats(self) -> dict:
        if not self._move_times:
            return {"avg_move_time_s": None, "moves": 0}
        return {
            "avg_move_time_s": sum(self._move_times) / len(self._move_times),
            "moves": len(self._move_times),
        }


class _StockfishPlayer(_EnginePlayer):
    """Wraps chess.engine.SimpleEngine for one game. UCI_LimitStrength /
    UCI_Elo are configured once at construction (mirrors
    StockfishBotWorker._configure_strength). The per-move timeout is
    enforced the same way StockfishBotWorker bounds live play: via
    chess.engine.Limit(time=...), which is authoritative for a
    UCI-compliant engine rather than needing a second thread-based abort."""

    def __init__(self, spec: EngineSpec) -> None:
        self._spec = spec
        self._move_times: list[float] = []
        self.engine_available = True
        self.missing_reason = ""
        self._engine: chess.engine.SimpleEngine | None = None
        try:
            self._engine = popen_uci(spec.engine_path or "stockfish")
        except TimeoutError as exc:
            self.engine_available = False
            self.missing_reason = (
                f"Timed out waiting for a UCI response from "
                f"'{spec.engine_path or 'stockfish'}'"
            )
            _LOGGER.warning("Stockfish handshake timed out: %s", exc)
            return
        except OSError as exc:
            self.engine_available = False
            self.missing_reason = str(exc) or "Could not launch Stockfish"
            _LOGGER.warning("Stockfish unavailable: %s", exc)
            return
        except chess.engine.EngineError as exc:
            self.engine_available = False
            self.missing_reason = str(exc) or "Stockfish did not initialise correctly"
            _LOGGER.warning("Stockfish did not initialise: %s", exc)
            return

        elo = max(1320, min(3190, int(spec.elo)))
        self._engine.configure({"UCI_LimitStrength": True, "UCI_Elo": elo})

    def pick_move(self, board: chess.Board, timeout_s: float) -> chess.Move | None:
        if not self.engine_available or self._engine is None:
            return None
        start = time.time()
        try:
            limit = chess.engine.Limit(time=min(self._spec.movetime_ms / 1000.0, timeout_s))
            play_result = self._engine.play(board, limit)
        except chess.engine.EngineTerminatedError:
            _LOGGER.warning("Stockfish process terminated mid-game (%s)", self._spec.display_name())
            self.engine_available = False
            return None
        except chess.engine.EngineError as exc:
            _LOGGER.warning("Stockfish play() error: %s", exc)
            return None
        self._move_times.append(time.time() - start)
        return play_result.move

    def close(self) -> None:
        if self._engine is not None:
            try:
                self._engine.quit()
            except chess.engine.EngineError:
                pass
            self._engine = None

    def stats(self) -> dict:
        if not self._move_times:
            return {"avg_move_time_s": None, "moves": 0}
        return {
            "avg_move_time_s": sum(self._move_times) / len(self._move_times),
            "moves": len(self._move_times),
        }


def _make_player(spec: EngineSpec) -> _EnginePlayer:
    if spec.kind == "native":
        return _NativePlayer(spec)
    if spec.kind == "stockfish":
        return _StockfishPlayer(spec)
    raise ValueError(f"Unknown EngineSpec.kind: {spec.kind!r}")


# ── Results ───────────────────────────────────────────────────────────────────


@dataclass
class GameResult:
    white: str                      # display name of the white engine
    black: str                      # display name of the black engine
    moves: list[str] = field(default_factory=list)   # UCI strings
    result: str = "*"                # "1-0" / "0-1" / "1/2-1/2" / "*"
    termination: str = "unknown"     # e.g. "checkmate", "timeout", "forfeit-white", ...
    pgn: str = ""
    white_stats: dict = field(default_factory=dict)
    black_stats: dict = field(default_factory=dict)
    aborted: bool = False


def _game_pgn(board: chess.Board, white_name: str, black_name: str) -> str:
    """Build a standard PGN for a headless match game, reusing chess.pgn
    the same way io.export_pgn() does rather than writing a second SAN
    writer. Kept local to this module (not routed through io.export_pgn)
    since match games have no ChessAdapter — there's no UI-facing board
    wrapper to construct just to satisfy that function's signature.

    Uses Game.from_board() rather than replaying board.move_stack against
    a fresh chess.pgn.Game() (which always starts from the standard
    position): a batch/gauntlet run may use a non-standard opening_fen,
    and from_board() correctly emits the [SetUp]/[FEN] header pair and
    reconstructs the move tree from whatever position the game actually
    started at.
    """
    game = chess.pgn.Game.from_board(board)
    game.headers["White"] = white_name
    game.headers["Black"] = black_name
    game.headers["Date"] = date.today().strftime("%Y.%m.%d")
    game.headers["Result"] = board.result(claim_draw=True)
    game.headers["Event"] = "Engine Match Framework"
    return str(game)


def play_game(
    white: EngineSpec,
    black: EngineSpec,
    opening_fen: str | None = None,
    per_move_timeout_s: float = DEFAULT_PER_MOVE_TIMEOUT_S,
    per_game_timeout_s: float = DEFAULT_PER_GAME_TIMEOUT_S,
) -> GameResult:
    """Play one headless game between two configured engines and return
    the full result: move list, PGN, result, termination reason, and
    per-move timing for each side.

    A per-move timeout and an overall per-game wall-clock timeout both
    apply, so a hung engine (native or Stockfish) can never hang a batch
    run indefinitely — see _NativePlayer/_StockfishPlayer for how each
    engine kind is bounded.
    """
    board = chess.Board(fen=opening_fen) if opening_fen else chess.Board()
    white_player = _make_player(white)
    black_player = _make_player(black)

    result = GameResult(white=white.display_name(), black=black.display_name())
    game_start = time.time()

    try:
        while not board.is_game_over(claim_draw=True):
            if time.time() - game_start > per_game_timeout_s:
                result.termination = "game-timeout"
                result.aborted = True
                break

            side_to_move = white_player if board.turn == chess.WHITE else black_player
            move = side_to_move.pick_move(board, per_move_timeout_s)

            if move is None:
                result.termination = "forfeit-" + ("white" if board.turn == chess.WHITE else "black")
                result.result = "0-1" if board.turn == chess.WHITE else "1-0"
                result.aborted = True
                break

            if move not in board.legal_moves:
                # Defensive: a conforming engine should never do this, but
                # a match runner must not trust external processes blindly.
                _LOGGER.error(
                    "Engine %s returned an illegal move %s in position %s",
                    (white if board.turn == chess.WHITE else black).display_name(),
                    move.uci(), board.fen(),
                )
                result.termination = "illegal-move-" + ("white" if board.turn == chess.WHITE else "black")
                result.result = "0-1" if board.turn == chess.WHITE else "1-0"
                result.aborted = True
                break

            board.push(move)
            result.moves.append(move.uci())
        else:
            outcome = board.outcome(claim_draw=True)
            if outcome is not None:
                result.termination = outcome.termination.name.lower()
                result.result = outcome.result()
            else:
                result.termination = "unknown"
                result.result = board.result(claim_draw=True)
    finally:
        result.pgn = _game_pgn(board, result.white, result.black)
        result.white_stats = white_player.stats()
        result.black_stats = black_player.stats()
        white_player.close()
        black_player.close()

    return result


# ── Batch ─────────────────────────────────────────────────────────────────────


@dataclass
class BatchResult:
    engine_a: str
    engine_b: str
    games: list[GameResult] = field(default_factory=list)
    a_wins: int = 0
    b_wins: int = 0
    draws: int = 0

    @property
    def a_score(self) -> float:
        """engine_a's score in standard chess-tournament points (win=1,
        draw=0.5, loss=0)."""
        return self.a_wins + 0.5 * self.draws

    @property
    def total_games(self) -> int:
        return len(self.games)


def run_batch(
    engine_a: EngineSpec,
    engine_b: EngineSpec,
    n_games: int,
    openings: list[str] | None = None,
    alternate_colors: bool = True,
    per_move_timeout_s: float = DEFAULT_PER_MOVE_TIMEOUT_S,
    per_game_timeout_s: float = DEFAULT_PER_GAME_TIMEOUT_S,
) -> BatchResult:
    """Run n_games between engine_a and engine_b, alternating colors by
    default and cycling through `openings` (a list of FENs; defaults to
    just the starting position) if it's shorter than n_games.

    Aggregates win/loss/draw counts from engine_a's perspective.
    """
    fens = openings if openings else [chess.STARTING_FEN]
    batch = BatchResult(engine_a=engine_a.display_name(), engine_b=engine_b.display_name())

    for i in range(n_games):
        fen = fens[i % len(fens)]
        a_is_white = (i % 2 == 0) if alternate_colors else True
        white_spec, black_spec = (engine_a, engine_b) if a_is_white else (engine_b, engine_a)

        game = play_game(
            white_spec, black_spec, opening_fen=fen,
            per_move_timeout_s=per_move_timeout_s,
            per_game_timeout_s=per_game_timeout_s,
        )
        batch.games.append(game)

        if game.result == "1-0":
            winner_is_a = a_is_white
        elif game.result == "0-1":
            winner_is_a = not a_is_white
        else:
            winner_is_a = None

        if winner_is_a is True:
            batch.a_wins += 1
        elif winner_is_a is False:
            batch.b_wins += 1
        else:
            batch.draws += 1

    return batch


# ── Gauntlet ──────────────────────────────────────────────────────────────────


@dataclass
class GauntletResult:
    primary: str
    opponents: list[BatchResult] = field(default_factory=list)

    def score_table(self) -> list[dict]:
        """Per-opponent summary: name, primary's W/L/D, and win rate."""
        table = []
        for batch in self.opponents:
            total = batch.total_games
            win_rate = batch.a_score / total if total else 0.0
            table.append({
                "opponent": batch.engine_b,
                "wins": batch.a_wins,
                "losses": batch.b_wins,
                "draws": batch.draws,
                "score": batch.a_score,
                "win_rate": win_rate,
            })
        return table


def run_gauntlet(
    primary: EngineSpec,
    opponents: list[EngineSpec],
    games_per_opponent: int,
    openings: list[str] | None = None,
    per_move_timeout_s: float = DEFAULT_PER_MOVE_TIMEOUT_S,
    per_game_timeout_s: float = DEFAULT_PER_GAME_TIMEOUT_S,
) -> GauntletResult:
    """Play `primary` against each of `opponents` for games_per_opponent
    games each, producing a per-opponent score table. This is the direct
    dependency 09_ELO_BENCHMARKING.md needs."""
    gauntlet = GauntletResult(primary=primary.display_name())
    for opponent in opponents:
        batch = run_batch(
            primary, opponent, games_per_opponent, openings=openings,
            per_move_timeout_s=per_move_timeout_s, per_game_timeout_s=per_game_timeout_s,
        )
        gauntlet.opponents.append(batch)
    return gauntlet


# ── Tournament (round robin) ─────────────────────────────────────────────────


@dataclass
class Standing:
    name: str
    points: float = 0.0
    games_played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


@dataclass
class TournamentResult:
    standings: list[Standing] = field(default_factory=list)
    pairings: list[BatchResult] = field(default_factory=list)


def run_tournament(
    configs: list[EngineSpec],
    games_per_pairing: int,
    openings: list[str] | None = None,
    per_move_timeout_s: float = DEFAULT_PER_MOVE_TIMEOUT_S,
    per_game_timeout_s: float = DEFAULT_PER_GAME_TIMEOUT_S,
) -> TournamentResult:
    """Round-robin every pair in `configs`, games_per_pairing games each,
    reusing run_batch per pairing rather than separate scheduling logic.
    Produces a simple standings table (points, games played)."""
    tally: dict[str, Standing] = {c.display_name(): Standing(name=c.display_name()) for c in configs}
    tournament = TournamentResult()

    for spec_a, spec_b in itertools.combinations(configs, 2):
        batch = run_batch(
            spec_a, spec_b, games_per_pairing, openings=openings,
            per_move_timeout_s=per_move_timeout_s, per_game_timeout_s=per_game_timeout_s,
        )
        tournament.pairings.append(batch)

        name_a, name_b = spec_a.display_name(), spec_b.display_name()
        tally[name_a].points += batch.a_score
        tally[name_a].games_played += batch.total_games
        tally[name_a].wins += batch.a_wins
        tally[name_a].losses += batch.b_wins
        tally[name_a].draws += batch.draws

        tally[name_b].points += batch.total_games - batch.a_score
        tally[name_b].games_played += batch.total_games
        tally[name_b].wins += batch.b_wins
        tally[name_b].losses += batch.a_wins
        tally[name_b].draws += batch.draws

    tournament.standings = sorted(tally.values(), key=lambda s: s.points, reverse=True)
    return tournament
