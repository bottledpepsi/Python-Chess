import pygame
import sys
import os
import time
import threading
import math
import tempfile
import chess

from data.classes.ChessAdapter   import ChessAdapter
from data.engine.bot             import ChessBot

pygame.init()

# ── Sound manager ─────────────────────────────────────────────────────────────
class SoundManager:
    def __init__(self):
        self._sounds = {}
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init()
            except Exception:
                return
        for name, path in (('move',    'data/sounds/move.ogg'),
                            ('capture', 'data/sounds/capture.ogg')):
            try:
                s = pygame.mixer.Sound(path)
                s.set_volume(0.6)
                self._sounds[name] = s
            except Exception:
                pass

    def play(self, name):
        s = self._sounds.get(name)
        if s:
            s.play()

sounds = SoundManager()

# ── States ────────────────────────────────────────────────────────────────────
STATE_MENU         = 'menu'
STATE_COLOR_PICK   = 'color_pick'
STATE_DIFFICULTY   = 'difficulty'
STATE_PREFERENCES  = 'preferences'
STATE_PVP          = 'pvp'
STATE_BOT          = 'bot'

# ── Difficulty presets ────────────────────────────────────────────────────────
DIFFICULTIES = [
    ('Beginner', 1),
    ('Easy',     2),
    ('Medium',   3),
    ('Hard',     4),
    ('Master',   5),
]

# ── Layout ────────────────────────────────────────────────────────────────────
BOARD_PX      = 600
TILE          = BOARD_PX // 8          # 75
RANK_LABEL_W  = 28
FILE_LABEL_H  = 26
TRAY_H        = 70
BOARD_X       = RANK_LABEL_W
BOARD_Y       = TRAY_H
PANEL_W       = 220
WIN_W         = RANK_LABEL_W + BOARD_PX + 4 + PANEL_W   # 852
WIN_H         = TRAY_H + BOARD_PX + FILE_LABEL_H + TRAY_H
PANEL_X       = RANK_LABEL_W + BOARD_PX + 4              # 632
ANIM_MS       = 120

# History panel sub-dimensions
HIST_HDR_H    = 30
HIST_FOOT_H   = 44
HIST_ROW_H    = 26
HIST_NUM_W    = 26
HIST_PAD      = 5
HIST_MOV_W    = (PANEL_W - HIST_NUM_W - HIST_PAD * 2) // 2   # 92

screen     = pygame.display.set_mode((WIN_W, WIN_H))
board_surf = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
pygame.display.set_caption('Python Chess')

# ── Fonts ─────────────────────────────────────────────────────────────────────
F_LABEL      = pygame.font.SysFont('Arial', 13, bold=True)
F_PROMO      = pygame.font.SysFont('Arial', 16, bold=True)
F_WIN        = pygame.font.SysFont('Arial', 52, bold=True)
F_WIN_S      = pygame.font.SysFont('Arial', 22)
F_TITLE      = pygame.font.SysFont('Georgia', 64, bold=True)
F_SUBTITLE   = pygame.font.SysFont('Arial', 16)
F_BTN        = pygame.font.SysFont('Arial', 22, bold=True)
F_BTN_SUB    = pygame.font.SysFont('Arial', 13)
F_THINK      = pygame.font.SysFont('Arial', 14)
F_COUNT      = pygame.font.SysFont('Arial', 11, bold=True)
F_LEAD       = pygame.font.SysFont('Arial', 13, bold=True)
F_PICK       = pygame.font.SysFont('Arial', 28, bold=True)
F_PICK_S     = pygame.font.SysFont('Arial', 14)
F_DIFF_N     = pygame.font.SysFont('Arial', 26, bold=True)
F_DIFF_L     = pygame.font.SysFont('Arial', 14, bold=True)
F_DIFF_S     = pygame.font.SysFont('Arial', 12)
# History panel fonts
F_HIST_HDR   = pygame.font.SysFont('Arial', 10, bold=True)
F_HIST_NUM   = pygame.font.SysFont('Arial', 11)
F_HIST_MOV   = pygame.font.SysFont('Arial', 13, bold=True)
F_LIVE_BTN   = pygame.font.SysFont('Arial', 13, bold=True)
# Overlay / in-game menu fonts
F_OV_TITLE   = pygame.font.SysFont('Arial', 20, bold=True)
F_OV_SUB     = pygame.font.SysFont('Arial', 13)
F_OV_BTN     = pygame.font.SysFont('Arial', 16, bold=True)
F_OV_BTN_SM  = pygame.font.SysFont('Arial', 13, bold=True)
F_IGMENU     = pygame.font.SysFont('Arial', 11, bold=True)

# ── Colours ───────────────────────────────────────────────────────────────────
BG            = (22,  22,  22)
TRAY_BG       = (52,  52,  52)
SHADOW        = (10,  10,  10)
LABEL_COL     = (120, 120, 120)
MENU_BG       = (18,  18,  18)
MENU_ACCENT   = (118, 150,  86)
MENU_BTN_NORM = (38,  38,  38)
MENU_BTN_HOV  = (55,  55,  55)
MENU_BTN_DIS  = (30,  30,  30)
MENU_BTN_BRD  = (70,  70,  70)
MENU_TEXT     = (220, 220, 220)
MENU_TEXT_SUB = (110, 110, 110)
MENU_TEXT_DIS = (70,  70,  70)
PICK_LIGHT    = (238, 238, 210)
PICK_DARK     = (118, 150,  86)
PICK_HOVER    = (255, 215,   0)
SQ_LIGHT      = (238, 238, 210)
SQ_DARK       = (118, 150,  86)

# ── Board Themes ──────────────────────────────────────────────────────────────
BOARD_THEMES = {
    'white_green': {'light': (238, 238, 210), 'dark': (118, 150,  86)},
    'white_blue':  {'light': (238, 238, 210), 'dark': ( 86, 118, 150)},
    'white_red':   {'light': (238, 238, 210), 'dark': (150,  86,  86)},
}

# ── Arrow Themes ──────────────────────────────────────────────────────────────
ARROW_THEMES = {
    'blue':   (0,   180, 255, 180),
    'yellow': (255, 200,  50, 180),
    'green':  (100, 220,  80, 180),
    'white':  (255, 255, 255, 180),
    'black':  (40,   40,  40, 180),
}
SQ_SEL_L      = (246, 246, 105)
SQ_SEL_D      = (186, 202,  43)
SQ_LAST_L     = (206, 210, 107)
SQ_LAST_D     = (170, 162,  58)
SQ_CHK_L      = (220,  80,  80)
SQ_CHK_D      = (168,  40,  40)
PROMO_BG_C    = (42,  42,  42)
PROMO_HOV     = (72,  72,  72)
PROMO_NORM    = (55,  55,  55)
PROMO_BRD     = (90,  90,  90)
# Panel colours
PANEL_BG      = (26,  26,  26)
PANEL_HDR_BG  = (33,  33,  33)
PANEL_BDR     = (46,  46,  46)
HIST_ROW_HOV  = (40,  40,  40)
HIST_SEL_BG   = (46,  68,  42)
HIST_SEL_FG   = (140, 200, 100)
HIST_NUM_COL  = (70,  70,  70)
HIST_MOV_COL  = (190, 190, 190)
LIVE_BG_ACT   = (32,  86,  32)
LIVE_BG_HOV   = (42, 108,  42)
LIVE_BG_OFF   = (33,  33,  33)

_DIFFICULTY_COLORS = [
    ( 90, 200,  90), (120, 200,  70), (155, 195,  50),
    (185, 180,  40), (210, 155,  40), (220, 120,  40),
    (220,  90,  50), (210,  60,  60), (200,  40,  40),
    (180,  20,  20),
]
def _difficulty_color(d):
    return _DIFFICULTY_COLORS[max(0, min(9, d - 1))]

# ── Unified difficulty labels (single 1-10 slider) ────────────────────────────
# Tier names correspond to pairs/groups of levels as specified.
_DIFF_TIER = {
    1: 'Novice',        2: 'Novice',
    3: 'Casual',        4: 'Casual',
    5: 'Intermediate',  6: 'Intermediate',
    7: 'Advanced',      8: 'Advanced',
    9: 'Master',
    10: 'Grandmaster',
}
# Short contextual description shown below the slider (real-time update).
_DIFF_DESC = {
    1: 'Beginner friendly, frequent tactical mistakes',
    2: 'Beginner friendly, frequent tactical mistakes',
    3: 'Plays briskly, classic kitchen-table difficulty',
    4: 'Plays briskly, classic kitchen-table difficulty',
    5: 'Club player standard, capitalizes on obvious blunders',
    6: 'Club player standard, capitalizes on obvious blunders',
    7: 'Tournament regular, sharp short-term tactics',
    8: 'Tournament regular, sharp short-term tactics',
    9: 'Extremely deep strategic vision, very rare slips',
    10: 'Engine max strength. Perfect calculation.',
}

# ── Piece images ──────────────────────────────────────────────────────────────
_PIECE_NAMES = {
    chess.PAWN:   'pawn',   chess.KNIGHT: 'knight',
    chess.BISHOP: 'bishop', chess.ROOK:   'rook',
    chess.QUEEN:  'queen',  chess.KING:   'king',
}
_NOTATION_TO_PT = {
    ' ': chess.PAWN,   'N': chess.KNIGHT, 'B': chess.BISHOP,
    'R': chess.ROOK,   'Q': chess.QUEEN,  'K': chess.KING,
}

def _load(name, color_char, size):
    img = pygame.image.load(f'data/imgs/{color_char}_{name}.png').convert_alpha()
    return pygame.transform.smoothscale(img, (size, size))

PIECE_SIZE   = int(TILE * 0.88)
PIECE_IMGS   = {}
TRAY_IMGS    = {}
PROMO_IMGS   = {}
PROMO_IMGS_S = {}
KING_IMGS    = {}

