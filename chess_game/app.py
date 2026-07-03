"""Bootstrap and main loop.

Every pygame.init()/display/font/image/sound/save-dir/bot-construction
side effect lives inside bootstrap()/main(), never at module import time.
Importing this module is now side-effect free.
"""
from __future__ import annotations

import os
import sys

import chess
import pygame

from chess_game import io as save_io
from chess_game import theme
from chess_game.analysis import AnalysisWorker
from chess_game.anim import ANIM_MS, FLIP_MIN_SCALE, ease_out
from chess_game.assets import load_images
from chess_game.bot_worker import BotWorker
from chess_game.clock import TIME_CONTROL_PRESETS, Clock
from chess_game.engine.bot import ChessBot
from chess_game.game import Game
from chess_game.input_handler import InputHandler
from chess_game.log import configure_logging
from chess_game.render import arrows as render_arrows
from chess_game.render import board as render_board
from chess_game.render import clocks as render_clocks
from chess_game.render import history as render_history
from chess_game.render import menus as render_menus
from chess_game.render import overlays as render_overlays
from chess_game.render import trays as render_trays
from chess_game.sound import SoundManager
from chess_game.state import GameState
from chess_game.stockfish_bot_worker import MAX_ELO, MIN_ELO, StockfishBotWorker
from chess_game.stockfish_download import StockfishDownloader
from chess_game.widgets import FOCUS_RING, FocusableRect, FocusGroup


def resource_path(relative: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__ + '/..')))
    return os.path.join(base, relative)


# Minimum mouse movement (in pixels) before a mousedown is promoted to a drag.
# Below this, a press+release is treated as a pure click (preserving the
# existing click-to-select / click-to-move behaviour unchanged).
DRAG_THRESHOLD_PX = 5


