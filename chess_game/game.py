"""The Game dataclass — replaces ~35 module globals."""
from __future__ import annotations

from dataclasses import dataclass, field

import chess

from chess_game.adapter import ChessAdapter
from chess_game.anim import AnimationState, FlipState, ReviewState
from chess_game.bot_worker import BotWorker
from chess_game.engine.bot import ChessBot
from chess_game.state import GameState


@dataclass
class Game:
    """Owns everything that was previously a module-level global.

    Every draw/input function takes a Game instance as a parameter.
    Two Game objects could run concurrently (e.g. in tests) without
    interfering with each other.
    """
    bot: ChessBot
    bot_worker: BotWorker

    state: GameState = GameState.MENU
    adapter: ChessAdapter | None = None

    winner_result: tuple[str, str] | None = None
    winner_alpha: float = 0.0
    game_over: bool = False

    player_color: str = "white"
    board_flipped: bool = False

    bot_level: int = 5
    bot_epoch: int | None = None  # epoch returned by bot_worker.start()

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

    piece_imgs: dict = field(default_factory=dict)

    @property
    def bot_thinking(self) -> bool:
        return self.bot_worker.thinking

    def start_game(self) -> None:
        """Reset all per-game state for a fresh ChessAdapter (join the
        worker and clear the TT in the correct order)."""
        self.bot_worker.cancel()
        self.bot_worker.join(timeout=2.0)
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
        self.clear_analysis_display()

    def launch_bot_move(self) -> None:
        bot_color = "black" if self.player_color == "white" else "white"
        assert self.adapter is not None
        self.bot_epoch = self.bot_worker.start(self.adapter.board, bot_color, self.bot_level)

    def poll_bot_move(self) -> chess.Move | None:
        """Return the bot's move if one is ready under the current epoch."""
        if self.bot_epoch is None:
            return None
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
