"""Pure board rendering, with a cached indicator-surface helper.

draw_board is pure: surface in, nothing mutated outside the surface.
"""
from __future__ import annotations

import chess
import pygame

from chess_game.theme import (
    BOARD_PX,
    BOARD_THEMES,
    SQ_CHK_D,
    SQ_CHK_L,
    SQ_LAST_D,
    SQ_LAST_L,
    SQ_SEL_D,
    SQ_SEL_L,
    TILE,
)

_IND_R = TILE // 2
_ind_dot: pygame.Surface | None = None
_ind_ring: pygame.Surface | None = None


def _indicators() -> tuple[pygame.Surface, pygame.Surface]:
    """Lazily build (and cache) the move-indicator dot/ring surfaces."""
    global _ind_dot, _ind_ring
    if _ind_dot is None or _ind_ring is None:
        dot = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        ring = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        pygame.draw.circle(dot, (0, 0, 0, 80), (_IND_R, _IND_R), _IND_R // 3)
        pygame.draw.circle(ring, (0, 0, 0, 85), (_IND_R, _IND_R), _IND_R - 4, 6)
        _ind_dot, _ind_ring = dot, ring
    return _ind_dot, _ind_ring


def square_screen_pos(sq: int, board_flipped: bool) -> tuple[int, int]:
    """Top-left pixel of `sq` within a BOARD_PX x BOARD_PX surface."""
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    if board_flipped:
        return (7 - file) * TILE, rank * TILE
    return file * TILE, (7 - rank) * TILE


def draw_board(
    board_surf,
    board,
    piece_imgs,
    board_theme_name,
    board_flipped,
    check_sq,
    last_move,
    sel_sq,
    targets,
    suppress,
):
    """Draw squares, highlights, pieces, and move indicators onto board_surf.

    Pure: takes the surface and all the data it needs, mutates only that
    surface. No globals, no module-level adapter/board_flipped reads.
    """
    theme = BOARD_THEMES[board_theme_name]
    theme_light, theme_dark = theme["light"], theme["dark"]
    ind_dot, ind_ring = _indicators()

    for rank in range(8):
        for file in range(8):
            sq = chess.square(file, rank)
            sx, sy = square_screen_pos(sq, board_flipped)
            rect = pygame.Rect(sx, sy, TILE, TILE)
            is_light = (file + rank) % 2 == 1

            if sq == check_sq:
                col = SQ_CHK_L if is_light else SQ_CHK_D
            elif sq == sel_sq:
                col = SQ_SEL_L if is_light else SQ_SEL_D
            elif last_move and sq in (last_move.from_square, last_move.to_square):
                col = SQ_LAST_L if is_light else SQ_LAST_D
            else:
                col = theme_light if is_light else theme_dark

            pygame.draw.rect(board_surf, col, rect)

            if not (suppress and sq in suppress):
                piece = board.piece_at(sq)
                if piece:
                    img = piece_imgs.get((piece.piece_type, piece.color))
                    if img:
                        board_surf.blit(img, img.get_rect(center=rect.center))

            if sel_sq is not None and sq in targets:
                cx, cy = rect.center
                has_piece = board.piece_at(sq) is not None and not (suppress and sq in suppress)
                surf = ind_ring if has_piece else ind_dot
                board_surf.blit(surf, (cx - _IND_R, cy - _IND_R))


def draw_labels(screen, board_flipped, fonts):
    """Draw rank (1-8) and file (a-h) labels around the board, pure.

    The label margin areas (left of the board and below it) are NOT covered
    by the board surface blit, so stale labels from a previous orientation
    would persist across a board flip. We clear just the label strips
    (not the full TILE height below the board — that would overwrite the
    bottom captured-piece tray).
    """
    from chess_game.theme import (
        BG,
        BOARD_PANEL_GAP,
        BOARD_X,
        BOARD_Y,
        FILE_LABEL_H,
        LABEL_COL,
        TILE,
    )

    # Clear the left margin (where rank labels live) and the bottom margin
    # (where file labels live) so stale labels from the previous orientation
    # don't bleed through after a board flip. The bottom clear is bounded
    # to FILE_LABEL_H so it doesn't overwrite the tray below the board.
    #
    # The left-margin clear's height is extended by FILE_LABEL_H (rather
    # than stopping flush with the board bottom at BOARD_Y + BOARD_PX) so it
    # also covers the small bottom-left corner square where the two clears
    # would otherwise meet without overlap. Similarly, the right-margin clear
    # is extended to include the FILE_LABEL_H area below the board so the
    # bottom-right corner gap is also fully covered. That corner, and the
    # BOARD_PANEL_GAP sliver on the right (below), were previously outside
    # both the cached board_surf blit and every other per-frame fill/blit,
    # leaving uncleared trails of dragged pieces.
    screen.fill(BG, (0, BOARD_Y, BOARD_X, BOARD_PX + FILE_LABEL_H))
    screen.fill(BG, (BOARD_X, BOARD_Y + BOARD_PX, BOARD_PX, FILE_LABEL_H))
    screen.fill(BG, (BOARD_X + BOARD_PX, BOARD_Y, BOARD_PANEL_GAP, BOARD_PX + FILE_LABEL_H))

    files = 'hgfedcba' if board_flipped else 'abcdefgh'
    for y in range(8):
        rank = str(y + 1) if board_flipped else str(8 - y)
        s = fonts.label.render(rank, True, LABEL_COL)
        ry = BOARD_Y + y * TILE + (TILE - s.get_height()) // 2
        screen.blit(s, (BOARD_X - s.get_width() - 4, ry))
    for x, letter in enumerate(files):
        s = fonts.label.render(letter, True, LABEL_COL)
        fx = BOARD_X + x * TILE + (TILE - s.get_width()) // 2
        screen.blit(s, (fx, BOARD_Y + BOARD_PX + 5))


# Eval bar geometry. It lives in the same left-margin gutter as the rank
# labels (RANK_LABEL_W is 28px; rank labels render right-aligned against
# the board edge, occupying roughly the rightmost 11px of that margin —
# see draw_labels above — so a 14px-wide bar flush against the window's
# left edge has a clear few-pixel gap and never overlaps them).
EVAL_BAR_W = 14
EVAL_BAR_X = 0
EVAL_BAR_LABEL_GAP = 4
# How far right of the bar's left edge the eval label is anchored. Moves
# the label off the window's left edge (negative-x clipping) since every
# realistic label string is wider than the bar itself — see draw_eval_bar.
EVAL_BAR_LABEL_X_OFFSET = 8

# Exponential ease-out rate (per second) for the eval bar's fill height —
# see Game.update_eval_bar_smoothing for the frame-rate-independent decay
# formula that uses this. Larger = snappier (converges faster); smaller =
# more sluggish. ~6.0 settles a full 0->1 swing in roughly half a second,
# which reads as a fluid slide rather than an instant snap without ever
# feeling laggy behind the position on screen. Tune this single constant
# to taste; nothing else needs to change.
EVAL_BAR_EASE_PER_SEC = 6.0


def eval_target_ratio(eval_cp: int | None, is_mate: bool, mate_in: int | None) -> float:
    """Pure function: map the latest analysis result to the eval bar's
    *target* white-fill ratio (0..1), with no easing applied.

    Factored out of draw_eval_bar so Game.update_eval_bar_smoothing can
    compute the same target the renderer would, without the renderer and
    the per-frame easing update needing to duplicate this logic or fight
    over which one owns "the real" ratio.
    """
    from chess_game.analysis import _eval_to_ratio

    if is_mate:
        # Pegged fully to the mating side. mate_in > 0 means White mates;
        # < 0 means Black mates (python-chess's own sign convention for
        # PovScore(...).white().mate()). mate_in == 0 is a degenerate edge
        # case some engines report for an already-checkmated position
        # (python-chess normalises both Mate(0) and Mate(-0) to plain 0,
        # so the side that delivered mate genuinely can't be recovered
        # from this value alone). Rather than guess and risk pegging to
        # the wrong side, fall back to an even bar — this should only
        # ever be reached if analysis runs on a position that was already
        # game-over, which the app doesn't normally do.
        if mate_in is not None and mate_in > 0:
            return 1.0
        if mate_in is not None and mate_in < 0:
            return 0.0
        return 0.5
    return _eval_to_ratio(eval_cp if eval_cp is not None else 0)


def draw_eval_bar(screen, eval_cp, board_flipped, is_mate, mate_in, fonts, display_ratio=None):
    """Draw the always-on-analysis eval bar in the left margin.

    A thin vertical strip, BOARD_PX tall, split between a light ("White")
    fill and a dark ("Black") fill at a point determined by eval_cp via a
    sigmoid (see analysis._eval_to_ratio / eval_target_ratio above) so the
    bar moves visibly on small advantages without ever fully pegging on
    large ones. Mate scores are the one exception: those DO peg fully to
    whichever side is mating, with a "M{n}" label instead of a decimal
    eval.

    `display_ratio`, if given, is used for the bar's *fill height*
    instead of recomputing the ratio fresh from eval_cp/is_mate/mate_in —
    this is the eased value from Game.update_eval_bar_smoothing, so the
    bar's height lags smoothly behind the true evaluation by a few frames
    instead of snapping instantly on every new engine result. The numeric
    label above the bar always reflects the real (un-eased) eval_cp /
    mate_in, since the *number* should never lie about the position even
    while the *bar* is still catching up to it visually. When
    display_ratio is None (e.g. existing callers/tests that haven't
    opted into smoothing), the un-eased target ratio is used for the fill
    too, preserving the previous instant-snap behaviour exactly.

    When board_flipped, the bar's geometry doesn't change (it isn't tied
    to a square), but its fill orientation does: White's fill always
    grows from whichever edge is visually "down" for White, so flipping
    the board flips the bar to match, exactly like the rank labels do.
    """
    from chess_game.theme import BOARD_PX, BOARD_Y, MENU_TEXT, PANEL_BDR

    bar_rect = pygame.Rect(EVAL_BAR_X, BOARD_Y, EVAL_BAR_W, BOARD_PX)

    target_ratio = eval_target_ratio(eval_cp, is_mate, mate_in)
    white_ratio = target_ratio if display_ratio is None else display_ratio
    white_ratio = max(0.0, min(1.0, white_ratio))

    # white_ratio is "fraction of the bar that is White's". White's fill
    # grows from the bottom of the bar when the board is in its normal
    # (White-at-bottom) orientation, and from the top when flipped (Black
    # at the bottom). Concretely: not flipped -> Black occupies the top
    # `black_h` pixels and White occupies the bottom `white_h` pixels;
    # flipped -> the reverse.
    white_h = int(round(BOARD_PX * white_ratio))
    black_h = BOARD_PX - white_h

    white_col = (235, 235, 230)
    black_col = (40, 40, 40)
    if board_flipped:
        # White sits at the top in this orientation, so White's fill
        # grows from the top and Black's from the bottom.
        screen.fill(white_col, (bar_rect.x, bar_rect.y, EVAL_BAR_W, white_h))
        screen.fill(black_col, (bar_rect.x, bar_rect.y + white_h, EVAL_BAR_W, black_h))
    else:
        screen.fill(black_col, (bar_rect.x, bar_rect.y, EVAL_BAR_W, black_h))
        screen.fill(white_col, (bar_rect.x, bar_rect.y + black_h, EVAL_BAR_W, white_h))

    pygame.draw.rect(screen, PANEL_BDR, bar_rect, 1)

    # Midpoint tick, always at the bar's vertical centre regardless of
    # orientation — it marks "dead even", not a side.
    tick_y = bar_rect.centery
    pygame.draw.line(screen, PANEL_BDR, (bar_rect.x, tick_y), (bar_rect.right, tick_y), 1)

    # Numeric label above the bar: "+1.20" / "-0.45" / "M5" / "M-3".
    # mate_in == 0 (mate already delivered) gets its own marker rather
    # than the confusing "M0" — see the white_ratio branch above for why
    # the side can't be recovered from this value.
    if is_mate and mate_in:
        label_text = f"M{mate_in}"
    elif is_mate:
        label_text = "M"
    elif eval_cp is not None:
        label_text = f"{eval_cp / 100:+.2f}"
    else:
        label_text = "--"
    label_s = fonts.label.render(label_text, True, MENU_TEXT)
    # Left-align the label a few pixels right of the bar's left edge,
    # rather than centring it on the bar's own midpoint. The bar is only
    # 14px wide but every realistic label ("+1.20", "M-12", ...) renders
    # wider than that, so centring on bar_rect.centerx pushed the label's
    # left edge to a negative x — off the left side of the window
    # entirely — for every value except the shortest ones. Anchoring from
    # the bar's left edge instead keeps the whole label on-screen and
    # roughly above the bar regardless of how wide the text is.
    label_x = bar_rect.x + EVAL_BAR_LABEL_X_OFFSET
    screen.blit(label_s, (label_x, bar_rect.y - label_s.get_height() - EVAL_BAR_LABEL_GAP))
