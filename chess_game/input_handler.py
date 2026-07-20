"""Input/event handling separate from App.

InputHandler owns event dispatch and drag/promotion flow while operating
on App state.
"""
from __future__ import annotations

import sys

import chess
import pygame

from chess_game import io as save_io
from chess_game import layout, theme
from chess_game.review import enter_review, exit_review, move_review
from chess_game.state import GameState
from chess_game.stockfish_bot_worker import MAX_ELO, MIN_ELO
from chess_game.widgets import FocusGroup

# Minimum mouse movement (in pixels) before a mousedown is promoted to a drag.
# Below this, a press+release is treated as a pure click (preserving the
# existing click-to-select / click-to-move behaviour unchanged).
DRAG_THRESHOLD_PX = 5


class InputHandler:
    """Translate pygame events into App/Game state transitions."""

    def __init__(self, app) -> None:
        self.app = app

    # ── Drag-and-drop tracking ──────────────────────────────────────────────

    def _reset_drag(self) -> None:
        """Clear all drag-and-drop tracking state."""
        app = self.app
        app.drag_pending = False
        app.drag_active = False
        app.drag_sq = None

    def _start_drag(self, sq: int, mx: int, my: int) -> None:
        """Begin tracking a potential drag originating from `sq`.

        Called after a click selects a piece — the piece is not yet lifted
        off the board; that only happens once the cursor moves past
        DRAG_THRESHOLD_PX (see _update_drag_motion).
        """
        app = self.app
        app.drag_pending = True
        app.drag_active = False
        app.drag_sq = sq
        app.drag_pos = (mx, my)
        app.drag_start_pos = (mx, my)

    def _update_drag_motion(self, mx: int, my: int) -> None:
        """Promote a pending drag to active once the cursor has moved past
        the threshold, and keep the dragged piece's screen position current."""
        app = self.app
        if not app.drag_pending:
            return
        dx = mx - app.drag_start_pos[0]
        dy = my - app.drag_start_pos[1]
        if not app.drag_active and (dx * dx + dy * dy) >= (DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX):
            app.drag_active = True
        if app.drag_active:
            app.drag_pos = (mx, my)

    def _complete_drag(self, mx: int, my: int) -> None:
        """On left-button release, if a drag is in flight, attempt to move
        the dragged piece to the square under the cursor. The drag state is
        always reset afterward.

        Dropping on an invalid square or outside the board cancels the drag
        and leaves the piece selected, so the user can click a target square
        next (mirroring the forgiving behaviour of click-to-move).
        """
        app = self.app
        g = app.game
        if not app.drag_active or app.drag_sq is None or g.adapter is None:
            self._reset_drag()
            return

        bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
        if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
            target_sq = layout.pixel_to_sq(bx, by, g.board_flipped)
            if target_sq in g.adapter.valid_move_targets:
                result = g.adapter.handle_click(target_sq)
                if result in ('move', 'capture', 'en_passant'):
                    if g.state == GameState.PVP and g.clock is not None:
                        g.clock.switch()
                    piece = g.adapter.board.piece_at(g.adapter.anim_to)
                    img = g.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
                    # Slide the piece from the release position so it moves smoothly to the destination.
                    g.start_anim(g.adapter.anim_from, g.adapter.anim_to, img, start_pos=(mx, my))
                    is_check = g.adapter.check_square is not None
                    is_over = g.adapter.is_game_over
                    app.sounds.play_for_move_result(result, is_check=is_check, is_game_over=is_over)
                    app.write_save()
                    app._restart_analysis_if_enabled()
                    if g.state == GameState.BOT and not g.adapter.promotion_pending:
                        app.launch_bot_move()
                    elif g.state == GameState.PVP and not g.adapter.promotion_pending and not is_over:
                        # Queue a board flip for when the slide animation
                        # finishes so the next player sits at the bottom.
                        g.pending_pvp_flip = True
                # result == 'promotion' is also valid here: the promotion
                # overlay will be drawn next frame and the user picks a
                # piece via the existing keyboard / click flow.
        # Either way, the drag is finished.
        self._reset_drag()

    # ── Event dispatch ───────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event, mx: int, my: int) -> None:
        app = self.app
        g = app.game

        if event.type == pygame.QUIT:
            app.game.bot_worker.cancel()
            app.game.bot_worker.join(timeout=2.0)
            app.game.em_white_native_worker.cancel()
            app.game.em_white_native_worker.join(timeout=2.0)
            app.game.em_black_native_worker.cancel()
            app.game.em_black_native_worker.join(timeout=2.0)
            app.game.em_white_stockfish_worker.cancel()
            app.game.em_black_stockfish_worker.cancel()
            app.analysis_worker.stop_engine()
            pygame.quit()
            sys.exit()

        # F11 toggles fullscreen at any time, regardless of what screen or
        # popup is active.
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
            app._toggle_fullscreen()
            return

        # Clear arrows only on a board click, not on every left click.
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and g.state in (GameState.PVP, GameState.BOT, GameState.ENGINE_MATCH)):
            bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
            if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                g.arrow_start_sq = None
                g.all_arrows.clear()

        # Escape backs out of sub-screens / dismisses overlays.
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self._handle_escape():
                return

        # Tab/Shift+Tab cycles focus within whichever screen is active.
        if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
            focus_group = self._focus_group_for_state(g.state)
            if focus_group is not None:
                focus_group.handle_key(event)
                return

        if app.pending_corrupt_error is not None:
            self._handle_error_modal_event(event, mx, my)
            return

        if app.pending_analysis_missing_modal:
            self._handle_analysis_missing_modal_event(event, mx, my)
            return

        if g.continue_new_overlay:
            self._handle_continue_new_overlay_event(event, mx, my)
            return

        if g.confirm_dialog is not None:
            self._handle_confirm_dialog_event(event, mx, my)
            return

        if g.main_menu_overlay:
            self._handle_main_menu_overlay_event(event, mx, my)
            return

        if (event.type == pygame.MOUSEWHEEL and mx >= theme.PANEL_X
                and g.state in (GameState.PVP, GameState.BOT, GameState.ENGINE_MATCH)):
            if g.adapter:
                n_rows = (len(g.adapter.san_history) + 1) // 2
                list_h = theme.WIN_H - theme.HIST_HDR_H - theme.HIST_FOOT_H
                max_sc = max(0, n_rows * theme.HIST_ROW_H - list_h)
                g.panel_scroll = max(0, min(max_sc, g.panel_scroll - event.y * theme.HIST_ROW_H))
            return

        if g.state == GameState.MENU:
            self._handle_menu_event(event, mx, my)
        elif g.state == GameState.TIME_CONTROL_PICK:
            self._handle_time_control_pick_event(event, mx, my)
        elif g.state == GameState.COLOR_PICK:
            self._handle_color_pick_event(event, mx, my)
        elif g.state == GameState.DIFFICULTY:
            self._handle_difficulty_event(event, mx, my)
        elif g.state == GameState.STOCKFISH_DIFFICULTY:
            self._handle_stockfish_difficulty_event(event, mx, my)
        elif g.state == GameState.PREFERENCES:
            self._handle_preferences_event(event, mx, my)
        elif g.state == GameState.ENGINE_SETUP:
            self._handle_engine_setup_event(event, mx, my)
        elif g.state in (GameState.PVP, GameState.BOT):
            self._handle_game_event(event, mx, my)
        elif g.state == GameState.ENGINE_MATCH:
            self._handle_engine_match_event(event, mx, my)

    def _focus_group_for_state(self, state) -> FocusGroup | None:
        """Return the FocusGroup that owns Tab-cycling for the given screen,
        or None for screens with no focusable widgets (e.g. PVP/BOT board)."""
        app = self.app
        return {
            GameState.MENU: app.menu_focus,
            GameState.TIME_CONTROL_PICK: app.tc_focus,
            GameState.COLOR_PICK: app.picker_focus,
            GameState.DIFFICULTY: app.diff_focus,
            GameState.STOCKFISH_DIFFICULTY: app.sf_diff_focus,
            GameState.ENGINE_SETUP: app.em_setup_focus,
            GameState.PREFERENCES: app.pref_focus,
        }.get(state)

    def _handle_escape(self) -> bool:
        app = self.app
        g = app.game
        if app.pending_corrupt_error is not None:
            app.pending_corrupt_error = None
            return True
        if app.pending_analysis_missing_modal:
            app.pending_analysis_missing_modal = False
            return True
        if g.continue_new_overlay:
            g.continue_new_overlay = False
            g.pending_save_data = None
            return True
        if g.confirm_dialog is not None:
            g.confirm_dialog = None
            return True
        if g.main_menu_overlay:
            g.main_menu_overlay = False
            return True
        if g.state == GameState.TIME_CONTROL_PICK:
            app.tc_focus.clear()
            g.state = GameState.MENU
            return True
        if g.state == GameState.COLOR_PICK:
            app.picker_focus.clear()
            g.state = GameState.MENU
            return True
        if g.state == GameState.DIFFICULTY:
            app.diff_focus.clear()
            g.state = GameState.COLOR_PICK
            return True
        if g.state == GameState.STOCKFISH_DIFFICULTY:
            app.sf_diff_focus.clear()
            g.state = GameState.COLOR_PICK
            return True
        if g.state == GameState.ENGINE_SETUP:
            app.em_setup_focus.clear()
            app.em_setup_dragging_side = None
            g.state = GameState.MENU
            return True
        if g.state == GameState.PREFERENCES:
            app.pref_focus.clear()
            g.state = g.preferences_return_state or GameState.MENU
            g.preferences_return_state = None
            return True
        if g.state in (GameState.PVP, GameState.BOT, GameState.ENGINE_MATCH):
            if g.review.active:
                exit_review(g)
                return True
            g.main_menu_overlay = True
            # Cancel any in-flight drag — the overlay will swallow the
            # subsequent mouseup, so the drag would otherwise leak.
            self._reset_drag()
            return True
        return False

    def _handle_error_modal_event(self, event, mx, my) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.app.pending_corrupt_error = None

    def _handle_analysis_missing_modal_event(self, event, mx, my) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.app.pending_analysis_missing_modal = False

    def _handle_continue_new_overlay_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.overlay_cont_btn and app.overlay_cont_btn.collidepoint(mx, my):
                assert isinstance(g.pending_save_data, save_io.SaveData)
                assert g.pending_mode is not None
                app.continue_saved_game(g.pending_save_data, g.pending_mode)
                g.continue_new_overlay = False
                g.pending_save_data = None
            elif app.overlay_new_btn and app.overlay_new_btn.collidepoint(mx, my):
                mode_str = 'bot' if g.pending_mode == GameState.BOT else 'pvp'
                save_io.delete_save(mode_str)
                if g.pending_mode == GameState.PVP:
                    # A new friend game should use the normal launcher flow
                    # and let the players choose a clock, rather than silently
                    # inheriting an implicit untimed game from the old save.
                    g.state = GameState.TIME_CONTROL_PICK
                else:
                    g.state = GameState.COLOR_PICK
                g.continue_new_overlay = False
                g.pending_save_data = None

    def _handle_main_menu_overlay_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        if g.state == GameState.ENGINE_MATCH:
            self._handle_engine_match_menu_overlay_event(event, mx, my)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.overlay_save_btn and app.overlay_save_btn.collidepoint(mx, my):
                app.write_save()
                g.review.reset()
                g.state = GameState.MENU
                g.main_menu_overlay = False
            elif app.overlay_export_btn and app.overlay_export_btn.collidepoint(mx, my):
                # Export and stay in the overlay/game — unlike Save & Quit
                # and Quit, exporting a PGN isn't a reason to leave the
                # current game in progress.
                app.export_pgn()
                g.main_menu_overlay = False
            elif app.overlay_preferences_btn and app.overlay_preferences_btn.collidepoint(mx, my):
                # Preferences' own Back button returns here (see
                # Game.preferences_return_state), so the overlay itself
                # can close now rather than staying "open" underneath.
                g.preferences_return_state = g.state
                g.main_menu_overlay = False
                app.pref_focus.clear()
                g.state = GameState.PREFERENCES
            elif app.overlay_draw_btn and app.overlay_draw_btn.collidepoint(mx, my):
                g.confirm_dialog = {
                    'action': 'draw',
                    'message': 'End the game as a draw by agreement?',
                }
            elif app.overlay_resign_btn and app.overlay_resign_btn.collidepoint(mx, my):
                if g.state == GameState.PVP and g.adapter is not None:
                    resigning = g.adapter.turn.capitalize()
                    msg = f'{resigning} resigns and loses the game. Continue?'
                else:
                    msg = 'Resign this game? The bot will be awarded the win.'
                g.confirm_dialog = {'action': 'resign', 'message': msg}
            elif app.overlay_quit_btn and app.overlay_quit_btn.collidepoint(mx, my):
                g.confirm_dialog = {
                    'action': 'quit_without_saving',
                    'message': "Discard this game without saving? This can't be undone.",
                }
            else:
                bw_chk, bh_chk = 320, 430
                box_r = pygame.Rect(
                    theme.PANEL_X // 2 - bw_chk // 2, theme.WIN_H // 2 - bh_chk // 2,
                    bw_chk, bh_chk,
                )
                if not box_r.collidepoint(mx, my):
                    g.main_menu_overlay = False

    def _handle_engine_match_menu_overlay_event(self, event, mx, my) -> None:
        """Reduced-overlay counterpart of _handle_main_menu_overlay_event
        for GameState.ENGINE_MATCH — see draw_engine_match_menu_overlay
        for why Save/Draw/Resign don't apply to this mode.

        Quit acts immediately (no confirm_dialog): unlike PVP/BOT's "Quit
        Without Saving", there's no unsaved game to lose here — engine
        matches were never going to be persisted as a resumable save in
        the first place (see Game's em_* fields docstring), so there's
        nothing a confirmation would be protecting the person from.
        """
        app = self.app
        g = app.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.em_overlay_export_btn and app.em_overlay_export_btn.collidepoint(mx, my):
                app.export_engine_match_pgn()
                g.main_menu_overlay = False
            elif app.em_overlay_quit_btn and app.em_overlay_quit_btn.collidepoint(mx, my):
                app.stop_engine_match()
                g.main_menu_overlay = False
                g.state = GameState.MENU
            else:
                bw_chk, bh_chk = 320, 180
                box_r = pygame.Rect(
                    theme.PANEL_X // 2 - bw_chk // 2, theme.WIN_H // 2 - bh_chk // 2,
                    bw_chk, bh_chk,
                )
                if not box_r.collidepoint(mx, my):
                    g.main_menu_overlay = False

    def _start_rematch(self) -> None:
        """Start a fresh game with the same settings as the one that just
        ended (same PvP time control, or same bot colour/level/engine),
        without sending the player back through the opponent/color/
        difficulty pickers. Mirrors _confirm_difficulty /
        _confirm_stockfish_difficulty / the PVP time-control confirm."""
        app = self.app
        g = app.game
        if g.state == GameState.PVP:
            g.board_flipped = False
            app.start_game()
            g.maybe_create_clock(g.time_control)
        elif g.state == GameState.BOT:
            app.start_game()
            if g.player_color == 'black':
                app.launch_bot_move()

    def _handle_confirm_dialog_event(self, event, mx, my) -> None:
        """Handle the Yes/Cancel confirmation raised for Resign, Offer
        Draw, and Quit Without Saving. Cancelling (or clicking outside
        both buttons) just clears the dialog and returns to the in-game
        menu overlay underneath, without side effects."""
        app = self.app
        g = app.game
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if app.confirm_yes_btn and app.confirm_yes_btn.collidepoint(mx, my):
            self._perform_confirmed_action()
        elif app.confirm_cancel_btn and app.confirm_cancel_btn.collidepoint(mx, my):
            g.confirm_dialog = None

    def _perform_confirmed_action(self) -> None:
        app = self.app
        g = app.game
        assert g.confirm_dialog is not None
        action = g.confirm_dialog['action']
        g.confirm_dialog = None
        g.main_menu_overlay = False
        if action == 'resign':
            resigning_color = g.adapter.turn if g.state == GameState.PVP else g.player_color
            g.resign(resigning_color)
            # Resignation (like a draw by agreement) has no representation
            # in the replayable move stack a save is built from, so the
            # save is discarded rather than written — see Game.resign.
            mode_str = 'bot' if g.state == GameState.BOT else 'pvp'
            save_io.delete_save(mode_str)
        elif action == 'draw':
            g.agree_draw()
            mode_str = 'bot' if g.state == GameState.BOT else 'pvp'
            save_io.delete_save(mode_str)
        elif action == 'quit_without_saving':
            mode_str = 'bot' if g.state == GameState.BOT else 'pvp'
            save_io.delete_save(mode_str)
            g.review.reset()
            g.state = GameState.MENU

    def _handle_menu_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        # The home screen is a direct mode launcher. Each card enters only
        # the setup that applies to that mode; saved games still get the
        # same continue/new choice before a fresh setup is opened.
        if app.menu_buttons[0].clicked(event) or app.menu_buttons[0].activated_by_key(event):
            save = app.safe_read_save('pvp')
            if save:
                g.pending_mode = GameState.PVP
                g.pending_save_data = save
                g.continue_new_overlay = True
            elif app.pending_corrupt_error is None:
                g.state = GameState.TIME_CONTROL_PICK
        elif app.menu_buttons[1].clicked(event) or app.menu_buttons[1].activated_by_key(event):
            save = app.safe_read_save('bot')
            if save:
                g.pending_mode = GameState.BOT
                g.pending_save_data = save
                g.continue_new_overlay = True
            elif app.pending_corrupt_error is None:
                g.state = GameState.COLOR_PICK
        elif app.menu_buttons[2].clicked(event) or app.menu_buttons[2].activated_by_key(event):
            g.state = GameState.ENGINE_SETUP
        elif app.menu_buttons[3].clicked(event) or app.menu_buttons[3].activated_by_key(event):
            g.state = GameState.PREFERENCES

    def _handle_time_control_pick_event(self, event, mx, my) -> None:
        """Handle the PvP time-control preset screen. Bot games never
        reach this handler - it is only wired up for GameState.TIME_CONTROL_PICK,
        which is entered from the Play a Friend home card."""
        app = self.app
        g = app.game
        activated_key: str | tuple[str, str] | None = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.tc_back and app.tc_back.collidepoint(mx, my):
                activated_key = 'back'
            elif app.tc_confirm_rect and app.tc_confirm_rect.collidepoint(mx, my):
                activated_key = 'confirm'
            else:
                for key, rect in app.tc_choice_rects.items():
                    if rect.collidepoint(mx, my):
                        activated_key = ('choice', key)
                        break
        else:
            for focusable in app.tc_focus.widgets:
                if focusable.activated_by_key(event):
                    activated_key = focusable.key
                    break

        if activated_key == 'back':
            app.tc_focus.clear()
            g.state = GameState.MENU
        elif activated_key == 'confirm':
            self._confirm_time_control()
        elif isinstance(activated_key, tuple) and activated_key[0] == 'choice':
            app.tc_choice = activated_key[1]

    def _confirm_time_control(self) -> None:
        """Start a fresh PvP game with the currently selected time control.

        Persists the choice to preferences (as the user's default for next
        time) and constructs the Clock (or leaves it untimed for "none")
        immediately after start_game() resets it to None.
        """
        app = self.app
        g = app.game
        app.tc_focus.clear()
        g.board_flipped = False
        g.state = GameState.PVP
        app.start_game()
        g.maybe_create_clock(app.tc_choice)
        save_io.write_preferences(g.board_theme, g.arrow_theme, g.reduced_motion,
                                  app._fullscreen, g.stockfish_path,
                                  g.bot_engine_pref, g.bot_elo,
                                  app.tc_choice, sound_enabled=g.sound_enabled)

    def _handle_color_pick_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        activated_key = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.picker_back and app.picker_back.collidepoint(mx, my):
                activated_key = 'back'
            else:
                for color, rect in app.picker_rects.items():
                    if rect.collidepoint(mx, my):
                        activated_key = color
                        break
        else:
            for focusable in app.picker_focus.widgets:
                if focusable.activated_by_key(event):
                    activated_key = focusable.key
                    break

        if activated_key == 'back':
            app.picker_focus.clear()
            g.state = GameState.MENU
        elif activated_key in ('white', 'black'):
            g.player_color = activated_key
            g.board_flipped = (activated_key == 'black')
            app.picker_focus.clear()
            if g.bot_engine_pref == 'stockfish':
                g.state = GameState.STOCKFISH_DIFFICULTY
            else:
                g.state = GameState.DIFFICULTY

    def _handle_difficulty_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.diff_back and app.diff_back.collidepoint(mx, my):
                app.diff_focus.clear()
                g.state = GameState.COLOR_PICK
            elif app.diff_confirm_rect and app.diff_confirm_rect.collidepoint(mx, my):
                self._confirm_difficulty()
            elif app.diff_slider_rect and app.diff_slider_rect.collidepoint(mx, my):
                app.diff_slider_dragging = True
                if app.diff_slider_info:
                    sl_x, sl_w, _ = app.diff_slider_info
                    t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                    # Round half-up, not banker's rounding.
                    app.diff_level = int(t * 9 + 0.5) + 1
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            app.diff_slider_dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if app.diff_slider_dragging and app.diff_slider_info:
                sl_x, sl_w, _ = app.diff_slider_info
                t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                app.diff_level = int(t * 9 + 0.5) + 1
        else:
            for focusable in app.diff_focus.widgets:
                if focusable.activated_by_key(event):
                    if focusable.key == 'back':
                        app.diff_focus.clear()
                        g.state = GameState.COLOR_PICK
                    elif focusable.key == 'confirm':
                        self._confirm_difficulty()
                    break

    def _confirm_difficulty(self) -> None:
        app = self.app
        g = app.game
        g.bot_level = app.diff_level
        app.diff_focus.clear()
        g.state = GameState.BOT
        app.start_game()
        if g.player_color == 'black':
            app.launch_bot_move()

    def _handle_stockfish_difficulty_event(self, event, mx, my) -> None:
        """ELO-slider equivalent of _handle_difficulty_event — same
        click/drag/keyboard shapes, just reading/writing g.bot_elo over
        [MIN_ELO, MAX_ELO] instead of g.bot_level over 1-10."""
        app = self.app
        g = app.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.sf_diff_back and app.sf_diff_back.collidepoint(mx, my):
                app.sf_diff_focus.clear()
                g.state = GameState.COLOR_PICK
            elif app.sf_diff_confirm_rect and app.sf_diff_confirm_rect.collidepoint(mx, my):
                self._confirm_stockfish_difficulty()
            elif app.sf_diff_slider_rect and app.sf_diff_slider_rect.collidepoint(mx, my):
                app.sf_diff_slider_dragging = True
                if app.sf_diff_slider_info:
                    sl_x, sl_w, _ = app.sf_diff_slider_info
                    t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                    g.bot_elo = int(round(MIN_ELO + t * (MAX_ELO - MIN_ELO)))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            app.sf_diff_slider_dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if app.sf_diff_slider_dragging and app.sf_diff_slider_info:
                sl_x, sl_w, _ = app.sf_diff_slider_info
                t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                g.bot_elo = int(round(MIN_ELO + t * (MAX_ELO - MIN_ELO)))
        else:
            for focusable in app.sf_diff_focus.widgets:
                if focusable.activated_by_key(event):
                    if focusable.key == 'back':
                        app.sf_diff_focus.clear()
                        g.state = GameState.COLOR_PICK
                    elif focusable.key == 'confirm':
                        self._confirm_stockfish_difficulty()
                    break

    def _confirm_stockfish_difficulty(self) -> None:
        app = self.app
        g = app.game
        app.sf_diff_focus.clear()
        g.state = GameState.BOT
        app.start_game()
        if g.player_color == 'black':
            app.launch_bot_move()

    def _handle_engine_setup_event(self, event, mx, my) -> None:
        """Configure both sides' engine kind and level/ELO, then start.

        The screen supports the same keyboard pattern as the rest of the
        app: Tab reaches every control, Enter/Space selects a choice or
        starts the match, and arrow keys adjust the focused slider.

        app.em_setup_dragging_side tracks which side's slider (if any) is
        currently being dragged, since — unlike every single-slider
        screen (diff_slider_dragging, sf_diff_slider_dragging) — there
        are two independent sliders that could each be mid-drag here.
        """
        app = self.app
        g = app.game
        rects = app.em_setup_rects
        if not rects:
            return  # first frame after entering this state, nothing drawn yet

        if event.type == pygame.KEYDOWN:
            focused_key = None
            if 0 <= app.em_setup_focus.index < len(app.em_setup_focus.widgets):
                focused_key = app.em_setup_focus.widgets[app.em_setup_focus.index].key

            if (isinstance(focused_key, tuple) and focused_key[0] == 'slider'
                    and event.key in (pygame.K_LEFT, pygame.K_DOWN, pygame.K_RIGHT, pygame.K_UP)):
                direction = -1 if event.key in (pygame.K_LEFT, pygame.K_DOWN) else 1
                self._adjust_engine_setup_slider(focused_key[1], direction)
                return

            if event.key in (pygame.K_RETURN, pygame.K_SPACE) and focused_key:
                action = focused_key[0]
                if action == 'back':
                    app.em_setup_focus.clear()
                    g.state = GameState.MENU
                elif action == 'confirm':
                    self._confirm_engine_match_setup()
                elif action == 'engine':
                    side, kind = focused_key[1], focused_key[2]
                    if side == 'white':
                        g.em_white_kind = kind
                    else:
                        g.em_black_kind = kind
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if rects.get('back') and rects['back'].collidepoint(mx, my):
                app.em_setup_focus.clear()
                g.state = GameState.MENU
                return
            if rects.get('confirm') and rects['confirm'].collidepoint(mx, my):
                self._confirm_engine_match_setup()
                return
            for side in ('white', 'black'):
                engine_rects = rects.get(f'{side}_engine', {})
                for kind, rect in engine_rects.items():
                    if rect.collidepoint(mx, my):
                        if side == 'white':
                            g.em_white_kind = kind
                        else:
                            g.em_black_kind = kind
                        return
                slider_rect = rects.get(f'{side}_slider')
                if slider_rect and slider_rect.collidepoint(mx, my):
                    app.em_setup_dragging_side = side
                    self._apply_engine_setup_slider_value(side, mx)
                    return
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            app.em_setup_dragging_side = None
        elif event.type == pygame.MOUSEMOTION:
            if app.em_setup_dragging_side is not None:
                self._apply_engine_setup_slider_value(app.em_setup_dragging_side, mx)

    def _adjust_engine_setup_slider(self, side: str, direction: int) -> None:
        """Move one discrete step on an engine-setup slider from the keyboard."""
        g = self.app.game
        kind = g.em_white_kind if side == 'white' else g.em_black_kind
        if kind == 'stockfish':
            step = 10
            if side == 'white':
                g.em_white_elo = max(MIN_ELO, min(MAX_ELO, g.em_white_elo + direction * step))
            else:
                g.em_black_elo = max(MIN_ELO, min(MAX_ELO, g.em_black_elo + direction * step))
        elif side == 'white':
            g.em_white_level = max(1, min(10, g.em_white_level + direction))
        else:
            g.em_black_level = max(1, min(10, g.em_black_level + direction))

    def _apply_engine_setup_slider_value(self, side: str, mx: int) -> None:
        """Convert a slider click/drag x-coordinate into a level (native)
        or ELO (stockfish) value for the given side, exactly like
        _handle_difficulty_event / _handle_stockfish_difficulty_event do
        for their own single slider — duplicated per-side here rather
        than factored out since each side also has to pick which of its
        two fields (level vs elo) the value even applies to."""
        app = self.app
        g = app.game
        slider_info = app.em_setup_slider_info.get(side)
        if not slider_info:
            return
        sl_x, sl_w, _sl_y = slider_info
        t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
        kind = g.em_white_kind if side == 'white' else g.em_black_kind
        if kind == 'stockfish':
            value = int(round(MIN_ELO + t * (MAX_ELO - MIN_ELO)))
            if side == 'white':
                g.em_white_elo = value
            else:
                g.em_black_elo = value
        else:
            value = int(t * 9 + 0.5) + 1  # round half-up, not banker's rounding
            if side == 'white':
                g.em_white_level = value
            else:
                g.em_black_level = value

    def _confirm_engine_match_setup(self) -> None:
        """Start a fresh engine-vs-engine match with both sides'
        currently-configured engine/level/ELO. Board orientation is
        always the standard White-at-bottom view — there's no player
        color to orient around, unlike BOT mode's board_flipped."""
        app = self.app
        g = app.game
        app.em_setup_focus.clear()
        g.board_flipped = False
        g.state = GameState.ENGINE_MATCH
        app.start_game()
        g.launch_engine_match_move('white')

    def _handle_preferences_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        activated_key = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.pref_back_rect and app.pref_back_rect.collidepoint(mx, my):
                activated_key = ('back', None)
            else:
                for theme_name, rect in app.pref_board_rects.items():
                    if rect.collidepoint(mx, my):
                        activated_key = ('board', theme_name)
                        break
                if activated_key is None:
                    for theme_name, rect in app.pref_arrow_rects.items():
                        if rect.collidepoint(mx, my):
                            activated_key = ('arrow', theme_name)
                            break
                if activated_key is None and app.pref_motion_rect and app.pref_motion_rect.collidepoint(mx, my):
                    activated_key = ('motion', None)
                if activated_key is None and app.pref_sound_rect and app.pref_sound_rect.collidepoint(mx, my):
                    activated_key = ('sound', None)
                if (activated_key is None and app.pref_download_rect
                        and app.pref_download_rect.collidepoint(mx, my)):
                    activated_key = ('download_stockfish', None)
                if activated_key is None:
                    for engine_key, rect in app.pref_engine_rects.items():
                        if rect.collidepoint(mx, my):
                            activated_key = ('engine', engine_key)
                            break
        else:
            for focusable in app.pref_focus.widgets:
                if focusable.activated_by_key(event):
                    activated_key = focusable.key
                    break

        if activated_key is None:
            return
        kind, value = activated_key
        if kind == 'back':
            app.pref_focus.clear()
            # Opened from the in-game menu -> return to the game in
            # progress rather than always landing on the main menu.
            g.state = g.preferences_return_state or GameState.MENU
            g.preferences_return_state = None
            return
        changed = False
        if kind == 'board':
            assert value is not None
            g.board_theme = value
            app._board_surf_dirty = True
            changed = True
        elif kind == 'arrow':
            assert value is not None
            g.arrow_theme = value
            changed = True
        elif kind == 'motion':
            g.reduced_motion = not g.reduced_motion
            if g.reduced_motion:
                g.winner_alpha = 255
            changed = True
        elif kind == 'sound':
            g.sound_enabled = not g.sound_enabled
            app.sounds.set_muted(not g.sound_enabled)
            changed = True
        elif kind == 'download_stockfish':
            app._start_stockfish_download()
            return
        elif kind == 'engine':
            assert value is not None
            g.bot_engine_pref = value
            changed = True
        if changed:
            save_io.write_preferences(g.board_theme, g.arrow_theme, g.reduced_motion,
                                      app._fullscreen, g.stockfish_path,
                                      g.bot_engine_pref, g.bot_elo,
                                      sound_enabled=g.sound_enabled)

    def _complete_promotion(self, piece_type) -> None:
        """Complete a pending promotion with the given piece type, whether
        triggered by a click on the promotion overlay or a Q/R/B/N keypress."""
        app = self.app
        g = app.game
        assert g.adapter is not None
        result = g.adapter.complete_promotion(piece_type)
        if g.state == GameState.PVP and g.clock is not None:
            g.clock.switch()
        is_check = g.adapter.check_square is not None
        app.sounds.play_for_move_result(result, is_check=is_check)
        promo_piece_color = (chess.WHITE if g.adapter.turn == 'black' else chess.BLACK)
        promo_img = g.piece_imgs.get((piece_type, promo_piece_color))
        g.start_anim(g.adapter.anim_from, g.adapter.anim_to, promo_img)
        app.write_save()
        app._restart_analysis_if_enabled()
        if g.state == GameState.BOT and g.adapter.turn != g.player_color:
            app.launch_bot_move()
        elif g.state == GameState.PVP and not g.adapter.is_game_over:
            g.pending_pvp_flip = True

    def _handle_engine_match_event(self, event, mx, my) -> None:
        """GameState.ENGINE_MATCH's event handler — a deliberately reduced
        sibling of _handle_game_event: the in-game menu button, history
        panel review (click a ply, scrub with Left/Right, live button),
        and right-click arrows all work exactly like PVP/BOT, but there
        is no click-to-select, drag-and-drop, or promotion overlay at
        all, since neither side is a human — every move arrives from
        App._apply_engine_match_move, never from a board click.
        """
        app = self.app
        g = app.game
        assert g.adapter is not None  # guaranteed by g.state == ENGINE_MATCH

        if event.type == pygame.KEYDOWN and event.key in (pygame.K_LEFT, pygame.K_RIGHT):
            move_review(g, -1 if event.key == pygame.K_LEFT else 1)
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.analysis_toggle_rect and app.analysis_toggle_rect.collidepoint(mx, my):
                app._toggle_analysis()
            elif app.em_pause_btn_rect and app.em_pause_btn_rect.collidepoint(mx, my):
                g.em_paused = not g.em_paused
            elif (app.em_step_btn_rect and g.em_paused
                    and app.em_step_btn_rect.collidepoint(mx, my)):
                # Step is a no-op while running (not paused) — guarded
                # here to match the dimmed/non-interactive look
                # App._render_game gives it in that state, so a click
                # that lands on its rect while running does nothing
                # rather than silently queuing a step for whenever the
                # person pauses next.
                g.em_step_requested = True
            elif app.menu_btn_ingame_rect and app.menu_btn_ingame_rect.collidepoint(mx, my):
                g.main_menu_overlay = True
            elif mx >= theme.PANEL_X:
                if (app._live_btn_rect and app._live_btn_rect.collidepoint(mx, my)
                        and g.review.active):
                    exit_review(g)
                else:
                    for rect, ply in app._history_ply_rects:
                        if rect.collidepoint(mx, my):
                            enter_review(g, ply)
                            break
            elif g.game_over and app.gameover_btn_rects:
                rects = app.gameover_btn_rects
                if rects['menu'].collidepoint(mx, my):
                    g.review.reset()
                    g.state = GameState.MENU
                elif rects['rematch'].collidepoint(mx, my):
                    self._start_engine_match_rematch()
                elif rects['review'].collidepoint(mx, my):
                    enter_review(g, len(g.adapter.san_history))
            # No board-click branch at all: nothing to select or drag.

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
            if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                g.arrow_start_sq = layout.pixel_to_sq(bx, by, g.board_flipped)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            if g.arrow_start_sq is not None:
                bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
                if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                    end_sq = layout.pixel_to_sq(bx, by, g.board_flipped)
                    if end_sq != g.arrow_start_sq:
                        g.all_arrows.append((g.arrow_start_sq, end_sq))
                g.arrow_start_sq = None

    def _start_engine_match_rematch(self) -> None:
        """Start a fresh match with the same two engine configurations as
        the one that just ended, without going back through
        ENGINE_SETUP — mirrors _start_rematch's PVP/BOT behaviour."""
        app = self.app
        g = app.game
        app.start_game()
        g.launch_engine_match_move('white')

    def _handle_game_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        assert g.adapter is not None  # guaranteed by g.state in (PVP, BOT)
        now_ms = pygame.time.get_ticks()
        is_animating = g.anim is not None and g.anim.is_animating(now_ms)
        # Block piece interaction while a board flip is in progress.
        # Menu, history, and overlay controls still work.
        flip_in_progress = g.flip is not None and g.flip.is_active(now_ms)

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                move_review(g, -1 if event.key == pygame.K_LEFT else 1)
            elif g.adapter.promotion_pending:
                promo_key_map = {
                    pygame.K_q: chess.QUEEN,
                    pygame.K_r: chess.ROOK,
                    pygame.K_b: chess.BISHOP,
                    pygame.K_n: chess.KNIGHT,
                }
                pt = promo_key_map.get(event.key)
                if pt is not None:
                    self._complete_promotion(pt)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # A fresh press ends any previous drag cycle (e.g. a mouseup that
            # was swallowed by an overlay). The state is re-armed below only
            # if this press selects a piece.
            self._reset_drag()
            if app.analysis_toggle_rect and app.analysis_toggle_rect.collidepoint(mx, my):
                app._toggle_analysis()
            elif app.menu_btn_ingame_rect and app.menu_btn_ingame_rect.collidepoint(mx, my):
                g.main_menu_overlay = True
            elif mx >= theme.PANEL_X:
                if (app._live_btn_rect and app._live_btn_rect.collidepoint(mx, my)
                        and g.review.active):
                    exit_review(g)
                else:
                    for rect, ply in app._history_ply_rects:
                        if rect.collidepoint(mx, my):
                            enter_review(g, ply)
                            break
            elif g.game_over and app.gameover_btn_rects:
                rects = app.gameover_btn_rects
                if rects['menu'].collidepoint(mx, my):
                    g.review.reset()
                    g.state = GameState.MENU
                elif rects['rematch'].collidepoint(mx, my):
                    self._start_rematch()
                elif rects['review'].collidepoint(mx, my):
                    enter_review(g, len(g.adapter.san_history))
            elif g.review.active or is_animating or g.game_over or flip_in_progress:
                # While the board-flip animation is in-flight, block all piece
                # interaction — the board is rotating and clicks would land on
                # the wrong squares. This also prevents the rapid-move race
                # condition at the input level (no new moves can be queued
                # while a flip is playing).
                pass
            elif g.adapter.promotion_pending:
                for rect, pt in g.promo_rects:
                    if rect.collidepoint(mx, my):
                        self._complete_promotion(pt)
                        break
            else:
                bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
                if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                    # Avoid a precedence bug that could drop PvP clicks when
                    # a stale bot_thinking flag was present.
                    bot_to_move = (g.state == GameState.BOT and g.adapter.turn != g.player_color)
                    if bot_to_move or (g.state == GameState.BOT and g.bot_thinking):
                        pass
                    else:
                        sq = layout.pixel_to_sq(bx, by, g.board_flipped)
                        result = g.adapter.handle_click(sq)
                        if result in ('move', 'capture', 'en_passant'):
                            if g.state == GameState.PVP and g.clock is not None:
                                g.clock.switch()
                            piece = g.adapter.board.piece_at(g.adapter.anim_to)
                            img = g.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
                            g.start_anim(g.adapter.anim_from, g.adapter.anim_to, img)
                            is_check = g.adapter.check_square is not None
                            is_over = g.adapter.is_game_over
                            app.sounds.play_for_move_result(result, is_check=is_check, is_game_over=is_over)
                            app.write_save()
                            app._restart_analysis_if_enabled()
                            if g.state == GameState.BOT and not g.adapter.promotion_pending:
                                app.launch_bot_move()
                            elif g.state == GameState.PVP and not g.adapter.promotion_pending and not is_over:
                                # Queue a board flip for when the slide
                                # animation finishes so the next player
                                # sits at the bottom on their turn.
                                g.pending_pvp_flip = True
                        elif result == 'selected':
                            # A piece was selected — arm a potential drag so
                            # the user can either release (pure click, piece
                            # stays selected) or drag the piece to a target.
                            self._start_drag(g.adapter.selected_square, mx, my)
                        # 'deselected', 'promotion', and None leave the drag
                        # state already reset by the _reset_drag() above.

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
            bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
            if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                g.arrow_start_sq = layout.pixel_to_sq(bx, by, g.board_flipped)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            if g.arrow_start_sq is not None:
                bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
                if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                    end_sq = layout.pixel_to_sq(bx, by, g.board_flipped)
                    if end_sq != g.arrow_start_sq:
                        g.all_arrows.append((g.arrow_start_sq, end_sq))
                g.arrow_start_sq = None

        elif event.type == pygame.MOUSEMOTION:
            # Live cursor tracking for an armed or active drag. Below the
            # threshold the piece stays on its square (pure-click path).
            # Suppress during a board flip — no drag can be in progress
            # (mousedown was blocked), but this is defensive.
            if not flip_in_progress:
                self._update_drag_motion(mx, my)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # Release after a drag: attempt the move if the cursor is over a
            # valid target, otherwise cancel and leave the piece selected.
            # If the press never crossed the drag threshold, drag_active is
            # False and this is a no-op (the mousedown already did the work).
            # Block during a board flip — the piece shouldn't move while
            # the board is rotating.
            if not flip_in_progress:
                self._complete_drag(mx, my)
