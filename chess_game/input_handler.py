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
                and g.state in (GameState.PVP, GameState.BOT)):
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

        if g.main_menu_overlay:
            self._handle_main_menu_overlay_event(event, mx, my)
            return

        if (event.type == pygame.MOUSEWHEEL and mx >= theme.PANEL_X
                and g.state in (GameState.PVP, GameState.BOT)):
            if g.adapter:
                n_rows = (len(g.adapter.san_history) + 1) // 2
                list_h = theme.WIN_H - theme.HIST_HDR_H - theme.HIST_FOOT_H
                max_sc = max(0, n_rows * theme.HIST_ROW_H - list_h)
                g.panel_scroll = max(0, min(max_sc, g.panel_scroll - event.y * theme.HIST_ROW_H))
            return

        if g.state == GameState.MENU:
            self._handle_menu_event(event, mx, my)
        elif g.state == GameState.OPPONENT_PICK:
            self._handle_opponent_pick_event(event, mx, my)
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
        elif g.state in (GameState.PVP, GameState.BOT):
            self._handle_game_event(event, mx, my)

    def _focus_group_for_state(self, state) -> FocusGroup | None:
        """Return the FocusGroup that owns Tab-cycling for the given screen,
        or None for screens with no focusable widgets (e.g. PVP/BOT board)."""
        app = self.app
        return {
            GameState.MENU: app.menu_focus,
            GameState.OPPONENT_PICK: app.opponent_focus,
            GameState.TIME_CONTROL_PICK: app.tc_focus,
            GameState.COLOR_PICK: app.picker_focus,
            GameState.DIFFICULTY: app.diff_focus,
            GameState.STOCKFISH_DIFFICULTY: app.sf_diff_focus,
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
        if g.main_menu_overlay:
            g.main_menu_overlay = False
            return True
        if g.state == GameState.OPPONENT_PICK:
            app.opponent_focus.clear()
            g.state = GameState.MENU
            return True
        if g.state == GameState.TIME_CONTROL_PICK:
            app.tc_focus.clear()
            g.state = GameState.OPPONENT_PICK
            return True
        if g.state == GameState.COLOR_PICK:
            app.picker_focus.clear()
            g.state = GameState.OPPONENT_PICK
            return True
        if g.state == GameState.DIFFICULTY:
            app.diff_focus.clear()
            g.state = GameState.COLOR_PICK
            return True
        if g.state == GameState.STOCKFISH_DIFFICULTY:
            app.sf_diff_focus.clear()
            g.state = GameState.COLOR_PICK
            return True
        if g.state == GameState.PREFERENCES:
            app.pref_focus.clear()
            g.state = GameState.MENU
            return True
        if g.state in (GameState.PVP, GameState.BOT):
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
                    g.board_flipped = False
                    g.state = GameState.PVP
                    app.start_game()
                else:
                    g.state = GameState.COLOR_PICK
                g.continue_new_overlay = False
                g.pending_save_data = None

    def _handle_main_menu_overlay_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
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
            elif app.overlay_quit_btn and app.overlay_quit_btn.collidepoint(mx, my):
                mode_str = 'bot' if g.state == GameState.BOT else 'pvp'
                save_io.delete_save(mode_str)
                g.review.reset()
                g.state = GameState.MENU
                g.main_menu_overlay = False
            else:
                bx_chk = theme.PANEL_X // 2
                by_chk = theme.WIN_H // 2
                bw_chk, bh_chk = 310, 260
                box_r = pygame.Rect(bx_chk - bw_chk // 2, by_chk - bh_chk // 2, bw_chk, bh_chk)
                if not box_r.collidepoint(mx, my):
                    g.main_menu_overlay = False

    def _handle_menu_event(self, event, mx, my) -> None:
        app = self.app
        g = app.game
        # Button 0: Local Play → opponent picker (player vs bot choice happens there)
        if app.menu_buttons[0].clicked(event) or app.menu_buttons[0].activated_by_key(event):
            g.state = GameState.OPPONENT_PICK
        # Button 1: Online Play — disabled (Coming soon). Button.clicked /
        # activated_by_key already return False for disabled buttons, so this
        # branch is effectively unreachable, but kept for clarity.
        elif app.menu_buttons[1].clicked(event) or app.menu_buttons[1].activated_by_key(event):
            pass
        # Button 2: Preferences
        elif app.menu_buttons[2].clicked(event) or app.menu_buttons[2].activated_by_key(event):
            g.state = GameState.PREFERENCES

    def _handle_opponent_pick_event(self, event, mx, my) -> None:
        """Handle the 'Select Opponent' screen (Player vs Bot).

        Choosing 'player' goes straight to a PvP game (checking for an
        existing PvP save first). Choosing 'bot' goes to the color picker
        (which then leads to the difficulty screen).
        """
        app = self.app
        g = app.game
        activated_key = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if app.opponent_back and app.opponent_back.collidepoint(mx, my):
                activated_key = 'back'
            else:
                for key, rect in app.opponent_rects.items():
                    if rect.collidepoint(mx, my):
                        activated_key = key
                        break
        else:
            for focusable in app.opponent_focus.widgets:
                if focusable.activated_by_key(event):
                    activated_key = focusable.key
                    break

        if activated_key == 'back':
            app.opponent_focus.clear()
            g.state = GameState.MENU
        elif activated_key == 'player':
            save = app.safe_read_save('pvp')
            if save:
                g.pending_mode = GameState.PVP
                g.pending_save_data = save
                g.continue_new_overlay = True
            elif app.pending_corrupt_error is None:
                g.state = GameState.TIME_CONTROL_PICK
        elif activated_key == 'bot':
            save = app.safe_read_save('bot')
            if save:
                g.pending_mode = GameState.BOT
                g.pending_save_data = save
                g.continue_new_overlay = True
            elif app.pending_corrupt_error is None:
                g.state = GameState.COLOR_PICK

    def _handle_time_control_pick_event(self, event, mx, my) -> None:
        """Handle the PvP time-control preset screen. Bot games never
        reach this handler - it's only wired up for GameState.TIME_CONTROL_PICK,
        which is only entered from the 'player' branch of OPPONENT_PICK."""
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
            g.state = GameState.OPPONENT_PICK
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
                                  app.tc_choice)

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
            g.state = GameState.OPPONENT_PICK
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
            g.state = GameState.MENU
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
                                      g.bot_engine_pref, g.bot_elo)

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
            elif (g.game_over and app.menu_from_gameover_rect
                  and app.menu_from_gameover_rect.collidepoint(mx, my)):
                g.review.reset()
                g.state = GameState.MENU
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
