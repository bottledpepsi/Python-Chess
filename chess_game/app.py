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
from chess_game import layout, theme
from chess_game.anim import ANIM_MS, ease_out
from chess_game.assets import load_images
from chess_game.bot_worker import BotWorker
from chess_game.engine.bot import ChessBot
from chess_game.game import Game
from chess_game.log import configure_logging
from chess_game.render import arrows as render_arrows
from chess_game.render import board as render_board
from chess_game.render import history as render_history
from chess_game.render import menus as render_menus
from chess_game.render import overlays as render_overlays
from chess_game.render import trays as render_trays
from chess_game.review import enter_review, exit_review, move_review
from chess_game.sound import SoundManager
from chess_game.state import GameState
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

        # Resizable + SCALED + vsync window (was a fixed-size set_mode).
        self.screen = pygame.display.set_mode(
            (theme.WIN_W, theme.WIN_H), pygame.SCALED | pygame.RESIZABLE, vsync=1
        )
        pygame.display.set_caption('Python Chess')
        self.board_surf = pygame.Surface((theme.BOARD_PX, theme.BOARD_PX), pygame.SRCALPHA)
        self._board_surf_dirty = True

        self.fonts = theme.load_fonts()
        self.assets = load_images(resource_path)
        self.sounds = SoundManager(resource_path)

        prefs = save_io.read_preferences()
        board_theme = prefs.get('board_theme') or 'white_green'
        arrow_theme = prefs.get('arrow_theme') or 'blue'
        reduced_motion = bool(prefs.get('reduced_motion', False))
        if board_theme not in theme.BOARD_THEMES:
            board_theme = 'white_green'
        if arrow_theme not in theme.ARROW_THEMES:
            arrow_theme = 'blue'

        bot = ChessBot(max_depth=3, book_path=resource_path('data/book/gm2001.bin'))
        worker = BotWorker(bot)
        self.game = Game(
            bot=bot, bot_worker=worker, board_theme=board_theme,
            arrow_theme=arrow_theme, reduced_motion=reduced_motion,
        )
        self.game.piece_imgs = self.assets.piece_imgs

        self.menu_buttons = render_menus.make_menu_buttons()
        self.menu_focus = FocusGroup(self.menu_buttons)
        self.clock = pygame.time.Clock()

        # Transient per-screen UI rects (not part of Game; rebuilt every frame).
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

        self.pref_back_rect: pygame.Rect | None = None
        self.pref_board_rects: dict = {}
        self.pref_arrow_rects: dict = {}
        self.pref_motion_rect: pygame.Rect | None = None
        self.pref_focus = FocusGroup([])

        self.menu_btn_ingame_rect: pygame.Rect | None = None
        self.menu_from_gameover_rect: pygame.Rect | None = None
        self.overlay_cont_btn: pygame.Rect | None = None
        self.overlay_new_btn: pygame.Rect | None = None
        self.overlay_save_btn: pygame.Rect | None = None
        self.overlay_quit_btn: pygame.Rect | None = None

        self.pending_corrupt_error: str | None = None

        # Drag-and-drop state for moving pieces by dragging. `drag_pending`
        # is set on mousedown over a selectable piece; it is promoted to
        # `drag_active` once the cursor moves past DRAG_THRESHOLD_PX, at
        # which point the piece is lifted off the board and drawn at the
        # cursor until mouseup. Click-to-select / click-to-move is fully
        # preserved: a press+release below the threshold behaves exactly
        # as before.
        self.drag_pending: bool = False
        self.drag_active: bool = False
        self.drag_sq: int | None = None
        self.drag_pos: tuple[int, int] = (0, 0)
        self.drag_start_pos: tuple[int, int] = (0, 0)

    # ── Lifecycle helpers ───────────────────────────────────────────────────

    def start_game(self) -> None:
        self.game.start_game()
        self._board_surf_dirty = True

    def launch_bot_move(self) -> None:
        self.game.launch_bot_move()

    def write_save(self) -> None:
        if self.game.adapter is None:
            return
        mode = 'bot' if self.game.state == GameState.BOT else 'pvp'
        save_io.write_save(
            mode, list(self.game.adapter.board.move_stack),
            self.game.player_color, self.game.bot_level
        )

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
            self.game.board_flipped = False
        self.game.state = mode
        self.start_game()
        assert self.game.adapter is not None  # guaranteed by start_game() above
        for move in save_data.moves:
            if move in self.game.adapter.board.legal_moves:
                self.game.adapter.apply_move(move)
        if mode == GameState.BOT and not self.game.adapter.is_game_over:
            if self.game.adapter.turn != self.game.player_color:
                self.launch_bot_move()
        self.write_save()

    # ── Drag-and-drop helpers ──────────────────────────────────────────────

    def _reset_drag(self) -> None:
        """Clear all drag-and-drop tracking state."""
        self.drag_pending = False
        self.drag_active = False
        self.drag_sq = None

    def _start_drag(self, sq: int, mx: int, my: int) -> None:
        """Begin tracking a potential drag originating from `sq`.

        Called after a click selects a piece — the piece is not yet lifted
        off the board; that only happens once the cursor moves past
        DRAG_THRESHOLD_PX (see _update_drag_motion).
        """
        self.drag_pending = True
        self.drag_active = False
        self.drag_sq = sq
        self.drag_pos = (mx, my)
        self.drag_start_pos = (mx, my)

    def _update_drag_motion(self, mx: int, my: int) -> None:
        """Promote a pending drag to active once the cursor has moved past
        the threshold, and keep the dragged piece's screen position current."""
        if not self.drag_pending:
            return
        dx = mx - self.drag_start_pos[0]
        dy = my - self.drag_start_pos[1]
        if not self.drag_active and (dx * dx + dy * dy) >= (DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX):
            self.drag_active = True
        if self.drag_active:
            self.drag_pos = (mx, my)

    def _complete_drag(self, mx: int, my: int) -> None:
        """On left-button release, if a drag is in flight, attempt to move
        the dragged piece to the square under the cursor. The drag state is
        always reset afterward.

        Dropping on an invalid square or outside the board cancels the drag
        and leaves the piece selected, so the user can click a target square
        next (mirroring the forgiving behaviour of click-to-move).
        """
        g = self.game
        if not self.drag_active or self.drag_sq is None or g.adapter is None:
            self._reset_drag()
            return

        bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
        if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
            target_sq = layout.pixel_to_sq(bx, by, g.board_flipped)
            if target_sq in g.adapter.valid_move_targets:
                result = g.adapter.handle_click(target_sq)
                if result in ('move', 'capture', 'en_passant'):
                    piece = g.adapter.board.piece_at(g.adapter.anim_to)
                    img = g.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
                    # Start the slide animation from the cursor's release
                    # position rather than the origin square, so the piece
                    # flows smoothly from where it was dropped to the
                    # destination instead of snapping back first.
                    g.start_anim(g.adapter.anim_from, g.adapter.anim_to, img, start_pos=(mx, my))
                    is_check = g.adapter.check_square is not None
                    is_over = g.adapter.is_game_over
                    self.sounds.play_for_move_result(result, is_check=is_check, is_game_over=is_over)
                    self.write_save()
                    if g.state == GameState.BOT and not g.adapter.promotion_pending:
                        self.launch_bot_move()
                # result == 'promotion' is also valid here: the promotion
                # overlay will be drawn next frame and the user picks a
                # piece via the existing keyboard / click flow.
        # Either way, the drag is finished.
        self._reset_drag()

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

    def _frame(self) -> None:
        dt = self.clock.tick(60)
        mx, my = pygame.mouse.get_pos()

        # Safety net: if a drag is armed or active but the left mouse button
        # is no longer held, the mouseup was swallowed by an overlay or
        # state transition. Clear the stale drag state so the next press
        # starts cleanly and no piece is left "stuck" to the cursor.
        if (self.drag_pending or self.drag_active) and not pygame.mouse.get_pressed()[0]:
            self._reset_drag()

        self.game.think_timer += dt
        if self.game.think_timer >= 500:
            self.game.think_dots += 1
            self.game.think_timer = 0

        for event in pygame.event.get():
            self._handle_event(event, mx, my)

        self._apply_bot_move()
        self._render(dt)
        pygame.display.flip()

    # ── Event dispatch ───────────────────────────────────────────────────────

    def _handle_event(self, event: pygame.event.Event, mx: int, my: int) -> None:
        g = self.game

        if event.type == pygame.QUIT:
            self.game.bot_worker.cancel()
            self.game.bot_worker.join(timeout=2.0)
            pygame.quit()
            sys.exit()

        # Clear arrows only on a click that lands on the board itself,
        # not on every left click (which used to also swallow modal clicks).
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

        if self.pending_corrupt_error is not None:
            self._handle_error_modal_event(event, mx, my)
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
        elif g.state == GameState.COLOR_PICK:
            self._handle_color_pick_event(event, mx, my)
        elif g.state == GameState.DIFFICULTY:
            self._handle_difficulty_event(event, mx, my)
        elif g.state == GameState.PREFERENCES:
            self._handle_preferences_event(event, mx, my)
        elif g.state in (GameState.PVP, GameState.BOT):
            self._handle_game_event(event, mx, my)

    def _focus_group_for_state(self, state) -> FocusGroup | None:
        """Return the FocusGroup that owns Tab-cycling for the given screen,
        or None for screens with no focusable widgets (e.g. PVP/BOT board)."""
        return {
            GameState.MENU: self.menu_focus,
            GameState.COLOR_PICK: self.picker_focus,
            GameState.DIFFICULTY: self.diff_focus,
            GameState.PREFERENCES: self.pref_focus,
        }.get(state)

    def _handle_escape(self) -> bool:
        g = self.game
        if self.pending_corrupt_error is not None:
            self.pending_corrupt_error = None
            return True
        if g.continue_new_overlay:
            g.continue_new_overlay = False
            g.pending_save_data = None
            return True
        if g.main_menu_overlay:
            g.main_menu_overlay = False
            return True
        if g.state == GameState.COLOR_PICK:
            self.picker_focus.clear()
            g.state = GameState.MENU
            return True
        if g.state == GameState.DIFFICULTY:
            self.diff_focus.clear()
            g.state = GameState.COLOR_PICK
            return True
        if g.state == GameState.PREFERENCES:
            self.pref_focus.clear()
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
            self.pending_corrupt_error = None

    def _handle_continue_new_overlay_event(self, event, mx, my) -> None:
        g = self.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.overlay_cont_btn and self.overlay_cont_btn.collidepoint(mx, my):
                assert isinstance(g.pending_save_data, save_io.SaveData)
                assert g.pending_mode is not None
                self.continue_saved_game(g.pending_save_data, g.pending_mode)
                g.continue_new_overlay = False
                g.pending_save_data = None
            elif self.overlay_new_btn and self.overlay_new_btn.collidepoint(mx, my):
                mode_str = 'bot' if g.pending_mode == GameState.BOT else 'pvp'
                save_io.delete_save(mode_str)
                if g.pending_mode == GameState.PVP:
                    g.board_flipped = False
                    g.state = GameState.PVP
                    self.start_game()
                else:
                    g.state = GameState.COLOR_PICK
                g.continue_new_overlay = False
                g.pending_save_data = None

    def _handle_main_menu_overlay_event(self, event, mx, my) -> None:
        g = self.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.overlay_save_btn and self.overlay_save_btn.collidepoint(mx, my):
                self.write_save()
                g.review.reset()
                g.state = GameState.MENU
                g.main_menu_overlay = False
            elif self.overlay_quit_btn and self.overlay_quit_btn.collidepoint(mx, my):
                mode_str = 'bot' if g.state == GameState.BOT else 'pvp'
                save_io.delete_save(mode_str)
                g.review.reset()
                g.state = GameState.MENU
                g.main_menu_overlay = False
            else:
                bx_chk = theme.PANEL_X // 2
                by_chk = theme.WIN_H // 2
                bw_chk, bh_chk = 310, 210
                box_r = pygame.Rect(bx_chk - bw_chk // 2, by_chk - bh_chk // 2, bw_chk, bh_chk)
                if not box_r.collidepoint(mx, my):
                    g.main_menu_overlay = False

    def _handle_menu_event(self, event, mx, my) -> None:
        g = self.game
        if self.menu_buttons[0].clicked(event) or self.menu_buttons[0].activated_by_key(event):
            save = self.safe_read_save('pvp')
            if save:
                g.pending_mode = GameState.PVP
                g.pending_save_data = save
                g.continue_new_overlay = True
            elif self.pending_corrupt_error is None:
                g.board_flipped = False
                g.state = GameState.PVP
                self.start_game()
        elif self.menu_buttons[1].clicked(event) or self.menu_buttons[1].activated_by_key(event):
            save = self.safe_read_save('bot')
            if save:
                g.pending_mode = GameState.BOT
                g.pending_save_data = save
                g.continue_new_overlay = True
            elif self.pending_corrupt_error is None:
                g.state = GameState.COLOR_PICK
        elif self.menu_buttons[2].clicked(event) or self.menu_buttons[2].activated_by_key(event):
            g.state = GameState.PREFERENCES

    def _handle_color_pick_event(self, event, mx, my) -> None:
        g = self.game
        activated_key = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.picker_back and self.picker_back.collidepoint(mx, my):
                activated_key = 'back'
            else:
                for color, rect in self.picker_rects.items():
                    if rect.collidepoint(mx, my):
                        activated_key = color
                        break
        else:
            for focusable in self.picker_focus.widgets:
                if focusable.activated_by_key(event):
                    activated_key = focusable.key
                    break

        if activated_key == 'back':
            self.picker_focus.clear()
            g.state = GameState.MENU
        elif activated_key in ('white', 'black'):
            g.player_color = activated_key
            g.board_flipped = (activated_key == 'black')
            self.picker_focus.clear()
            g.state = GameState.DIFFICULTY

    def _handle_difficulty_event(self, event, mx, my) -> None:
        g = self.game
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.diff_back and self.diff_back.collidepoint(mx, my):
                self.diff_focus.clear()
                g.state = GameState.COLOR_PICK
            elif self.diff_confirm_rect and self.diff_confirm_rect.collidepoint(mx, my):
                self._confirm_difficulty()
            elif self.diff_slider_rect and self.diff_slider_rect.collidepoint(mx, my):
                self.diff_slider_dragging = True
                if self.diff_slider_info:
                    sl_x, sl_w, _ = self.diff_slider_info
                    t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                    # Round half-up, not banker's rounding.
                    self.diff_level = int(t * 9 + 0.5) + 1
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.diff_slider_dragging = False
        elif event.type == pygame.MOUSEMOTION:
            if self.diff_slider_dragging and self.diff_slider_info:
                sl_x, sl_w, _ = self.diff_slider_info
                t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                self.diff_level = int(t * 9 + 0.5) + 1
        else:
            for focusable in self.diff_focus.widgets:
                if focusable.activated_by_key(event):
                    if focusable.key == 'back':
                        self.diff_focus.clear()
                        g.state = GameState.COLOR_PICK
                    elif focusable.key == 'confirm':
                        self._confirm_difficulty()
                    break

    def _confirm_difficulty(self) -> None:
        g = self.game
        g.bot_level = self.diff_level
        self.diff_focus.clear()
        g.state = GameState.BOT
        self.start_game()
        if g.player_color == 'black':
            self.launch_bot_move()

    def _handle_preferences_event(self, event, mx, my) -> None:
        g = self.game
        activated_key = None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.pref_back_rect and self.pref_back_rect.collidepoint(mx, my):
                activated_key = ('back', None)
            else:
                for theme_name, rect in self.pref_board_rects.items():
                    if rect.collidepoint(mx, my):
                        activated_key = ('board', theme_name)
                        break
                if activated_key is None:
                    for theme_name, rect in self.pref_arrow_rects.items():
                        if rect.collidepoint(mx, my):
                            activated_key = ('arrow', theme_name)
                            break
                if activated_key is None and self.pref_motion_rect and self.pref_motion_rect.collidepoint(mx, my):
                    activated_key = ('motion', None)
        else:
            for focusable in self.pref_focus.widgets:
                if focusable.activated_by_key(event):
                    activated_key = focusable.key
                    break

        if activated_key is None:
            return
        kind, value = activated_key
        if kind == 'back':
            self.pref_focus.clear()
            g.state = GameState.MENU
            return
        changed = False
        if kind == 'board':
            assert value is not None
            g.board_theme = value
            self._board_surf_dirty = True
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
        if changed:
            save_io.write_preferences(g.board_theme, g.arrow_theme, g.reduced_motion)

    def _complete_promotion(self, piece_type) -> None:
        """Complete a pending promotion with the given piece type, whether
        triggered by a click on the promotion overlay or a Q/R/B/N keypress."""
        g = self.game
        assert g.adapter is not None
        result = g.adapter.complete_promotion(piece_type)
        is_check = g.adapter.check_square is not None
        self.sounds.play_for_move_result(result, is_check=is_check)
        promo_piece_color = (chess.WHITE if g.adapter.turn == 'black' else chess.BLACK)
        promo_img = g.piece_imgs.get((piece_type, promo_piece_color))
        g.start_anim(g.adapter.anim_from, g.adapter.anim_to, promo_img)
        self.write_save()
        if g.state == GameState.BOT and g.adapter.turn != g.player_color:
            self.launch_bot_move()

    def _handle_game_event(self, event, mx, my) -> None:
        g = self.game
        assert g.adapter is not None  # guaranteed by g.state in (PVP, BOT)
        is_animating = g.anim is not None and g.anim.is_animating(pygame.time.get_ticks())

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
            if self.menu_btn_ingame_rect and self.menu_btn_ingame_rect.collidepoint(mx, my):
                g.main_menu_overlay = True
            elif mx >= theme.PANEL_X:
                if (self._live_btn_rect and self._live_btn_rect.collidepoint(mx, my)
                        and g.review.active):
                    exit_review(g)
                else:
                    for rect, ply in self._history_ply_rects:
                        if rect.collidepoint(mx, my):
                            enter_review(g, ply)
                            break
            elif (g.game_over and self.menu_from_gameover_rect
                  and self.menu_from_gameover_rect.collidepoint(mx, my)):
                g.review.reset()
                g.state = GameState.MENU
            elif g.review.active or is_animating or g.game_over:
                pass
            elif g.adapter.promotion_pending:
                for rect, pt in g.promo_rects:
                    if rect.collidepoint(mx, my):
                        self._complete_promotion(pt)
                        break
            else:
                bx, by = mx - theme.BOARD_X, my - theme.BOARD_Y
                if 0 <= bx < theme.BOARD_PX and 0 <= by < theme.BOARD_PX:
                    # Precedence bug fixed - this used to be
                    # `state == STATE_BOT and adapter.turn != player_color or bot_thinking`
                    # which (and binds tighter than or) silently dropped PvP
                    # clicks whenever a stale bot_thinking flag leaked True.
                    bot_to_move = (g.state == GameState.BOT and g.adapter.turn != g.player_color)
                    if bot_to_move or (g.state == GameState.BOT and g.bot_thinking):
                        pass
                    else:
                        sq = layout.pixel_to_sq(bx, by, g.board_flipped)
                        result = g.adapter.handle_click(sq)
                        if result in ('move', 'capture', 'en_passant'):
                            piece = g.adapter.board.piece_at(g.adapter.anim_to)
                            img = g.piece_imgs.get((piece.piece_type, piece.color)) if piece else None
                            g.start_anim(g.adapter.anim_from, g.adapter.anim_to, img)
                            is_check = g.adapter.check_square is not None
                            is_over = g.adapter.is_game_over
                            self.sounds.play_for_move_result(result, is_check=is_check, is_game_over=is_over)
                            self.write_save()
                            if g.state == GameState.BOT and not g.adapter.promotion_pending:
                                self.launch_bot_move()
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
            self._update_drag_motion(mx, my)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # Release after a drag: attempt the move if the cursor is over a
            # valid target, otherwise cancel and leave the piece selected.
            # If the press never crossed the drag threshold, drag_active is
            # False and this is a no-op (the mousedown already did the work).
            self._complete_drag(mx, my)

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

    # ── Rendering ────────────────────────────────────────────────────────────

    _history_ply_rects: list = []
    _live_btn_rect: pygame.Rect | None = None

    def _draw_focus_ring(self, focus_group: FocusGroup) -> None:
        """Draw a visible focus ring around the currently focused widget for
        screens that draw their own custom rects (not Button.draw())."""
        if 0 <= focus_group.index < len(focus_group.widgets):
            focused = focus_group.widgets[focus_group.index]
            pygame.draw.rect(self.screen, FOCUS_RING, focused.rect, 3, border_radius=8)

    def _render(self, dt: int) -> None:
        g = self.game
        if g.state == GameState.MENU:
            render_menus.draw_menu(self.screen, self.menu_buttons, self.fonts)
            if g.continue_new_overlay:
                self.overlay_cont_btn, self.overlay_new_btn = render_overlays.draw_continue_new_overlay(
                    self.screen, theme.WIN_W, theme.WIN_H, self.fonts
                )
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
        elif g.state == GameState.PREFERENCES:
            (self.pref_back_rect, self.pref_board_rects,
             self.pref_arrow_rects, self.pref_motion_rect) = render_menus.draw_preferences(
                self.screen, g.board_theme, g.arrow_theme, g.reduced_motion, self.fonts
            )
            pref_focusables = [FocusableRect(self.pref_back_rect, ('back', None))]
            pref_focusables += [
                FocusableRect(rect, ('board', name)) for name, rect in self.pref_board_rects.items()
            ]
            pref_focusables += [
                FocusableRect(rect, ('arrow', name)) for name, rect in self.pref_arrow_rects.items()
            ]
            pref_focusables.append(FocusableRect(self.pref_motion_rect, ('motion', None)))
            self.pref_focus.rebuild(pref_focusables)
            self._draw_focus_ring(self.pref_focus)
        elif g.state in (GameState.PVP, GameState.BOT):
            self._render_game(dt)

        if self.pending_corrupt_error is not None:
            render_overlays.draw_error_modal(
                self.screen, theme.WIN_W, theme.WIN_H, self.pending_corrupt_error, self.fonts
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
        self.screen.blit(self.board_surf, (theme.BOARD_X, theme.BOARD_Y))
        if g.anim is not None and g.anim.is_animating(now_ms):
            self._draw_anim_items(g.anim, now_ms)
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
        render_board.draw_labels(self.screen, g.board_flipped, self.fonts)
        render_arrows.draw_board_arrow_overlay(self.screen, g.all_arrows, g.arrow_theme, g.board_flipped)

        self._history_ply_rects, self._live_btn_rect, g.panel_scroll = render_history.draw_history_panel(
            self.screen, theme.PANEL_X, theme.PANEL_W, theme.WIN_W, theme.WIN_H,
            g.adapter.san_history if g.adapter else None, g.review.ply, g.panel_scroll, self.fonts,
        )

        menu_btn_w, menu_btn_h = 76, 18
        self.menu_btn_ingame_rect = pygame.Rect(
            theme.PANEL_X - menu_btn_w - 6, 2, menu_btn_w, menu_btn_h
        )
        mx_, my_ = pygame.mouse.get_pos()
        mm_hov = self.menu_btn_ingame_rect.collidepoint(mx_, my_)
        pygame.draw.rect(self.screen, (52, 52, 52) if mm_hov else (42, 42, 42),
                          self.menu_btn_ingame_rect, border_radius=6)
        pygame.draw.rect(self.screen, (90, 90, 90) if mm_hov else (62, 62, 62),
                          self.menu_btn_ingame_rect, 1, border_radius=6)
        mm_s = self.fonts.igmenu.render('\u2261  Menu', True, (210, 210, 210) if mm_hov else (140, 140, 140))
        self.screen.blit(mm_s, mm_s.get_rect(center=self.menu_btn_ingame_rect.center))

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
                self.menu_from_gameover_rect = render_overlays.draw_winner(
                    self.screen, theme.WIN_W, theme.WIN_H, theme.PANEL_X,
                    g.winner_result, g.winner_alpha, self.fonts,
                )

        if g.main_menu_overlay:
            self.overlay_save_btn, self.overlay_quit_btn = render_menus.draw_main_menu_overlay(
                self.screen, self.fonts, theme.PANEL_X
            )


def bootstrap() -> App:
    """Construct the App (and everything it owns). Safe to call multiple
    times in tests; each call produces an independent App/Game pair."""
    return App()


def main() -> None:
    app = bootstrap()
    app.run()
