"""The Game dataclass — replaces ~35 module globals."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import chess

from chess_game.adapter import ChessAdapter
from chess_game.anim import AnimationState, FlipState, ReviewState
from chess_game.bot_worker import BotWorker
from chess_game.clock import Clock
from chess_game.engine.bot import ChessBot
from chess_game.state import GameState
from chess_game.stockfish_bot_worker import DEFAULT_ELO, StockfishBotWorker


@dataclass
class Game:
    """Owns everything that was previously a module-level global.

    Every draw/input function takes a Game instance as a parameter.
    Two Game objects could run concurrently (e.g. in tests) without
    interfering with each other.
    """
    bot: ChessBot
    bot_worker: BotWorker
    # Owns its own UCI subprocess for *playing* moves, distinct from
    # App.analysis_worker which only ever evaluates. Constructed eagerly
    # (mirrors bot_worker) but the subprocess itself is opened lazily on
    # first use, same as AnalysisWorker.
    stockfish_bot_worker: StockfishBotWorker = field(default_factory=StockfishBotWorker)

    state: GameState = GameState.MENU
    adapter: ChessAdapter | None = None

    winner_result: tuple[str, str] | None = None
    winner_alpha: float = 0.0
    game_over: bool = False

    player_color: str = "white"
    board_flipped: bool = False

    bot_level: int = 5
    bot_epoch: int | None = None  # epoch returned by bot_worker.start()

    # PvP-only chess clock. None = untimed (also always None in bot games,
    # regardless of the user's saved time-control preference - see
    # App._handle_time_control_pick_event / App.start_game).
    clock: Clock | None = None
    time_control: str | None = None  # preset name, e.g. "3+2"; None = untimed

    # "native" -> chess_game.engine.bot.ChessBot via bot_worker (the
    # original 1-10 alpha-beta engine). "stockfish" -> the external
    # Stockfish binary via stockfish_bot_worker, strength-limited by ELO.
    bot_engine_pref: str = "native"
    bot_elo: int = DEFAULT_ELO

    think_dots: int = 0
    think_timer: float = 0.0

    promo_rects: list = field(default_factory=list)

    review: ReviewState = field(default_factory=ReviewState)
    panel_scroll: int = 0

    all_arrows: list = field(default_factory=list)
    arrow_start_sq: int | None = None

    board_theme: str = "white_green"
    arrow_theme: str = "blue"
    reduced_motion: bool = False
    sound_enabled: bool = True
    stockfish_path: str = ""

    # Always-on engine analysis mode (eval bar + PV arrows). The worker
    # itself lives on App (like bot_worker would, but analysis_worker owns
    # a real subprocess so App constructs and tears it down explicitly).
    analysis_enabled: bool = False
    analysis_epoch: int | None = None
    analysis_eval: int | None = None
    analysis_pv: list = field(default_factory=list)
    analysis_is_mate: bool = False
    analysis_mate_in: int | None = None
    # Set once per App lifetime the first time the user enables analysis
    # and Stockfish turns out to be unavailable, so the "not found" modal
    # only ever shows once rather than re-triggering on every toggle.
    analysis_missing_modal_shown: bool = False

    # The eval bar's *currently displayed* white-fill ratio, eased toward
    # whatever analysis_eval/analysis_is_mate computes as the target each
    # frame (see App._update_eval_bar_smoothing). None until the first
    # analysis result arrives, at which point it snaps straight to that
    # first value instead of easing in from a default — there's no
    # meaningful "previous" position to animate from on the very first
    # frame analysis becomes available.
    eval_bar_display_ratio: float | None = None

    # When set, a board-flip animation is in flight. The actual
    # `board_flipped` toggle happens at the animation midpoint (when the
    # board is squashed to zero width). Set by `start_flip()` after a PvP
    # move's slide animation completes.
    flip: FlipState | None = None
    # Internal latch: ensures the orientation swap inside update_flip fires
    # exactly once per flip animation, not every frame of the second half.
    flip_swapped: bool = False
    # Set by the click/drag handlers after a PvP move is applied. The main
    # loop's _maybe_arm_pvp_flip() converts this into a FlipState once the
    # move-slide animation has finished.
    pending_pvp_flip: bool = False

    anim: AnimationState | None = None

    # UI overlay flags
    continue_new_overlay: bool = False
    pending_mode: GameState | None = None
    pending_save_data: object = None

    main_menu_overlay: bool = False

    # Set while a Yes/Cancel confirmation is pending on top of the in-game
    # menu overlay (Resign / Offer Draw / Quit Without Saving all route
    # through this rather than acting immediately, since all three are
    # destructive/irreversible). {'action': str, 'message': str} or None.
    confirm_dialog: dict | None = None

    # Set to GameState.PVP or GameState.BOT when Preferences is opened from
    # the in-game menu overlay, so the Preferences screen's Back button
    # returns to the game in progress instead of always going to MENU.
    # None means Preferences was opened from the main menu as usual.
    preferences_return_state: GameState | None = None

    piece_imgs: dict = field(default_factory=dict)

    @property
    def bot_thinking(self) -> bool:
        if self.bot_engine_pref == "stockfish":
            return self.stockfish_bot_worker.thinking
        return self.bot_worker.thinking

    def start_game(self) -> None:
        """Reset all per-game state for a fresh ChessAdapter (join the
        worker and clear the TT in the correct order)."""
        self.bot_worker.cancel()
        self.bot_worker.join(timeout=2.0)
        self.stockfish_bot_worker.cancel()
        self.stockfish_bot_worker.join(timeout=2.0)
        self.bot.clear_tt()

        self.adapter = ChessAdapter()
        self.winner_result = None
        self.winner_alpha = 0.0
        self.game_over = False
        self.promo_rects = []
        self.bot_epoch = None
        self.anim = None
        self.flip = None
        self.flip_swapped = False
        self.pending_pvp_flip = False
        self.review.reset()
        self.panel_scroll = 0
        self.analysis_epoch = None
        self.eval_bar_display_ratio = None
        self.clear_analysis_display()
        # Cleared unconditionally here; callers that want a timed PvP game
        # construct a fresh Clock immediately after calling start_game().
        self.clock = None

    def launch_bot_move(self) -> None:
        bot_color = "black" if self.player_color == "white" else "white"
        assert self.adapter is not None
        if self.bot_engine_pref == "stockfish":
            self.bot_epoch = self.stockfish_bot_worker.start(
                self.adapter.board, bot_color, self.bot_elo
            )
        else:
            self.bot_epoch = self.bot_worker.start(self.adapter.board, bot_color, self.bot_level)

    def poll_bot_move(self) -> chess.Move | None:
        """Return the bot's move if one is ready under the current epoch."""
        if self.bot_epoch is None:
            return None
        if self.bot_engine_pref == "stockfish":
            return self.stockfish_bot_worker.take(self.bot_epoch)
        return self.bot_worker.take(self.bot_epoch)

    def launch_analysis(self, analysis_worker) -> None:
        """(Re)start engine analysis on the current position, if enabled.

        Takes the worker explicitly rather than owning one itself — App
        owns analysis_worker (it manages a real subprocess, so its
        lifecycle is tied to App.run()'s try/finally, not to per-game
        resets like start_game()).
        """
        if not self.analysis_enabled or self.adapter is None:
            return
        self.analysis_epoch = analysis_worker.start(self.adapter.board)

    def poll_analysis(self, analysis_worker) -> None:
        """Pull a ready analysis result (if any) under the current epoch
        and store it on the Game. No-op while analysis is disabled."""
        if not self.analysis_enabled or self.analysis_epoch is None:
            return
        result = analysis_worker.take(self.analysis_epoch)
        if result is None:
            return
        eval_cp, pv, is_mate, mate_in = result
        self.analysis_eval = eval_cp
        self.analysis_pv = pv
        self.analysis_is_mate = is_mate
        self.analysis_mate_in = mate_in

    def clear_analysis_display(self) -> None:
        """Clear the last-shown eval/PV, e.g. when analysis is toggled off
        so stale numbers don't linger on screen."""
        self.analysis_eval = None
        self.analysis_pv = []
        self.analysis_is_mate = False
        self.analysis_mate_in = None

    def update_eval_bar_smoothing(self, dt_ms: int) -> None:
        """Ease eval_bar_display_ratio toward the current target ratio.

        Called once per frame from the render loop (App._render_game),
        independent of whether a *new* analysis result actually arrived
        that frame — the bar keeps easing toward the last known target
        across multiple frames even if no new engine output has landed
        yet, which is what makes the transition smooth rather than a
        series of instant jumps every time take() happens to succeed.

        See chess_game.render.board for the exponential-decay formula
        and how to tune its speed.
        """
        from chess_game.render.board import EVAL_BAR_EASE_PER_SEC, eval_target_ratio

        if not self.analysis_enabled:
            return
        target = eval_target_ratio(self.analysis_eval, self.analysis_is_mate, self.analysis_mate_in)
        if self.eval_bar_display_ratio is None:
            # First result of this game/position — snap rather than ease
            # in from an arbitrary default.
            self.eval_bar_display_ratio = target
            return
        # Exponential ease-out, frame-rate independent: the fraction of
        # the remaining gap closed this frame depends only on dt, not on
        # how many frames it took to get here, so a slow machine (big dt,
        # few frames/sec) converges in the same wall-clock time as a fast
        # one (small dt, many frames/sec).
        dt_s = max(0.0, dt_ms) / 1000.0
        alpha = 1.0 - math.exp(-EVAL_BAR_EASE_PER_SEC * dt_s)
        self.eval_bar_display_ratio += (target - self.eval_bar_display_ratio) * alpha

    def resolve_board_view(self):
        """Return (board, check_sq, last_move, sel_sq, targets) for whichever
        board should currently be drawn — review_board when in review mode,
        else the live adapter board. Mirrors the original draw_chess_board's
        selection logic exactly, just without module globals."""
        assert self.adapter is not None
        if self.review.active and self.review.board is not None:
            board = self.review.board
            move_list = list(self.adapter.board.move_stack)
            last_move = move_list[self.review.ply - 1] if self.review.ply > 0 else None
            check_sq = board.king(board.turn) if board.is_check() else None
            sel_sq = None
            targets: set[int] = set()
        else:
            board = self.adapter.board
            check_sq = self.adapter.check_square
            last_move = self.adapter.last_move
            sel_sq = self.adapter.selected_square
            targets = self.adapter.valid_move_targets
        return board, check_sq, last_move, sel_sq, targets

    def animation_suppress_set(self, now_ms: int) -> set[int] | None:
        """Squares whose static piece should be hidden because an animated
        piece is currently sliding into/out of them."""
        if self.anim is not None and self.anim.is_animating(now_ms):
            sup = {item.suppress_sq for item in self.anim.items if item.suppress_sq is not None}
            return sup if sup else None
        return None

    def start_flip(self, now_ms: int, target_flipped: bool) -> None:
        """Arm a board-flip animation. The actual `board_flipped` SET is
        applied at the animation midpoint (inside update_flip), so callers
        should NOT toggle `board_flipped` themselves.

        `target_flipped` is the ABSOLUTE orientation the board should have
        after the flip. Using an absolute target (not a relative toggle)
        prevents race conditions where rapid moves could leave the board
        in the wrong orientation.

        If `reduced_motion` is enabled, the flip is applied instantly with
        no animation.
        """
        if self.reduced_motion:
            self.board_flipped = target_flipped
            return
        self.flip = FlipState(start_ms=now_ms, target_flipped=target_flipped)

    def update_flip(self, now_ms: int) -> None:
        """Advance any in-flight board-flip animation. SETS `board_flipped`
        to the flip's target at the midpoint and clears `self.flip` when the
        animation completes."""
        if self.flip is None:
            return
        if self.flip.is_active(now_ms):
            # Set the absolute target orientation at the midpoint (when the
            # board is at minimum width, hiding the orientation change).
            if self.flip.should_swap_orientation(now_ms) and not self.flip_swapped:
                self.board_flipped = self.flip.target_flipped
                self.flip_swapped = True
            return
        # Animation finished — ensure the orientation was set to the target
        # (in case no update_flip frame landed during the second half) and
        # clean up. This is the safety net: no matter what happened during
        # the animation, the final orientation is always the correct one.
        self.board_flipped = self.flip.target_flipped
        self.flip = None
        self.flip_swapped = False

    def start_anim(self, from_sq: int, to_sq: int, img, start_pos: tuple[int, int] | None = None) -> None:
        """Start (or extend) the current animation batch.

        Matches the original's semantics: if an animation is already
        in-flight, the new item is appended to play simultaneously rather
        than restarting the batch's clock.

        When reduced_motion is enabled this is a no-op: pieces snap
        straight to their final position instead of sliding.

        When `start_pos` is provided (absolute screen-pixel coordinates),
        the animation begins from that point instead of the centre of
        `from_sq`. This is used by the drag-and-drop flow so the piece
        slides smoothly from where the cursor released it to the
        destination square, rather than snapping back to its origin first.
        """
        if self.reduced_motion:
            return

        import pygame

        from chess_game.anim import AnimationState, AnimItem
        from chess_game.layout import sq_to_screen

        if start_pos is not None:
            sx, sy = start_pos
        else:
            sx, sy = sq_to_screen(from_sq, self.board_flipped)
        ex, ey = sq_to_screen(to_sq, self.board_flipped)
        item = AnimItem(sx, sy, ex, ey, img, to_sq)
        now_ms = pygame.time.get_ticks()
        if self.anim is None or not self.anim.is_animating(now_ms):
            self.anim = AnimationState(items=[item], start_ms=now_ms)
        else:
            self.anim.items.append(item)

    def tick_clock(self, now_ms: int) -> None:
        """Advance the PvP chess clock by one frame and apply a flag-fall
        loss if the side on move just ran out of time.

        No-op when untimed (self.clock is None), already game-over, or
        already flagged (Clock.tick is itself a no-op once flagged, but
        the game_over/winner_result bookkeeping below must still only
        run once - guarded by `g.game_over` at the call site in App).
        """
        if self.clock is None:
            return
        self.clock.tick(now_ms)
        flagged = self.clock.flagged()
        if flagged is None:
            return
        winner = "Black" if flagged == chess.WHITE else "White"
        self.winner_result = (f"{winner} Wins!", "on Time")
        self.game_over = True

    def resign(self, resigning_color: str) -> None:
        """End the game as a resignation by `resigning_color` ("white" or
        "black"). Mirrors tick_clock's flag-fall bookkeeping: set
        winner_result + game_over, and cancel any in-flight bot thinking
        so it can't post a move into a game that has already ended.

        Callers are responsible for persisting/discarding the save
        afterwards - resignation (like a draw by agreement) has no
        representation in the replayable move stack, so App deletes the
        save rather than writing one that would silently "un-resign" on
        the next resume.
        """
        self.bot_worker.cancel()
        self.bot_worker.join(timeout=2.0)
        self.stockfish_bot_worker.cancel()
        self.stockfish_bot_worker.join(timeout=2.0)
        winner = "Black" if resigning_color == "white" else "White"
        self.winner_result = (f"{winner} Wins!", "by Resignation")
        self.game_over = True

    def agree_draw(self) -> None:
        """End the game as a draw by agreement. See `resign` for why the
        bot worker is cancelled and why callers should discard rather than
        write the save afterwards.
        """
        self.bot_worker.cancel()
        self.bot_worker.join(timeout=2.0)
        self.stockfish_bot_worker.cancel()
        self.stockfish_bot_worker.join(timeout=2.0)
        self.winner_result = ("Draw", "by Agreement")
        self.game_over = True

    def maybe_create_clock(self, time_control: str | None) -> None:
        """Construct a fresh PvP Clock from `time_control` (a preset name
        like "3+2", or None/"none" for untimed). Call after start_game().

        Bot games must never call this - callers are responsible for only
        invoking it on the PvP path (see App._handle_time_control_pick_event).
        """
        self.time_control = time_control
        if time_control is None or time_control == "none":
            self.clock = None
            return
        self.clock = Clock.from_preset(time_control)
