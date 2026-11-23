"""Decoupled rig state machine driving arms, key glows, chest bubbles, eyes, and petting."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum

from src.rig import KeySpec, get_key_spec


class HandSide(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    NEITHER = "neither"


LEFT_HAND_VKS: frozenset[int] = frozenset(
    {
        0x1B, 0xC0, 0x09, 0x14, 0xA0, 0xA2, 0x5B, 0xA4, 0x10, 0x11, 0x12,
        0x31, 0x32, 0x33, 0x34, 0x35,
        0x51, 0x57, 0x45, 0x52, 0x54,
        0x41, 0x53, 0x44, 0x46, 0x47,
        0x5A, 0x58, 0x43, 0x56, 0x42,
        0x70, 0x71, 0x72, 0x73, 0x74,
    }
)

RIGHT_HAND_VKS: frozenset[int] = frozenset(
    {
        0x08, 0x0D, 0xA1, 0xA3, 0x5C, 0xA5, 0x5D,
        0x36, 0x37, 0x38, 0x39, 0x30, 0xBD, 0xBB,
        0x59, 0x55, 0x49, 0x4F, 0x50, 0xDB, 0xDD, 0xDC,
        0x48, 0x4A, 0x4B, 0x4C, 0xBA, 0xDE,
        0x4E, 0x4D, 0xBC, 0xBE, 0xBF,
        0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x7B,
        0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22,
        0x25, 0x26, 0x27, 0x28,
        *range(0x60, 0x70),
    }
)


def classify_vk_side(vk: int, toggle_hint: HandSide = HandSide.RIGHT) -> HandSide:
    if vk in LEFT_HAND_VKS:
        return HandSide.LEFT
    if vk in RIGHT_HAND_VKS:
        return HandSide.RIGHT
    return toggle_hint


@dataclass
class KeyPressState:
    vk: int
    bubble_label: str
    spec: KeySpec
    arm_side: str  # "viewer_left" or "viewer_right"
    pressed_ms: int
    held: bool = True
    released_ms: int = 0
    first_pressed_ms: int | None = None

    def __post_init__(self) -> None:
        if self.first_pressed_ms is None:
            self.first_pressed_ms = self.pressed_ms


@dataclass
class RigSnapshot:
    pose_mode: str  # "idle" (sitting upright 1.png), "mouse" (lean left 7.png), "typing" (crouch 4.png)
    viewer_left_target: tuple[float, float] | None
    viewer_left_on_mouse: bool
    viewer_left_rest_kb: bool
    viewer_right_target: tuple[float, float] | None
    viewer_right_rest_kb: bool
    squint: bool
    lean_x: float  # -1.0 (lean left toward mouse) .. +0.3
    head_drop: float  # 0.0 (upright) .. 1.0 (looking down while typing)
    head_turn_x: float  # -1.0 .. 1.0 subtle head turn toward mouse/key
    head_turn_y: float  # -1.0 .. 1.0 subtle pitch toward mouse/key
    eye_dx: float  # -1.0 .. 1.0
    eye_dy: float  # -1.0 .. 1.0
    mouse_dx: float
    mouse_dy: float
    mouse_left_down: bool
    mouse_right_down: bool
    key_glows: list[tuple[KeySpec, float]]
    chest_bubbles: list[tuple[str, float, float, bool, float]]
    left_arm_ext: float = 0.0
    left_arm_uv: tuple[float, float] | None = None
    right_arm_ext: float = 0.0
    right_arm_uv: tuple[float, float] | None = None
    mouse_arm_ext: float = 0.0
    prev_pose_mode: str = "idle"
    pose_transition: float = 1.0  # 0.0 (start) -> 1.0 (settled in pose_mode)
    eye_openness: float = 1.0  # 1.0 = fully open, 0.0 = closed squint line
    groom_progress: float = 0.0  # 0.0 = normal idle, 1.0 = licking paw after long idle
    groom_lick_phase: float = 0.0  # continuous radians driving subtle lick bobbing & tongue motion


@dataclass
class CatStateMachine:
    """Drives decoupled dual arms, key glows, chest bubbles, eyes, lean, and petting."""

    idle_frame: int = 1
    blink_enabled: bool = True
    mouse_react_enabled: bool = True
    mirror_keyboard: bool = True
    eye_tracking_enabled: bool = True
    petting_enabled: bool = True

    min_tap_hold_ms: int = 85
    rest_after_type_ms: int = 750
    mouse_hold_ms: int = 1800
    mouse_glance_ms: int = 360
    typing_gaze_ms: int = 1500
    sleep_after_idle_ms: int = 15000
    bubble_fade_ms: int = 1050
    glow_fade_ms: int = 240

    # Key states
    _held_keys: dict[int, KeyPressState] = field(default_factory=dict)
    _recent_keys: list[KeyPressState] = field(default_factory=list)
    _last_viewer_left_key: KeyPressState | None = None
    _last_viewer_right_key: KeyPressState | None = None
    _last_toggle: str = "viewer_right"
    _last_active_u: float = 0.5
    _last_active_v: float = 0.56

    # Mouse & cursor states
    _mouse_buttons: set[str] = field(default_factory=set)
    _mouse_button_press_ms: dict[str, int] = field(default_factory=dict)
    _last_key_time_ms: int = -10000
    _last_mouse_time_ms: int = -10000
    _mouse_glance_until_ms: int = -1
    _last_activity_ms: int = 0
    _cursor_dir_x: float = 0.0
    _cursor_dir_y: float = 0.0
    _smooth_eye_x: float = 0.0
    _smooth_eye_y: float = 0.0
    _smooth_lean: float = 0.0
    _smooth_head_drop: float = 0.0
    _smooth_head_tx: float = 0.0
    _smooth_head_ty: float = 0.0
    _mouse_slide_x: float = 0.0
    _mouse_slide_y: float = 0.0
    _smooth_mouse_x: float = 0.0
    _smooth_mouse_y: float = 0.0
    _last_snap_ms: int = -1
    _left_arm_ext: float = 0.0
    _left_arm_uv: tuple[float, float] | None = None
    _left_arm_vk: int = -1
    _left_retract_for_next: bool = False
    _left_pending_uv: tuple[float, float] | None = None
    _right_arm_ext: float = 0.0
    _right_arm_uv: tuple[float, float] | None = None
    _right_arm_vk: int = -1
    _right_retract_for_next: bool = False
    _right_pending_uv: tuple[float, float] | None = None
    _mouse_arm_ext: float = 0.0
    _cur_pose_mode: str = ""
    _prev_pose_mode: str = ""
    _pose_blend: float = 1.0

    # Independent natural blink scheduler & head-hover petting state
    _next_blink_ms: int = -1
    _blink_until_ms: int = -1
    _pet_until_ms: int = -1
    _head_pressed: bool = False
    _head_press_ms: int = -1
    _hover_head_since_ms: int = -1
    _hover_head_active: bool = False
    _eye_openness: float = 1.0
    _groom_ext: float = 0.0
    _activity_inited: bool = False

    def _assign_arm_for_spec(self, vk: int, spec: KeySpec) -> str:
        if vk == 0x20:
            if self._is_mouse_active_raw():
                return "viewer_right"
            self._last_toggle = (
                "viewer_left" if self._last_toggle == "viewer_right" else "viewer_right"
            )
            return self._last_toggle
        return "viewer_left" if spec.u < 0.48 else "viewer_right"

    def _is_mouse_active_raw(self) -> bool:
        return bool(self._mouse_buttons) or (
            self._last_mouse_time_ms >= self._last_key_time_ms
            and self._last_mouse_time_ms > 0
        )

    def on_key_down(self, vk: int, now_ms: int, bubble_label: str = "") -> bool:
        """Register key press; returns True if fresh (non-repeat) press."""
        mouse_live_now = self.mouse_react_enabled and (
            bool(self._mouse_buttons)
            or (self._last_mouse_time_ms > 0 and (now_ms - self._last_mouse_time_ms) < 650)
        )
        is_fresh = vk not in self._held_keys
        if is_fresh:
            spec = get_key_spec(vk, mirror=self.mirror_keyboard)
            # When mouse is concurrently active (holding/moving mouse), dedicate ALL keystrokes to right arm
            # so left hand stays on mouse even for left-side keyboard keys (matching video 38s-end).
            arm = "viewer_right" if mouse_live_now else self._assign_arm_for_spec(vk, spec)
            st = KeyPressState(
                vk=vk,
                bubble_label=bubble_label or "?",
                spec=spec,
                arm_side=arm,
                pressed_ms=now_ms,
                held=True,
            )
            self._held_keys[vk] = st
            self._recent_keys = [k for k in self._recent_keys if k.vk != vk]
            self._recent_keys.append(st)
            if len(self._recent_keys) > 8:
                self._recent_keys = self._recent_keys[-8:]
            if arm == "viewer_left":
                if self._left_arm_ext > 0.16 and vk != self._left_arm_vk:
                    self._left_retract_for_next = True
                    self._left_pending_uv = (spec.u, spec.v)
                self._left_arm_vk = vk
                self._last_viewer_left_key = st
            else:
                if self._right_arm_ext > 0.16 and vk != self._right_arm_vk:
                    self._right_retract_for_next = True
                    self._right_pending_uv = (spec.u, spec.v)
                self._right_arm_vk = vk
                self._last_viewer_right_key = st
            self._last_active_u = spec.u
            self._last_active_v = spec.v
        else:
            st = self._held_keys[vk]
            st.pressed_ms = max(st.pressed_ms, now_ms - 10)
            self._last_active_u = st.spec.u
            self._last_active_v = st.spec.v

        prev_activity = self._last_activity_ms
        self._last_key_time_ms = now_ms
        self._last_activity_ms = now_ms
        # Keystroke immediately focuses head & gaze on the pressed keyboard key
        self._mouse_glance_until_ms = -1
        # Clear stale mouse timestamps during pure typing so cat won't auto-grab mouse after finishing typing
        if not mouse_live_now:
            self._last_mouse_time_ms = -10000
        elif is_fresh and not self._mouse_buttons:
            # In concurrent mouse_typing (video 39s-end), add subtle reach/retract recoil pulse on fresh key tap
            self._mouse_arm_ext = min(self._mouse_arm_ext, 0.32)
        if self._next_blink_ms < 0 or (
            prev_activity > 0 and (now_ms - prev_activity) >= self.sleep_after_idle_ms
        ):
            self._next_blink_ms = now_ms + random.randint(2400, 3600)
        return is_fresh

    def on_key_up(self, vk: int, now_ms: int) -> bool:
        st = self._held_keys.pop(vk, None)
        if st is None:
            return False
        st.held = False
        st.released_ms = now_ms
        self._last_activity_ms = now_ms
        return True

    def on_mouse_button(self, button: str, down: bool, now_ms: int) -> None:
        if down:
            if button not in self._mouse_buttons:
                self._mouse_button_press_ms[button] = now_ms
            self._mouse_buttons.add(button)
        else:
            self._mouse_buttons.discard(button)
            self._mouse_button_press_ms.pop(button, None)
        prev_activity = self._last_activity_ms
        self._last_mouse_time_ms = now_ms
        self._mouse_glance_until_ms = now_ms + self.mouse_glance_ms
        self._last_activity_ms = now_ms
        if self._next_blink_ms < 0 or (
            prev_activity > 0 and (now_ms - prev_activity) >= self.sleep_after_idle_ms
        ):
            self._next_blink_ms = now_ms + random.randint(2400, 3600)

    def on_mouse_move(
        self,
        now_ms: int,
        dir_x: float = 0.0,
        dir_y: float = 0.0,
        local_norm: tuple[float, float] | None = None,
        screen_norm: tuple[float, float] | None = None,
    ) -> None:
        """Update mouse activity, eye tracking target, mouse slide, and head-petting rub."""
        prev_activity = self._last_activity_ms
        self._last_mouse_time_ms = now_ms
        self._mouse_glance_until_ms = now_ms + self.mouse_glance_ms
        self._last_activity_ms = now_ms
        if self._next_blink_ms < 0 or (
            prev_activity > 0 and (now_ms - prev_activity) >= self.sleep_after_idle_ms
        ):
            self._next_blink_ms = now_ms + random.randint(2400, 3600)
        cx = max(-1.0, min(1.0, dir_x))
        cy = max(-1.0, min(1.0, dir_y))
        self._cursor_dir_x = cx
        self._cursor_dir_y = cy
        if screen_norm is not None:
            sx = max(-1.0, min(1.0, screen_norm[0]))
            sy = max(-1.0, min(1.0, screen_norm[1]))
            # Blend full-screen position with local direction so desk mouse moves freely even when cat sits in screen corners
            self._mouse_slide_x = max(-1.0, min(1.0, 0.85 * sx + 0.15 * cx))
            self._mouse_slide_y = max(-1.0, min(1.0, 0.85 * sy + 0.15 * cy))
        else:
            self._mouse_slide_x = cx
            self._mouse_slide_y = cy

    @staticmethod
    def is_on_head(local_norm: tuple[float, float] | None) -> bool:
        """Return True when normalized window position hits the cat's head silhouette."""
        if local_norm is None:
            return False
        lx, ly = local_norm
        return (0.10 <= lx <= 0.78) and (0.02 <= ly <= 0.45)

    def on_head_click(self, down: bool, now_ms: int) -> None:
        """Close eyes while clicking/pressing cat's head; reopen smoothly after release."""
        self._last_activity_ms = now_ms
        self._activity_inited = True
        if not self.petting_enabled:
            self._head_pressed = False
            return
        if down:
            self._head_pressed = True
            self._head_press_ms = now_ms
            self._pet_until_ms = max(self._pet_until_ms, now_ms + 650)
        else:
            if self._head_pressed:
                self._pet_until_ms = max(now_ms + 320, self._head_press_ms + 650)
            self._head_pressed = False

    def update_head_hover(self, on_head: bool, now_ms: int) -> None:
        """Hovering no longer closes eyes; clicking the cat's head triggers eye closure."""
        self._hover_head_since_ms = -1
        self._hover_head_active = False

    def trigger_pet_poke(self, now_ms: int) -> None:
        self._last_activity_ms = now_ms
        self._activity_inited = True
        if self.petting_enabled:
            self._pet_until_ms = max(self._pet_until_ms, now_ms + 650)

    def held_keys_snapshot(self) -> list[tuple[int, int]]:
        """Return [(vk, first_pressed_ms), ...] for currently held keys."""
        return [
            (vk, st.first_pressed_ms if st.first_pressed_ms is not None else st.pressed_ms)
            for vk, st in self._held_keys.items()
        ]

    def held_mouse_buttons_snapshot(self) -> list[tuple[str, int]]:
        """Return [(button, pressed_ms), ...] for currently held mouse buttons."""
        return [(btn, self._mouse_button_press_ms.get(btn, 0)) for btn in self._mouse_buttons]

    def head_press_state(self) -> tuple[bool, int]:
        """Return (head_pressed, press_ms)."""
        return self._head_pressed, self._head_press_ms

    def reset_inputs(self) -> None:
        for st in self._held_keys.values():
            st.held = False
            st.released_ms = 0
        self._held_keys.clear()
        self._mouse_buttons.clear()
        self._mouse_button_press_ms.clear()
        self._last_viewer_left_key = None
        self._last_viewer_right_key = None
        self._mouse_glance_until_ms = -1
        self._hover_head_since_ms = -1
        self._hover_head_active = False
        self._head_pressed = False
        self._head_press_ms = -1
        self._pet_until_ms = -1
        self._eye_openness = 1.0
        self._groom_ext = 0.0
        self._left_arm_ext = 0.0
        self._left_arm_uv = None
        self._left_arm_vk = -1
        self._left_retract_for_next = False
        self._left_pending_uv = None
        self._right_arm_ext = 0.0
        self._right_arm_uv = None
        self._right_arm_vk = -1
        self._right_retract_for_next = False
        self._right_pending_uv = None

    @staticmethod
    def _step_typing_arm(
        arm_ext: float,
        arm_uv: tuple[float, float] | None,
        retract_for_next: bool,
        pending_uv: tuple[float, float] | None,
        target_uv: tuple[float, float] | None,
        dt_ms: float,
    ) -> tuple[float, tuple[float, float] | None, bool, tuple[float, float] | None]:
        """Advance single typing arm with snappy retract-then-strike on rapid key switches."""
        if target_uv is not None:
            if retract_for_next and arm_uv is not None:
                # Rapidly pull back along previous key line instead of sliding sideways across keycaps
                arm_ext = max(0.0, arm_ext - dt_ms / 44.0)
                if arm_ext <= 0.12:
                    retract_for_next = False
                    arm_uv = pending_uv if pending_uv is not None else target_uv
                    pending_uv = None
                    arm_ext = min(1.0, arm_ext + dt_ms / 48.0)
                return arm_ext, arm_uv, retract_for_next, pending_uv

            retract_for_next = False
            pending_uv = None
            if arm_uv is None or arm_ext <= 0.15:
                arm_uv = target_uv
            else:
                arm_uv = (
                    arm_uv[0] + (target_uv[0] - arm_uv[0]) * 0.52,
                    arm_uv[1] + (target_uv[1] - arm_uv[1]) * 0.52,
                )
            arm_ext = min(1.0, arm_ext + dt_ms / 54.0)
            return arm_ext, arm_uv, retract_for_next, pending_uv

        retract_for_next = False
        pending_uv = None
        arm_ext = max(0.0, arm_ext - dt_ms / 135.0)
        if arm_ext <= 0.01:
            arm_uv = None
        return arm_ext, arm_uv, retract_for_next, pending_uv

    def _is_grooming_idle(self, now_ms: int, pose_mode: str = "idle") -> bool:
        return (
            pose_mode == "idle"
            and self.idle_frame == 1
            and self._last_activity_ms > 0
            and (now_ms - self._last_activity_ms >= self.sleep_after_idle_ms)
            and not self._head_pressed
            and self._pet_until_ms <= now_ms
        )

    def _eval_eye_closure(self, now_ms: int, pose_mode: str = "idle") -> tuple[bool, bool]:
        """Return (want_closed, is_short_blink)."""
        if self.petting_enabled and (self._head_pressed or self._pet_until_ms > now_ms):
            return True, False
        if self._is_grooming_idle(now_ms, pose_mode):
            return True, False
        if (
            self.blink_enabled
            and self._last_activity_ms > 0
            and (now_ms - self._last_activity_ms >= self.sleep_after_idle_ms)
        ):
            return True, False
        if self.blink_enabled:
            if self._blink_until_ms > now_ms:
                return True, True
            if self._next_blink_ms < 0:
                self._next_blink_ms = now_ms + random.randint(2400, 3600)
                return False, False
            if now_ms >= self._next_blink_ms:
                self._blink_until_ms = now_ms + 125
                self._next_blink_ms = now_ms + random.randint(3200, 5200)
                return True, True
        return False, False

    def _squint_active(self, now_ms: int) -> bool:
        return self._eval_eye_closure(now_ms)[0]

    def current_frame(self, now_ms: int) -> int:
        """Legacy frame-index API preserved for compatibility and simple tests."""
        snap = self.snapshot(now_ms)
        if snap.viewer_left_target and snap.viewer_right_target:
            return 5
        if snap.viewer_right_target:
            return 3
        if snap.viewer_left_target:
            return 2
        if snap.squint:
            return 6
        if snap.viewer_left_on_mouse:
            return 7
        if snap.viewer_left_rest_kb or snap.viewer_right_rest_kb:
            return 1
        return self.idle_frame

    def snapshot(self, now_ms: int) -> RigSnapshot:
        """Compute full procedural rig snapshot for the current frame."""
        if not self._activity_inited:
            self._activity_inited = True
            if self._last_activity_ms <= 0:
                self._last_activity_ms = now_ms
        self._recent_keys = [
            k
            for k in self._recent_keys
            if k.held or (now_ms - k.released_ms) < self.bubble_fade_ms
        ]

        left_held = [k for k in self._held_keys.values() if k.arm_side == "viewer_left"]
        left_target: tuple[float, float] | None = None
        if left_held:
            latest = max(left_held, key=lambda k: k.pressed_ms)
            left_target = (latest.spec.u, latest.spec.v)
        elif (
            self._last_viewer_left_key is not None
            and (now_ms - self._last_viewer_left_key.pressed_ms) < self.min_tap_hold_ms
        ):
            left_target = (self._last_viewer_left_key.spec.u, self._last_viewer_left_key.spec.v)

        right_held = [k for k in self._held_keys.values() if k.arm_side == "viewer_right"]
        right_target: tuple[float, float] | None = None
        if right_held:
            latest = max(right_held, key=lambda k: k.pressed_ms)
            right_target = (latest.spec.u, latest.spec.v)
        elif (
            self._last_viewer_right_key is not None
            and (now_ms - self._last_viewer_right_key.pressed_ms) < self.min_tap_hold_ms
        ):
            right_target = (self._last_viewer_right_key.spec.u, self._last_viewer_right_key.spec.v)

        mouse_recent = (
            self.mouse_react_enabled
            and (
                bool(self._mouse_buttons)
                or (
                    self._last_mouse_time_ms > 0
                    and (now_ms - self._last_mouse_time_ms) < self.mouse_hold_ms
                    and self._last_mouse_time_ms >= self._last_key_time_ms - 650
                )
            )
            and left_target is None
        )

        # Typing session active while a key is pressed or shortly after releasing keys
        typing_recent = (
            left_target is not None
            or right_target is not None
            or (now_ms - self._last_key_time_ms) < self.typing_gaze_ms
        )
        concurrent_typing = (
            right_target is not None
            or (self._last_key_time_ms > 0 and (now_ms - self._last_key_time_ms) < 750)
        )

        if mouse_recent and concurrent_typing:
            pose_mode = "mouse_typing"
        elif mouse_recent:
            pose_mode = "mouse"
        elif typing_recent or self.idle_frame == 4:
            pose_mode = "typing"
        else:
            pose_mode = "idle"

        # When idle sitting (idle_frame == 1), hands are baked as the 4 straight lines on keyboard;
        # when sitting idle_frame == 4 or during brief pauses right after typing, curled/resting paws apply.
        rest_kb = (
            pose_mode == "idle"
            or (
                pose_mode == "typing"
                and self.idle_frame == 1
                and left_target is None
                and right_target is None
                and (now_ms - self._last_key_time_ms) < self.rest_after_type_ms
            )
        )

        squint, is_short_blink = self._eval_eye_closure(now_ms, pose_mode)
        groom_active = self._is_grooming_idle(now_ms, pose_mode)
        lick_phase = ((now_ms % 980) / 980.0) * 2.0 * math.pi if groom_active or self._groom_ext > 0.01 else 0.0

        # While typing (including concurrent mouse_typing), cat keeps looking at the pressed key (e.g. A/S/D),
        # briefly glancing at mouse only when mouse moves, then quickly snapping gaze back onto the key!
        mouse_glance_active = mouse_recent and now_ms < self._mouse_glance_until_ms
        typing_gaze = (
            pose_mode in ("typing", "mouse_typing")
            and (left_target is not None or right_target is not None or typing_recent)
            and not mouse_glance_active
        )

        if groom_active:
            lick_nod = 0.5 - 0.5 * math.cos(lick_phase)
            target_ex = 0.0
            target_ey = 0.0
            target_drop = 0.0
            target_htx = -0.12 + 0.12 * math.sin(lick_phase)
            target_hty = -0.15 + 1.15 * lick_nod
        elif typing_gaze:
            # Project active key's (u, v) to 940x940 canvas x so cat turns head & focuses pupils on the actual key!
            top_x = 204.0 + (836.0 - 204.0) * self._last_active_u
            bot_x = 186.0 + (864.0 - 186.0) * self._last_active_u
            key_canvas_x = top_x + (bot_x - top_x) * self._last_active_v
            head_center_x = 474.0
            target_htx = max(-0.92, min(0.92, (key_canvas_x - head_center_x) / 260.0))
            turned_eye_mid_x = head_center_x + target_htx * 26.0
            target_ex = max(-0.96, min(0.96, (key_canvas_x - turned_eye_mid_x) / 240.0))
            target_ey = max(0.76, min(0.98, 0.78 + self._last_active_v * 0.22))
            target_drop = 1.0
            target_hty = 0.62
        elif mouse_recent and self.eye_tracking_enabled:
            target_ex = self._cursor_dir_x
            target_ey = self._cursor_dir_y
            target_drop = 0.0
            target_htx = self._cursor_dir_x
            target_hty = self._cursor_dir_y
        elif self.eye_tracking_enabled:
            target_ex = self._cursor_dir_x * 0.78
            target_ey = self._cursor_dir_y * 0.78
            target_drop = 0.0
            target_htx = self._cursor_dir_x * 0.80
            target_hty = self._cursor_dir_y * 0.80
        else:
            target_ex = 0.0
            target_ey = 0.0
            target_drop = 0.0
            target_htx = 0.0
            target_hty = 0.0

        eye_gain = 0.52 if typing_gaze else 0.40
        head_gain = 0.42 if typing_gaze else 0.36
        self._smooth_eye_x += (target_ex - self._smooth_eye_x) * eye_gain
        self._smooth_eye_y += (target_ey - self._smooth_eye_y) * eye_gain
        self._smooth_head_drop += (target_drop - self._smooth_head_drop) * 0.24
        self._smooth_head_tx += (target_htx - self._smooth_head_tx) * head_gain
        self._smooth_head_ty += (target_hty - self._smooth_head_ty) * head_gain
        target_mx = self._mouse_slide_x if mouse_recent else 0.0
        target_my = self._mouse_slide_y if mouse_recent else 0.0
        self._smooth_mouse_x += (target_mx - self._smooth_mouse_x) * 0.24
        self._smooth_mouse_y += (target_my - self._smooth_mouse_y) * 0.24

        # Smooth arm extension/retraction kinematics (reach ~60ms, retract ~135ms, mouse grip ~135ms)
        if self._last_snap_ms < 0:
            raw_dt = 16
            dt_ms = 16.0
        else:
            raw_dt = now_ms - self._last_snap_ms
            dt_ms = 16.0 if (raw_dt <= 0 or raw_dt > 500) else float(raw_dt)
        self._last_snap_ms = now_ms

        # Continuous eyelid opening/closing process (~185ms close, ~205ms reopen on hover/pet; faster for blink)
        target_open = 0.0 if squint else 1.0
        if raw_dt > 1000:
            self._eye_openness = target_open
        elif self._eye_openness > target_open:
            dur = 90.0 if is_short_blink else 185.0
            self._eye_openness = max(target_open, self._eye_openness - dt_ms / dur)
        elif self._eye_openness < target_open:
            dur = 115.0 if (now_ms - self._blink_until_ms) < 250 else 205.0
            self._eye_openness = min(target_open, self._eye_openness + dt_ms / dur)

        target_groom = 1.0 if groom_active else 0.0
        if raw_dt > 1000:
            self._groom_ext = target_groom
        elif self._groom_ext < target_groom:
            self._groom_ext = min(1.0, self._groom_ext + dt_ms / 280.0)
        elif self._groom_ext > target_groom:
            self._groom_ext = max(0.0, self._groom_ext - dt_ms / 180.0)

        target_lean = 0.0
        if pose_mode == "mouse":
            target_lean = max(-0.25, min(0.25, self._cursor_dir_x * 0.25))
        elif pose_mode == "mouse_typing":
            # Lean gently toward mouse while left arm reaches out, settle back upright as paw retracts
            arm_factor = max(0.0, min(1.0, self._mouse_arm_ext))
            target_lean = -0.22 * arm_factor + max(-0.10, min(0.10, self._cursor_dir_x * 0.10))
        elif left_target is not None and right_target is None:
            target_lean = -0.22
        elif right_target is not None and left_target is None:
            target_lean = 0.22
        self._smooth_lean += (target_lean - self._smooth_lean) * 0.20

        mouse_step = dt_ms / 135.0

        # Left typing arm (with rapid retract-then-strike on consecutive fast keys)
        (
            self._left_arm_ext,
            self._left_arm_uv,
            self._left_retract_for_next,
            self._left_pending_uv,
        ) = self._step_typing_arm(
            self._left_arm_ext,
            self._left_arm_uv,
            self._left_retract_for_next,
            self._left_pending_uv,
            left_target if pose_mode == "typing" else None,
            dt_ms,
        )

        # Right typing arm (works in typing & mouse_typing / mouse with rapid retract-then-strike)
        (
            self._right_arm_ext,
            self._right_arm_uv,
            self._right_retract_for_next,
            self._right_pending_uv,
        ) = self._step_typing_arm(
            self._right_arm_ext,
            self._right_arm_uv,
            self._right_retract_for_next,
            self._right_pending_uv,
            right_target,
            dt_ms,
        )

        # Mouse left-arm reach & release transition:
        # In mouse_typing (video 39s-end), left arm dynamically retracts toward chest when cursor pauses
        # (>260ms since last move without button held) and springs back out upon movement.
        mouse_idle_ms = (now_ms - self._last_mouse_time_ms) if self._last_mouse_time_ms > 0 else 99999
        want_mouse_grip = mouse_recent and (
            pose_mode == "mouse" or bool(self._mouse_buttons) or mouse_idle_ms < 280
        )
        if want_mouse_grip:
            step = dt_ms / 105.0 if pose_mode == "mouse_typing" else mouse_step
            self._mouse_arm_ext = min(1.0, self._mouse_arm_ext + step)
        else:
            step = dt_ms / 115.0 if pose_mode == "mouse_typing" else mouse_step
            self._mouse_arm_ext = max(0.0, self._mouse_arm_ext - step)

        # Smooth pose-to-pose transition progress (~175ms across any mode switches)
        if not self._cur_pose_mode:
            self._cur_pose_mode = pose_mode
            self._prev_pose_mode = pose_mode
            self._pose_blend = 1.0
        elif pose_mode != self._cur_pose_mode:
            self._prev_pose_mode = (
                self._prev_pose_mode if self._pose_blend < 0.5 else self._cur_pose_mode
            )
            self._cur_pose_mode = pose_mode
            self._pose_blend = 0.0
        elif self._pose_blend < 1.0:
            dur = 210.0 if pose_mode == "idle" else 170.0
            self._pose_blend = min(1.0, self._pose_blend + dt_ms / dur)

        key_glows: list[tuple[KeySpec, float]] = []
        for k in self._recent_keys:
            if k.held:
                key_glows.append((k.spec, 1.0))
            else:
                age = now_ms - k.released_ms
                if age < self.glow_fade_ms:
                    key_glows.append((k.spec, max(0.0, 1.0 - age / self.glow_fade_ms)))

        chest_bubbles: list[tuple[str, float, float, bool, float]] = []
        for k in self._recent_keys:
            if k.held:
                alpha = 1.0
            else:
                age = now_ms - k.released_ms
                alpha = (
                    1.0
                    if age < 450
                    else max(0.0, 1.0 - (age - 450) / (self.bubble_fade_ms - 450))
                )
            if alpha <= 0.02:
                continue
            w_scale = 1.45 if k.vk == 0x20 else 1.0
            chest_bubbles.append((k.bubble_label, k.spec.u, w_scale, k.held, alpha))

        return RigSnapshot(
            pose_mode=pose_mode,
            viewer_left_target=left_target,
            viewer_left_on_mouse=(pose_mode in ("mouse", "mouse_typing")),
            viewer_left_rest_kb=rest_kb,
            viewer_right_target=right_target,
            viewer_right_rest_kb=rest_kb,
            squint=squint,
            lean_x=self._smooth_lean,
            head_drop=self._smooth_head_drop,
            head_turn_x=self._smooth_head_tx,
            head_turn_y=self._smooth_head_ty,
            eye_dx=self._smooth_eye_x,
            eye_dy=self._smooth_eye_y,
            mouse_dx=self._smooth_mouse_x,
            mouse_dy=self._smooth_mouse_y,
            mouse_left_down="left" in self._mouse_buttons,
            mouse_right_down="right" in self._mouse_buttons,
            key_glows=key_glows,
            chest_bubbles=chest_bubbles,
            left_arm_ext=self._left_arm_ext,
            left_arm_uv=self._left_arm_uv,
            right_arm_ext=self._right_arm_ext,
            right_arm_uv=self._right_arm_uv,
            mouse_arm_ext=self._mouse_arm_ext,
            prev_pose_mode=self._prev_pose_mode or pose_mode,
            pose_transition=self._pose_blend,
            eye_openness=self._eye_openness,
            groom_progress=self._groom_ext,
            groom_lick_phase=lick_phase,
        )
