"""Button and Slider widgets, keyboard navigable.

Tab moves focus between registered widgets in a screen; Enter/Space
activates the focused button; Left/Right (or Up/Down) adjust a focused
slider. Esc handling lives in app.py since it's screen-level, not
widget-level.
"""
from __future__ import annotations

from collections.abc import Callable

import pygame

from chess_game.theme import (
    MENU_BTN_BRD,
    MENU_BTN_DIS,
    MENU_BTN_HOV,
    MENU_BTN_NORM,
    MENU_TEXT,
    MENU_TEXT_DIS,
    MENU_TEXT_SUB,
)

FOCUS_RING = (140, 190, 250)


class Button:
    def __init__(self, rect, label: str, sublabel: str | None = None,
                 disabled: bool = False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.sublabel = sublabel
        self.disabled = disabled
        self.focused = False

    def draw(self, surface: pygame.Surface, fonts) -> None:
        mx, my = pygame.mouse.get_pos()
        hov = self.rect.collidepoint(mx, my) and not self.disabled
        bg = MENU_BTN_DIS if self.disabled else (MENU_BTN_HOV if hov else MENU_BTN_NORM)
        pygame.draw.rect(surface, bg, self.rect, border_radius=10)
        pygame.draw.rect(surface, MENU_BTN_BRD, self.rect, 2, border_radius=10)
        if self.focused and not self.disabled:
            pygame.draw.rect(surface, FOCUS_RING, self.rect, 2, border_radius=10)
        tc = MENU_TEXT_DIS if self.disabled else MENU_TEXT
        lbl = fonts.btn.render(self.label, True, tc)
        surface.blit(lbl, lbl.get_rect(
            center=(self.rect.centerx,
                    self.rect.centery - (8 if self.sublabel else 0))))
        if self.sublabel:
            sc = MENU_TEXT_DIS if self.disabled else MENU_TEXT_SUB
            sl = fonts.btn_sub.render(self.sublabel, True, sc)
            surface.blit(sl, sl.get_rect(
                center=(self.rect.centerx, self.rect.centery + 14)))

    def clicked(self, event: pygame.event.Event) -> bool:
        return (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos) and not self.disabled)

    def activated_by_key(self, event: pygame.event.Event) -> bool:
        """True if this focused button should fire from a keyboard Enter/Space."""
        return (self.focused and not self.disabled
                and event.type == pygame.KEYDOWN
                and event.key in (pygame.K_RETURN, pygame.K_SPACE))


