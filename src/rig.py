"""Procedural 2D cat rig: keyboard key coordinates, articulated arms, and eye pupils."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

# Canonical mirrored ANSI 60% mechanical keyboard (15.0u wide x 5 rows, facing viewer from cat's side).
# Each tuple: (row_idx, u0_units, u1_units, accent_color, vks)
# accent_color: "ivory" | "orange"
KEYBOARD_60_SPEC: list[tuple[int, float, float, str, tuple[int, ...]]] = [
    # Row 0 (closest to cat: Spacebar row)
    (0, 0.00, 1.25, "ivory", (0xA3,)),
    (0, 1.25, 2.50, "ivory", (0x5C,)),
    (0, 2.50, 3.75, "ivory", (0xA5,)),
    (0, 3.75, 10.00, "ivory", (0x20,)),          # 6.25u Spacebar
    (0, 10.00, 11.25, "ivory", (0xA4, 0x12)),
    (0, 11.25, 12.50, "ivory", (0x5B,)),
    (0, 12.50, 13.75, "ivory", ()),
    (0, 13.75, 15.00, "ivory", (0xA2, 0x11)),
    # Row 1 (Z..M row)
    (1, 0.00, 2.75, "ivory", (0xA1,)),
    (1, 2.75, 3.75, "ivory", (0xBF, 0x25, 0x28)),  # / (plus arrow fallback region)
    (1, 3.75, 4.75, "ivory", (0xBE,)),
    (1, 4.75, 5.75, "ivory", (0xBC,)),
    (1, 5.75, 6.75, "ivory", (0x4D,)),           # M
    (1, 6.75, 7.75, "ivory", (0x4E,)),           # N
    (1, 7.75, 8.75, "ivory", (0x42,)),           # B
    (1, 8.75, 9.75, "ivory", (0x56,)),           # V
    (1, 9.75, 10.75, "ivory", (0x43,)),          # C
    (1, 10.75, 11.75, "ivory", (0x58,)),         # X
    (1, 11.75, 12.75, "ivory", (0x5A,)),         # Z
    (1, 12.75, 15.00, "ivory", (0xA0, 0x10)),    # LShift
    # Row 2 (Home row A..L, orange Enter on far left & Caps on right matching reference proportions)
    (2, 0.00, 1.75, "orange", (0x0D,)),          # Enter (orange)
    (2, 1.75, 2.75, "ivory", (0xDE,)),           # '
    (2, 2.75, 3.75, "ivory", (0xBA,)),           # ;
    (2, 3.75, 4.75, "ivory", (0x4C,)),           # L
    (2, 4.75, 5.75, "ivory", (0x4B,)),           # K
    (2, 5.75, 6.75, "ivory", (0x4A,)),           # J
    (2, 6.75, 7.75, "ivory", (0x48,)),           # H
    (2, 7.75, 8.75, "ivory", (0x47,)),           # G
    (2, 8.75, 9.75, "ivory", (0x46,)),           # F
    (2, 9.75, 10.75, "ivory", (0x44,)),          # D
    (2, 10.75, 11.75, "ivory", (0x53,)),         # S
    (2, 11.75, 12.75, "ivory", (0x41,)),         # A
    (2, 12.75, 15.00, "ivory", (0x14,)),         # Caps Lock
    # Row 3 (QWERTY row)
    (3, 0.00, 1.50, "ivory", (0xDC,)),           # \
    (3, 1.50, 2.50, "ivory", (0xDD,)),           # ]
    (3, 2.50, 3.50, "ivory", (0xDB,)),           # [
    (3, 3.50, 4.50, "ivory", (0x50,)),           # P
    (3, 4.50, 5.50, "ivory", (0x4F,)),           # O
    (3, 5.50, 6.50, "ivory", (0x49,)),           # I
    (3, 6.50, 7.50, "ivory", (0x55,)),           # U
    (3, 7.50, 8.50, "ivory", (0x59,)),           # Y
    (3, 8.50, 9.50, "ivory", (0x54,)),           # T
    (3, 9.50, 10.50, "ivory", (0x52,)),          # R
    (3, 10.50, 11.50, "ivory", (0x45,)),         # E
    (3, 11.50, 12.50, "ivory", (0x57,)),         # W
    (3, 12.50, 13.50, "ivory", (0x51,)),         # Q
    (3, 13.50, 15.00, "ivory", (0x09,)),         # Tab
    # Row 4 (Number row + Backspace on left + orange Esc on bottom-right)
    (4, 0.00, 2.00, "ivory", (0x08,)),           # Backspace
    (4, 2.00, 3.00, "ivory", (0xBB,)),           # =
    (4, 3.00, 4.00, "ivory", (0xBD,)),           # -
    (4, 4.00, 5.00, "ivory", (0x30,)),           # 0
    (4, 5.00, 6.00, "ivory", (0x39,)),           # 9
    (4, 6.00, 7.00, "ivory", (0x38,)),           # 8
    (4, 7.00, 8.00, "ivory", (0x37,)),           # 7
    (4, 8.00, 9.00, "ivory", (0x36,)),           # 6
    (4, 9.00, 10.00, "ivory", (0x35,)),          # 5
    (4, 10.00, 11.00, "ivory", (0x34,)),         # 4
    (4, 11.00, 12.00, "ivory", (0x33,)),         # 3
    (4, 12.00, 13.00, "ivory", (0x32,)),         # 2
    (4, 13.00, 14.00, "ivory", (0x31, 0xC0)),    # 1 / `
    (4, 14.00, 15.00, "orange", (0x1B,)),        # Esc (orange corner key)
]

KEYBOARD_ROW_V_BOUNDS: tuple[tuple[float, float], ...] = (
    (0.025, 0.190),
    (0.215, 0.380),
    (0.405, 0.570),
    (0.595, 0.760),
    (0.785, 0.960),
)

MIRRORED_KEY_LAYOUT: dict[int, tuple[float, float, float, float]] = {}
for _r, _u0u, _u1u, _col, _vks in KEYBOARD_60_SPEC:
    _rv0, _rv1 = KEYBOARD_ROW_V_BOUNDS[_r]
    _cu = (_u0u + _u1u) / 30.0
    _wu = (_u1u - _u0u) / 15.0
    _cv = (_rv0 + _rv1) * 0.5
    _hv = _rv1 - _rv0
    for _vk in _vks:
        MIRRORED_KEY_LAYOUT[_vk] = (_cu, _cv, _wu, _hv)

# Preserve explicit positions for secondary arrow / nav keys outside the 60% legend list
MIRRORED_KEY_LAYOUT.update(
    {
        0x25: (0.150, 0.298, 0.062, 0.165),
        0x28: (0.092, 0.298, 0.062, 0.165),
        0x27: (0.042, 0.298, 0.062, 0.165),
        0x26: (0.092, 0.488, 0.062, 0.165),
        0x2E: (0.042, 0.678, 0.062, 0.165),
    }
)

for _i in range(12):
    MIRRORED_KEY_LAYOUT[0x70 + _i] = (0.86 - _i * 0.068, 0.87, 0.058, 0.165)
for _i in range(10):
    MIRRORED_KEY_LAYOUT[0x60 + _i] = (0.18 + (_i % 3) * 0.06, 0.50 + (_i // 3) * 0.14, 0.058, 0.165)


@dataclass
class KeySpec:
    u: float
    v: float
    w: float
    h: float


def get_key_spec(vk: int, mirror: bool = True) -> KeySpec:
    """Resolve normalized keyboard coordinates (u, v, w, h) for any VK code."""
    u, v, w, h = MIRRORED_KEY_LAYOUT.get(vk, (0.50, 0.52, 0.065, 0.20))
    if not mirror:
        u = 1.0 - u
    return KeySpec(u=u, v=v, w=w, h=h)


class CatRig:
    """Geometry helpers and QPainter drawing routines matching the cleaned cat assets."""

    def __init__(self, parts_dir: Path | str) -> None:
        parts_dir = Path(parts_dir)
        meta = json.loads((parts_dir / "parts_meta.json").read_text(encoding="utf-8"))
        self.canvas_size: float = float(meta["canvas_size"])
        self.left_eye: dict[str, float] = meta["left_eye"]
        self.right_eye: dict[str, float] = meta["right_eye"]
        self.modes: dict[str, dict] = meta.get("modes", {})
        rgb = meta["eye_green_rgb"]
        self.eye_green = QColor(rgb[0], rgb[1], rgb[2])
        self.neck_pivot = QPointF(*meta["neck_pivot"])
        self.hip_pivot = QPointF(*meta["hip_pivot"])
        self.left_shoulder = QPointF(*meta["left_shoulder"])
        self.right_shoulder = QPointF(*meta["right_shoulder"])
        mouse_mode = self.modes.get("mouse", {})
        self.mouse_left_shoulder = QPointF(*mouse_mode.get("left_shoulder", [204.0, 456.0]))
        self.mouse_right_shoulder = QPointF(*mouse_mode.get("right_shoulder", [445.0, 515.0]))
        self.mouse_neck_pivot = QPointF(*mouse_mode.get("neck_pivot", [290.0, 342.0]))
        self.mouse_grip_center = QPointF(*mouse_mode.get("mouse_grip_center", [98.0, 726.0]))
        self.mouse_head_cx: float = float(mouse_mode.get("head_cx", 260.0))
        idle_mode = self.modes.get("idle", {})
        self.idle_neck_pivot = QPointF(*idle_mode.get("neck_pivot", [488.0, 365.0]))
        # Calibrate white keycap field quad tightly to the crisp 3D keyboard case
        self.kb_quad = [
            QPointF(204.0, 722.0),
            QPointF(844.0, 753.0),
            QPointF(868.0, 875.0),
            QPointF(188.0, 833.0),
        ]
        self.mouse_rect = meta["mouse_rect"]
        self.mouse_center = QPointF(*meta["mouse_center"])

    def kb_uv_to_px(self, u: float, v: float) -> QPointF:
        """Bilinearly project normalized keyboard (u, v) onto the 940x940 canvas."""
        tl, tr, br, bl = self.kb_quad
        top = QPointF(tl.x() + (tr.x() - tl.x()) * u, tl.y() + (tr.y() - tl.y()) * u)
        bot = QPointF(bl.x() + (br.x() - bl.x()) * u, bl.y() + (br.y() - bl.y()) * u)
        return QPointF(top.x() + (bot.x() - top.x()) * v, top.y() + (bot.y() - top.y()) * v)

    def kb_key_polygon(self, spec: KeySpec) -> QPolygonF:
        """Return the tilted quadrilateral of a key on the 940x940 keyboard."""
        u0 = max(0.01, spec.u - spec.w * 0.5)
        u1 = min(0.99, spec.u + spec.w * 0.5)
        v0 = max(0.02, spec.v - spec.h * 0.5)
        v1 = min(0.98, spec.v + spec.h * 0.5)
        return QPolygonF(
            [
                self.kb_uv_to_px(u0, v0),
                self.kb_uv_to_px(u1, v0),
                self.kb_uv_to_px(u1, v1),
                self.kb_uv_to_px(u0, v1),
            ]
        )

    def draw_keyboard(
        self,
        painter: QPainter,
        highlights: list[tuple[KeySpec, float]],
        show_glow: bool = True,
    ) -> None:
        """Render the crisp 5-row 3D mechanical keyboard matching the reference image with live per-key press depression."""
        # Outer dark charcoal case matching reference keyboard dimensions and slight perspective tilt
        case_deck = QPolygonF(
            [
                QPointF(193.0, 714.0),
                QPointF(855.0, 746.0),
                QPointF(884.0, 887.0),
                QPointF(174.0, 842.0),
            ]
        )
        case_front = QPolygonF(
            [
                QPointF(174.0, 842.0),
                QPointF(884.0, 887.0),
                QPointF(888.0, 913.0),
                QPointF(170.0, 865.0),
            ]
        )
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(22, 23, 24))
        painter.drawPolygon(case_deck)
        painter.setBrush(QColor(42, 44, 45))
        painter.drawPolygon(case_front)
        painter.setPen(QPen(QColor(18, 19, 20), 1.6))
        painter.drawLine(QPointF(174.0, 842.0), QPointF(884.0, 887.0))

        # Index active/fading key press intensities by (row_idx, key_u_center)
        press_by_key: dict[tuple[int, float], float] = {}
        for spec, intensity in highlights:
            if intensity <= 0.02:
                continue
            # Match to the nearest physical keycap in KEYBOARD_60_SPEC
            best_key = None
            best_d = 999.0
            for r_idx, u0u, u1u, _col, _vks in KEYBOARD_60_SPEC:
                rv0, rv1 = KEYBOARD_ROW_V_BOUNDS[r_idx]
                cu = (u0u + u1u) / 30.0
                cv = (rv0 + rv1) * 0.5
                d = abs(spec.u - cu) + abs(spec.v - cv) * 0.65
                if d < best_d:
                    best_d = d
                    best_key = (r_idx, cu)
            if best_key is not None:
                press_by_key[best_key] = max(press_by_key.get(best_key, 0.0), min(1.0, intensity))

        pad_u = 0.0045
        pad_v = 0.014
        for r_idx, u0u, u1u, accent, _vks in KEYBOARD_60_SPEC:
            rv0, rv1 = KEYBOARD_ROW_V_BOUNDS[r_idx]
            cu = (u0u + u1u) / 30.0
            u0 = (u0u / 15.0) + pad_u
            u1 = (u1u / 15.0) - pad_u
            v0 = rv0 + pad_v
            v1 = rv1 - pad_v

            press_k = press_by_key.get((r_idx, cu), 0.0)
            # Rest 3D keycap elevation (~7.4px) sinks cleanly down (~6.2px) into socket when pressed!
            lift_y = 7.4 - 6.2 * press_k
            # Base socket footprint (on deck)
            b_tl = self.kb_uv_to_px(u0, v0)
            b_tr = self.kb_uv_to_px(u1, v0)
            b_br = self.kb_uv_to_px(u1, v1)
            b_bl = self.kb_uv_to_px(u0, v1)

            # Lifted/depressed top keycap face (slight perspective taper inward at top)
            shrink_x = 3.2
            t_tl = QPointF(b_tl.x() + shrink_x, b_tl.y() - lift_y)
            t_tr = QPointF(b_tr.x() - shrink_x, b_tr.y() - lift_y)
            t_br = QPointF(b_br.x() - shrink_x * 0.45, b_br.y() - lift_y + 1.2)
            t_bl = QPointF(b_bl.x() + shrink_x * 0.45, b_bl.y() - lift_y + 1.2)

            if accent == "orange":
                top_rgb = (242, 168, 44)
                side_rgb = (182, 120, 28)
            else:
                top_rgb = (252, 251, 245)
                side_rgb = (186, 184, 170)

            if press_k > 0.01:
                if show_glow:
                    # Blend pressed keycap cleanly toward lime green
                    gr, gg, gb = self.eye_green.red(), self.eye_green.green(), self.eye_green.blue()
                    mix = 0.78 * press_k
                    top_rgb = (
                        int(top_rgb[0] * (1.0 - mix) + gr * mix),
                        int(top_rgb[1] * (1.0 - mix) + gg * mix),
                        int(top_rgb[2] * (1.0 - mix) + gb * mix),
                    )
                    side_rgb = (
                        int(side_rgb[0] * (1.0 - mix) + gr * 0.74 * mix),
                        int(side_rgb[1] * (1.0 - mix) + gg * 0.74 * mix),
                        int(side_rgb[2] * (1.0 - mix) + gb * 0.74 * mix),
                    )
                else:
                    # Subtle cool shadow depression when key glow is turned off
                    shade = 1.0 - 0.14 * press_k
                    top_rgb = tuple(int(c * shade) for c in top_rgb)

            # Dark switch-well shadow under keycap
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(28, 29, 30))
            painter.drawPolygon(QPolygonF([b_tl, b_tr, b_br, b_bl]))

            # 3D keycap front + left/right bevel skirts
            bevel_front = QPolygonF([t_bl, t_br, b_br, b_bl])
            bevel_left = QPolygonF([b_tl, t_tl, t_bl, b_bl])
            bevel_right = QPolygonF([t_tr, b_tr, b_br, t_br])
            side_col = QColor(*side_rgb)
            painter.setBrush(side_col)
            painter.drawPolygon(bevel_front)
            painter.setBrush(side_col.darker(108))
            painter.drawPolygon(bevel_left)
            painter.drawPolygon(bevel_right)

            # Crisp keycap top face
            top_poly = QPolygonF([t_tl, t_tr, t_br, t_bl])
            painter.setBrush(QColor(*top_rgb))
            painter.setPen(QPen(QColor(156, 154, 144, 175), 1.0))
            painter.drawPolygon(top_poly)

            # Subtle centered key legend mark (dot on 1u keys, short bar on wide modifiers, clean on spacebar)
            cx = (t_tl.x() + t_tr.x() + t_br.x() + t_bl.x()) * 0.25
            cy = (t_tl.y() + t_tr.y() + t_br.y() + t_bl.y()) * 0.25
            span_u = u1u - u0u
            mark_col = QColor(120, 118, 110, 175) if accent == "ivory" else QColor(125, 78, 16, 185)
            painter.setPen(Qt.NoPen)
            painter.setBrush(mark_col)
            if span_u < 1.1:
                painter.drawEllipse(QPointF(cx, cy), 1.6, 1.3)
            elif span_u < 3.5:
                painter.drawRoundedRect(QRectF(cx - 4.2, cy - 1.1, 8.4, 2.2), 1.0, 1.0)

        painter.restore()

    def draw_key_highlights(
        self,
        painter: QPainter,
        highlights: list[tuple[KeySpec, float]],
    ) -> None:
        """Legacy helper kept for API compatibility; highlights & depression are rendered inside draw_keyboard."""
        if not highlights:
            return
        painter.save()
        for spec, intensity in highlights:
            if intensity <= 0.02:
                continue
            poly = self.kb_key_polygon(spec)
            col = QColor(self.eye_green)
            col.setAlphaF(0.65 * intensity)
            painter.setBrush(col)
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(poly)
        painter.restore()

    def draw_mouse_click_glow(
        self,
        painter: QPainter,
        mouse_offset: QPointF,
        left_down: bool,
        right_down: bool,
    ) -> None:
        """Paint lime-green click highlight over left/right half of the white mouse."""
        if not (left_down or right_down):
            return
        mx, my, mw, mh = self.mouse_rect
        cx = mx + mw * 0.5 + mouse_offset.x()
        cy = my + mh * 0.5 + mouse_offset.y()
        rx = mw * 0.36
        ry = mh * 0.40

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(18.0)
        clip_path = QPainterPath()
        clip_path.addEllipse(QPointF(0, 0), rx, ry)
        painter.setClipPath(clip_path)

        glow = QColor(self.eye_green)
        glow.setAlpha(185)
        if left_down:
            painter.fillRect(QRectF(-rx, -ry, rx * 0.92, ry * 2.0), glow)
        if right_down:
            painter.fillRect(QRectF(rx * 0.08, -ry, rx * 0.92, ry * 2.0), glow)
        painter.restore()

    def draw_eye_pupils(
        self,
        painter: QPainter,
        dx_norm: float,
        dy_norm: float,
        mode: str = "typing",
    ) -> None:
        """Draw black oval pupils clipped cleanly inside the mode-specific tilted green eye ovals."""
        mode_meta = self.modes.get(mode, {})
        eyes = (
            mode_meta.get("left_eye", self.left_eye),
            mode_meta.get("right_eye", self.right_eye),
        )
        # Subtle pupil tilt matching each reference frame's head perspective (left_deg, right_deg)
        pupil_tilts = {
            "idle": (0.0, 0.0),
            "typing": (-10.0, 12.0),
            "mouse": (4.0, -8.0),
        }.get(mode, (0.0, 0.0))
        pupil_radii = {
            "idle": (13.8, 22.0),
            "typing": (14.5, 22.5),
            "mouse": (12.5, 20.5),
        }.get(mode, (14.5, 22.5))

        for idx, eye in enumerate(eyes):
            cx, cy = eye["cx"], eye["cy"]
            rx, ry = eye["rx"], eye["ry"]
            angle = float(eye.get("angle_deg", 0.0))

            painter.save()
            painter.translate(cx, cy)
            painter.rotate(angle)

            clip = QPainterPath()
            clip.addEllipse(QPointF(0.0, 0.0), rx * 0.92, ry * 0.92)
            painter.setClipPath(clip)

            # Reset rotation to world axes so dx_norm/dy_norm shifts horizontally/vertically as expected
            painter.rotate(-angle)
            bbox_w = float(eye.get("bbox_w", rx * 2.0))
            bbox_h = float(eye.get("bbox_h", ry * 2.0))
            world_dx = dx_norm * (bbox_w * 0.24)
            world_dy = dy_norm * (bbox_h * 0.26)
            painter.translate(world_dx, world_dy)
            painter.rotate(pupil_tilts[idx])

            painter.setBrush(QColor(18, 18, 18))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(0.0, 0.0), pupil_radii[0], pupil_radii[1])
            painter.restore()

    def draw_head_features(
        self,
        painter: QPainter,
        mode: str,
        head_turn_x: float,
        head_turn_y: float,
        eye_dx: float,
        eye_dy: float,
        eye_openness: float = 1.0,
    ) -> None:
        """Render 3D-turning green eyes, clipped gaze pupils, continuous eyelid blink/squint, and whiskers."""
        lerp = lambda a, b, k: a + (b - a) * k
        t = max(-1.0, min(1.0, head_turn_x))
        u = (t + 1.0) * 0.5  # 0.0 = extreme left, 0.5 = center, 1.0 = extreme right

        if mode == "mouse":
            shift_x = u * 74.0
            shift_y = head_turn_y * 13.5
            lx = 164.8 + shift_x
            ly = lerp(183.8, 194.5, u) + shift_y
            rx_c = 282.2 + shift_x
            ry_c = lerp(195.8, 184.5, u) + shift_y
            if u <= 0.5:
                k = u * 2.0
                lw, lh, l_tilt = lerp(67.0, 82.0, k), 76.0, lerp(3.0, -5.0, k)
                rw, rh, r_tilt = lerp(91.0, 82.0, k), 76.0, lerp(-14.0, 4.0, k)
            else:
                k = (u - 0.5) * 2.0
                lw, lh, l_tilt = lerp(82.0, 91.0, k), 76.0, lerp(-5.0, 12.0, k)
                rw, rh, r_tilt = lerp(82.0, 67.0, k), 76.0, lerp(4.0, -3.0, k)
            specs = [
                (lx, ly, lw * 0.5, lh * 0.5, l_tilt, lerp(11.5, 13.5, u), 20.5, lerp(4.0, -8.0, u)),
                (rx_c, ry_c, rw * 0.5, rh * 0.5, r_tilt, lerp(13.5, 11.5, u), 20.5, lerp(4.0, -8.0, u)),
            ]
            l_anchor_x = lx - lerp(19.0, 21.0, u)
            l_anchor_y = ly + 66.0
            l_len = lerp(66.0, 56.0, u)
            r_anchor_x = rx_c + lerp(6.0, 14.0, u)
            r_anchor_y = ry_c + 70.0
            r_len = lerp(56.0, 66.0, u)
            w_angles = [(2.0, 0.0, -5.5), (12.0, 14.0, -5.8), (24.0, 28.0, -6.2)]
        elif mode == "typing":
            # Turn across the typing head silhouette: u=0 looks clearly left (J/K/L/Backspace),
            # u=0.5 centered forward-down, u=1.0 matches calibrated 4.png right-gaze look.
            shift_y = head_turn_y * 6.5
            lx = lerp(387.0, 443.3, u)
            ly = lerp(242.6, 259.0, u) + shift_y
            rx_c = lerp(506.0, 570.3, u)
            ry_c = lerp(259.0, 242.6, u) + shift_y
            if u <= 0.5:
                k = u * 2.0
                lrx, lry, l_tilt = lerp(33.5, 37.0, k), lerp(45.5, 48.0, k), lerp(8.0, 2.0, k)
                rrx, rry, r_tilt = lerp(38.0, 37.0, k), lerp(49.5, 48.0, k), lerp(-18.0, -2.0, k)
            else:
                k = (u - 0.5) * 2.0
                lrx, lry, l_tilt = lerp(37.0, 38.0, k), lerp(48.0, 49.5, k), lerp(2.0, 16.0, k)
                rrx, rry, r_tilt = lerp(37.0, 34.5, k), lerp(48.0, 45.8, k), lerp(-2.0, -14.0, k)
            specs = [
                (lx, ly, lrx, lry, l_tilt, lerp(13.0, 14.8, u), 22.0, lerp(-4.0, -12.0, u)),
                (rx_c, ry_c, rrx, rry, r_tilt, lerp(14.8, 13.0, u), 22.0, lerp(6.0, 12.0, u)),
            ]
            l_anchor_x = lx - lerp(12.0, 16.0, u)
            l_anchor_y = ly + 71.0
            l_len = lerp(60.0, 52.0, u)
            r_anchor_x = rx_c + lerp(18.0, 24.0, u)
            r_anchor_y = ry_c + 68.0
            r_len = lerp(52.0, 60.0, u)
            w_angles = [(-2.0, 0.0, -5.5), (9.0, 13.0, -5.8), (21.0, 26.0, -6.2)]
        else:
            # Upright idle pose centered around frame 1 (423.8, 182.2) & (553.4, 187.1)
            shift_x = t * 18.0
            # Emphasize 3D front-view face pitch downward along curved skull during head nodding ("一低一抬")
            shift_y = head_turn_y * 14.5
            pitch_dn = max(0.0, head_turn_y)
            lx = 423.8 + shift_x
            ly = 182.2 + shift_y - t * 2.0
            rx_c = 553.4 + shift_x
            ry_c = 187.1 + shift_y + t * 2.0
            lrx, lry, l_tilt = 37.3 * (1.0 + 0.06 * t), 44.9, 5.0 - t * 6.0
            rrx, rry, r_tilt = 37.2 * (1.0 - 0.06 * t), 44.7, -3.0 + t * 6.0
            specs = [
                (lx, ly, lrx, lry, l_tilt, 13.8, 22.0, 0.0),
                (rx_c, ry_c, rrx, rry, r_tilt, 13.8, 22.0, 0.0),
            ]
            l_anchor_x = lx - 20.0
            l_anchor_y = ly + 66.0 + pitch_dn * 2.0
            l_len = lerp(58.0, 50.0, u)
            r_anchor_x = rx_c + 16.0
            r_anchor_y = ry_c + 68.0 + pitch_dn * 2.0
            r_len = lerp(50.0, 58.0, u)
            w_angles = [
                (2.0 + pitch_dn * 3.0, 0.0, -5.5),
                (12.0 + pitch_dn * 3.5, 14.0, -5.8),
                (24.0 + pitch_dn * 4.0, 28.0, -6.2),
            ]

        # Continuous eyelid opening/closing animation (video 5-8s smooth squash & line fade)
        open_k = max(0.0, min(1.0, float(eye_openness)))
        open_ease = 0.4 * open_k + 0.6 * (open_k * open_k * (3.0 - 2.0 * open_k))

        if open_k > 0.14:
            ery_factor = 0.07 + 0.93 * open_ease
            pupil_alpha = min(1.0, max(0.0, (open_k - 0.17) / 0.28))
            for cx, cy, erx, ery, tilt, prx, pry, ptilt in specs:
                cur_ery = max(3.0, ery * ery_factor)
                # Upper eyelid closes downward from top -> bottom, so remaining eye aperture shifts downward
                drop_y = (1.0 - open_ease) * (ery * 0.62)
                painter.save()
                painter.translate(cx, cy + drop_y)
                painter.rotate(tilt)
                painter.setBrush(self.eye_green)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(0.0, 0.0), erx, cur_ery)

                if pupil_alpha > 0.02:
                    clip = QPainterPath()
                    clip.addEllipse(QPointF(0.0, 0.0), erx * 0.92, cur_ery * 0.92)
                    painter.setClipPath(clip)

                    painter.rotate(-tilt)
                    px = eye_dx * (erx * 0.56)
                    py = eye_dy * (cur_ery * 0.54)
                    painter.translate(px, py)
                    painter.rotate(ptilt)
                    painter.setOpacity(pupil_alpha)
                    painter.setBrush(QColor(18, 18, 18))
                    painter.drawEllipse(
                        QPointF(0.0, 0.0),
                        prx,
                        pry * min(1.0, 0.45 + 0.55 * open_ease),
                    )
                painter.restore()

        if open_k < 0.26:
            # Sleek crescent squint with softly rounded ends (avoiding overly sharp needle tips)
            sq_alpha = 1.0 if open_k <= 0.14 else (0.26 - open_k) / 0.12
            thickness = lerp(8.8, 10.6, min(1.0, open_k / 0.26))
            painter.save()
            painter.setOpacity(sq_alpha)
            for idx, (cx, cy, erx, ery, _ang, _pw, _ph, _pt) in enumerate(specs):
                span = erx * 0.98
                pitch_curve = max(0.0, head_turn_y) * 2.8 if mode == "idle" else 0.0
                y_l = -1.4 if idx == 0 else -1.7
                y_r = -1.7 if idx == 0 else -1.4
                up_c1_y = 4.4 + pitch_curve
                up_c2_y = 4.4 + pitch_curve
                dn_c1_y = 4.4 + thickness * 1.24 + pitch_curve
                dn_c2_y = 4.4 + thickness * 1.24 + pitch_curve
                sq_tilt = (0.4 if idx == 0 else -0.4) if mode == "idle" else lerp(1.8, -1.8, u)

                # Inner crescent leaf + soft rounded centerline stroke so both tips end gently rounded
                leaf = QPainterPath()
                leaf.moveTo(-span, y_l)
                leaf.cubicTo(-span * 0.36, up_c1_y, span * 0.36, up_c2_y, span, y_r)
                leaf.cubicTo(span * 0.36, dn_c1_y, -span * 0.36, dn_c2_y, -span, y_l)
                leaf.closeSubpath()

                mid_c1_y = (up_c1_y + dn_c1_y) * 0.45
                mid_c2_y = (up_c2_y + dn_c2_y) * 0.45
                tip_spine = QPainterPath()
                tip_spine.moveTo(-span, y_l)
                tip_spine.cubicTo(-span * 0.36, mid_c1_y, span * 0.36, mid_c2_y, span, y_r)

                tip_pen = QPen(self.eye_green, 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

                painter.save()
                painter.translate(cx, cy + ery * 0.56)
                painter.rotate(sq_tilt)
                painter.setPen(Qt.NoPen)
                painter.setBrush(self.eye_green)
                painter.drawPath(leaf)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(tip_pen)
                painter.drawPath(tip_spine)
                painter.restore()
            painter.restore()

        painter.save()
        w_pen = QPen(QColor(250, 250, 252), 3.3)
        w_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(w_pen)
        painter.setBrush(Qt.NoBrush)
        for i, (deg_down, y_off, bend_y) in enumerate(w_angles):
            rad = math.radians(deg_down)
            ux_w = math.cos(rad)
            uy_w = math.sin(rad)

            lx0, ly0 = l_anchor_x + i * 2.0, l_anchor_y + y_off
            lx1, ly1 = lx0 - ux_w * l_len, ly0 + uy_w * l_len
            lp = QPainterPath()
            lp.moveTo(lx0, ly0)
            lp.quadTo((lx0 + lx1) * 0.5, (ly0 + ly1) * 0.5 + bend_y, lx1, ly1)
            painter.drawPath(lp)

            rx0, ry0 = r_anchor_x - i * 1.5, r_anchor_y + y_off
            rx1, ry1 = rx0 + ux_w * r_len, ry0 + uy_w * r_len
            rp = QPainterPath()
            rp.moveTo(rx0, ry0)
            rp.quadTo((rx0 + rx1) * 0.5, (ry0 + ry1) * 0.5 + bend_y, rx1, ry1)
            painter.drawPath(rp)
        painter.restore()

    @staticmethod
    def draw_tapered_stroke(
        painter: QPainter,
        points: list[QPointF],
        max_half_w: float = 1.65,
        start_taper: bool = True,
        end_taper: bool = True,
        taper_margin: float = 0.5,
        color: QColor | None = None,
    ) -> None:
        """Draw a smooth anti-aliased variable-width outline that tapers delicately toward ends."""
        n = len(points)
        if n < 2:
            return
        left_side: list[QPointF] = []
        right_side: list[QPointF] = []
        margin = max(0.05, min(0.5, taper_margin))
        for i, p in enumerate(points):
            t = i / (n - 1)
            prev_p = points[max(0, i - 1)]
            next_p = points[min(n - 1, i + 1)]
            tx = next_p.x() - prev_p.x()
            ty = next_p.y() - prev_p.y()
            tl = max(1e-4, math.hypot(tx, ty))
            nx, ny = -ty / tl, tx / tl

            if margin < 0.49:
                # Taper smoothly near ends over `margin` fraction while keeping middle section steady
                s_k = min(1.0, t / margin) if start_taper else 1.0
                e_k = min(1.0, (1.0 - t) / margin) if end_taper else 1.0
                env = (s_k ** 0.72) * (e_k ** 0.72)
                w = max_half_w * env
            elif start_taper and end_taper:
                w = max_half_w * (math.sin(math.pi * t) ** 0.72)
            elif end_taper:
                w = max_half_w * max(0.08, (1.0 - t) ** 0.65)
            elif start_taper:
                w = max_half_w * max(0.08, t ** 0.65)
            else:
                w = max_half_w
            left_side.append(QPointF(p.x() + nx * w, p.y() + ny * w))
            right_side.append(QPointF(p.x() - nx * w, p.y() - ny * w))

        poly = QPolygonF(left_side + list(reversed(right_side)))
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color if color is not None else QColor(250, 250, 252))
        painter.drawPolygon(poly)
        painter.restore()

    def draw_mouse_head_features(
        self,
        painter: QPainter,
        head_turn_x: float,
        head_turn_y: float,
        eye_dx: float,
        eye_dy: float,
        squint: bool | float,
    ) -> None:
        """Compatibility wrapper delegating to draw_head_features for mouse silhouette."""
        openness = float(0.0 if squint is True else (1.0 if squint is False else squint))
        self.draw_head_features(painter, "mouse", head_turn_x, head_turn_y, eye_dx, eye_dy, openness)

    @classmethod
    def draw_curled_paw(cls, painter: QPainter, side: str, alpha: float = 1.0) -> None:
        """Draw the resting curled paw tapered white outline on the cat's chest (matching 4.png)."""
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, alpha)))
        path = QPainterPath()
        if side == "left":
            path.moveTo(318, 535)
            path.cubicTo(314, 578, 376, 588, 386, 540)
        else:
            path.moveTo(576, 586)
            path.cubicTo(616, 588, 628, 558, 616, 538)
        pts = [path.pointAtPercent(i / 18.0) for i in range(19)]
        cls.draw_tapered_stroke(painter, pts, max_half_w=2.0, start_taper=True, end_taper=True)
        painter.restore()

    @classmethod
    def draw_idle_front_paws(cls, painter: QPainter, torso_point_fn, alpha: float = 1.0) -> None:
        """Draw unified idle front arms + plump circular paws using the same smooth wrist-to-paw geometry as draw_extended_arm."""
        if alpha <= 0.01:
            return
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, alpha)))
        # Each spec: (shoulder_pt, target_pt, width_start, width_end, paw_rx, paw_ry)
        arm_specs = [
            (QPointF(405.0, 488.0), QPointF(408.0, 690.5), 37.0, 23.0, 33.5, 29.0),
            (QPointF(532.0, 495.0), QPointF(529.0, 691.5), 37.0, 23.0, 33.5, 29.0),
        ]
        fur = QColor(24, 24, 23)
        for sh_local, tg_local, w_start, w_end, paw_rx, paw_ry in arm_specs:
            sh = torso_point_fn(sh_local)
            tg = torso_point_fn(tg_local)
            sx, sy = sh.x(), sh.y()
            tx, ty = tg.x(), tg.y()
            dx, dy = tx - sx, ty - sy
            dist = max(1e-3, math.hypot(dx, dy))

            samples = 18
            left_edge: list[QPointF] = []
            right_edge: list[QPointF] = []
            for i in range(samples + 1):
                t = i / samples
                px = sx + dx * t
                py = sy + dy * t
                hw = w_start * (1.0 - t) + w_end * t
                left_edge.append(QPointF(px - hw, py))
                right_edge.append(QPointF(px + hw, py))

            arm_poly = QPolygonF(left_edge + list(reversed(right_edge)))
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(fur)
            painter.drawPolygon(arm_poly)
            painter.drawEllipse(QPointF(tx, ty), paw_rx, paw_ry)
            painter.restore()

            # Circular paw arc wrapping around the round paw pad (from 206 deg through 90 deg bottom to -26 deg)
            a_start = math.radians(206.0)
            a_end = math.radians(-26.0)
            paw_arc: list[QPointF] = []
            arc_steps = 22
            for j in range(arc_steps + 1):
                uj = j / arc_steps
                a = a_start + (a_end - a_start) * uj
                paw_arc.append(QPointF(tx + math.cos(a) * paw_rx, ty + math.sin(a) * paw_ry))

            def _quad_pts(p0: QPointF, p1: QPointF, p2: QPointF, n: int = 6) -> list[QPointF]:
                out: list[QPointF] = []
                for k in range(1, n):
                    tk = k / n
                    mt = 1.0 - tk
                    out.append(
                        QPointF(
                            mt * mt * p0.x() + 2 * mt * tk * p1.x() + tk * tk * p2.x(),
                            mt * mt * p0.y() + 2 * mt * tk * p1.y() + tk * tk * p2.y(),
                        )
                    )
                return out

            start_idx = 4
            wrist_idx = samples - 3
            l_arm = left_edge[start_idx : wrist_idx - 1]
            l_ctrl = QPointF(left_edge[wrist_idx].x() - 0.5, paw_arc[1].y() - 9.0)
            l_blend = _quad_pts(left_edge[wrist_idx - 2], l_ctrl, paw_arc[1])
            r_ctrl = QPointF(right_edge[wrist_idx].x() + 0.5, paw_arc[-2].y() - 9.0)
            r_blend = _quad_pts(paw_arc[-2], r_ctrl, right_edge[wrist_idx - 2])
            r_arm = list(reversed(right_edge[start_idx : wrist_idx - 1]))

            full_pts = l_arm + l_blend + paw_arc[1:-1] + r_blend + r_arm
            cls.draw_tapered_stroke(
                painter,
                full_pts,
                max_half_w=1.85,
                start_taper=True,
                end_taper=True,
                taper_margin=0.12,
            )
        painter.restore()

    @classmethod
    def draw_licking_tongue(
        cls,
        painter: QPainter,
        head_point_fn,
        groom_ext: float,
        lick_phase: float,
        head_turn_y: float = 0.0,
    ) -> None:
        """Draw the coral-pink cat tongue hugging and sweeping smoothly around the curved back contour of the raised paw."""
        t_alpha = min(1.0, max(0.0, (groom_ext - 0.15) / 0.55))
        if t_alpha <= 0.01:
            return

        # Asymmetric swipe wave: tongue starts tucked behind top crest, wraps & sweeps around dorsal paw rim, then retracts
        lick_wave = (0.5 - 0.5 * math.cos(lick_phase)) ** 0.85
        g_k = min(1.0, groom_ext * 1.2)
        wrap_arc = lick_wave * g_k
        m_dy = head_turn_y * 11.5

        def mp(x: float, y: float) -> QPointF:
            return head_point_fn(QPointF(x, y + m_dy))

        # Compact, dainty pink tongue hugging clockwise along the dorsal paw curve without ballooning
        p_mid_top = mp(479.0, 275.0)
        p_l_top = mp(465.0, 269.0)
        p_l_wrap = mp(454.0, 284.0 + 10.0 * wrap_arc)
        p_l_base = mp(462.0, 302.0 + 16.0 * wrap_arc)
        p_tip = mp(484.0 + 8.0 * wrap_arc, 300.0 + 23.0 * wrap_arc)
        p_r_mid = mp(497.0 + 8.0 * wrap_arc, 288.0 + 17.0 * wrap_arc)
        p_r_flare = mp(500.0 + 5.0 * wrap_arc, 279.0 + 6.0 * wrap_arc)
        p_r_top = mp(492.0, 269.0)

        tongue = QPainterPath()
        tongue.moveTo(p_mid_top)
        tongue.cubicTo(
            mp(474.0, 273.0),
            mp(469.0, 270.0),
            p_l_top,
        )
        tongue.quadTo(p_l_wrap, p_l_base)
        tongue.cubicTo(
            mp(467.0 + 3.0 * wrap_arc, 304.0 + 20.0 * wrap_arc),
            mp(477.0 + 6.0 * wrap_arc, 304.0 + 24.0 * wrap_arc),
            p_tip,
        )
        tongue.cubicTo(
            mp(495.0 + 10.0 * wrap_arc, 296.0 + 22.0 * wrap_arc),
            mp(501.0 + 9.0 * wrap_arc, 292.0 + 18.0 * wrap_arc),
            p_r_mid,
        )
        tongue.quadTo(p_r_flare, p_r_top)
        tongue.cubicTo(
            mp(487.0, 270.0),
            mp(483.0, 273.0),
            p_mid_top,
        )
        tongue.closeSubpath()

        painter.save()
        painter.setOpacity(t_alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(216, 121, 128))
        painter.drawPath(tongue)
        painter.restore()

    @classmethod
    def draw_groom_paws(
        cls,
        painter: QPainter,
        torso_point_fn,
        groom_ext: float,
        lick_phase: float,
    ) -> None:
        """Draw the raised licking paw at the mouth and curled resting tummy paw during idle grooming."""
        g_alpha = min(1.0, max(0.0, (groom_ext - 0.12) / 0.55))
        if g_alpha <= 0.01:
            return

        g_ease = 1.0 - (1.0 - max(0.0, min(1.0, groom_ext))) ** 2
        lick_wave = (0.5 - 0.5 * math.cos(lick_phase)) ** 0.85
        lick_dx = 3.5 * math.sin(lick_phase) * g_ease
        lick_dy = (-5.5 * lick_wave) * g_ease
        lift_dx = (1.0 - g_ease) * -22.0 + lick_dx
        lift_dy = (1.0 - g_ease) * 145.0 + lick_dy

        painter.save()
        painter.setOpacity(g_alpha)

        # 1. Right tummy curled resting paw (viewer's right): open U-shaped tapered white contour
        rp_path = QPainterPath()
        rp_path.moveTo(torso_point_fn(QPointF(528.0, 488.0 + (1.0 - g_ease) * 28.0)))
        rp_path.cubicTo(
            torso_point_fn(QPointF(534.0, 550.0 + (1.0 - g_ease) * 24.0)),
            torso_point_fn(QPointF(620.0, 550.0 + (1.0 - g_ease) * 24.0)),
            torso_point_fn(QPointF(616.0, 482.0 + (1.0 - g_ease) * 28.0)),
        )
        rp_pts = [rp_path.pointAtPercent(i / 24.0) for i in range(25)]
        cls.draw_tapered_stroke(
            painter,
            rp_pts,
            max_half_w=2.0,
            start_taper=True,
            end_taper=True,
            taper_margin=0.14,
        )

        # 2. Raised licking paw (viewer's left): crisp unbroken white outline hugging the mouth/tongue arc
        def gp(x: float, y: float) -> QPointF:
            blend = max(0.25, min(1.0, (445.0 - y) / 145.0))
            return torso_point_fn(QPointF(x + lift_dx * blend, y + lift_dy * blend))

        arm_hook = QPainterPath()
        arm_hook.moveTo(gp(358.0, 392.0))
        arm_hook.cubicTo(gp(378.0, 326.0), gp(420.0, 290.0), gp(458.0, 298.0))
        arm_hook.cubicTo(gp(492.0, 307.0), gp(493.0, 349.0), gp(458.0, 353.0))
        arm_hook.cubicTo(gp(445.0, 354.0), gp(438.0, 345.0), gp(433.0, 354.0))
        arm_hook.cubicTo(gp(420.0, 376.0), gp(410.0, 405.0), gp(406.0, 434.0))

        # Charcoal black fill matching cat fur overlaps tongue base cleanly
        paw_fill = QPainterPath(arm_hook)
        paw_fill.lineTo(gp(366.0, 436.0))
        paw_fill.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(24, 24, 23))
        painter.drawPath(paw_fill)

        hook_pts = [arm_hook.pointAtPercent(i / 36.0) for i in range(37)]
        cls.draw_tapered_stroke(
            painter,
            hook_pts,
            max_half_w=1.95,
            start_taper=True,
            end_taper=True,
            taper_margin=0.14,
        )
        painter.restore()

    @classmethod
    def draw_extended_arm(
        cls,
        painter: QPainter,
        side: str,
        shoulder: QPointF,
        target: QPointF,
        outer_line: bool = True,
        paw_contact_offset_y: float = -6.0,
        fur_color: QColor | None = None,
        width_start: float = 41.0,
        width_end: float = 22.0,
        paw_rx: float = 29.0,
        paw_ry: float = 25.0,
    ) -> None:
        """Draw a tapered charcoal-black cat arm whose paw pad stamps onto `target` with continuous arm-to-paw white outline."""
        sx, sy = shoulder.x(), shoulder.y()
        tx, ty = target.x(), target.y() + paw_contact_offset_y
        dx, dy = tx - sx, ty - sy
        dist = math.hypot(dx, dy)
        if dist < 1e-3:
            return

        ux, uy = dx / dist, dy / dist
        nx, ny = -uy, ux
        outward = -1.0 if side == "left" else 1.0
        if nx * outward < 0:
            nx, ny = -nx, -ny
        bend = max(10.0, min(32.0, dist * 0.12))
        ctrl = QPointF((sx + tx) * 0.5 + nx * bend, (sy + ty) * 0.5 + ny * bend)

        samples = 18
        pts: list[QPointF] = []
        norms: list[QPointF] = []
        for i in range(samples + 1):
            t = i / samples
            mt = 1.0 - t
            px = mt * mt * sx + 2.0 * mt * t * ctrl.x() + t * t * tx
            py = mt * mt * sy + 2.0 * mt * t * ctrl.y() + t * t * ty
            pts.append(QPointF(px, py))

            vx = 2.0 * mt * (ctrl.x() - sx) + 2.0 * t * (tx - ctrl.x())
            vy = 2.0 * mt * (ctrl.y() - sy) + 2.0 * t * (ty - ctrl.y())
            vl = max(1e-4, math.hypot(vx, vy))
            n = QPointF(-vy / vl, vx / vl)
            if n.x() * outward < 0:
                n = QPointF(-n.x(), -n.y())
            norms.append(n)

        outer_edge: list[QPointF] = []
        inner_edge: list[QPointF] = []
        for i in range(samples + 1):
            t = i / samples
            half_w = width_start * (1.0 - t) + width_end * t
            p, n = pts[i], norms[i]
            outer_edge.append(QPointF(p.x() + n.x() * half_w, p.y() + n.y() * half_w))
            inner_edge.append(QPointF(p.x() - n.x() * half_w, p.y() - n.y() * half_w))

        arm_poly = QPolygonF(outer_edge + list(reversed(inner_edge)))

        painter.save()
        fill_fur = fur_color if fur_color is not None else QColor(25, 25, 25)
        painter.setBrush(fill_fur)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(shoulder, width_start, width_start)
        painter.drawPolygon(arm_poly)
        painter.drawEllipse(QPointF(tx, ty), paw_rx, paw_ry)

        # Build ONE continuous stroke running down arm inner side, gliding cleanly into the rounded paw, and up outer side!
        start_idx = 5 if outer_line else 6
        wrist_idx = samples - 3
        in_p = inner_edge[wrist_idx]
        out_p = outer_edge[wrist_idx]
        fwd = math.atan2(dy, dx)
        ang_in = math.atan2(in_p.y() - ty, in_p.x() - tx)
        ang_out = math.atan2(out_p.y() - ty, out_p.x() - tx)

        # Wrap slightly tighter (~+-2.1 rad) so wrist edges glide tangentially into the rounded paw contour
        d_in = math.atan2(math.sin(ang_in - fwd), math.cos(ang_in - fwd))
        d_out = math.atan2(math.sin(ang_out - fwd), math.cos(ang_out - fwd))
        a_start = fwd + d_in * 0.90
        a_end = fwd + d_out * 0.90
        paw_arc: list[QPointF] = []
        arc_steps = 18
        for j in range(arc_steps + 1):
            u_j = j / arc_steps
            a = a_start + (a_end - a_start) * u_j
            paw_arc.append(QPointF(tx + math.cos(a) * paw_rx, ty + math.sin(a) * paw_ry))

        # Insert smooth quadratic transition points between wrist edges and paw arc (eliminates wrist-to-paw corner kink)
        def _quad_pts(p0: QPointF, p1: QPointF, p2: QPointF, n: int = 5) -> list[QPointF]:
            out: list[QPointF] = []
            for k in range(1, n):
                t = k / n
                mt = 1.0 - t
                out.append(
                    QPointF(
                        mt * mt * p0.x() + 2 * mt * t * p1.x() + t * t * p2.x(),
                        mt * mt * p0.y() + 2 * mt * t * p1.y() + t * t * p2.y(),
                    )
                )
            return out

        in_arm = inner_edge[start_idx : wrist_idx - 1]
        in_blend = _quad_pts(inner_edge[wrist_idx - 2], inner_edge[-1], paw_arc[1])
        out_blend = _quad_pts(paw_arc[-2], outer_edge[-1], outer_edge[wrist_idx - 2])
        out_arm = list(reversed(outer_edge[start_idx : wrist_idx - 1]))

        if outer_line:
            full_pts = in_arm + in_blend + paw_arc[1:-1] + out_blend + out_arm
            cls.draw_tapered_stroke(
                painter,
                full_pts,
                max_half_w=1.62,
                start_taper=True,
                end_taper=True,
                taper_margin=0.14,
            )
        else:
            half_pts = in_arm + in_blend + paw_arc[1 : arc_steps // 2 + 3]
            cls.draw_tapered_stroke(
                painter,
                half_pts,
                max_half_w=1.62,
                start_taper=True,
                end_taper=True,
                taper_margin=0.18,
            )
        painter.restore()