class App:
    """Owns everything bootstrap() creates: screen, fonts, assets, sounds,
    the Game instance, and per-screen UI state that doesn't belong on Game
    (menu buttons, transient slider/picker rects)."""

    def __init__(self) -> None:
        self.logger = configure_logging()
        pygame.init()

        prefs = save_io.read_preferences()
        board_theme = prefs.get('board_theme') or 'white_green'
        arrow_theme = prefs.get('arrow_theme') or 'blue'
        reduced_motion = bool(prefs.get('reduced_motion', False))
        sound_enabled = bool(prefs.get('sound_enabled', True))
        stockfish_path = prefs.get('stockfish_path') or ''
        bot_engine_pref = prefs.get('bot_engine_pref') or 'native'
        if bot_engine_pref not in ('native', 'stockfish'):
            bot_engine_pref = 'native'
        bot_elo = int(prefs.get('bot_elo') or 1500)
        self._fullscreen = bool(prefs.get('fullscreen', False))
        if board_theme not in theme.BOARD_THEMES:
            board_theme = 'white_green'
        if arrow_theme not in theme.ARROW_THEMES:
            arrow_theme = 'blue'

        flags = pygame.SCALED
        if self._fullscreen:
            flags |= pygame.FULLSCREEN
        self.screen = pygame.display.set_mode(
            (theme.WIN_W, theme.WIN_H), flags, vsync=1
        )
        pygame.display.set_caption('Python Chess')
        self.board_surf = pygame.Surface((theme.BOARD_PX, theme.BOARD_PX), pygame.SRCALPHA)
        self._board_surf_dirty = True

        self.fonts = theme.load_fonts()
        self.assets = load_images(resource_path)
        self.sounds = SoundManager(resource_path)
        self.sounds.set_muted(not sound_enabled)

        bot = ChessBot(max_depth=3, book_path=resource_path('data/book/gm2001.bin'))
        worker = BotWorker(bot)
        self.analysis_worker = AnalysisWorker(stockfish_path)
        stockfish_worker = StockfishBotWorker(stockfish_path)
        bot_elo = max(MIN_ELO, min(MAX_ELO, bot_elo))
        self.game = Game(
            bot=bot, bot_worker=worker, stockfish_bot_worker=stockfish_worker,
            board_theme=board_theme,
            arrow_theme=arrow_theme, reduced_motion=reduced_motion,
            sound_enabled=sound_enabled,
            stockfish_path=stockfish_path,
            bot_engine_pref=bot_engine_pref, bot_elo=bot_elo,
        )
        self.game.piece_imgs = self.assets.piece_imgs

        self.menu_buttons = render_menus.make_menu_buttons()
        self.menu_focus = FocusGroup(self.menu_buttons)
        self.clock = pygame.time.Clock()
        self.input = InputHandler(self)

        # Transient per-screen UI rects (not part of Game; rebuilt every frame).
        self.opponent_rects: dict = {}
        self.opponent_back: pygame.Rect | None = None
        self.opponent_focus = FocusGroup([])

        self.picker_rects: dict = {}
        self.picker_back: pygame.Rect | None = None
        self.picker_focus = FocusGroup([])
        self.diff_back: pygame.Rect | None = None
        self.diff_confirm_rect: pygame.Rect | None = None
        self.diff_slider_rect: pygame.Rect | None = None
        self.diff_slider_info: tuple | None = None
        self.diff_slider_dragging = False
        self.diff_level = 5
        self.diff_focus = FocusGroup([])

        # Time-control preset picker (GameState.TIME_CONTROL_PICK), reached
        # from OPPONENT_PICK's 'player' card for a fresh PvP game. tc_choice
        # is initialised from the saved preference so re-opening the screen
        # remembers the last pick; it only ever changes via this screen.
        default_time_control = prefs.get('default_time_control') or 'none'
        if default_time_control not in render_menus.TIME_CONTROL_CHOICES:
            default_time_control = 'none'
        self.tc_choice = default_time_control
        self.tc_back: pygame.Rect | None = None
        self.tc_confirm_rect: pygame.Rect | None = None
        self.tc_choice_rects: dict = {}
        self.tc_focus = FocusGroup([])

        # Stockfish ELO sub-menu (GameState.STOCKFISH_DIFFICULTY) — same
        # shape as the diff_* block above, kept separate rather than
        # reusing it so switching engine preference mid-session can never
        # leave one screen's drag state bleeding into the other's.
        self.sf_diff_back: pygame.Rect | None = None
        self.sf_diff_confirm_rect: pygame.Rect | None = None
        self.sf_diff_slider_rect: pygame.Rect | None = None
        self.sf_diff_slider_info: tuple | None = None
        self.sf_diff_slider_dragging = False
        self.sf_diff_focus = FocusGroup([])

        self.pref_back_rect: pygame.Rect | None = None
        self.pref_board_rects: dict = {}
        self.pref_arrow_rects: dict = {}
        self.pref_motion_rect: pygame.Rect | None = None
        self.pref_sound_rect: pygame.Rect | None = None
        self.pref_download_rect: pygame.Rect | None = None
        self.pref_engine_rects: dict = {}
        self.pref_focus = FocusGroup([])

        # Stockfish auto-download status: 'idle'/'downloading'/'done'/'error'.
        # The downloader is polled each frame like the other worker threads.
        self.stockfish_downloader = StockfishDownloader()
        self.stockfish_download_status = 'idle'
        self.stockfish_download_error: str | None = None

        self.menu_btn_ingame_rect: pygame.Rect | None = None
        self.gameover_btn_rects: dict | None = None
        self.overlay_cont_btn: pygame.Rect | None = None
        self.overlay_new_btn: pygame.Rect | None = None
        self.overlay_save_btn: pygame.Rect | None = None
        self.overlay_quit_btn: pygame.Rect | None = None
        self.overlay_export_btn: pygame.Rect | None = None
        self.overlay_preferences_btn: pygame.Rect | None = None
        self.overlay_draw_btn: pygame.Rect | None = None
        self.overlay_resign_btn: pygame.Rect | None = None
        self.confirm_yes_btn: pygame.Rect | None = None
        self.confirm_cancel_btn: pygame.Rect | None = None
        self._last_cursor = pygame.SYSTEM_CURSOR_ARROW
        self.pending_pgn_export_path: str | None = None

        self.pending_corrupt_error: str | None = None

        # In-game analysis toggle button rect (rebuilt every frame, like
        # menu_btn_ingame_rect) and the one-time "Stockfish not found"
        # modal's OK button rect.
        self.analysis_toggle_rect: pygame.Rect | None = None
        self.pending_analysis_missing_modal: bool = False
        self.analysis_missing_ok_rect: pygame.Rect | None = None

        # Drag-and-drop state for moving pieces. drag_pending becomes
        # drag_active once the cursor moves past DRAG_THRESHOLD_PX.
        # A click remains a normal select/move if the threshold is not crossed.
        self.drag_pending: bool = False
        self.drag_active: bool = False
        self.drag_sq: int | None = None
        self.drag_pos: tuple[int, int] = (0, 0)
        self.drag_start_pos: tuple[int, int] = (0, 0)

    # ── Lifecycle helpers ───────────────────────────────────────────────────

    def start_game(self) -> None:
        self.game.start_game()
        self._board_surf_dirty = True
        self.game.launch_analysis(self.analysis_worker)

    def launch_bot_move(self) -> None:
        self.game.launch_bot_move()

    def _restart_analysis_if_enabled(self) -> None:
        """Restart engine analysis on the post-move position. Called after
        every move-application path (click-move, drag-move, promotion,
        bot-move) so the eval bar and PV arrows always reflect the
        current position, not a stale one."""
        self.game.launch_analysis(self.analysis_worker)

    def _toggle_analysis(self) -> None:
        """Toggle analysis mode and restart or cancel the worker as needed."""
        g = self.game
        g.analysis_enabled = not g.analysis_enabled
        if g.analysis_enabled:
            g.launch_analysis(self.analysis_worker)
            if not self.analysis_worker.engine_available and not g.analysis_missing_modal_shown:
                g.analysis_missing_modal_shown = True
                self.pending_analysis_missing_modal = True
        else:
            self.analysis_worker.cancel()
            g.analysis_epoch = None
            g.eval_bar_display_ratio = None
            g.clear_analysis_display()

    def _start_stockfish_download(self) -> None:
        """Kick off (or retry) downloading Stockfish into the same
        directory preferences.json and saved games already live in.
        No-op while a download is already in flight."""
        if self.stockfish_downloader.busy:
            return
        self.stockfish_download_status = 'downloading'
        self.stockfish_download_error = None
        install_dir = save_io.get_save_dir() / 'stockfish'
        self.stockfish_downloader.start(install_dir)

    def _poll_stockfish_download(self) -> None:
        """Poll the downloader and apply its result when finished."""
        result = self.stockfish_downloader.take_result()
        if result is None:
            return
        path, error = result
        g = self.game
        if error is not None:
            self.stockfish_download_status = 'error'
            self.stockfish_download_error = error
            return

        self.stockfish_download_status = 'done'
        self.stockfish_download_error = None
        assert path is not None
        g.stockfish_path = path
        # The old engine (if any) may be pointed at a different, possibly
        # now-broken path; close it so the next analysis start re-opens
        # fresh against the new binary rather than continuing to use a
        # stale process or a worker that's permanently given up after an
        # earlier failed popen_uci attempt.
        self.analysis_worker.stop_engine()
        self.analysis_worker.set_engine_path(path)
        g.analysis_missing_modal_shown = False
        self._persist_window_prefs()
        if g.analysis_enabled:
            g.launch_analysis(self.analysis_worker)

    def write_save(self) -> None:
        if self.game.adapter is None:
            return
        g = self.game
        assert g.adapter is not None
        mode = 'bot' if g.state == GameState.BOT else 'pvp'
        if mode == 'bot':
            save_io.write_save(mode, list(g.adapter.board.move_stack), g.player_color, g.bot_level)
            return
        time_control = None
        white_ms = black_ms = active_side = None
        if g.clock is not None:
            time_control = g.time_control
            white_ms = g.clock.remaining(chess.WHITE)
            black_ms = g.clock.remaining(chess.BLACK)
            active_side = 'black' if g.clock.active == chess.BLACK else 'white'
        save_io.write_save(
            mode, list(g.adapter.board.move_stack), g.player_color, g.bot_level,
            time_control=time_control, white_time_ms=white_ms,
            black_time_ms=black_ms, active_side=active_side,
        )

    def export_pgn(self) -> None:
        """Export the current game's move history to a PGN file.

        Fire-and-forget, same as write_save(): on failure the error is
        logged but not surfaced as a blocking modal, since losing a PGN
        export (the JSON save still exists) isn't as consequential as
        losing the save itself.
        """
        if self.game.adapter is None:
            return
        mode = 'bot' if self.game.state == GameState.BOT else 'pvp'
        path = save_io.pgn_export_path()
        try:
            save_io.export_pgn(
                self.game.adapter, path,
                mode, self.game.player_color, self.game.bot_level,
            )
        except OSError:
            self.logger.exception('Failed to export PGN')

    def safe_read_save(self, mode: str):
        """Returns SaveData, or None, or sets pending_corrupt_error and
        returns None if the save is corrupt (never silently treated
        as 'no save')."""
        try:
            return save_io.read_save(mode)
        except save_io.CorruptSaveError:
            self.pending_corrupt_error = 'Your saved game could not be read.'
            return None

    def continue_saved_game(self, save_data: save_io.SaveData, mode: GameState) -> None:
        if mode == GameState.BOT:
            self.game.player_color = save_data.color
            self.game.board_flipped = (save_data.color == 'black')
            self.game.bot_level = save_data.level
            self.diff_level = save_data.level
        else:
            # PvP auto-flip: orient the board so the player whose turn it is
            # sits at the bottom. White to move = not flipped; Black to move
            # = flipped. The turn is determined after replaying the moves
            # below, so set a placeholder here and correct it afterwards.
            self.game.board_flipped = False
        self.game.state = mode
        self.start_game()
        assert self.game.adapter is not None  # guaranteed by start_game() above
        for move in save_data.moves:
            if move in self.game.adapter.board.legal_moves:
                self.game.adapter.apply_move(move)
        if mode == GameState.PVP and not self.game.adapter.is_game_over:
            # Orient for the side to move (Black to move = flipped).
            self.game.board_flipped = (self.game.adapter.turn == 'black')
        if mode == GameState.PVP:
            self._restore_clock_from_save(save_data)
        if mode == GameState.BOT and not self.game.adapter.is_game_over:
            if self.game.adapter.turn != self.game.player_color:
                self.launch_bot_move()
        self.write_save()

    def _restore_clock_from_save(self, save_data: save_io.SaveData) -> None:
        """Reconstruct g.clock from a resumed PvP save's persisted clock
        fields, or leave it untimed if the save predates time controls
        (version-1 saves, or a version-2 save written with time_control
        = None for an untimed game).

        _last_tick_ms is left at its post-construction default of None
        (see Clock.__init__/.switch), so the very next tick() call treats
        "now" as the baseline instead of subtracting the real-world gap
        between when the game was saved and when it's being resumed.
        """
        g = self.game
        if save_data.time_control is None:
            g.time_control = None
            g.clock = None
            return
        if save_data.time_control not in TIME_CONTROL_PRESETS:
            g.time_control = None
            g.clock = None
            return
        _initial_s, increment_s = TIME_CONTROL_PRESETS[save_data.time_control]
        white_ms = save_data.white_time_ms
        black_ms = save_data.black_time_ms
        if white_ms is None or black_ms is None:
            g.time_control = None
            g.clock = None
            return
        clock = Clock(initial_ms=white_ms, increment_ms=increment_s * 1000)
        clock.times[chess.WHITE] = white_ms
        clock.times[chess.BLACK] = black_ms
        clock.active = chess.BLACK if save_data.active_side == 'black' else chess.WHITE
        g.time_control = save_data.time_control
        g.clock = clock


    def _maybe_arm_pvp_flip(self, now_ms: int) -> None:
        """Arm a board-flip animation once the move-slide finishes.

        The target orientation is derived from the current turn.
        """
        g = self.game
        if not g.pending_pvp_flip:
            return
        # Wait until the move slide has finished so the piece lands before
        # the board starts rotating.
        if g.anim is not None and g.anim.is_animating(now_ms):
            return
        # If a previous flip is still in-flight, cancel it and arm a fresh
        # one with the correct target. The old flip's midpoint swap may or
        # may not have fired — it doesn't matter, because the new flip will
        # SET the board to the correct absolute orientation at its midpoint
        # (and at completion as a safety net).
        if g.flip is not None and g.flip.is_active(now_ms):
            g.flip = None
            g.flip_swapped = False
        g.pending_pvp_flip = False
        # Absolute target: Black to move → board flipped so Black sits at
        # the bottom. This is computed at flip-arm time from the live turn,
        # so it's always correct regardless of how many flips queued up.
        assert g.adapter is not None
        target_flipped = (g.adapter.turn == 'black')
        g.start_flip(now_ms, target_flipped)

    def _enforce_pvp_orientation(self, now_ms: int) -> None:
        """Force the board orientation to match the current PVP turn.

        Only runs when no flip or move animation is active.
        """
        g = self.game
        if g.state != GameState.PVP or g.adapter is None:
            return
        # Don't interfere while a flip is in-flight or pending — those will
        # set the correct orientation themselves.
        if g.flip is not None and g.flip.is_active(now_ms):
            return
        if g.pending_pvp_flip:
            return
        # Don't interfere while a move slide is animating — the flip will
        # arm after it finishes.
        if g.anim is not None and g.anim.is_animating(now_ms):
            return
        # Don't interfere during review mode or game-over.
        if g.review.active or g.game_over:
            return
        correct = (g.adapter.turn == 'black')
        if g.board_flipped != correct:
            g.board_flipped = correct

    # ── Fullscreen toggle ──────────────────────────────────────────────────

    def _toggle_fullscreen(self) -> None:
        """Toggle between windowed and fullscreen via F11.

        Uses pygame.display.toggle_fullscreen() which flips the mode
        in-place without recreating the display surface — no renderer
        teardown, no flashing. Falls back to set_mode with the new flags
        if the in-place toggle fails (rare).
        """
        self._fullscreen = not self._fullscreen
        try:
            result = pygame.display.toggle_fullscreen()
            if result == 1:
                self._persist_window_prefs()
                return
        except pygame.error:
            pass

        # Fallback: recreate the display with the new flags. We must
        # quit/init the display to avoid the "failed to create renderer"
        # error on Windows when reusing SCALED.
        flags = pygame.SCALED
        if self._fullscreen:
            flags |= pygame.FULLSCREEN
        pygame.display.quit()
        pygame.display.init()
        self.screen = pygame.display.set_mode(
            (theme.WIN_W, theme.WIN_H), flags, vsync=1
        )
        pygame.display.set_caption('Python Chess')
        # Re-convert piece images to the new display's pixel format.
        self.assets = load_images(resource_path)
        self.game.piece_imgs = self.assets.piece_imgs
        self._persist_window_prefs()

    def _persist_window_prefs(self) -> None:
        """Save the fullscreen state to preferences."""
        g = self.game
        save_io.write_preferences(g.board_theme, g.arrow_theme, g.reduced_motion,
                                  self._fullscreen, g.stockfish_path,
                                  g.bot_engine_pref, g.bot_elo,
                                  sound_enabled=g.sound_enabled)

    # ── Bootstrap entry point ───────────────────────────────────────────────

    def run(self) -> None:
        try:
            while True:
                self._frame()
        except SystemExit:
            raise
        finally:
            self.game.bot_worker.cancel()
            self.game.bot_worker.join(timeout=2.0)
            self.analysis_worker.stop_engine()

    def _frame(self) -> None:
        dt = self.clock.tick(60)
        mx, my = pygame.mouse.get_pos()

        # Safety net: if a drag is armed or active but the left mouse button
        # is no longer held, the mouseup was swallowed by an overlay or
        # state transition. Clear the stale drag state so the next press
        # starts cleanly and no piece is left "stuck" to the cursor.
        if (self.drag_pending or self.drag_active) and not pygame.mouse.get_pressed()[0]:
            self.input._reset_drag()

        self.game.think_timer += dt
        if self.game.think_timer >= 500:
            self.game.think_dots += 1
            self.game.think_timer = 0

        for event in pygame.event.get():
            self._handle_event(event, mx, my)

        self._apply_bot_move()
        self._tick_chess_clock()
        self.game.poll_analysis(self.analysis_worker)
        self._poll_stockfish_download()
        # Arm any pending board flip once the move slide has finished, then
        # advance any in-flight flip animation. The board rotates between
        # turns so each player sits at the bottom on their move.
        now = pygame.time.get_ticks()
        self._maybe_arm_pvp_flip(now)
        self.game.update_flip(now)
        # Final safety net: if no flip is in-flight or pending and no move
        # slide is animating in PvP mode, force the board orientation to
        # match the current turn. This catches any edge case where rapid
        # moves left the board in the wrong orientation — the player will
        # see a one-frame snap to the correct view rather than a stale view.
        self._enforce_pvp_orientation(now)
        self._render(dt)
        self._update_cursor(*pygame.mouse.get_pos())
        pygame.display.flip()

    # ── Event dispatch ──────────────────────────────────────────────────────
    # Full per-screen handler tree lives in InputHandler (chess_game/input_handler.py).

    def _handle_event(self, event: pygame.event.Event, mx: int, my: int) -> None:
        self.input.handle_event(event, mx, my)

    # ── Bot move application ────────────────────────────────────────────────

    def _apply_bot_move(self) -> None:
        g = self.game
        if g.state != GameState.BOT:
            return
        assert g.adapter is not None
        is_animating = g.anim is not None and g.anim.is_animating(pygame.time.get_ticks())
        if is_animating or g.review.active:
            return
        move = g.poll_bot_move()
        if move and move in g.adapter.board.legal_moves:
            piece = g.adapter.board.piece_at(move.from_square)
            img = g.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
            result = g.adapter.apply_move(move)
            g.start_anim(g.adapter.anim_from, g.adapter.anim_to, img)
            is_check = g.adapter.check_square is not None
            is_over = g.adapter.is_game_over
            self.sounds.play_for_move_result(result, is_check=is_check, is_game_over=is_over)
            self.write_save()
            self._restart_analysis_if_enabled()

    def _tick_chess_clock(self) -> None:
        """Advance the PvP chess clock once per frame and handle flag-fall.

        Gated exactly like _apply_bot_move's animation guard, plus the
        PVP-only and game-over checks: the clock must not run during
        animation, review mode, or once the game has already ended (either
        by a normal result or by an earlier flag-fall on a previous frame).

        No-op whenever g.clock is None, which covers both untimed PvP
        games and every bot game (bot games never have a clock at all -
        see Game.maybe_create_clock / App._confirm_time_control).
        """
        g = self.game
        if g.state != GameState.PVP or g.clock is None:
            return
        if g.game_over or g.review.active:
            return
        is_animating = g.anim is not None and g.anim.is_animating(pygame.time.get_ticks())
        if is_animating:
            return
        g.tick_clock(pygame.time.get_ticks())
        if g.game_over:
            # Flag-fall just ended the game this frame - persist it like
            # any other game-ending move, and stop ticking further (tick_clock
            # already no-ops once Clock itself is flagged, but write_save
            # here keeps the saved clock state consistent with game_over).
            self.write_save()

    # ── Rendering ────────────────────────────────────────────────────────────

    _history_ply_rects: list = []
    _live_btn_rect: pygame.Rect | None = None

    def _popup_active(self) -> bool:
        """True if any modal popup/overlay is currently on screen.

        When this returns True, hover highlighting on the base screen layer
        is suppressed (the mouse position is reported as off-screen to the
        draw functions) so elements behind the popup don't light up as the
        cursor moves over them.
        """
        g = self.game
        return (self.pending_corrupt_error is not None
                or self.pending_analysis_missing_modal
                or g.continue_new_overlay
                or g.main_menu_overlay
                or g.confirm_dialog is not None)

    def _draw_focus_ring(self, focus_group: FocusGroup) -> None:
        """Draw a visible focus ring around the currently focused widget for
        screens that draw their own custom rects (not Button.draw())."""
        if 0 <= focus_group.index < len(focus_group.widgets):
            focused = focus_group.widgets[focus_group.index]
            pygame.draw.rect(self.screen, FOCUS_RING, focused.rect, 3, border_radius=8)

    def _update_cursor(self, mx: int, my: int) -> None:
        """Show a hand cursor over anything clickable, an arrow otherwise.

        Reuses the same rect collections already assembled this frame for
        click handling and focus rings (the *_focus FocusGroups for the
        picker/menu screens, and the individual rect attributes for
        popups and the in-game HUD/history panel), so this can't drift
        out of sync with what's actually clickable.
        """
        g = self.game
        rects: list[pygame.Rect | None] = []

        if g.confirm_dialog is not None:
            rects += [self.confirm_yes_btn, self.confirm_cancel_btn]
        elif g.continue_new_overlay:
            rects += [self.overlay_cont_btn, self.overlay_new_btn]
        elif g.main_menu_overlay:
            rects += [self.overlay_save_btn, self.overlay_export_btn,
                      self.overlay_preferences_btn, self.overlay_draw_btn,
                      self.overlay_resign_btn, self.overlay_quit_btn]
        elif self.pending_analysis_missing_modal:
            rects.append(self.analysis_missing_ok_rect)
        elif self.pending_corrupt_error is None:
            focus_group = self.input._focus_group_for_state(g.state)
            if focus_group is not None:
                rects += [w.rect for w in focus_group.widgets]
            if g.state in (GameState.PVP, GameState.BOT):
                rects += [self.menu_btn_ingame_rect, self.analysis_toggle_rect]
                if g.review.active:
                    rects.append(self._live_btn_rect)
                rects += [rect for rect, _ply in self._history_ply_rects]
                if g.adapter is not None and g.adapter.promotion_pending:
                    rects += [rect for rect, _pt in g.promo_rects]
                if g.game_over and self.gameover_btn_rects:
                    rects += list(self.gameover_btn_rects.values())

        hovering = any(r is not None and r.collidepoint(mx, my) for r in rects)
        cursor = pygame.SYSTEM_CURSOR_HAND if hovering else pygame.SYSTEM_CURSOR_ARROW
        if cursor != self._last_cursor:
            pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND if hovering else pygame.SYSTEM_CURSOR_ARROW)
            self._last_cursor = cursor

    def _render(self, dt: int) -> None:
        # When a popup is active, suppress hover highlighting on the base
        # screen by temporarily making the mouse position read as off-screen.
        # The draw functions all call pygame.mouse.get_pos() for hover
        # detection, so this cleanly disables hover without changing any
        # signatures. The real mouse position is restored before drawing
        # the popup layer itself (so the popup's own buttons still hover).
        popup_before = self._popup_active()
        real_get_pos = pygame.mouse.get_pos
        if popup_before:
            pygame.mouse.get_pos = lambda: (-9999, -9999)
        try:
            self._render_base(dt)
        finally:
            pygame.mouse.get_pos = real_get_pos
        # Now draw the popup layer (if any) with the real mouse position.
        self._render_popups(dt)

    def _render_base(self, dt: int) -> None:
        g = self.game
        if g.state == GameState.MENU:
            render_menus.draw_menu(self.screen, self.menu_buttons, self.fonts)
        elif g.state == GameState.OPPONENT_PICK:
            self.opponent_rects, self.opponent_back = render_menus.draw_opponent_picker(
                self.screen, self.fonts, self.assets.king_imgs
            )
            opponent_focusables = [FocusableRect(self.opponent_back, 'back')] + [
                FocusableRect(rect, key) for key, rect in self.opponent_rects.items()
            ]
            self.opponent_focus.rebuild(opponent_focusables)
            self._draw_focus_ring(self.opponent_focus)
        elif g.state == GameState.TIME_CONTROL_PICK:
            self.tc_back, self.tc_confirm_rect, self.tc_choice_rects = (
                render_menus.draw_time_control_picker(self.screen, self.tc_choice, self.fonts)
            )
            tc_focusables = [FocusableRect(self.tc_back, 'back')] + [
                FocusableRect(rect, ('choice', key)) for key, rect in self.tc_choice_rects.items()
            ] + [FocusableRect(self.tc_confirm_rect, 'confirm')]
            self.tc_focus.rebuild(tc_focusables)
            self._draw_focus_ring(self.tc_focus)
        elif g.state == GameState.COLOR_PICK:
            self.picker_rects, self.picker_back = render_menus.draw_color_picker(
                self.screen, self.fonts, self.assets.king_imgs
            )
            picker_focusables = [FocusableRect(self.picker_back, 'back')] + [
                FocusableRect(rect, color) for color, rect in self.picker_rects.items()
            ]
            self.picker_focus.rebuild(picker_focusables)
            self._draw_focus_ring(self.picker_focus)
        elif g.state == GameState.DIFFICULTY:
            (self.diff_back, self.diff_confirm_rect,
             self.diff_slider_rect, self.diff_slider_info) = render_menus.draw_difficulty(
                self.screen, self.diff_level, self.fonts
            )
            self.diff_focus.rebuild([
                FocusableRect(self.diff_back, 'back'),
                FocusableRect(self.diff_confirm_rect, 'confirm'),
            ])
            self._draw_focus_ring(self.diff_focus)
        elif g.state == GameState.STOCKFISH_DIFFICULTY:
            (self.sf_diff_back, self.sf_diff_confirm_rect,
             self.sf_diff_slider_rect, self.sf_diff_slider_info) = render_menus.draw_stockfish_difficulty(
                self.screen, g.bot_elo, self.fonts
            )
            self.sf_diff_focus.rebuild([
                FocusableRect(self.sf_diff_back, 'back'),
                FocusableRect(self.sf_diff_confirm_rect, 'confirm'),
            ])
            self._draw_focus_ring(self.sf_diff_focus)
        elif g.state == GameState.PREFERENCES:
            (self.pref_back_rect, self.pref_board_rects,
             self.pref_arrow_rects, self.pref_motion_rect,
             self.pref_download_rect, self.pref_engine_rects,
             self.pref_sound_rect) = render_menus.draw_preferences(
                self.screen, g.board_theme, g.arrow_theme, g.reduced_motion,
                g.stockfish_path, self.fonts,
                download_status=self.stockfish_download_status,
                download_progress=self.stockfish_downloader.progress(),
                download_error=self.stockfish_download_error,
                bot_engine_pref=g.bot_engine_pref,
                sound_enabled=g.sound_enabled,
            )
            pref_focusables = [FocusableRect(self.pref_back_rect, ('back', None))]
            pref_focusables += [
                FocusableRect(rect, ('board', name)) for name, rect in self.pref_board_rects.items()
            ]
            pref_focusables += [
                FocusableRect(rect, ('arrow', name)) for name, rect in self.pref_arrow_rects.items()
            ]
            pref_focusables.append(FocusableRect(self.pref_motion_rect, ('motion', None)))
            pref_focusables.append(FocusableRect(self.pref_sound_rect, ('sound', None)))
            pref_focusables += [
                FocusableRect(rect, ('engine', name)) for name, rect in self.pref_engine_rects.items()
            ]
            self.pref_focus.rebuild(pref_focusables)
            self._draw_focus_ring(self.pref_focus)
        elif g.state in (GameState.PVP, GameState.BOT):
            self._render_game(dt)

    def _render_popups(self, dt: int) -> None:
        """Draw modal popups/overlays on top of the base screen. Called
        after _render_base with the real mouse position restored, so the
        popup's own buttons get hover highlighting."""
        g = self.game
        if g.continue_new_overlay and g.state in (GameState.MENU, GameState.OPPONENT_PICK):
            self.overlay_cont_btn, self.overlay_new_btn = render_overlays.draw_continue_new_overlay(
                self.screen, theme.WIN_W, theme.WIN_H, self.fonts
            )
        if g.main_menu_overlay and g.state in (GameState.PVP, GameState.BOT):
            (self.overlay_save_btn, self.overlay_export_btn,
             self.overlay_preferences_btn, self.overlay_draw_btn,
             self.overlay_resign_btn, self.overlay_quit_btn) = render_menus.draw_main_menu_overlay(
                self.screen, self.fonts, theme.PANEL_X
            )
            if g.confirm_dialog is not None:
                self.confirm_yes_btn, self.confirm_cancel_btn = render_overlays.draw_confirm_modal(
                    self.screen, theme.WIN_W, theme.WIN_H, g.confirm_dialog['message'], self.fonts,
                )
        if self.pending_corrupt_error is not None:
            render_overlays.draw_error_modal(
                self.screen, theme.WIN_W, theme.WIN_H, self.pending_corrupt_error, self.fonts
            )
        if self.pending_analysis_missing_modal:
            self.analysis_missing_ok_rect = render_overlays.draw_info_modal(
                self.screen, theme.WIN_W, theme.WIN_H, 'Stockfish Not Found',
                'Install Stockfish or set its path in Preferences to use analysis mode.',
                self.fonts,
            )

    def _draw_anim_items(self, anim, now_ms: int) -> None:
        """Blit each in-flight piece slide at its eased, interpolated
        position. AnimItem coordinates are absolute screen-pixel positions
        (see layout.sq_to_screen), so these are blitted onto self.screen
        directly rather than onto the cached board_surf."""
        t = (now_ms - anim.start_ms) / ANIM_MS
        eased = ease_out(t)
        for item in anim.items:
            if item.img is None:
                continue
            x = item.sx + (item.ex - item.sx) * eased
            y = item.sy + (item.ey - item.sy) * eased
            rect = item.img.get_rect(center=(x, y))
            self.screen.blit(item.img, rect)

    def _render_game(self, dt: int) -> None:
        g = self.game
        assert g.adapter is not None  # guaranteed by g.state in (PVP, BOT)
        now_ms = pygame.time.get_ticks()
        is_bot_mode = (g.state == GameState.BOT)

        # Only repaint the cached board surface when something that
        # affects its pixels has actually changed, instead of every frame.
        board, check_sq, last_move, sel_sq, targets = g.resolve_board_view()
        suppress = g.animation_suppress_set(now_ms)
        # While a drag is in flight, lift the dragged piece off its origin
        # square so it isn't drawn twice (once statically on the board, and
        # once at the cursor below). The selection highlight and valid-target
        # indicators are independent of `suppress` and remain visible.
        if self.drag_active and self.drag_sq is not None:
            suppress = {self.drag_sq} if suppress is None else suppress | {self.drag_sq}

        render_board.draw_labels(self.screen, g.board_flipped, self.fonts)

        render_board.draw_board(
            self.board_surf, board, g.piece_imgs, g.board_theme, g.board_flipped,
            check_sq, last_move, sel_sq, targets, suppress,
        )

        bot_color = 'black' if g.player_color == 'white' else 'white'
        top_thinking = is_bot_mode and g.bot_thinking and bot_color == ('black' if not g.board_flipped else 'white')
        bottom_thinking = is_bot_mode and g.bot_thinking and not top_thinking

        render_trays.draw_trays(
            self.screen, theme.PANEL_X, theme.WIN_H - theme.TRAY_H, g.adapter, g.board_flipped,
            self.fonts, self.assets.tray_imgs, top_thinking, bottom_thinking, g.think_dots,
        )
        # PvP-only; no-op for bot games and untimed PvP games (g.clock is
        # None in both cases). Drawn inside the same tray bars draw_trays
        # just painted, on the right-hand side - see render/clocks.py.
        render_clocks.draw_clocks(
            self.screen, theme.PANEL_X, theme.WIN_H - theme.TRAY_H, g, self.fonts, g.board_flipped,
        )

        menu_btn_w, menu_btn_h = 76, 18
        self.menu_btn_ingame_rect = pygame.Rect(
            theme.PANEL_X - menu_btn_w - 6, 2, menu_btn_w, menu_btn_h
        )

        # If a board-flip animation is in flight, scale the board and add a
        # darkening overlay so the orientation swap feels smooth.
        flip = g.flip
        if flip is not None and flip.is_active(now_ms):
            scale_x = flip.progress(now_ms)
            board_w = self.board_surf.get_width()
            board_h = self.board_surf.get_height()
            new_w = max(1, int(board_w * scale_x))
            squashed = pygame.transform.smoothscale(self.board_surf, (new_w, board_h))
            # Centre the scaled board horizontally.
            offset_x = (board_w - new_w) // 2
            self.screen.blit(squashed, (theme.BOARD_X + offset_x, theme.BOARD_Y))
            # Add a darkening overlay during the flip for a smoother feel.
            darkness = (1.0 - (scale_x - FLIP_MIN_SCALE) / (1.0 - FLIP_MIN_SCALE)) * 90
            if darkness > 1:
                veil = pygame.Surface((new_w, board_h), pygame.SRCALPHA)
                veil.fill((0, 0, 0, int(min(90, darkness))))
                self.screen.blit(veil, (theme.BOARD_X + offset_x, theme.BOARD_Y))
            # Suppress the move-slide animation and drag-piece overlay during
            # the flip — their absolute screen coordinates are in the pre-flip
            # orientation and would visually drift as the board scales.
        else:
            self.screen.blit(self.board_surf, (theme.BOARD_X, theme.BOARD_Y))
            if g.anim is not None and g.anim.is_animating(now_ms):
                self._draw_anim_items(g.anim, now_ms)

            # Draw menu and analysis buttons before the dragged piece so they
            # appear below (behind) the dragged piece in the z-order.
            mx_, my_ = pygame.mouse.get_pos()
            mm_hov = self.menu_btn_ingame_rect.collidepoint(mx_, my_)
            pygame.draw.rect(self.screen, (52, 52, 52) if mm_hov else (42, 42, 42),
                              self.menu_btn_ingame_rect, border_radius=6)
            pygame.draw.rect(self.screen, (90, 90, 90) if mm_hov else (62, 62, 62),
                              self.menu_btn_ingame_rect, 1, border_radius=6)
            mm_s = self.fonts.igmenu.render('\u2261  Menu', True, (210, 210, 210) if mm_hov else (140, 140, 140))
            self.screen.blit(mm_s, mm_s.get_rect(center=self.menu_btn_ingame_rect.center))

            # Analysis toggle, immediately to the left of the Menu button.
            an_btn_w, an_btn_h = 28, 18
            self.analysis_toggle_rect = pygame.Rect(
                self.menu_btn_ingame_rect.x - an_btn_w - 6, 2, an_btn_w, an_btn_h
            )
            an_hov = self.analysis_toggle_rect.collidepoint(mx_, my_)
            if g.analysis_enabled:
                an_bg = (58, 96, 58) if an_hov else (48, 82, 48)
                an_brd = (110, 170, 100)
                an_fg = (210, 240, 200)
            else:
                an_bg = (52, 52, 52) if an_hov else (42, 42, 42)
                an_brd = (90, 90, 90) if an_hov else (62, 62, 62)
                an_fg = (210, 210, 210) if an_hov else (140, 140, 140)
            pygame.draw.rect(self.screen, an_bg, self.analysis_toggle_rect, border_radius=6)
            pygame.draw.rect(self.screen, an_brd, self.analysis_toggle_rect, 1, border_radius=6)
            an_s = self.fonts.igmenu.render('A', True, an_fg)
            self.screen.blit(an_s, an_s.get_rect(center=self.analysis_toggle_rect.center))

            # Draw eval bar before the dragged piece so the dragged piece
            # renders on top of the eval bar.
            if g.analysis_enabled:
                g.update_eval_bar_smoothing(dt)
                render_board.draw_eval_bar(
                    self.screen, g.analysis_eval, g.board_flipped,
                    g.analysis_is_mate, g.analysis_mate_in, self.fonts,
                    display_ratio=g.eval_bar_display_ratio,
                )

            # While a drag is in flight, draw the lifted piece at the cursor on
            # top of the board (and any in-flight slide animation) but below the
            # labels, arrows, and any modal overlays that follow.
            if self.drag_active and self.drag_sq is not None:
                piece = board.piece_at(self.drag_sq)
                if piece is not None:
                    img = g.piece_imgs.get((piece.piece_type, piece.color))
                    if img is not None:
                        rect = img.get_rect(center=self.drag_pos)
                        self.screen.blit(img, rect)
        render_arrows.draw_board_arrow_overlay(self.screen, g.all_arrows, g.arrow_theme, g.board_flipped)

        self._history_ply_rects, self._live_btn_rect, g.panel_scroll = render_history.draw_history_panel(
            self.screen, theme.PANEL_X, theme.PANEL_W, theme.WIN_W, theme.WIN_H,
            g.adapter.san_history if g.adapter else None, g.review.ply, g.panel_scroll, self.fonts,
        )

        is_animating = g.anim is not None and g.anim.is_animating(now_ms)
        if g.adapter.promotion_pending and not is_animating:
            g.promo_rects = render_overlays.draw_promotion_overlay(
                self.screen, theme.BOARD_X, theme.BOARD_Y, g.adapter.turn,
                self.fonts, self.assets.promo_imgs_small,
            )
        else:
            g.promo_rects = []

        if g.review.ply is None:
            if not g.game_over and not g.adapter.promotion_pending and not is_animating:
                if g.adapter.is_game_over:
                    g.winner_result = g.adapter.game_result_text
                    g.game_over = True
            if g.game_over:
                if g.reduced_motion:
                    g.winner_alpha = 255
                else:
                    # Dt-scaled fade, not a flat per-frame increment
                    # (was `winner_alpha = min(winner_alpha + 3, 255)`, which
                    # took 1.4s at 60fps but 2.8s at 30fps).
                    g.winner_alpha = min(g.winner_alpha + dt * 0.18, 255)
                self.gameover_btn_rects = render_overlays.draw_winner(
                    self.screen, theme.WIN_W, theme.WIN_H, theme.PANEL_X,
                    g.winner_result, g.winner_alpha, self.fonts,
                )
            else:
                self.gameover_btn_rects = None
        else:
            # In review mode the winner overlay isn't drawn (see above),
            # so its buttons must not stay clickable underneath the board.
            self.gameover_btn_rects = None


def bootstrap() -> App:
    """Construct the App (and everything it owns). Safe to call multiple
    times in tests; each call produces an independent App/Game pair."""
    return App()


def main() -> None:
    app = bootstrap()
    app.run()