class MenuCard(Button):
    """Large, descriptive launcher card used on the home screen.

    It deliberately keeps Button's click and keyboard contract so a home card
    works with the existing FocusGroup without a parallel input path.
    """

    def __init__(self, rect, label: str, sublabel: str, icon: str,
                 accent: tuple[int, int, int]):
        super().__init__(rect, label, sublabel)
        self.icon = icon
        self.accent = accent

    def draw(self, surface: pygame.Surface, fonts) -> None:
        mx, my = pygame.mouse.get_pos()
        hov = self.rect.collidepoint(mx, my)
        bg = (48, 48, 54) if hov else (31, 31, 36)
        border = self.accent if hov else (68, 68, 76)

        pygame.draw.rect(surface, bg, self.rect, border_radius=14)
        pygame.draw.rect(surface, border, self.rect, 2 if hov else 1,
                         border_radius=14)
        pygame.draw.rect(surface, self.accent,
                         (self.rect.x, self.rect.y + 14, 4, self.rect.height - 28),
                         border_radius=2)

        badge_center = (self.rect.x + 48, self.rect.centery)
        pygame.draw.circle(surface, (24, 24, 28), badge_center, 24)
        pygame.draw.circle(surface, self.accent, badge_center, 24, 2)
        self._draw_icon(surface, badge_center)

        label = fonts.btn.render(self.label, True, MENU_TEXT)
        surface.blit(label, (self.rect.x + 84, self.rect.y + 35))
        sublabel = fonts.btn_sub.render(self.sublabel, True, MENU_TEXT_SUB)
        surface.blit(sublabel, (self.rect.x + 84, self.rect.y + 66))

        chevron = fonts.pick.render('\u203a', True, self.accent if hov else MENU_TEXT_SUB)
        surface.blit(chevron, chevron.get_rect(midright=(self.rect.right - 18, self.rect.centery)))
        if self.focused:
            pygame.draw.rect(surface, FOCUS_RING, self.rect, 3, border_radius=14)

    def _draw_icon(self, surface: pygame.Surface, center: tuple[int, int]) -> None:
        """Draw compact, font-independent icons for the four home actions."""
        x, y = center
        if self.icon == 'friend':
            for dx, dy in ((-7, -5), (7, -5)):
                pygame.draw.circle(surface, self.accent, (x + dx, y + dy), 5, 2)
                pygame.draw.arc(surface, self.accent, (x + dx - 7, y + dy + 4, 14, 12),
                                190, 350, 2)
        elif self.icon == 'computer':
            pygame.draw.rect(surface, self.accent, (x - 12, y - 10, 24, 16), 2, border_radius=2)
            pygame.draw.line(surface, self.accent, (x, y + 6), (x, y + 11), 2)
            pygame.draw.line(surface, self.accent, (x - 7, y + 12), (x + 7, y + 12), 2)
        elif self.icon == 'match':
            pygame.draw.line(surface, self.accent, (x - 13, y - 7), (x + 13, y - 7), 2)
            pygame.draw.line(surface, self.accent, (x + 13, y - 7), (x + 8, y - 12), 2)
            pygame.draw.line(surface, self.accent, (x + 13, y - 7), (x + 8, y - 2), 2)
            pygame.draw.line(surface, self.accent, (x + 13, y + 7), (x - 13, y + 7), 2)
            pygame.draw.line(surface, self.accent, (x - 13, y + 7), (x - 8, y + 2), 2)
            pygame.draw.line(surface, self.accent, (x - 13, y + 7), (x - 8, y + 12), 2)
        elif self.icon == 'preferences':
            pygame.draw.circle(surface, self.accent, center, 8, 2)
            pygame.draw.circle(surface, self.accent, center, 2)
            for dx, dy in ((0, -12), (12, 0), (0, 12), (-12, 0)):
                pygame.draw.line(surface, self.accent, (x + dx // 2, y + dy // 2), (x + dx, y + dy), 3)


class Slider:
    """A 1-D slider with discrete integer steps, focusable and arrow-key adjustable."""

    def __init__(self, rect, vmin: int, vmax: int, value: int,
                 on_change: Callable[[int], None] | None = None):
        self.rect = pygame.Rect(rect)
        self.vmin = vmin
        self.vmax = vmax
        self.value = value
        self.on_change = on_change
        self.focused = False
        self.dragging = False

    def value_from_x(self, x: int) -> int:
        sl_x, sl_w = self.rect.x, self.rect.width
        t = max(0.0, min(1.0, (x - sl_x) / sl_w))
        # Round half-up, not banker's rounding.
        steps = self.vmax - self.vmin
        return int(t * steps + 0.5) + self.vmin

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Returns True if this event changed the slider's value."""
        changed = False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.dragging = True
                new_val = self.value_from_x(event.pos[0])
                if new_val != self.value:
                    self.value = new_val
                    changed = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            new_val = self.value_from_x(event.pos[0])
            if new_val != self.value:
                self.value = new_val
                changed = True
        elif self.focused and event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_LEFT, pygame.K_DOWN):
                new_val = max(self.vmin, self.value - 1)
                if new_val != self.value:
                    self.value, changed = new_val, True
            elif event.key in (pygame.K_RIGHT, pygame.K_UP):
                new_val = min(self.vmax, self.value + 1)
                if new_val != self.value:
                    self.value, changed = new_val, True

        if changed and self.on_change is not None:
            self.on_change(self.value)
        return changed


class FocusableRect:
    """Minimal focusable wrapper around a plain pygame.Rect + a key.

    Used by screens (color picker, difficulty, preferences) that draw their
    own custom widgets rather than chess_game.widgets.Button instances, so
    they can still participate in a FocusGroup. `key` identifies which
    logical action this rect corresponds to, for the event handler to read
    back after Tab/Enter routing.
    """

    def __init__(self, rect: pygame.Rect, key):
        self.rect = rect
        self.key = key
        self.focused = False

    def activated_by_key(self, event: pygame.event.Event) -> bool:
        return (self.focused and event.type == pygame.KEYDOWN
                and event.key in (pygame.K_RETURN, pygame.K_SPACE))


class FocusGroup:
    """Tab/Shift+Tab cycling across a list of focusable widgets."""

    def __init__(self, widgets: list):
        self.widgets = widgets
        self.index = -1

    def rebuild(self, widgets: list) -> None:
        """Replace the widget list (e.g. after rects were recreated for a
        new frame), preserving which index is focused if still in range."""
        self.widgets = widgets
        if self.widgets and 0 <= self.index < len(self.widgets):
            self.widgets[self.index].focused = True
        else:
            self.index = -1

    def handle_key(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN or event.key != pygame.K_TAB:
            return
        if not self.widgets:
            return
        if self.index >= 0:
            self.widgets[self.index].focused = False
        step = -1 if (event.mod & pygame.KMOD_SHIFT) else 1
        self.index = (self.index + step) % len(self.widgets)
        self.widgets[self.index].focused = True

    def clear(self) -> None:
        for w in self.widgets:
            w.focused = False
        self.index = -1
