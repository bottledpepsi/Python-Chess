"""Widget tests: round-half-up slider snapping, plus Slider.handle_event,
FocusableRect, FocusGroup, and Button focus-ring coverage."""
from __future__ import annotations

import pygame

from chess_game.widgets import Button, FocusableRect, FocusGroup, Slider


def test_slider_value_from_x_round_half_up_not_banker():
    # 1-10 slider, 380px wide, matching draw_difficulty's geometry.
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    # t=0.5 exactly -> steps=9, 9*0.5=4.5 -> round-half-up means 5, + vmin(1) = 6
    midpoint_x = int(380 * 0.5)
    val = sl.value_from_x(midpoint_x)
    assert val == 6, f"expected round-half-up to give 6, got {val}"


def test_slider_value_from_x_clamped_to_range():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    assert sl.value_from_x(-100) == 1
    assert sl.value_from_x(10000) == 10


def test_slider_handle_event_mousedown_inside_changes_value():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(379, 10))
    changed = sl.handle_event(ev)
    assert changed is True
    assert sl.dragging is True
    assert sl.value == 10


def test_slider_handle_event_mousedown_outside_rect_noop():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=5)
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(1000, 1000))
    changed = sl.handle_event(ev)
    assert changed is False
    assert sl.dragging is False
    assert sl.value == 5


def test_slider_handle_event_mouseup_ends_drag():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=5)
    sl.dragging = True
    ev = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0))
    changed = sl.handle_event(ev)
    assert changed is False
    assert sl.dragging is False


def test_slider_handle_event_motion_while_dragging():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    sl.dragging = True
    ev = pygame.event.Event(pygame.MOUSEMOTION, pos=(380, 10))
    changed = sl.handle_event(ev)
    assert changed is True
    assert sl.value == 10


def test_slider_handle_event_motion_while_not_dragging_noop():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=5)
    ev = pygame.event.Event(pygame.MOUSEMOTION, pos=(380, 10))
    changed = sl.handle_event(ev)
    assert changed is False
    assert sl.value == 5


def test_slider_handle_event_keyboard_left_right_when_focused():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=5)
    sl.focused = True
    left = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT, mod=0)
    assert sl.handle_event(left) is True
    assert sl.value == 4
    right = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0)
    assert sl.handle_event(right) is True
    assert sl.value == 5
    up = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP, mod=0)
    assert sl.handle_event(up) is True
    assert sl.value == 6
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN, mod=0)
    assert sl.handle_event(down) is True
    assert sl.value == 5


def test_slider_handle_event_keyboard_clamped_at_bounds():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1)
    sl.focused = True
    left = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT, mod=0)
    assert sl.handle_event(left) is False
    assert sl.value == 1


def test_slider_handle_event_keyboard_ignored_when_not_focused():
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=5)
    sl.focused = False
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0)
    assert sl.handle_event(ev) is False
    assert sl.value == 5


def test_slider_on_change_callback_fires_on_change():
    seen = []
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1, on_change=seen.append)
    sl.focused = True
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0)
    sl.handle_event(ev)
    assert seen == [2]


def test_slider_on_change_not_called_when_unchanged():
    seen = []
    sl = Slider((0, 0, 380, 20), vmin=1, vmax=10, value=1, on_change=seen.append)
    sl.focused = True
    left = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT, mod=0)
    sl.handle_event(left)  # already at vmin, no change
    assert seen == []


def test_focusable_rect_activated_by_key():
    fr = FocusableRect(pygame.Rect(0, 0, 10, 10), key='back')
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0)
    assert fr.activated_by_key(ev) is False  # not focused yet
    fr.focused = True
    assert fr.activated_by_key(ev) is True
    space_ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, mod=0)
    assert fr.activated_by_key(space_ev) is True
    other_key = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a, mod=0)
    assert fr.activated_by_key(other_key) is False


def test_focus_group_rebuild_preserves_index_in_range():
    a, b = FocusableRect(pygame.Rect(0, 0, 1, 1), 'a'), FocusableRect(pygame.Rect(0, 0, 1, 1), 'b')
    fg = FocusGroup([a, b])
    fg.index = 1
    new_a, new_b = FocusableRect(pygame.Rect(0, 0, 1, 1), 'a'), FocusableRect(pygame.Rect(0, 0, 1, 1), 'b')
    fg.rebuild([new_a, new_b])
    assert fg.index == 1
    assert new_b.focused is True
    assert new_a.focused is False


def test_focus_group_rebuild_resets_index_when_out_of_range():
    fg = FocusGroup([FocusableRect(pygame.Rect(0, 0, 1, 1), 'a')])
    fg.index = 5  # stale, out of range for the new list
    fg.rebuild([])
    assert fg.index == -1


def test_focus_group_handle_key_ignores_non_tab_events():
    a = FocusableRect(pygame.Rect(0, 0, 1, 1), 'a')
    fg = FocusGroup([a])
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0)
    fg.handle_key(ev)
    assert fg.index == -1


def test_focus_group_handle_key_noop_on_empty_widgets():
    fg = FocusGroup([])
    ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, mod=0)
    fg.handle_key(ev)  # must not raise
    assert fg.index == -1


def test_focus_group_handle_key_tab_cycles_forward_and_wraps():
    a, b = FocusableRect(pygame.Rect(0, 0, 1, 1), 'a'), FocusableRect(pygame.Rect(0, 0, 1, 1), 'b')
    fg = FocusGroup([a, b])
    tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, mod=0)
    fg.handle_key(tab)
    assert fg.index == 0 and a.focused is True
    fg.handle_key(tab)
    assert fg.index == 1 and b.focused is True and a.focused is False
    fg.handle_key(tab)  # wraps back to 0
    assert fg.index == 0 and a.focused is True and b.focused is False


def test_focus_group_handle_key_shift_tab_cycles_backward():
    a, b = FocusableRect(pygame.Rect(0, 0, 1, 1), 'a'), FocusableRect(pygame.Rect(0, 0, 1, 1), 'b')
    fg = FocusGroup([a, b])
    shift_tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, mod=pygame.KMOD_SHIFT)
    # From the unfocused state (index -1), stepping by -1 and wrapping via
    # Python's modulo lands on index 0, not the last widget - (-1 + -1) % 2 == 0.
    fg.handle_key(shift_tab)
    assert fg.index == 0 and a.focused is True
    # From here, a further shift-tab correctly wraps backward to the last widget.
    fg.handle_key(shift_tab)
    assert fg.index == 1 and b.focused is True and a.focused is False


def test_focus_group_clear():
    a, b = FocusableRect(pygame.Rect(0, 0, 1, 1), 'a'), FocusableRect(pygame.Rect(0, 0, 1, 1), 'b')
    fg = FocusGroup([a, b])
    a.focused = True
    fg.index = 0
    fg.clear()
    assert a.focused is False and b.focused is False
    assert fg.index == -1


def test_button_draw_focused_shows_focus_ring(monkeypatch):
    """Covers the focus-ring branch in Button.draw (only reachable when
    focused and not disabled)."""
    pygame.font.init()
    monkeypatch.setattr(pygame.mouse, 'get_pos', lambda: (-1, -1))
    btn = Button((0, 0, 100, 40), 'Test', sublabel='sub')
    btn.focused = True
    surf = pygame.Surface((100, 40))

    class _Fonts:
        btn = pygame.font.SysFont('Arial', 18)
        btn_sub = pygame.font.SysFont('Arial', 14)

    btn.draw(surf, _Fonts())  # must not raise; exercises the focus-ring branch