for _ct, _pt in [(chess.WHITE, 'w'), (chess.BLACK, 'b')]:
    for _piece_type, _pname in _PIECE_NAMES.items():
        PIECE_IMGS[(_piece_type, _ct)] = _load(_pname, _pt, PIECE_SIZE)
        TRAY_IMGS[f'{_pt}_{_pname}']   = _load(_pname, _pt, 30)
    for _pname in ('queen', 'rook', 'bishop', 'knight'):
        PROMO_IMGS[f'{_pt}_{_pname}']   = _load(_pname, _pt, 78)
        PROMO_IMGS_S[f'{_pt}_{_pname}'] = _load(_pname, _pt, 54)

KING_IMGS['white'] = _load('king', 'w', 100)
KING_IMGS['black'] = _load('king', 'b', 100)

PROMO_OPTIONS = [
    ('Queen',  chess.QUEEN,  'queen'),
    ('Rook',   chess.ROOK,   'rook'),
    ('Bishop', chess.BISHOP, 'bishop'),
    ('Knight', chess.KNIGHT, 'knight'),
]

# ── Pre-created move-indicator surfaces ───────────────────────────────────────
_IND_R    = TILE // 2
_IND_DOT  = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
_IND_RING = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
pygame.draw.circle(_IND_DOT,  (0, 0, 0,  80), (_IND_R, _IND_R), _IND_R // 3)
pygame.draw.circle(_IND_RING, (0, 0, 0,  85), (_IND_R, _IND_R), _IND_R - 4, 6)

# ── Button widget ─────────────────────────────────────────────────────────────
class Button:
    def __init__(self, rect, label, sublabel=None, disabled=False):
        self.rect     = pygame.Rect(rect)
        self.label    = label
        self.sublabel = sublabel
        self.disabled = disabled

    def draw(self, surface):
        mx, my = pygame.mouse.get_pos()
        hov = self.rect.collidepoint(mx, my) and not self.disabled
        bg  = MENU_BTN_DIS if self.disabled else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
        pygame.draw.rect(surface, bg,           self.rect, border_radius=10)
        pygame.draw.rect(surface, MENU_BTN_BRD, self.rect, 2, border_radius=10)
        tc  = MENU_TEXT_DIS if self.disabled else MENU_TEXT
        lbl = F_BTN.render(self.label, True, tc)
        surface.blit(lbl, lbl.get_rect(
            center=(self.rect.centerx,
                    self.rect.centery - (8 if self.sublabel else 0))))
        if self.sublabel:
            sc = MENU_TEXT_DIS if self.disabled else MENU_TEXT_SUB
            sl = F_BTN_SUB.render(self.sublabel, True, sc)
            surface.blit(sl, sl.get_rect(
                center=(self.rect.centerx, self.rect.centery + 14)))

    def clicked(self, event):
        return (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos) and not self.disabled)


