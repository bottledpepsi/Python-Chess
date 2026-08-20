from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import pygame

Color = tuple[int, int, int] | tuple[int, int, int, int]

_SAFE_ERODE_PX = 2


def _supersample_factor(w: int, h: int) -> int:
    area = max(1, w * h)
    if area <= 4_000:       # small: buttons, slider handles, badges, ticks
        return 4
    if area <= 30_000:      # medium: menu cards, modals' rounded panels
        return 3
    return 2                 # large: full-width section cards, big overlays


def _finish(
    size: tuple[int, int],
    color: Color,
    draw_hi: Callable[[pygame.Surface, int], None],
    draw_safe_interior: Callable[[pygame.Surface], None],
    factor: int,
) -> pygame.Surface:
    w, h = max(1, size[0]), max(1, size[1])

    hi = pygame.Surface((w * factor, h * factor), pygame.SRCALPHA)
    draw_hi(hi, factor)
    mask = pygame.transform.smoothscale(hi, (w, h))

    safe = pygame.Surface((w, h), pygame.SRCALPHA)
    draw_safe_interior(safe)
    mask.blit(safe, (0, 0), special_flags=pygame.BLEND_RGBA_MAX)

    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.fill((*color[:3], 255))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    if len(color) == 4 and color[3] != 255:
        out.set_alpha(color[3])
    return out


def aa_rounded_rect(
    surface: pygame.Surface,
    color: Color,
    rect: pygame.Rect | tuple[int, int, int, int],
    border_radius: int,
    width: int = 0,
    factor: int | None = None,
    border_top_left_radius: int = -1,
    border_top_right_radius: int = -1,
    border_bottom_left_radius: int = -1,
    border_bottom_right_radius: int = -1,
) -> None:
    rect = pygame.Rect(rect)
    if rect.width <= 0 or rect.height <= 0:
        return
    w, h = rect.width, rect.height
    f = factor or _supersample_factor(w, h)
    cap = min(w // 2, h // 2)
    r = max(0, min(border_radius, cap))

    def _corner(v: int) -> int:
        return r if v < 0 else max(0, min(v, cap))

    tl, tr = _corner(border_top_left_radius), _corner(border_top_right_radius)
    bl, br = _corner(border_bottom_left_radius), _corner(border_bottom_right_radius)

    def draw_hi(hi: pygame.Surface, hf: int) -> None:
        hi_rect = pygame.Rect(0, 0, w * hf, h * hf)
        pygame.draw.rect(hi, (255, 255, 255, 255), hi_rect,
                          width * hf if width > 0 else 0, border_radius=r * hf,
                          border_top_left_radius=tl * hf, border_top_right_radius=tr * hf,
                          border_bottom_left_radius=bl * hf, border_bottom_right_radius=br * hf)

    def draw_safe(safe: pygame.Surface) -> None:
        e = _SAFE_ERODE_PX
        inner = pygame.Rect(e, e, max(0, w - 2 * e), max(0, h - 2 * e))
        if inner.width <= 0 or inner.height <= 0:
            return
        inner_tl, inner_tr = max(0, tl - e), max(0, tr - e)
        inner_bl, inner_br = max(0, bl - e), max(0, br - e)
        if width <= 0:
            pygame.draw.rect(safe, (255, 255, 255, 255), inner, 0,
                              border_top_left_radius=inner_tl, border_top_right_radius=inner_tr,
                              border_bottom_left_radius=inner_bl, border_bottom_right_radius=inner_br)
        else:
            inner_width = width - 2 * e
            if inner_width > 0:
                pygame.draw.rect(safe, (255, 255, 255, 255), inner, inner_width,
                                  border_top_left_radius=inner_tl, border_top_right_radius=inner_tr,
                                  border_bottom_left_radius=inner_bl, border_bottom_right_radius=inner_br)

    out = _finish((w, h), color, draw_hi, draw_safe, f)
    surface.blit(out, rect.topleft)


def aa_circle(
    surface: pygame.Surface,
    color: Color,
    center: tuple[int, int],
    radius: int,
    width: int = 0,
    factor: int | None = None,
) -> None:
    if radius <= 0:
        return
    d = radius * 2
    f = factor or _supersample_factor(d, d)

    def draw_hi(hi: pygame.Surface, hf: int) -> None:
        pygame.draw.circle(hi, (255, 255, 255, 255), (radius * hf, radius * hf),
                            radius * hf, width * hf if width > 0 else 0)

    def draw_safe(safe: pygame.Surface) -> None:
        e = _SAFE_ERODE_PX
        inner_r = radius - e
        if inner_r <= 0:
            return
        if width <= 0:
            pygame.draw.circle(safe, (255, 255, 255, 255), (radius, radius), inner_r)
        else:
            inner_width = width - 2 * e
            if inner_width > 0:
                pygame.draw.circle(safe, (255, 255, 255, 255), (radius, radius),
                                    inner_r, inner_width)

    out = _finish((d, d), color, draw_hi, draw_safe, f)
    surface.blit(out, (center[0] - radius, center[1] - radius))


def aa_polygon(
    surface: pygame.Surface,
    color: Color,
    points: list[tuple[float, float]],
    width: int = 0,
    factor: int = 4,
) -> None:
    if len(points) < 3:
        return
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs), min(ys)
    margin = max(1, width) + 1
    w = int(max(xs) - min_x) + margin * 2
    h = int(max(ys) - min_y) + margin * 2
    local_pts = [(px - min_x + margin, py - min_y + margin) for px, py in points]

    hi = pygame.Surface((w * factor, h * factor), pygame.SRCALPHA)
    hi_pts = [(px * factor, py * factor) for px, py in local_pts]
    pygame.draw.polygon(hi, (255, 255, 255, 255), hi_pts, width * factor if width > 0 else 0)
    mask = pygame.transform.smoothscale(hi, (w, h))

    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.fill((*color[:3], 255))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    if len(color) == 4 and color[3] != 255:
        out.set_alpha(color[3])
    surface.blit(out, (min_x - margin, min_y - margin))


@lru_cache(maxsize=256)
def aa_button_backdrop(
    size: tuple[int, int],
    border_radius: int,
    fill_color: Color,
    border_color: Color | None,
    border_width: int,
) -> pygame.Surface:
    w, h = size
    result = pygame.Surface((w, h), pygame.SRCALPHA)
    aa_rounded_rect(result, fill_color, (0, 0, w, h), border_radius)
    if border_color is not None and border_width > 0:
        aa_rounded_rect(result, border_color, (0, 0, w, h), border_radius, width=border_width)
    return result


def blit_button_backdrop(
    surface: pygame.Surface,
    rect: pygame.Rect,
    border_radius: int,
    fill_color: Color,
    border_color: Color | None = None,
    border_width: int = 1,
) -> None:

    if rect.width <= 0 or rect.height <= 0:
        return
    backdrop = aa_button_backdrop(
        (rect.width, rect.height), border_radius, fill_color, border_color, border_width,
    )
    surface.blit(backdrop, rect.topleft)