def _make_menu_buttons():
    cx, bw, bh, gap = WIN_W // 2, 280, 68, 18
    y0 = WIN_H // 2 + 30
    return [
        Button((cx - bw//2, y0,              bw, bh), 'Play vs Friend', 'Local 2-player'),
        Button((cx - bw//2, y0 + bh+gap,    bw, bh), 'Play vs Bot',    'AI opponent'),
        Button((cx - bw//2, y0 + 2*(bh+gap), bw, bh), 'Preferences',    'Board & Arrow themes'),
    ]

menu_buttons = _make_menu_buttons()

# ── Thread safety ─────────────────────────────────────────────────────────────
_bot_lock = threading.Lock()

# ── Save / load ───────────────────────────────────────────────────────────────
SAVE_FILES = {STATE_PVP: 'python-chess_pvp_game.txt', STATE_BOT: 'python-chess_bot_game.txt'}
PREF_FILE  = 'python-chess_preferences.txt'

SAVE_DIR = os.path.join(tempfile.gettempdir(), 'python-chess')
os.makedirs(SAVE_DIR, exist_ok=True)


def _save_path(filename):
    return os.path.join(SAVE_DIR, filename)


def write_preferences():
    try:
        path = _save_path(PREF_FILE)
        with open(path, 'w') as f:
            f.write(f'board_theme={CURRENT_BOARD_THEME}\n')
            f.write(f'arrow_theme={CURRENT_ARROW_THEME}\n')
        print(f'[DEBUG] Preferences saved → {path}')
    except Exception as e:
        print(f'[DEBUG] Failed to save preferences: {e}')

def read_preferences():
    prefs = {}
    path = _save_path(PREF_FILE)
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if '=' not in line:
                    continue
                key, value = line.split('=', 1)
                prefs[key.strip()] = value.strip()
        print(f'[DEBUG] Preferences loaded ← {path} | {prefs}')
    except FileNotFoundError:
        print(f'[DEBUG] No preferences file found at {path}')
    except Exception as e:
        print(f'[DEBUG] Failed to load preferences: {e}')
    return prefs

def write_save(mode):
    path = _save_path(SAVE_FILES.get(mode))
    if not path or adapter is None:
        print(f'[DEBUG] write_save({mode}) skipped — path={path!r}, adapter={adapter}')
        return
    moves = ','.join(m.uci() for m in adapter.board.move_stack)
    if mode == STATE_BOT:
        meta = f'mode=bot,color={player_color},level={bot_level}'
    else:
        meta = 'mode=pvp'
    try:
        with open(path, 'w') as f:
            f.write(meta + '\n')
            f.write(moves + '\n')
    except Exception as e:
        print(f'[DEBUG] Failed to save game ({mode}): {e}')

def read_save(mode):
    path = _save_path(SAVE_FILES.get(mode))
    if not path:
        print(f'[DEBUG] read_save({mode}) — no path resolved')
        return None
    try:
        with open(path) as f:
            lines = f.read().strip().split('\n')
        meta = {}
        for part in lines[0].split(','):
            if '=' in part:
                k, v = part.split('=', 1)
                meta[k.strip()] = v.strip()
        raw_moves = lines[1] if len(lines) > 1 else ''
        moves = [chess.Move.from_uci(m) for m in raw_moves.split(',') if m.strip()]
        print(f'[DEBUG] Game loaded ({mode}) ← {path} | meta={meta} | moves={len(moves)}')
        return {'meta': meta, 'moves': moves}
    except FileNotFoundError:
        print(f'[DEBUG] No save file found for ({mode}) at {path}')
        return None
    except Exception as e:
        print(f'[DEBUG] Failed to load game ({mode}): {e}')
        return None

def delete_save(mode):
    path = _save_path(SAVE_FILES.get(mode))
    if path:
        try:
            os.remove(path)
            print(f'[DEBUG] Save deleted ({mode}) — {path}')
        except FileNotFoundError:
            print(f'[DEBUG] delete_save({mode}) — file already gone: {path}')
        except Exception as e:
            print(f'[DEBUG] Failed to delete save ({mode}): {e}')

# ── Game state ────────────────────────────────────────────────────────────────
state         = STATE_MENU
adapter       = None
winner_result = None
winner_alpha  = 0
game_over     = False
player_color  = 'white'
board_flipped = False
bot           = ChessBot(max_depth=3)
bot_thread    = None
bot_result    = None
bot_thinking  = False
think_dots    = 0
think_timer   = 0
promo_rects   = []

# Intermediate-screen UI rects
picker_rects          = {}
picker_back           = None
diff_back            = None
diff_confirm_rect    = None
diff_slider_rect     = None      # hit-area for the single 1-10 slider
diff_slider_info     = None      # (sl_x, sl_w, sl_y) for mouse math
diff_slider_dragging = False
diff_level           = 5         # current UI slider value (1-10); default Intermediate
bot_level            = 5         # active level used by launch_bot_move
menu_from_gameover_rect   = None

# Preferences screen UI rects
pref_board_rects    = {}
pref_arrow_rects    = {}
pref_back_rect      = None

# ── Review mode state ─────────────────────────────────────────────────────────
review_ply        = None   # None = live; int = ply index (0=start, N=after N moves)
review_board      = None   # chess.Board at review_ply
review_target     = None   # target ply for animated stepping
review_going_live = False  # True while stepping back to live position

# History panel UI
panel_scroll      = 0
history_ply_rects = []     # [(pygame.Rect, ply_index)]
live_btn_rect     = None

# Overlay state
continue_new_overlay = False
pending_mode         = None
pending_save_data    = None
overlay_cont_btn     = None
overlay_new_btn      = None

main_menu_overlay    = False
overlay_save_btn     = None
overlay_quit_btn     = None

menu_btn_ingame_rect = None   # "≡ Menu" button in the bottom tray

# Arrow drawing state
all_arrows        = []
arrow_start_sq    = None
CURRENT_BOARD_THEME = 'white_green'
CURRENT_ARROW_THEME = 'blue'
prefs = read_preferences()
board_theme = prefs.get('board_theme')
if board_theme in BOARD_THEMES:
    CURRENT_BOARD_THEME = board_theme
arrow_theme = prefs.get('arrow_theme')
if arrow_theme in ARROW_THEMES:
    CURRENT_ARROW_THEME = arrow_theme
ARROW_WIDTH       = 10
ARROW_HEAD_SIZE   = 18

# Animation state
# `anim` is either None or a dict: {'items': [item,...], 'start_ms': int}
# each item: {'sx','sy','ex','ey','img','suppress_sq'}
anim = None

# ── Coordinate helpers ────────────────────────────────────────────────────────

def sq_to_screen(sq):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    if board_flipped:
        x = BOARD_X + (7 - file) * TILE + TILE // 2
        y = BOARD_Y + rank * TILE + TILE // 2
    else:
        x = BOARD_X + file * TILE + TILE // 2
        y = BOARD_Y + (7 - rank) * TILE + TILE // 2
    return x, y

def sq_to_board(sq):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    if board_flipped:
        x = (7 - file) * TILE + TILE // 2
        y = rank * TILE + TILE // 2
    else:
        x = file * TILE + TILE // 2
        y = (7 - rank) * TILE + TILE // 2
    return x, y


def pixel_to_sq(bx, by):
    col = max(0, min(7, bx // TILE))
    row = max(0, min(7, by // TILE))
    if board_flipped:
        return chess.square(7 - col, row)
    return chess.square(col, 7 - row)

def _draw_arrow(surface, start, end, color, width=ARROW_WIDTH, head_size=ARROW_HEAD_SIZE):
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    dist = math.hypot(dx, dy)
    if dist < 1:
        return

    nx = dx / dist
    ny = dy / dist
    perp_x = -ny
    perp_y = nx
    head_dx = nx * head_size
    head_dy = ny * head_size
    tip = (ex, ey)
    base = (ex - head_dx, ey - head_dy)

    half_w = width / 2
    p1 = (sx + perp_x * half_w, sy + perp_y * half_w)
    p2 = (base[0] + perp_x * half_w, base[1] + perp_y * half_w)
    p3 = (base[0] - perp_x * half_w, base[1] - perp_y * half_w)
    p4 = (sx - perp_x * half_w, sy - perp_y * half_w)

    wing1 = (base[0] + perp_x * head_size * 0.55,
             base[1] + perp_y * head_size * 0.55)
    wing2 = (base[0] - perp_x * head_size * 0.55,
             base[1] - perp_y * head_size * 0.55)

    pygame.draw.polygon(surface, color, [p1, p2, p3, p4])
    pygame.draw.polygon(surface, color, [tip, wing1, wing2])


def _draw_polyline_arrow(surface, points, color, width=ARROW_WIDTH, head_size=ARROW_HEAD_SIZE):
    if len(points) < 2:
        return
    for i in range(len(points) - 1):
        segment_start = points[i]
        segment_end = points[i + 1]
        if i == len(points) - 2:
            _draw_arrow(surface, segment_start, segment_end, color, width, head_size)
        else:
            pygame.draw.line(surface, color, segment_start, segment_end, width)


def _arrow_path(start_sq, end_sq):
    start = sq_to_board(start_sq)
    end = sq_to_board(end_sq)
    dx = abs(chess.square_file(end_sq) - chess.square_file(start_sq))
    dy = abs(chess.square_rank(end_sq) - chess.square_rank(start_sq))
    if (dx, dy) in ((1, 2), (2, 1)):
        if dy > dx:
            corner = (start[0], end[1])
        else:
            corner = (end[0], start[1])
        return [start, corner, end]
    return [start, end]


def _draw_board_arrow_overlay():
    if not all_arrows:
        return

    arrow_color = ARROW_THEMES[CURRENT_ARROW_THEME]
    arrow_surf = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
    for start_sq, end_sq in all_arrows:
        points = _arrow_path(start_sq, end_sq)
        _draw_polyline_arrow(arrow_surf, points, arrow_color)
    screen.blit(arrow_surf, (BOARD_X, BOARD_Y))


def is_animating():
    return (anim is not None
            and (pygame.time.get_ticks() - anim['start_ms']) < ANIM_MS
            and len(anim.get('items', [])) > 0)

def start_anim(from_sq, to_sq, img):
    global anim
    sx, sy = sq_to_screen(from_sq)
    ex, ey = sq_to_screen(to_sq)
    item = {
        'sx': sx,     'sy': sy,
        'ex': ex,     'ey': ey,
        'img': img,
        'suppress_sq': to_sq,
    }
    if anim is None or not is_animating():
        anim = {'items': [item], 'start_ms': pygame.time.get_ticks()}
    else:
        # append to existing animation batch (will play simultaneously)
        anim['items'].append(item)

def ease_out(t):
    return 1.0 - (1.0 - min(1.0, max(0.0, t))) ** 2

# ── Review helpers ────────────────────────────────────────────────────────────

def build_review_board(ply):
    """Return chess.Board with first `ply` moves applied."""
    b = chess.Board()
    for move in list(adapter.board.move_stack)[:ply]:
        b.push(move)
    return b

def _reset_review():
    global review_ply, review_board, review_target, review_going_live
    review_ply        = None
    review_board      = None
    review_target     = None
    review_going_live = False

def _enter_review(target_ply):
    """Enter review mode (or change target) and animate directly to target_ply."""
    global review_ply, review_board, review_target, review_going_live, anim
    if review_ply is None:
        review_ply   = len(adapter.san_history)
        review_board = build_review_board(review_ply)

    if target_ply == review_ply:
        return

    move_list = list(adapter.board.move_stack)
    items = []
    now = pygame.time.get_ticks()
    if target_ply > review_ply:
        cur_board = review_board.copy()
        for i in range(review_ply, min(target_ply, len(move_list))):
            m = move_list[i]
            piece = cur_board.piece_at(m.from_square)
            img = PIECE_IMGS.get((piece.piece_type, piece.color)) if piece else None
            sx, sy = sq_to_screen(m.from_square)
            ex, ey = sq_to_screen(m.to_square)
            items.append({'sx': sx, 'sy': sy, 'ex': ex, 'ey': ey,
                          'img': img, 'suppress_sq': m.to_square})
            cur_board.push(m)
    else:
        cur_board = review_board.copy()
        for i in range(review_ply - 1, max(target_ply - 1, -1), -1):
            m = move_list[i]
            piece = cur_board.piece_at(m.to_square)
            img = PIECE_IMGS.get((piece.piece_type, piece.color)) if piece else None
            sx, sy = sq_to_screen(m.to_square)
            ex, ey = sq_to_screen(m.from_square)
            items.append({'sx': sx, 'sy': sy, 'ex': ex, 'ey': ey,
                          'img': img, 'suppress_sq': m.from_square})
            cur_board.pop()

    review_ply = target_ply
    review_board = build_review_board(review_ply)
    review_target = None
    review_going_live = False

    if items:
        anim = {'items': items, 'start_ms': now}

def _exit_review():
    """Return immediately to live position without animating."""
    global review_ply, review_board, review_target, review_going_live, anim
    review_ply = None
    review_board = None
    review_target = None
    review_going_live = False
    anim = None

def _move_review(delta):
    """Step review mode by delta plys using arrow keys."""
    if adapter is None:
        return
    total_plies = len(adapter.san_history)
    if total_plies == 0:
        return

    if review_ply is None:
        if delta < 0:
            _enter_review(total_plies - 1)
        elif delta > 0:
            _enter_review(1)
        return

    target = review_ply + delta
    if target <= 0:
        target = 0
    elif target >= total_plies:
        target = total_plies

    if target == total_plies:
        _exit_review()
    elif target != review_ply:
        _enter_review(target)


def step_review_toward_target():
    """Take one animation step from review_ply toward review_target."""
    global review_ply, review_board, review_target, review_going_live
    if review_target is None:
        return
    # Already arrived?
    if review_ply == review_target:
        if review_going_live:
            review_ply        = None
            review_board      = None
            review_going_live = False
        review_target = None
        return

    move_list = list(adapter.board.move_stack)
    direction = 1 if review_target > review_ply else -1

    if direction == 1 and review_ply < len(move_list):
        move  = move_list[review_ply]
        piece = review_board.piece_at(move.from_square)
        img   = PIECE_IMGS.get((piece.piece_type, piece.color)) if piece else None
        review_ply  += 1
        review_board = build_review_board(review_ply)
        start_anim(move.from_square, move.to_square, img)
    elif direction == -1 and review_ply > 0:
        move  = move_list[review_ply - 1]
        piece = review_board.piece_at(move.to_square)
        img   = PIECE_IMGS.get((piece.piece_type, piece.color)) if piece else None
        review_ply  -= 1
        review_board = build_review_board(review_ply)
        start_anim(move.to_square, move.from_square, img)   # reversed

# ── Game lifecycle ────────────────────────────────────────────────────────────

def start_game():
    global adapter, winner_result, winner_alpha, game_over
    global promo_rects, bot_thread, bot_result, bot_thinking, anim
    global review_ply, review_board, review_target, review_going_live, panel_scroll
    adapter        = ChessAdapter()
    winner_result  = None
    winner_alpha   = 0
    game_over      = False
    promo_rects    = []
    bot_thread     = None
    bot_result     = None
    bot_thinking   = False
    anim           = None
    review_ply        = None
    review_board      = None
    review_target     = None
    review_going_live = False
    panel_scroll      = 0
    bot.clear_tt()

def launch_bot_move():
    global bot_thread, bot_thinking
    bot_color    = 'black' if player_color == 'white' else 'white'
    bot_thinking = True

    def _run():
        global bot_result, bot_thinking
        board_copy = adapter.board.copy()
        move       = bot.get_move(board_copy, bot_color, bot_level)
        with _bot_lock:
            bot_result   = move
            bot_thinking = False

    bot_thread = threading.Thread(target=_run, daemon=True)
    bot_thread.start()

def _continue_saved_game(save_data, mode):
    """Restore settings from save, replay moves silently, optionally trigger bot."""
    global player_color, board_flipped, bot_level, diff_level, state
    meta  = save_data['meta']
    moves = save_data['moves']
    if mode == STATE_BOT:
        color         = meta.get('color', 'white')
        player_color  = color
        board_flipped = (color == 'black')
        # Support both the new 'level' key and the old 'difficulty' key so
        # save files written by earlier versions of the game still load.
        if 'level' in meta:
            level = int(meta['level'])
        elif 'difficulty' in meta:
            level = int(meta.get('difficulty', '5'))
        else:
            level = 5
        bot_level  = level
        diff_level = level          # sync the UI slider position
    else:
        board_flipped = False
    state = mode
    start_game()
    for move in moves:
        if move in adapter.board.legal_moves:
            adapter.apply_move(move)
    if mode == STATE_BOT and not adapter.is_game_over:
        if adapter.turn != player_color:
            launch_bot_move()
    write_save(state)   # persist restored state

# ── Piece-point table (mirrors ChessAdapter) ──────────────────────────────────
_PIECE_POINTS = {
    chess.PAWN:   1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK:   5, chess.QUEEN:  9,
}
_TRAY_ORDER = [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]

def _group_captures(pieces):
    counts = {}
    for info in pieces:
        pt    = _NOTATION_TO_PT.get(info['notation'], chess.PAWN)
        color = info['color']
        key   = (pt, color)
        counts[key] = counts.get(key, 0) + 1
    result = []
    for pt in _TRAY_ORDER:
        for color in ('white', 'black'):
            k = (pt, color)
            if k in counts:
                result.append((pt, color, counts[k]))
    return result

# ── Draw: chess board surface ─────────────────────────────────────────────────

def draw_chess_board():
    """Draw the board, honouring review_board when in review mode."""
    # Get current board theme colors
    board_theme = BOARD_THEMES[CURRENT_BOARD_THEME]
    theme_light = board_theme['light']
    theme_dark = board_theme['dark']
    
    if review_ply is not None and review_board is not None:
        board     = review_board
        move_list = list(adapter.board.move_stack)
        last_move = move_list[review_ply - 1] if review_ply > 0 else None
        check_sq  = (review_board.king(review_board.turn)
                     if review_board.is_check() else None)
        sel_sq    = None
        targets   = set()
    else:
        board     = adapter.board
        check_sq  = adapter.check_square
        last_move = adapter.last_move
        sel_sq    = adapter.selected_square
        targets   = adapter.valid_move_targets

    if is_animating():
        sup_items = [it.get('suppress_sq') for it in anim.get('items', []) if it.get('suppress_sq') is not None]
        suppress = set(sup_items) if sup_items else None
    else:
        suppress = None

    for rank in range(8):
        for file in range(8):
            sq = chess.square(file, rank)
            if board_flipped:
                sx = (7 - file) * TILE
                sy = rank * TILE
            else:
                sx = file * TILE
                sy = (7 - rank) * TILE
            rect     = pygame.Rect(sx, sy, TILE, TILE)
            is_light = (file + rank) % 2 == 1

            if sq == check_sq:
                col = SQ_CHK_L  if is_light else SQ_CHK_D
            elif sq == sel_sq:
                col = SQ_SEL_L  if is_light else SQ_SEL_D
            elif last_move and sq in (last_move.from_square, last_move.to_square):
                col = SQ_LAST_L if is_light else SQ_LAST_D
            else:
                col = theme_light if is_light else theme_dark

            pygame.draw.rect(board_surf, col, rect)

            if not (suppress and sq in suppress):
                piece = board.piece_at(sq)
                if piece:
                    img = PIECE_IMGS.get((piece.piece_type, piece.color))
                    if img:
                        board_surf.blit(img, img.get_rect(center=rect.center))

            if sel_sq is not None and sq in targets:
                cx, cy    = rect.center
                has_piece = board.piece_at(sq) and sq != suppress
                surf      = _IND_RING if has_piece else _IND_DOT
                board_surf.blit(surf, (cx - _IND_R, cy - _IND_R))

# ── Draw: labels ──────────────────────────────────────────────────────────────

def draw_labels():
    files = 'hgfedcba' if board_flipped else 'abcdefgh'
    for y in range(8):
        rank = str(y + 1) if board_flipped else str(8 - y)
        s    = F_LABEL.render(rank, True, LABEL_COL)
        ry   = BOARD_Y + y * TILE + (TILE - s.get_height()) // 2
        screen.blit(s, (BOARD_X - s.get_width() - 4, ry))
    for x, letter in enumerate(files):
        s  = F_LABEL.render(letter, True, LABEL_COL)
        fx = BOARD_X + x * TILE + (TILE - s.get_width()) // 2
        screen.blit(s, (fx, BOARD_Y + BOARD_PX + 5))

# ── Draw: trays ───────────────────────────────────────────────────────────────

def draw_tray(y0, pieces, label, lead=0, thinking=False):
    W = PANEL_X   # tray only spans the board area
    pygame.draw.rect(screen, TRAY_BG, (0, y0, W, TRAY_H))
    pygame.draw.line(screen, (62, 62, 62), (0, y0), (W, y0))
    lbl = F_LABEL.render(label, True, (140, 140, 140))
    screen.blit(lbl, (6, y0 + 4))

    if thinking:
        dots = '.' * (1 + think_dots % 3)
        ts   = F_THINK.render(f'Bot is thinking{dots}', True, MENU_ACCENT)
        screen.blit(ts, ts.get_rect(midright=(W - 90, y0 + TRAY_H // 2)))

    grouped = _group_captures(pieces)
    ICON_W  = 28
    cx      = 6
    cy_icon = y0 + 20
    for pt, color, count in grouped:
        key = f"{color[0]}_{_PIECE_NAMES.get(pt, 'pawn')}"
        img = TRAY_IMGS.get(key)
        if img:
            screen.blit(img, (cx, cy_icon))
        if count > 1:
            badge = F_COUNT.render(f'x{count}', True, (220, 220, 220))
            screen.blit(badge, (cx + ICON_W - badge.get_width(), cy_icon + ICON_W - 2))
        cx += ICON_W + (6 if count > 1 else 2)
        if cx + ICON_W > W - 100:
            break
    if lead > 0:
        lead_s = F_LEAD.render(f'+{lead}', True, (180, 220, 130))
        screen.blit(lead_s, (cx + 6, cy_icon + 6))

# ── Draw: promotion overlay ───────────────────────────────────────────────────

def draw_promotion_overlay():
    # Draw the whole promotion overlay into a temporary surface first
    # and blit it onto `screen` in one step. This avoids blending
    # interactions that can corrupt previously-drawn board pixels.
    overlay = pygame.Surface((BOARD_PX, BOARD_PX), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 155))
    color_char = 'w' if adapter.turn == 'white' else 'b'

    icon, gap, pad = 54, 6, 10
    n     = len(PROMO_OPTIONS)
    box_w = n * icon + (n - 1) * gap + pad * 2
    box_h = icon + pad * 2
    box_x = BOARD_X + (BOARD_PX - box_w) // 2
    box_y = BOARD_Y + (BOARD_PX - box_h) // 2
    lbl_h = 18

    # Panel coordinates relative to overlay surface
    panel  = pygame.Rect(box_x - 2 - BOARD_X, box_y - lbl_h - 6 - BOARD_Y,
                         box_w + 4, box_h + lbl_h + 10)
    pygame.draw.rect(overlay, PROMO_BG_C, panel, border_radius=10)
    pygame.draw.rect(overlay, PROMO_BRD,  panel, 1, border_radius=10)
    title = F_LABEL.render('PROMOTE TO', True, (140, 140, 140))
    overlay.blit(title, (box_x + (box_w - title.get_width()) // 2 - BOARD_X,
                         box_y - lbl_h - 2 - BOARD_Y))

    mx, my = pygame.mouse.get_pos()
    rects  = []
    for i, (label, pt, pname) in enumerate(PROMO_OPTIONS):
        ix   = box_x + pad + i * (icon + gap)
        iy   = box_y + pad
        rect = pygame.Rect(ix - 3, iy - 3, icon + 6, icon + 6)
        hov  = rect.collidepoint(mx, my)
        # Draw rects onto overlay (translate coords to overlay-local)
        rect_local = pygame.Rect(rect.x - BOARD_X, rect.y - BOARD_Y,
                                 rect.width, rect.height)
        pygame.draw.rect(overlay, PROMO_HOV if hov else PROMO_NORM, rect_local, border_radius=7)
        if hov:
            pygame.draw.rect(overlay, (150, 150, 150), rect_local, 1, border_radius=7)
            tip    = F_LABEL.render(label, True, (220, 220, 220))
            tip_w  = tip.get_width() + 10
            tip_x  = rect.centerx - tip_w // 2
            tip_y  = rect.top - 22
            tip_bg = pygame.Rect(tip_x - 2 - BOARD_X, tip_y - BOARD_Y, tip_w + 4, 18)
            pygame.draw.rect(overlay, (55, 55, 55), tip_bg, border_radius=4)
            overlay.blit(tip, (tip_x + 3 - BOARD_X, tip_y + 2 - BOARD_Y))
        img = PROMO_IMGS_S.get(f'{color_char}_{pname}')
        if img:
            img_rect = img.get_rect(center=rect.center)
            overlay.blit(img, img_rect.move(-BOARD_X, -BOARD_Y))
        rects.append((rect, pt))

    try:
        overlay = overlay.convert_alpha()
    except Exception:
        pass
    screen.blit(overlay, (BOARD_X, BOARD_Y))
    return rects

# ── Draw: winner fade ─────────────────────────────────────────────────────────

def draw_winner(result, alpha):
    global menu_from_gameover_rect
    headline, subtitle = result
    ov = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    ov.fill((0, 0, 0, min(alpha, 175)))
    screen.blit(ov, (0, 0))
    menu_from_gameover_rect = None
    if alpha > 80:
        a  = min(255, (alpha - 80) * 5)
        cx = PANEL_X // 2   # centre of board area
        cy = WIN_H // 2

        head_col = (255, 215, 0) if 'Wins' in headline else (180, 180, 220)
        ws = F_WIN.render(headline, True, head_col)
        ws.set_alpha(a)
        screen.blit(ws, ws.get_rect(center=(cx, cy - 44)))
        if subtitle:
            ss = F_WIN_S.render(subtitle, True, (200, 200, 200))
            ss.set_alpha(a)
            screen.blit(ss, ss.get_rect(center=(cx, cy + 8)))
        if a > 200:
            bw, bh = 180, 42
            btn    = pygame.Rect(cx - bw // 2, cy + 44, bw, bh)
            mx_, my_ = pygame.mouse.get_pos()
            hov  = btn.collidepoint(mx_, my_)
            bg   = pygame.Surface((bw, bh), pygame.SRCALPHA)
            bg.fill((60, 60, 60, 210) if hov else (40, 40, 40, 190))
            screen.blit(bg, btn.topleft)
            border_col = (160, 160, 160) if hov else (90, 90, 90)
            pygame.draw.rect(screen, border_col, btn, 1, border_radius=8)
            lbl = F_BTN.render('Main Menu', True, (220, 220, 220) if hov else (170, 170, 170))
            lbl.set_alpha(a)
            screen.blit(lbl, lbl.get_rect(center=btn.center))
            menu_from_gameover_rect = btn

# ── Draw: history panel ───────────────────────────────────────────────────────

def draw_history_panel():
    global history_ply_rects, live_btn_rect, panel_scroll

    # Panel background strip
    pygame.draw.rect(screen, PANEL_BG, (PANEL_X, 0, PANEL_W, WIN_H))
    pygame.draw.line(screen, PANEL_BDR, (PANEL_X, 0), (PANEL_X, WIN_H), 1)

    # Header
    pygame.draw.rect(screen, PANEL_HDR_BG, (PANEL_X, 0, PANEL_W, HIST_HDR_H))
    pygame.draw.line(screen, PANEL_BDR, (PANEL_X, HIST_HDR_H), (WIN_W, HIST_HDR_H), 1)
    hdr_s = F_HIST_HDR.render('MOVE HISTORY', True, (88, 88, 88))
    screen.blit(hdr_s, hdr_s.get_rect(midleft=(PANEL_X + HIST_PAD, HIST_HDR_H // 2)))
    if review_ply is not None:
        rv_s = F_HIST_HDR.render('● REVIEW', True, (110, 180, 100))
        screen.blit(rv_s, rv_s.get_rect(midright=(WIN_W - HIST_PAD, HIST_HDR_H // 2)))

    # Footer area
    foot_y = WIN_H - HIST_FOOT_H
    pygame.draw.line(screen, PANEL_BDR, (PANEL_X, foot_y), (WIN_W, foot_y), 1)
    btn_m        = 6
    live_btn_rect = pygame.Rect(PANEL_X + btn_m, foot_y + btn_m,
                                 PANEL_W - btn_m * 2, HIST_FOOT_H - btn_m * 2)
    mx_, my_      = pygame.mouse.get_pos()
    is_live_now   = review_ply is None
    live_hov      = live_btn_rect.collidepoint(mx_, my_) and not is_live_now
    live_bg       = LIVE_BG_OFF if is_live_now else (LIVE_BG_HOV if live_hov else LIVE_BG_ACT)
    pygame.draw.rect(screen, live_bg, live_btn_rect, border_radius=6)
    live_brd = (50, 50, 50) if is_live_now else (80, 155, 80)
    pygame.draw.rect(screen, live_brd, live_btn_rect, 1, border_radius=6)
    live_label = '● LIVE' if is_live_now else 'Live'
    live_col   = (55, 55, 55) if is_live_now else (190, 238, 190)
    live_s = F_LIVE_BTN.render(live_label, True, live_col)
    screen.blit(live_s, live_s.get_rect(center=live_btn_rect.center))

    if adapter is None:
        return

    san_list    = adapter.san_history
    total_plies = len(san_list)
    n_rows      = (total_plies + 1) // 2

    # Current display ply for highlighting
    if review_ply is not None:
        cur_ply = review_ply
    else:
        cur_ply = total_plies   # 1-based: after total_plies moves

    # List area bounds
    list_top_y = HIST_HDR_H
    list_bot_y = foot_y
    list_h     = list_bot_y - list_top_y

    # Auto-scroll to keep current ply visible
    if cur_ply > 0:
        cur_row = (cur_ply - 1) // 2
    else:
        cur_row = 0
    max_scroll   = max(0, n_rows * HIST_ROW_H - list_h)
    row_y_abs    = cur_row * HIST_ROW_H
    if row_y_abs < panel_scroll:
        panel_scroll = row_y_abs
    elif row_y_abs + HIST_ROW_H > panel_scroll + list_h:
        panel_scroll = row_y_abs + HIST_ROW_H - list_h
    panel_scroll = max(0, min(max_scroll, panel_scroll))

    # Clipped list drawing
    screen.set_clip(pygame.Rect(PANEL_X, list_top_y, PANEL_W, list_h))
    history_ply_rects = []

    for row_i in range(n_rows):
        w_idx = row_i * 2
        b_idx = row_i * 2 + 1
        row_y = list_top_y + row_i * HIST_ROW_H - panel_scroll

        if row_y + HIST_ROW_H < list_top_y or row_y > list_bot_y:
            continue

        # Alternating row tint
        row_bg = (30, 30, 30) if row_i % 2 == 0 else PANEL_BG
        pygame.draw.rect(screen, row_bg,
                         (PANEL_X, row_y, PANEL_W, HIST_ROW_H))

        # Move number
        num_s = F_HIST_NUM.render(f'{row_i + 1}.', True, HIST_NUM_COL)
        screen.blit(num_s, (PANEL_X + HIST_PAD,
                             row_y + (HIST_ROW_H - num_s.get_height()) // 2))

        # White ply
        w_ply = w_idx + 1   # 1-based review ply index
        if w_idx < total_plies:
            wx     = PANEL_X + HIST_PAD + HIST_NUM_W
            w_rect = pygame.Rect(wx, row_y, HIST_MOV_W, HIST_ROW_H)
            w_sel  = (cur_ply == w_ply)
            w_hov  = w_rect.collidepoint(mx_, my_)
            if w_sel:
                pygame.draw.rect(screen, HIST_SEL_BG, w_rect, border_radius=3)
            elif w_hov:
                pygame.draw.rect(screen, HIST_ROW_HOV, w_rect, border_radius=3)
            w_col = HIST_SEL_FG if w_sel else HIST_MOV_COL
            w_s   = F_HIST_MOV.render(san_list[w_idx], True, w_col)
            screen.blit(w_s, (wx + 4, row_y + (HIST_ROW_H - w_s.get_height()) // 2))
            history_ply_rects.append((w_rect, w_ply))

        # Black ply
        b_ply = b_idx + 1
        if b_idx < total_plies:
            bx     = PANEL_X + HIST_PAD + HIST_NUM_W + HIST_MOV_W
            b_rect = pygame.Rect(bx, row_y, HIST_MOV_W, HIST_ROW_H)
            b_sel  = (cur_ply == b_ply)
            b_hov  = b_rect.collidepoint(mx_, my_)
            if b_sel:
                pygame.draw.rect(screen, HIST_SEL_BG, b_rect, border_radius=3)
            elif b_hov:
                pygame.draw.rect(screen, HIST_ROW_HOV, b_rect, border_radius=3)
            b_col = HIST_SEL_FG if b_sel else HIST_MOV_COL
            b_s   = F_HIST_MOV.render(san_list[b_idx], True, b_col)
            screen.blit(b_s, (bx + 4, row_y + (HIST_ROW_H - b_s.get_height()) // 2))
            history_ply_rects.append((b_rect, b_ply))

    screen.set_clip(None)

    # Scrollbar
    if n_rows > 0 and n_rows * HIST_ROW_H > list_h:
        sb_ratio = panel_scroll / max(1, n_rows * HIST_ROW_H)
        sb_size  = max(20, int(list_h * list_h / max(1, n_rows * HIST_ROW_H)))
        sb_y     = list_top_y + int((list_h - sb_size) * sb_ratio)
        pygame.draw.rect(screen, (58, 58, 58),
                         (WIN_W - 5, sb_y, 4, sb_size), border_radius=2)

# ── Draw: overlays ────────────────────────────────────────────────────────────

def draw_continue_new_overlay():
    global overlay_cont_btn, overlay_new_btn
    ov = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 200))
    screen.blit(ov, (0, 0))

    cx = WIN_W // 2
    cy = WIN_H // 2
    bw, bh = 340, 200
    box = pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh)
    pygame.draw.rect(screen, (30, 30, 30), box, border_radius=14)
    pygame.draw.rect(screen, (66, 66, 66), box, 2, border_radius=14)

    mode_name = 'PvP' if pending_mode == STATE_PVP else 'Bot'
    t_s = F_OV_TITLE.render('Resume Saved Game?', True, MENU_TEXT)
    screen.blit(t_s, t_s.get_rect(center=(cx, cy - 62)))
    s_s = F_OV_SUB.render(f'A saved {mode_name} game was found.', True, MENU_TEXT_SUB)
    screen.blit(s_s, s_s.get_rect(center=(cx, cy - 36)))

    mx_, my_ = pygame.mouse.get_pos()
    bw2, bh2 = 138, 44
    cont_btn = pygame.Rect(cx - bw2 - 7, cy + 4, bw2, bh2)
    new_btn  = pygame.Rect(cx + 7,        cy + 4, bw2, bh2)
    for btn, label, accent in [
        (cont_btn, 'Continue',  (65, 115, 65)),
        (new_btn,  'New Game',  (140, 75, 55)),
    ]:
        hov = btn.collidepoint(mx_, my_)
        bg  = tuple(min(255, int(c * (0.48 if hov else 0.30))) for c in accent)
        pygame.draw.rect(screen, bg, btn, border_radius=8)
        brd = accent if hov else tuple(int(c * 0.58) for c in accent)
        pygame.draw.rect(screen, brd, btn, 1, border_radius=8)
        l_s = F_OV_BTN.render(label, True, MENU_TEXT)
        screen.blit(l_s, l_s.get_rect(center=btn.center))
    overlay_cont_btn = cont_btn
    overlay_new_btn  = new_btn


def draw_main_menu_overlay():
    global overlay_save_btn, overlay_quit_btn
    ov = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    ov.fill((0, 0, 0, 200))
    screen.blit(ov, (0, 0))

    cx = PANEL_X // 2   # centre of board area
    cy = WIN_H // 2
    bw, bh = 310, 210
    box = pygame.Rect(cx - bw // 2, cy - bh // 2, bw, bh)
    pygame.draw.rect(screen, (30, 30, 30), box, border_radius=14)
    pygame.draw.rect(screen, (66, 66, 66), box, 2, border_radius=14)

    t_s = F_OV_TITLE.render('Main Menu', True, MENU_TEXT)
    screen.blit(t_s, t_s.get_rect(center=(cx, cy - 66)))
    s_s = F_OV_SUB.render('What would you like to do?', True, MENU_TEXT_SUB)
    screen.blit(s_s, s_s.get_rect(center=(cx, cy - 40)))

    mx_, my_ = pygame.mouse.get_pos()
    bw2 = 210
    save_btn = pygame.Rect(cx - bw2 // 2, cy - 12, bw2, 42)
    quit_btn = pygame.Rect(cx - bw2 // 2, cy + 40, bw2, 42)
    for btn, label, font, accent in [
        (save_btn, 'Save & Quit',        F_OV_BTN,    (65, 115, 65)),
        (quit_btn, 'Quit Without Saving', F_OV_BTN_SM, (130, 65, 55)),
    ]:
        hov = btn.collidepoint(mx_, my_)
        bg  = tuple(min(255, int(c * (0.48 if hov else 0.28))) for c in accent)
        pygame.draw.rect(screen, bg, btn, border_radius=8)
        brd = accent if hov else tuple(int(c * 0.58) for c in accent)
        pygame.draw.rect(screen, brd, btn, 1, border_radius=8)
        l_s = font.render(label, True, MENU_TEXT)
        screen.blit(l_s, l_s.get_rect(center=btn.center))
    overlay_save_btn = save_btn
    overlay_quit_btn = quit_btn

# ── Draw: full game frame ─────────────────────────────────────────────────────

def draw_game(is_bot_mode=False):
    global promo_rects, winner_alpha, winner_result, game_over
    global menu_btn_ingame_rect

    bot_color    = ('black' if player_color == 'white' else 'white') if is_bot_mode else None
    top_thinking = is_bot_mode and bot_thinking and bot_color == 'black'
    bot_thinking_bottom = is_bot_mode and bot_thinking and bot_color == 'white'

    screen.fill(BG)

    # History panel (draws right strip first so trays don't bleed under it)
    draw_history_panel()

    # Trays
    wl, bl = adapter.material_advantage()
    if board_flipped:
        draw_tray(0,         adapter.captured_pieces['black'],
                  "White's captures", lead=wl, thinking=top_thinking)
    else:
        draw_tray(0,         adapter.captured_pieces['black'],
                  "Black's captures", lead=bl, thinking=top_thinking)

    # Board shadow
    pygame.draw.rect(screen, SHADOW, (BOARD_X + 5, BOARD_Y + 5, BOARD_PX, BOARD_PX))

    draw_chess_board()
    screen.blit(board_surf, (BOARD_X, BOARD_Y))
    _draw_board_arrow_overlay()
    pygame.draw.rect(screen, (50, 50, 50), (BOARD_X, BOARD_Y, BOARD_PX, BOARD_PX), 1)

    # Review-mode lock indicator — subtle coloured border
    if review_ply is not None:
        pygame.draw.rect(screen, (80, 140, 80),
                         (BOARD_X, BOARD_Y, BOARD_PX, BOARD_PX), 2)

    # Animated piece(s)
    if is_animating():
        now = pygame.time.get_ticks()
        t = ease_out((now - anim['start_ms']) / ANIM_MS)
        for item in anim.get('items', []):
            px = item['sx'] + (item['ex'] - item['sx']) * t
            py = item['sy'] + (item['ey'] - item['sy']) * t
            img = item.get('img')
            if img:
                screen.blit(img, img.get_rect(center=(int(px), int(py))))

    draw_labels()

    bottom_y = BOARD_Y + BOARD_PX + FILE_LABEL_H
    if board_flipped:
        draw_tray(bottom_y, adapter.captured_pieces['white'],
                  "Black's captures", lead=bl, thinking=bot_thinking_bottom)
    else:
        draw_tray(bottom_y, adapter.captured_pieces['white'],
                  "White's captures", lead=wl, thinking=bot_thinking_bottom)

    # ≡ Menu button in bottom tray
    mb_w, mb_h = 74, 28
    mb_x = PANEL_X - mb_w - 8
    mb_y = bottom_y + (TRAY_H - mb_h) // 2
    menu_btn_ingame_rect = pygame.Rect(mb_x, mb_y, mb_w, mb_h)
    mx_, my_ = pygame.mouse.get_pos()
    mm_hov   = menu_btn_ingame_rect.collidepoint(mx_, my_)
    pygame.draw.rect(screen,
                     (52, 52, 52) if mm_hov else (42, 42, 42),
                     menu_btn_ingame_rect, border_radius=6)
    pygame.draw.rect(screen,
                     (90, 90, 90) if mm_hov else (62, 62, 62),
                     menu_btn_ingame_rect, 1, border_radius=6)
    mm_s = F_IGMENU.render('≡  Menu', True,
                            (210, 210, 210) if mm_hov else (140, 140, 140))
    screen.blit(mm_s, mm_s.get_rect(center=menu_btn_ingame_rect.center))

    # Promotion overlay
    if adapter.promotion_pending and not is_animating():
        promo_rects = draw_promotion_overlay()
    else:
        promo_rects = []

    # Game-over detection (live mode only)
    if review_ply is None:
        if not game_over and not adapter.promotion_pending and not is_animating():
            if adapter.is_game_over:
                winner_result = adapter.game_result_text
                game_over     = True
        if game_over:
            winner_alpha = min(winner_alpha + 3, 255)
            draw_winner(winner_result, winner_alpha)

    # In-game overlays
    if main_menu_overlay:
        draw_main_menu_overlay()

# ── Draw: menu screens ────────────────────────────────────────────────────────

def draw_menu():
    screen.fill(MENU_BG)
    tile = 36
    for col in range(WIN_W // tile + 1):
        c = (32, 32, 32) if col % 2 == 0 else (26, 26, 26)
        pygame.draw.rect(screen, c, (col * tile, 0, tile, tile * 2))
    pygame.draw.line(screen, (40, 40, 40), (0, tile*2), (WIN_W, tile*2), 1)
    cx    = WIN_W // 2
    title = F_TITLE.render('Python Chess', True, MENU_ACCENT)
    screen.blit(title, title.get_rect(center=(cx, WIN_H // 2 - 70)))
    tw = title.get_width()
    pygame.draw.line(screen, MENU_ACCENT,
                     (cx - tw//2, WIN_H//2 - 40), (cx + tw//2, WIN_H//2 - 40), 2)
    for btn in menu_buttons:
        btn.draw(screen)
    foot = F_SUBTITLE.render('Built with Python & pygame', True, (55, 55, 55))
    screen.blit(foot, foot.get_rect(center=(cx, WIN_H - 22)))
    if continue_new_overlay:
        draw_continue_new_overlay()


def draw_color_picker():
    screen.fill(MENU_BG)
    cx = WIN_W // 2
    s  = F_PICK.render('Choose your colour', True, MENU_TEXT)
    screen.blit(s, s.get_rect(center=(cx, 120)))
    s  = F_PICK_S.render('Click the side you want to play', True, MENU_TEXT_SUB)
    screen.blit(s, s.get_rect(center=(cx, 158)))

    mx, my = pygame.mouse.get_pos()
    bw, bh = 200, 220
    x0     = cx - (bw * 2 + 40) // 2
    rects  = {}
    for color, label, bg, fg, bx in (
        ('white', 'White', PICK_LIGHT, (50, 50, 50),   x0),
        ('black', 'Black', PICK_DARK,  (200,200,200),  x0 + bw + 40),
    ):
        by_  = WIN_H // 2 - bh // 2
        rect = pygame.Rect(bx, by_, bw, bh)
        hov  = rect.collidepoint(mx, my)
        pygame.draw.rect(screen, bg,  rect, border_radius=12)
        pygame.draw.rect(screen, PICK_HOVER if hov else (90,90,90), rect, 3, border_radius=12)
        img  = KING_IMGS[color]
        screen.blit(img, img.get_rect(center=(bx + bw//2, by_ + bh//2 - 15)))
        lbl  = F_BTN.render(label, True, fg)
        screen.blit(lbl, lbl.get_rect(center=(bx + bw//2, by_ + bh - 28)))
        rects[color] = rect
    s = F_PICK_S.render('← Back', True, MENU_TEXT_SUB)
    screen.blit(s, (18, 18))
    return rects, pygame.Rect(0, 0, 80, 36)


def _draw_slider(value, vmin, vmax, sl_x, sl_w, sl_y, color):
    t = (value - vmin) / (vmax - vmin)
    pygame.draw.rect(screen, (48, 48, 48), (sl_x, sl_y - 4, sl_w, 8), border_radius=4)
    fill_w = max(8, int(sl_w * t))
    pygame.draw.rect(screen, color, (sl_x, sl_y - 4, fill_w, 8), border_radius=4)
    steps = vmax - vmin
    for i in range(steps + 1):
        tx = sl_x + int(sl_w * i / steps)
        pygame.draw.line(screen, (70, 70, 70), (tx, sl_y - 8), (tx, sl_y + 8), 1)
        if i in (0, steps // 2, steps):
            t_s = F_COUNT.render(str(vmin + i), True, (100, 100, 100))
            screen.blit(t_s, t_s.get_rect(center=(tx, sl_y + 20)))
    hx = sl_x + int(sl_w * t)
    pygame.draw.circle(screen, (30, 30, 30), (hx, sl_y), 12)
    pygame.draw.circle(screen, color, (hx, sl_y), 12, 3)


def draw_difficulty():
    """
    Single-slider difficulty selector.

    Layout (top to bottom)
    -----------------------
      Title           "Bot Difficulty"
      Large level num  "5"  (coloured by tier)
      Tier name        "Intermediate"
      Engine info      "Depth 3 · 40% blunder chance"
      ─ separator ─
      Slider 1-10      ────────────●──── (with tick marks + numeric endpoints)
      Tier label       "Intermediate"  (bold, coloured)
      Context line     "Club player standard, capitalizes on obvious blunders"
      ─ separator ─
      [Start Game]
      ← Back

    Returns
    -------
    (back_rect, confirm_rect, slider_rect, slider_info)
      slider_info = (sl_x, sl_w, sl_y) — used by the event handler for
      pixel-to-value conversion on MOUSEBUTTONDOWN / MOUSEMOTION.
    """
    from data.engine.bot import DIFFICULTY_CONFIG   # read live depth+prob values

    screen.fill(MENU_BG)
    cx   = WIN_W // 2
    sl_x = cx - 190
    sl_w = 380

    level    = diff_level
    col      = _difficulty_color(level)
    tier     = _DIFF_TIER[level]
    desc     = _DIFF_DESC[level]
    cfg      = DIFFICULTY_CONFIG[level]
    depth    = cfg['depth']
    blunder  = int(cfg['blunder_prob'] * 100)

    # ── Page title ────────────────────────────────────────────────────────────
    title_s = F_PICK.render('Bot Difficulty', True, MENU_TEXT)
    screen.blit(title_s, title_s.get_rect(center=(cx, 72)))

    # ── Large level number ────────────────────────────────────────────────────
    # Uses the largest available font (F_WIN = 52 pt) to give the number
    # visual weight; coloured to match the current difficulty tier.
    num_s = F_WIN.render(str(level), True, col)
    screen.blit(num_s, num_s.get_rect(center=(cx, 148)))

    # ── Tier name (e.g. "Intermediate") ──────────────────────────────────────
    tier_s = F_DIFF_L.render(tier.upper(), True, col)
    screen.blit(tier_s, tier_s.get_rect(center=(cx, 190)))

    # ── Engine internals hint: depth + blunder probability ───────────────────
    if blunder == 0:
        info_txt = f'Searches {depth} moves ahead  ·  Perfect play (0% blunder)'
    else:
        info_txt = f'Searches {depth} move{"s" if depth != 1 else ""} ahead  ·  {blunder}% blunder chance'
    info_s = F_DIFF_S.render(info_txt, True, MENU_TEXT_SUB)
    screen.blit(info_s, info_s.get_rect(center=(cx, 214)))

    # Thin separator
    pygame.draw.line(screen, (44, 44, 44), (sl_x, 238), (sl_x + sl_w, 238), 1)

    # ── Single 1-10 slider ────────────────────────────────────────────────────
    sl_y = 272
    _draw_slider(level, 1, 10, sl_x, sl_w, sl_y, col)
    # Clickable rect for mouse interaction (generous padding for usability)
    slider_rect = pygame.Rect(sl_x - 14, sl_y - 18, sl_w + 28, 36)

    # ── Context labels (real-time, updated the moment the slider moves) ───────
    # Line 1: tier name in the accent colour (bold, prominent)
    tier_lbl = F_DIFF_L.render(tier, True, col)
    screen.blit(tier_lbl, tier_lbl.get_rect(center=(cx, 316)))

    # Line 2: descriptive behaviour profile in a softer tone
    desc_s = F_DIFF_S.render(desc, True, (155, 155, 155))
    screen.blit(desc_s, desc_s.get_rect(center=(cx, 336)))

    # Thin separator
    pygame.draw.line(screen, (44, 44, 44), (sl_x, 360), (sl_x + sl_w, 360), 1)

    # ── Start Game button ─────────────────────────────────────────────────────
    bw, bh   = 200, 48
    btn      = pygame.Rect(cx - bw // 2, 384, bw, bh)
    mx_, my_ = pygame.mouse.get_pos()
    hov      = btn.collidepoint(mx_, my_)
    bg_col   = tuple(min(255, int(c * (0.38 if hov else 0.22))) for c in col)
    pygame.draw.rect(screen, bg_col, btn, border_radius=10)
    brd_col  = col if hov else tuple(int(c * 0.55) for c in col)
    pygame.draw.rect(screen, brd_col, btn, 2 if hov else 1, border_radius=10)
    btn_lbl  = F_BTN.render('Start Game', True, MENU_TEXT)
    screen.blit(btn_lbl, btn_lbl.get_rect(center=btn.center))

    # ── Back link ─────────────────────────────────────────────────────────────
    back_s = F_PICK_S.render('← Back', True, MENU_TEXT_SUB)
    screen.blit(back_s, (18, 18))

    return (
        pygame.Rect(0, 0, 80, 36),  # back hit-area
        btn,                         # start button
        slider_rect,                 # slider hit-area
        (sl_x, sl_w, sl_y),         # (origin_x, width, centre_y) for value math
    )

def draw_preferences():
    """
    Preferences menu for board and arrow themes.
    
    Returns
    -------
    (back_rect, board_rects, arrow_rects)
      board_rects = {'white_green': rect, 'white_blue': rect, 'white_red': rect}
      arrow_rects = {'blue': rect, 'yellow': rect, ...}
    """
    global pref_board_rects, pref_arrow_rects, pref_back_rect
    
    screen.fill(MENU_BG)
    cx = WIN_W // 2
    
    # Title
    title_s = F_PICK.render('Preferences', True, MENU_TEXT)
    screen.blit(title_s, title_s.get_rect(center=(cx, 50)))
    
    # Board Theme section
    board_label = F_DIFF_L.render('Board Theme', True, MENU_TEXT)
    screen.blit(board_label, (cx - 120, 110))
    
    board_themes = ['white_green', 'white_blue', 'white_red']
    board_rects = {}
    board_y = 150
    for i, theme_name in enumerate(board_themes):
        theme = BOARD_THEMES[theme_name]
        theme_colors = theme_name.split('_')
        label = f'{theme_colors[0].capitalize()} & {theme_colors[1].capitalize()}'
        
        rect_x = cx - 120 + i * 100
        rect = pygame.Rect(rect_x, board_y, 80, 60)
        
        mx_, my_ = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx_, my_)
        selected = (CURRENT_BOARD_THEME == theme_name)
        
        # Draw theme preview
        pygame.draw.rect(screen, theme['light'], (rect.x + 2, rect.y + 2, 35, 35))
        pygame.draw.rect(screen, theme['dark'], (rect.x + 37, rect.y + 2, 35, 35))
        
        # Border
        border_col = MENU_ACCENT if selected else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
        border_width = 3 if selected else 2
        pygame.draw.rect(screen, border_col, rect, border_width, border_radius=8)
        
        # Label
        lbl = F_BTN_SUB.render(label, True, MENU_TEXT if selected else MENU_TEXT_SUB)
        screen.blit(lbl, lbl.get_rect(center=(rect.centerx, rect.bottom + 12)))
        
        board_rects[theme_name] = rect
    
    # Arrow Theme section
    arrow_label = F_DIFF_L.render('Arrow Theme', True, MENU_TEXT)
    screen.blit(arrow_label, (cx - 120, 250))
    
    arrow_themes = ['blue', 'yellow', 'green', 'white', 'black']
    arrow_rects = {}
    arrow_y = 290
    for i, theme_name in enumerate(arrow_themes):
        color = ARROW_THEMES[theme_name]
        # Convert RGBA to RGB for display
        display_color = color[:3]
        label = theme_name.capitalize()
        
        rect_x = cx - 120 + i * 100
        rect = pygame.Rect(rect_x, arrow_y, 80, 60)
        
        mx_, my_ = pygame.mouse.get_pos()
        hov = rect.collidepoint(mx_, my_)
        selected = (CURRENT_ARROW_THEME == theme_name)
        
        # Draw color preview circle
        pygame.draw.circle(screen, display_color, (rect.centerx, rect.centery - 10), 20)
        pygame.draw.circle(screen, (80, 80, 80), (rect.centerx, rect.centery - 10), 20, 2)
        
        # Border
        border_col = MENU_ACCENT if selected else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
        border_width = 3 if selected else 2
        pygame.draw.rect(screen, border_col, rect, border_width, border_radius=8)
        
        # Label
        lbl = F_BTN_SUB.render(label, True, MENU_TEXT if selected else MENU_TEXT_SUB)
        screen.blit(lbl, lbl.get_rect(center=(rect.centerx, rect.bottom - 12)))
        
        arrow_rects[theme_name] = rect
    
    # Back button
    back_s = F_PICK_S.render('← Back', True, MENU_TEXT_SUB)
    screen.blit(back_s, (18, 18))
    
    pref_back_rect = pygame.Rect(0, 0, 80, 36)
    pref_board_rects = board_rects
    pref_arrow_rects = arrow_rects
    
    return pref_back_rect, board_rects, arrow_rects

# ── Move sound helper ─────────────────────────────────────────────────────────

def play_move_sound(result):
    if result in ('capture', 'en_passant'):
        sounds.play('capture')
    elif result == 'move':
        sounds.play('move')

# ── Main loop ─────────────────────────────────────────────────────────────────

clock = pygame.time.Clock()

while True:
    dt     = clock.tick(60)
    mx, my = pygame.mouse.get_pos()

    think_timer += dt
    if think_timer >= 500:
        think_dots  += 1
        think_timer  = 0

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            arrow_start_sq = None
            all_arrows.clear()

        # ── Continue / New Game overlay (highest priority) ─────────────────
        if continue_new_overlay:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if overlay_cont_btn and overlay_cont_btn.collidepoint(mx, my):
                    _continue_saved_game(pending_save_data, pending_mode)
                    continue_new_overlay = False
                    pending_save_data    = None
                elif overlay_new_btn and overlay_new_btn.collidepoint(mx, my):
                    delete_save(pending_mode)
                    if pending_mode == STATE_PVP:
                        board_flipped = False
                        state         = STATE_PVP
                        start_game()
                    else:
                        state = STATE_COLOR_PICK
                    continue_new_overlay = False
                    pending_save_data    = None
            continue   # swallow all other events while overlay is up

        # ── In-game Main Menu overlay ──────────────────────────────────────
        if main_menu_overlay:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if overlay_save_btn and overlay_save_btn.collidepoint(mx, my):
                    write_save(state)
                    _reset_review()
                    state             = STATE_MENU
                    main_menu_overlay = False
                elif overlay_quit_btn and overlay_quit_btn.collidepoint(mx, my):
                    delete_save(state)
                    _reset_review()
                    state             = STATE_MENU
                    main_menu_overlay = False
                else:
                    # Click outside box = close overlay
                    bx_chk = PANEL_X // 2
                    by_chk = WIN_H // 2
                    bw_chk, bh_chk = 310, 210
                    box_r  = pygame.Rect(bx_chk - bw_chk//2, by_chk - bh_chk//2,
                                         bw_chk, bh_chk)
                    if not box_r.collidepoint(mx, my):
                        main_menu_overlay = False
            continue

        # ── Mousewheel — history panel ─────────────────────────────────────
        if event.type == pygame.MOUSEWHEEL and mx >= PANEL_X and state in (STATE_PVP, STATE_BOT):
            if adapter:
                n_rows   = (len(adapter.san_history) + 1) // 2
                list_h   = WIN_H - HIST_HDR_H - HIST_FOOT_H
                max_sc   = max(0, n_rows * HIST_ROW_H - list_h)
                panel_scroll = max(0, min(max_sc, panel_scroll - event.y * HIST_ROW_H))
            continue

        # ── Menu ──────────────────────────────────────────────────────────
        if state == STATE_MENU:
            if menu_buttons[0].clicked(event):   # Play vs Friend
                save = read_save(STATE_PVP)
                if save:
                    pending_mode         = STATE_PVP
                    pending_save_data    = save
                    continue_new_overlay = True
                else:
                    board_flipped = False
                    state         = STATE_PVP
                    start_game()
            elif menu_buttons[1].clicked(event):  # Play vs Bot
                save = read_save(STATE_BOT)
                if save:
                    pending_mode         = STATE_BOT
                    pending_save_data    = save
                    continue_new_overlay = True
                else:
                    state = STATE_COLOR_PICK
            elif menu_buttons[2].clicked(event):  # Preferences
                state = STATE_PREFERENCES

        # ── Colour picker ──────────────────────────────────────────────────
        elif state == STATE_COLOR_PICK:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if picker_back and picker_back.collidepoint(mx, my):
                    state = STATE_MENU
                else:
                    for color, rect in picker_rects.items():
                        if rect.collidepoint(mx, my):
                            player_color  = color
                            board_flipped = (color == 'black')
                            state         = STATE_DIFFICULTY
                            break

        # ── Difficulty ─────────────────────────────────────────────────────
        # ── Difficulty screen ──────────────────────────────────────────────
        elif state == STATE_DIFFICULTY:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if diff_back and diff_back.collidepoint(mx, my):
                    state = STATE_COLOR_PICK
                elif diff_confirm_rect and diff_confirm_rect.collidepoint(mx, my):
                    # Commit the chosen level and start the game
                    bot_level = diff_level
                    state     = STATE_BOT
                    start_game()
                    if player_color == 'black':
                        launch_bot_move()
                elif diff_slider_rect and diff_slider_rect.collidepoint(mx, my):
                    diff_slider_dragging = True
                    if diff_slider_info:
                        sl_x, sl_w, _ = diff_slider_info
                        t = max(0.0, min(1.0, (mx - sl_x) / sl_w))
                        diff_level = round(t * 9) + 1
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                diff_slider_dragging = False
            elif event.type == pygame.MOUSEMOTION:
                if diff_slider_dragging and diff_slider_info:
                    sl_x, sl_w, _ = diff_slider_info
                    diff_level = round(max(0.0, min(1.0, (mx - sl_x) / sl_w)) * 9) + 1

        # ── Preferences ────────────────────────────────────────────────────
        elif state == STATE_PREFERENCES:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if pref_back_rect and pref_back_rect.collidepoint(mx, my):
                    state = STATE_MENU
                else:
                    # Check board theme selections
                    preference_changed = False
                    for theme_name, rect in pref_board_rects.items():
                        if rect.collidepoint(mx, my):
                            globals()['CURRENT_BOARD_THEME'] = theme_name
                            board_surf.fill((0, 0, 0, 0))  # Clear board surface
                            preference_changed = True
                            break
                    # Check arrow theme selections
                    for theme_name, rect in pref_arrow_rects.items():
                        if rect.collidepoint(mx, my):
                            globals()['CURRENT_ARROW_THEME'] = theme_name
                            preference_changed = True
                            break
                    if preference_changed:
                        write_preferences()

        # ── PvP / Bot — shared panel + board handling ──────────────────────
        elif state in (STATE_PVP, STATE_BOT):
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                    _move_review(-1 if event.key == pygame.K_LEFT else 1)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:

                # 1. In-game Menu button
                if menu_btn_ingame_rect and menu_btn_ingame_rect.collidepoint(mx, my):
                    main_menu_overlay = True

                # 2. History panel (right strip)
                elif mx >= PANEL_X:
                    if (live_btn_rect and live_btn_rect.collidepoint(mx, my)
                            and review_ply is not None):
                        _exit_review()
                    else:
                        for rect, ply in history_ply_rects:
                            if rect.collidepoint(mx, my):
                                _enter_review(ply)
                                break

                # 3. Game-over "Main Menu" button
                elif (game_over and menu_from_gameover_rect
                      and menu_from_gameover_rect.collidepoint(mx, my)):
                    _reset_review()
                    state = STATE_MENU

                # 4. Board locked (review mode / animating / game over)
                elif review_ply is not None or is_animating() or game_over:
                    pass

                # 5. Promotion
                elif adapter.promotion_pending:
                    for rect, pt in promo_rects:
                        if rect.collidepoint(mx, my):
                            result = adapter.complete_promotion(pt)
                            play_move_sound(result)
                            promo_piece_color = (chess.WHITE
                                                 if adapter.turn == 'black'
                                                 else chess.BLACK)
                            # promotion move.promotion is set; find the promoted piece
                            promo_img = PIECE_IMGS.get((pt, promo_piece_color))
                            start_anim(adapter.anim_from, adapter.anim_to, promo_img)
                            write_save(state)
                            if state == STATE_BOT and adapter.turn != player_color:
                                launch_bot_move()
                            break

                # 6. Normal board click
                else:
                    bx, by = mx - BOARD_X, my - BOARD_Y
                    if 0 <= bx < BOARD_PX and 0 <= by < BOARD_PX:
                        # Bot mode: only accept player's turn
                        if state == STATE_BOT and adapter.turn != player_color or bot_thinking:
                            pass
                        else:
                            sq     = pixel_to_sq(bx, by)
                            result = adapter.handle_click(sq)
                            if result in ('move', 'capture', 'en_passant'):
                                piece = adapter.board.piece_at(adapter.anim_to)
                                img   = (PIECE_IMGS.get((piece.piece_type, piece.color))
                                         if piece else None)
                                start_anim(adapter.anim_from, adapter.anim_to, img)
                                play_move_sound(result)
                                write_save(state)
                                if state == STATE_BOT and not adapter.promotion_pending:
                                    launch_bot_move()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                bx, by = mx - BOARD_X, my - BOARD_Y
                if 0 <= bx < BOARD_PX and 0 <= by < BOARD_PX:
                    arrow_start_sq = pixel_to_sq(bx, by)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                if arrow_start_sq is not None:
                    bx, by = mx - BOARD_X, my - BOARD_Y
                    if 0 <= bx < BOARD_PX and 0 <= by < BOARD_PX:
                        arrow_end_sq = pixel_to_sq(bx, by)
                        if arrow_end_sq != arrow_start_sq:
                            all_arrows.append((arrow_start_sq, arrow_end_sq))
                    arrow_start_sq = None

    # ── Review stepping (between events) ──────────────────────────────────────
    if (state in (STATE_PVP, STATE_BOT)
            and review_target is not None
            and not is_animating()):
        step_review_toward_target()

    # ── Apply bot move (lock-protected; skipped while in review) ─────────────
    if state == STATE_BOT and not is_animating() and review_ply is None:
        move = None
        with _bot_lock:
            if bot_result is not None:
                move       = bot_result
                bot_result = None
        if move and move in adapter.board.legal_moves:
            piece  = adapter.board.piece_at(move.from_square)
            img    = PIECE_IMGS.get((piece.piece_type, piece.color)) if piece else None
            result = adapter.apply_move(move)
            start_anim(adapter.anim_from, adapter.anim_to, img)
            play_move_sound(result)
            write_save(state)

    # ── Render ────────────────────────────────────────────────────────────────
    if state == STATE_MENU:
        draw_menu()
    elif state == STATE_COLOR_PICK:
        picker_rects, picker_back = draw_color_picker()
    elif state == STATE_DIFFICULTY:
        (diff_back, diff_confirm_rect,
         diff_slider_rect, diff_slider_info) = draw_difficulty()
    elif state == STATE_PREFERENCES:
        pref_back_rect, pref_board_rects, pref_arrow_rects = draw_preferences()
    elif state in (STATE_PVP, STATE_BOT):
        draw_game(is_bot_mode=(state == STATE_BOT))

    pygame.display.flip()
