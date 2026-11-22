#!/usr/bin/env python3
"""Clean stray UI badges, remove white cutout halos, and align all 7 cat frames."""

from __future__ import annotations

import os
import cv2
import numpy as np
from PIL import Image


def load_rgba(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA"), dtype=np.uint8)


def save_rgba(arr: np.ndarray, path: str) -> None:
    Image.fromarray(arr, mode="RGBA").save(path)


def inpaint_dark_fur(arr: np.ndarray, mask: np.ndarray, seed: int = 42) -> None:
    """Fill `mask` smoothly using ONLY surrounding dark fur pixels (never white lines)."""
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return

    # Valid dark fur pixels strictly outside mask
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    dark_valid = ((~mask) & (a > 220) & (r < 50) & (g < 50) & (b < 50)).astype(
        np.float32
    )
    rgb = arr[:, :, :3].astype(np.float32)

    # Normalized Gaussian convolution over dark_valid pixels to get smooth local gradient
    num = cv2.GaussianBlur(rgb * dark_valid[:, :, None], (0, 0), sigmaX=12.0)
    den = cv2.GaussianBlur(dark_valid, (0, 0), sigmaX=12.0)

    # Fallback global median dark fur if a region has very sparse dark neighbors
    dark_pts = arr[dark_valid > 0.5]
    fallback = (
        np.median(dark_pts[:, :3], axis=0).astype(np.float32)
        if len(dark_pts)
        else np.array([23.0, 23.0, 23.0], dtype=np.float32)
    )

    filled = np.where(
        den[:, :, None] > 1e-4,
        num / np.maximum(den[:, :, None], 1e-4),
        fallback[None, None, :],
    )

    rng = np.random.default_rng(seed)
    noise = rng.integers(-1, 2, size=(len(ys), 3)).astype(np.float32)
    arr[ys, xs, :3] = np.clip(filled[ys, xs] + noise, 0, 255).astype(np.uint8)
    arr[ys, xs, 3] = 255


def detect_white_box_in_roi(
    arr: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    luma_thresh: int = 195,
    dilate_px: int = 3,
    min_area: int = 300,
) -> np.ndarray:
    """Detect bright rounded-rect badge inside an ROI and dilate slightly."""
    roi = arr[y0:y1, x0:x1]
    luma = (
        0.299 * roi[:, :, 0].astype(np.float32)
        + 0.587 * roi[:, :, 1].astype(np.float32)
        + 0.114 * roi[:, :, 2].astype(np.float32)
    )
    cand = ((roi[:, :, 3] > 40) & (luma > luma_thresh)).astype(np.uint8)
    close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    closed = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, close_k)
    num, lbl, stats, _ = cv2.connectedComponentsWithStats(closed)
    keep = np.zeros_like(closed, dtype=bool)
    for k in range(1, num):
        if stats[k, 4] >= min_area:
            keep |= lbl == k
    if dilate_px > 0 and np.any(keep):
        dk = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1)
        )
        keep = cv2.dilate(keep.astype(np.uint8), dk, iterations=1) > 0
    full = np.zeros((arr.shape[0], arr.shape[1]), dtype=bool)
    full[y0:y1, x0:x1] = keep
    return full


def remove_tail_s_badge(arr: np.ndarray) -> np.ndarray:
    """Erase the [S] keycap badge tucked under the tail in frames 1, 6, 7."""
    out = arr.copy()
    x0, y0, x1, y1 = 690, 605, 860, 765
    roi = out[y0:y1, x0:x1]
    white = (
        (roi[:, :, 3] > 80)
        & (roi[:, :, 0] > 180)
        & (roi[:, :, 1] > 180)
        & (roi[:, :, 2] > 180)
    )
    # Keep largest white component ([S] interior)
    num, lbl, stats, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8))
    if num <= 1:
        return out
    best = max(range(1, num), key=lambda k: stats[k, 4])
    if stats[best, 4] < 500:
        return out
    white_box = (lbl == best).astype(np.uint8)
    # Close inner black 'S' letter so white_box is a solid rounded rectangle
    white_box = cv2.morphologyEx(
        white_box, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    )
    # Dilate by 11px to capture the entire black border of [S] cleanly without touching the hip
    badge_local = cv2.dilate(
        white_box, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (23, 23))
    ) > 0

    wy, wx = np.where(white_box > 0)
    w_min_x, w_max_x = x0 + int(wx.min()), x0 + int(wx.max())
    w_min_y, w_max_y = y0 + int(wy.min()), y0 + int(wy.max())

    # Sample clean bottom edge of tail just left & right of the outer border (w_min_x-10 .. w_max_x+10)
    def sample_tail_bottom(x_range, scan_up_margin: int):
        pts_x, pts_y = [], []
        scan_top = max(0, w_min_y - scan_up_margin)
        scan_bot = min(out.shape[0], w_max_y + 15)
        for x in x_range:
            if not (0 <= x < out.shape[1]):
                continue
            col_a = out[scan_top:scan_bot, x, 3]
            opaque = np.where(col_a > 128)[0]
            if len(opaque) == 0:
                continue
            top_idx = int(opaque[0])
            bot_idx = top_idx
            while bot_idx + 1 < len(col_a) and col_a[bot_idx + 1] > 128:
                bot_idx += 1
            if 18 <= (bot_idx - top_idx) <= 98:
                pts_x.append(float(x))
                pts_y.append(float(scan_top + bot_idx))
        return pts_x, pts_y

    lx, ly = sample_tail_bottom(range(w_min_x - 36, w_min_x - 9), scan_up_margin=65)
    rx, ry = sample_tail_bottom(range(w_max_x + 12, w_max_x + 54), scan_up_margin=160)

    # Fit tangent-matched Hermite spline using exact smoothed endpoint heights so zero step occurs
    p_left = np.poly1d(np.polyfit(lx[-12:], ly[-12:], deg=1))
    p_right = np.poly1d(np.polyfit(rx[:14], ry[:14], deg=1))
    xL, xR = float(lx[-1]), float(rx[0])
    yL = float(ly[-1])
    yR = float(ry[0])
    mL = float(p_left.coeffs[0])
    mR = float(p_right.coeffs[0])
    dx = max(1.0, xR - xL)

    def tail_bottom_y(x_vals: np.ndarray) -> np.ndarray:
        t = np.clip((x_vals - xL) / dx, 0.0, 1.0)
        h00 = 2 * t**3 - 3 * t**2 + 1
        h10 = t**3 - 2 * t**2 + t
        h01 = -2 * t**3 + 3 * t**2
        h11 = t**3 - t**2
        return h00 * yL + h10 * (dx * mL) + h01 * yR + h11 * (dx * mR)

    # Sample clean tail dark fur directly above badge
    tail_sample = out[max(0, w_min_y - 55) : max(1, w_min_y - 18), w_min_x : w_max_x]
    dark_px = tail_sample[
        (tail_sample[:, :, 3] > 230)
        & (tail_sample[:, :, 0] < 45)
        & (tail_sample[:, :, 1] < 45)
    ]
    fur = (
        np.median(dark_px, axis=0).astype(np.uint8)
        if len(dark_px)
        else np.array([18, 18, 18, 255], dtype=np.uint8)
    )
    fur[3] = 255

    # Edit entire [S] badge footprint (from badge top down): fill fur above curve_y, transparent below
    yy, xx = np.mgrid[y0:y1, x0:x1]
    curve_y = tail_bottom_y(xx.astype(np.float64))
    dist = curve_y - yy
    alpha = np.clip((dist + 0.75) / 1.5, 0.0, 1.0)
    edit_zone = (badge_local | (yy >= w_min_y)) & (yy >= (w_min_y - 12)) & (xx >= xL) & (xx <= xR)

    roi_box = out[y0:y1, x0:x1]
    for c in range(3):
        roi_box[:, :, c] = np.where(edit_zone, fur[c], roi_box[:, :, c])
    roi_box[:, :, 3] = np.where(
        edit_zone, (alpha * 255.0).astype(np.uint8), roi_box[:, :, 3]
    )
    out[y0:y1, x0:x1] = roi_box
    return out


def draw_smooth_polyline(
    arr: np.ndarray, pts: np.ndarray, color=(252, 252, 252, 255), thickness: int = 3
) -> None:
    """Draw an anti-aliased white line onto an RGBA image."""
    h, w = arr.shape[:2]
    layer = np.zeros((h, w), dtype=np.uint8)
    cv2.polylines(layer, [pts.astype(np.int32)], False, 255, thickness, cv2.LINE_AA)
    a = layer.astype(np.float32) / 255.0
    for c in range(3):
        arr[:, :, c] = np.clip(
            arr[:, :, c].astype(np.float32) * (1.0 - a) + color[c] * a, 0, 255
        ).astype(np.uint8)
    arr[:, :, 3] = np.maximum(arr[:, :, 3], layer)


def clean_frame_1(arr: np.ndarray) -> np.ndarray:
    return remove_tail_s_badge(arr)


def clean_frame_2(arr: np.ndarray) -> np.ndarray:
    out = arr.copy()
    # 1. Remove middle belly white rounded rectangle (cap y<=626 to avoid touching diagonal arm line)
    belly_mask = detect_white_box_in_roi(
        out, 510, 550, 620, 628, luma_thresh=200, dilate_px=4
    )
    belly_mask[628:, :] = False
    inpaint_dark_fur(out, belly_mask, seed=21)

    # 2. Remove [L] semi-transparent badge over curled left paw (x=322..430, y=576..648)
    sub = out[576:648, 322:430]
    luma_sub = 0.299 * sub[:, :, 0] + 0.587 * sub[:, :, 1] + 0.114 * sub[:, :, 2]
    box_l = (luma_sub > 55).astype(np.uint8)
    box_l = cv2.morphologyEx(
        box_l, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (23, 23))
    )
    box_l = cv2.dilate(box_l, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (8, 8))) > 0
    l_roi = np.zeros((1024, 1024), dtype=bool)
    l_roi[576:648, 322:430] = box_l & (out[576:648, 322:430, 3] > 200)
    inpaint_dark_fur(out, l_roi, seed=22)

    # Redraw smooth curled left paw arcs bridging the exact existing endpoints
    t = np.linspace(0, 1, 60)
    p0, p1, p2, p3 = (
        np.array([348.0, 574.0]),
        np.array([332.0, 622.0]),
        np.array([402.0, 632.0]),
        np.array([428.0, 572.0]),
    )
    inner_pts = (
        ((1 - t) ** 3)[:, None] * p0
        + (3 * ((1 - t) ** 2) * t)[:, None] * p1
        + (3 * (1 - t) * (t**2))[:, None] * p2
        + (t**3)[:, None] * p3
    )
    draw_smooth_polyline(out, inner_pts, thickness=3)

    q0, q1, q2, q3 = (
        np.array([336.0, 592.0]),
        np.array([341.0, 642.0]),
        np.array([407.0, 639.0]),
        np.array([424.0, 596.0]),
    )
    outer_pts = (
        ((1 - t) ** 3)[:, None] * q0
        + (3 * ((1 - t) ** 2) * t)[:, None] * q1
        + (3 * (1 - t) * (t**2))[:, None] * q2
        + (t**3)[:, None] * q3
    )
    draw_smooth_polyline(out, outer_pts, thickness=3)

    # 3. Remove [R] badge straddling right hip/tail root (x=640..712, y=580..648)
    sub_r = out[580:648, 640:712]
    luma_r = 0.299 * sub_r[:, :, 0] + 0.587 * sub_r[:, :, 1] + 0.114 * sub_r[:, :, 2]
    box_r = (luma_r > 55).astype(np.uint8)
    box_r = cv2.morphologyEx(
        box_r, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    )
    box_r = cv2.dilate(box_r, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))) > 0

    clean_fur = out[560:578, 635:665]
    fur_med = np.median(clean_fur[clean_fur[:, :, 3] > 220], axis=0).astype(np.uint8)
    fur_med[3] = 255

    u = np.linspace(0, 1, 120)
    bx_pts = ((1 - u) ** 2) * 670 + 2 * (1 - u) * u * 675 + (u**2) * 712
    by_pts = ((1 - u) ** 2) * 648 + 2 * (1 - u) * u * 629 + (u**2) * 625
    body_mask_r = np.ones((648 - 580, 712 - 640), dtype=np.float32)
    for px in range(670, 712):
        idx = int(np.argmin(np.abs(bx_pts - px)))
        cy = by_pts[idx]
        for py in range(580, 648):
            d = cy - py
            body_mask_r[py - 580, px - 640] = float(np.clip((d + 0.75) / 1.5, 0.0, 1.0))

    for c in range(3):
        sub_r[:, :, c] = np.where(box_r, fur_med[c], sub_r[:, :, c])
    sub_r[:, :, 3] = np.where(
        box_r, np.minimum(sub_r[:, :, 3], (body_mask_r * 255.0).astype(np.uint8)), sub_r[:, :, 3]
    )
    out[580:648, 640:712] = sub_r
    return out


def clean_frame_3(arr: np.ndarray) -> np.ndarray:
    out = arr.copy()
    belly = detect_white_box_in_roi(
        out, 515, 570, 644, 655, luma_thresh=200, dilate_px=4
    )
    # Keep the intact white right-paw arc exiting at x >= 644
    belly[:, 643:] = False
    inpaint_dark_fur(out, belly, seed=31)
    return out


def clean_frame_4(arr: np.ndarray) -> np.ndarray:
    out = arr.copy()
    belly = detect_white_box_in_roi(
        out, 468, 548, 568, 642, luma_thresh=200, dilate_px=5
    )
    inpaint_dark_fur(out, belly, seed=41)
    return out


def clean_frame_5(arr: np.ndarray) -> np.ndarray:
    out = arr.copy()
    # 1. Remove [L] inside left arm (strictly x=395..459, never touching white lines at ~391 & ~462!)
    l_mask = np.zeros((1024, 1024), dtype=bool)
    sub_l = out[575:658, 394:461]
    luma_l = 0.299 * sub_l[:, :, 0] + 0.587 * sub_l[:, :, 1] + 0.114 * sub_l[:, :, 2]
    box_l = (luma_l > 42).astype(np.uint8)
    box_l = cv2.morphologyEx(
        box_l, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (23, 23))
    )
    box_l = cv2.dilate(box_l, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))) > 0
    l_mask[575:658, 394:461] = box_l
    # Protect the two crisp white left-arm lines dynamically (any pixel in x=388..395 or x>=460)
    l_mask[:, :395] = False
    l_mask[:, 459:] = False
    # Clean any subtle grey border right up to x=459, except preserve white line itself
    inpaint_dark_fur(out, l_mask, seed=51)

    # 2. Remove stacked [N] boxes in chest (x=476..576, y=552..660), keeping right white arm line untouched!
    n_mask = detect_white_box_in_roi(
        out, 476, 552, 576, 660, luma_thresh=140, dilate_px=5
    )
    n_mask[:, :475] = False
    inpaint_dark_fur(out, n_mask, seed=52)

    # 3. Remove [F] + [E] + stacked box behind [E] (x=590..775, y=590..708)
    sub_fe = out[590:708, 590:775]
    luma_fe = 0.299 * sub_fe[:, :, 0] + 0.587 * sub_fe[:, :, 1] + 0.114 * sub_fe[:, :, 2]
    badge_fe = ((sub_fe[:, :, 3] > 25) & (luma_fe > 55)).astype(np.uint8)
    badge_fe = cv2.morphologyEx(
        badge_fe, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    )
    badge_fe = cv2.dilate(badge_fe, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0

    chest_px = out[558:585, 590:650]
    fur_med = np.median(chest_px[chest_px[:, :, 3] > 220], axis=0).astype(np.uint8)
    fur_med[3] = 255

    poly_canvas = np.zeros((1024, 1024), dtype=np.uint8)
    t = np.linspace(0, 1, 100)
    ox = ((1 - t) ** 2) * 732 + 2 * (1 - t) * t * 748 + (t**2) * 768
    oy = ((1 - t) ** 2) * 590 + 2 * (1 - t) * t * 646 + (t**2) * 708
    ix = ((1 - t) ** 2) * 612 + 2 * (1 - t) * t * 672 + (t**2) * 705
    iy = ((1 - t) ** 2) * 684 + 2 * (1 - t) * t * 622 + (t**2) * 708

    outer_pts = np.column_stack([ox, oy])
    inner_pts = np.column_stack([ix[::-1], iy[::-1]])
    poly_pts = np.vstack([
        [[585, 588], [732, 588]],
        outer_pts,
        [[705, 710]],
        inner_pts,
        [[602, 710], [585, 710]],
    ]).astype(np.int32)
    cv2.fillPoly(poly_canvas, [poly_pts], 255)
    poly_alpha = cv2.GaussianBlur(poly_canvas.astype(np.float32), (3, 3), 0.7)

    roi_fe = out[590:708, 590:775]
    sil_roi = poly_alpha[590:708, 590:775]
    rng = np.random.default_rng(53)
    noise = rng.integers(-1, 2, size=roi_fe[:, :, :3].shape)
    fur_patch = np.clip(
        fur_med[:3].astype(np.int16)[None, None, :] + noise, 0, 255
    ).astype(np.uint8)

    for c in range(3):
        roi_fe[:, :, c] = np.where(badge_fe, fur_patch[:, :, c], roi_fe[:, :, c])
    roi_fe[:, :, 3] = np.where(
        badge_fe,
        np.clip(sil_roi, 0, 255).astype(np.uint8),
        roi_fe[:, :, 3],
    )
    out[590:708, 590:775] = roi_fe
    return out


def clean_frame_6(arr: np.ndarray) -> np.ndarray:
    return remove_tail_s_badge(arr)


def clean_frame_7(arr: np.ndarray) -> np.ndarray:
    return remove_tail_s_badge(arr)


def remove_outer_white_halo(arr: np.ndarray) -> np.ndarray:
    """Remove stray bright white background fringe pixels around the cat silhouette."""
    out = arr.copy()
    h, w = out.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    a = out[:, :, 3]
    eroded = cv2.erode((a > 128).astype(np.uint8), np.ones((5, 5), np.uint8))
    outer_band = (a > 0) & (eroded == 0)

    r, g, b = out[:, :, 0], out[:, :, 1], out[:, :, 2]
    bright = (r > 170) & (g > 170) & (b > 170)

    protected = ((xx < 285) & (yy > 650)) | (yy > 755) | (yy < 435)
    adj_zero = cv2.dilate((a < 20).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    fringe = outer_band & adj_zero & bright & (~protected) & (a < 235)
    out[fringe, 3] = 0
    return out


def add_mouse_outline_if_faint(arr: np.ndarray, roi=(40, 640, 260, 940)) -> np.ndarray:
    """Give faint white mouse on the left a crisp thin dark border matching frame 3."""
    out = arr.copy()
    x0, y0, x1, y1 = roi
    sub = out[y0:y1, x0:x1]
    a = sub[:, :, 3]
    bright = (
        (a > 40) & (sub[:, :, 0] > 185) & (sub[:, :, 1] > 185) & (sub[:, :, 2] > 185)
    ).astype(np.uint8)
    num, lbl, stats, _ = cv2.connectedComponentsWithStats(bright)
    if num <= 1:
        return out
    best = max(range(1, num), key=lambda k: stats[k, 4])
    if stats[best, 4] < 1500:
        return out
    mouse_mask = (lbl == best).astype(np.uint8)
    # Close inner scroll wheel slot so mouse_mask is solid oval
    mouse_solid = cv2.morphologyEx(
        mouse_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    )
    ring_outer = (
        cv2.dilate(mouse_solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))) > 0
    )
    ring = ring_outer & (mouse_solid == 0)
    not_black_paw = ~((a > 200) & (sub[:, :, 0] < 60))
    sub[ring & not_black_paw] = [24, 24, 24, 255]
    out[y0:y1, x0:x1] = sub
    return out


def orange_centroids(arr: np.ndarray) -> np.ndarray:
    r, g, b, a = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2], arr[:, :, 3]
    yy = np.arange(arr.shape[0])[:, None]
    orange = (a > 128) & (r > 200) & (g > 110) & (g < 220) & (b < 80) & (yy > 700)
    num, _, stats, cent = cv2.connectedComponentsWithStats(orange.astype(np.uint8))
    pts = [(cent[k, 0], cent[k, 1]) for k in range(1, num) if stats[k, 4] > 200]
    pts.sort(key=lambda p: p[0])
    return np.array([pts[0], pts[-1]], dtype=np.float32)


def kb_feature_img(arr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY).astype(np.float32)
    alpha = arr[:, :, 3].astype(np.float32) / 255.0
    return alpha * 128.0 + (gray * alpha) * 0.5


def align_to_reference(src: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Align src onto ref by locking the bottom keyboard silhouette via similarity + ECC."""
    src_pts = orange_centroids(src)
    ref_pts = orange_centroids(ref)
    M0, _ = cv2.estimateAffinePartial2D(src_pts, ref_pts)
    if M0 is None:
        return src

    src_m0 = cv2.warpAffine(
        src,
        M0,
        (1024, 1024),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )

    ref_feat = kb_feature_img(ref)
    src_feat = kb_feature_img(src_m0)
    mask = np.zeros((1024, 1024), dtype=np.uint8)
    mask[835:980, 170:965] = 255

    warp = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5)
    try:
        _, warp = cv2.findTransformECC(
            ref_feat, src_feat, warp, cv2.MOTION_EUCLIDEAN, criteria, inputMask=mask
        )
        aligned = cv2.warpAffine(
            src_m0,
            warp,
            (1024, 1024),
            flags=cv2.INTER_LANCZOS4 + cv2.WARP_INVERSE_MAP,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        return aligned
    except cv2.error:
        return src_m0


def replace_sparkles_from_ref(frame5: np.ndarray, ref4: np.ndarray) -> np.ndarray:
    """Replace the two static green sparkles on frame 5 keyboard using aligned frame 4."""
    out = frame5.copy()
    r, g, b, a = out[:, :, 0], out[:, :, 1], out[:, :, 2], out[:, :, 3]
    yy = np.arange(out.shape[0])[:, None]
    xx = np.arange(out.shape[1])[None, :]
    spark = (
        (a > 30)
        & (yy > 745)
        & (yy < 880)
        & (xx > 450)
        & (xx < 740)
        & (g > 150)
        & (b < 140)
        & ((g.astype(np.int16) - b.astype(np.int16)) > 50)
    )
    if np.any(spark):
        dk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        spark_dil = cv2.dilate(spark.astype(np.uint8), dk) > 0
        out[spark_dil] = ref4[spark_dil]
    return out


def unify_mouse_from_frame3(target: np.ndarray, clean3: np.ndarray) -> np.ndarray:
    """Replace the faint white mouse in typing frames 1,2,4,5 with frame 3's crisp mouse."""
    out = target.copy()
    yy, xx = np.mgrid[0:1024, 0:1024]
    t_a = (out[:, :, 3] > 20) & (xx < 225) & (yy > 670) & (yy < 935)
    num, lbl, stats, _ = cv2.connectedComponentsWithStats(t_a.astype(np.uint8))
    for k in range(1, num):
        if stats[k, 0] + stats[k, 2] < 225:
            out[lbl == k] = [0, 0, 0, 0]

    c3_a = (clean3[:, :, 3] > 20) & (xx < 230) & (yy > 670) & (yy < 935)
    num3, lbl3, stats3, _ = cv2.connectedComponentsWithStats(c3_a.astype(np.uint8))
    for k in range(1, num3):
        if stats3[k, 4] > 1000 and (stats3[k, 0] + stats3[k, 2] < 228):
            m = lbl3 == k
            out[m] = clean3[m]
    return out


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_dir = os.path.join(root, "image")
    out_dir = os.path.join(root, "assets", "frames")
    os.makedirs(out_dir, exist_ok=True)

    cleaners = {
        1: clean_frame_1,
        2: clean_frame_2,
        3: clean_frame_3,
        4: clean_frame_4,
        5: clean_frame_5,
        6: clean_frame_6,
        7: clean_frame_7,
    }

    cleaned: dict[int, np.ndarray] = {}
    for idx in range(1, 8):
        raw = load_rgba(os.path.join(in_dir, f"{idx}.png"))
        c = cleaners[idx](raw)
        c = remove_outer_white_halo(c)
        cleaned[idx] = c

    ref4 = cleaned[4]
    aligned: dict[int, np.ndarray] = {4: ref4}
    for idx in (1, 2, 3, 5, 6, 7):
        aligned[idx] = align_to_reference(cleaned[idx], ref4)

    aligned[5] = replace_sparkles_from_ref(aligned[5], aligned[4])

    for idx in (1, 2, 4, 5):
        aligned[idx] = unify_mouse_from_frame3(aligned[idx], aligned[3])
    for idx in (6, 7):
        aligned[idx] = add_mouse_outline_if_faint(aligned[idx], roi=(40, 640, 260, 940))

    union_mask = np.zeros((1024, 1024), dtype=bool)
    for idx in range(1, 8):
        union_mask |= aligned[idx][:, :, 3] > 15
    ys, xs = np.where(union_mask)
    pad = 24
    x0 = max(0, int(xs.min()) - pad)
    y0 = max(0, int(ys.min()) - pad)
    x1 = min(1024, int(xs.max()) + pad)
    y1 = min(1024, int(ys.max()) + pad)
    side = max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    sx0 = max(0, cx - side // 2)
    sy0 = max(0, cy - side // 2)
    if sx0 + side > 1024:
        sx0 = max(0, 1024 - side)
    if sy0 + side > 1024:
        sy0 = max(0, 1024 - side)
    side = min(side, 1024 - sx0, 1024 - sy0)

    print(f"Unified crop box: ({sx0}, {sy0}, {sx0 + side}, {sy0 + side}) -> {side}x{side}")

    cropped: dict[int, np.ndarray] = {}
    for idx in range(1, 8):
        crop = aligned[idx][sy0 : sy0 + side, sx0 : sx0 + side]
        cropped[idx] = crop
        save_rgba(crop, os.path.join(out_dir, f"{idx}.png"))

    cell = 420
    grid = Image.new("RGBA", (cell * 4, cell * 2), (72, 76, 84, 255))
    for i in range(1, 8):
        im = Image.fromarray(cropped[i], "RGBA").resize((cell, cell), Image.Resampling.LANCZOS)
        gx = ((i - 1) % 4) * cell
        gy = ((i - 1) // 4) * cell
        grid.alpha_composite(im, (gx, gy))
    grid.save(os.path.join(out_dir, "preview_grid.png"))

    acc = np.zeros((side, side, 4), dtype=np.float32)
    for idx in range(1, 8):
        acc += cropped[idx].astype(np.float32) / 7.0
    bg_check = Image.new("RGBA", (side, side), (90, 95, 105, 255))
    overlay = Image.alpha_composite(
        bg_check, Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8), "RGBA")
    )
    overlay.save(os.path.join(out_dir, "preview_alignment.png"))
    print("Saved polished frames + previews")

    export_parts(root, cropped)


def _extract_head_pair(
    src: np.ndarray,
    y_cut: float,
    feather_px: float,
    seed: int,
    tilt_slope: float = 0.0,
    tilt_x0: float = 0.0,
    squint_slope: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, dict, dict, tuple[int, int, int]]:
    """Extract open & squinted heads from a source frame, fitting tilted eye ellipses."""
    side = src.shape[0]
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    head = src.copy()

    y_lim = y_cut + tilt_slope * (xx - tilt_x0)
    head[yy > y_lim] = [0, 0, 0, 0]
    band = (yy >= (y_lim - feather_px)) & (yy <= y_lim)
    alpha_f = np.clip((y_lim - yy) / max(1.0, feather_px), 0.0, 1.0)
    head[band, 3] = (head[band, 3].astype(np.float32) * alpha_f[band]).astype(np.uint8)

    green_eye = (
        (head[:, :, 3] > 128)
        & (head[:, :, 1] > 170)
        & (head[:, :, 0] > 130)
        & (head[:, :, 2] < 120)
        & (yy < 360)
    )
    eye_rgb = np.median(head[green_eye, :3], axis=0).astype(np.uint8)

    # First close small interior pupils, then use convex hull per eye so pupils that touch the lower/outer edge
    # (as in typing crouch frame 4) are cleanly restored into smooth convex almond ovals.
    eye_closed = cv2.morphologyEx(
        green_eye.astype(np.uint8),
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (39, 39)),
    )
    num_e, lbl_e, stats_e, _ = cv2.connectedComponentsWithStats(eye_closed)
    eye_solid = np.zeros_like(eye_closed)
    eye_infos = []
    for k in range(1, num_e):
        if stats_e[k, 4] < 450:
            continue
        comp = (lbl_e == k).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnt = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(cnt)
        cv2.drawContours(eye_solid, [hull], -1, 1, thickness=-1)
        ell = cv2.fitEllipse(hull)  # ((cx, cy), (w, h), angle_deg)
        (ecx, ecy), (ew, eh), angle = ell
        eye_infos.append(
            {
                "cx": float(ecx),
                "cy": float(ecy),
                "rx": float(ew / 2.0),
                "ry": float(eh / 2.0),
                "angle_deg": float(angle),
                "bbox_w": int(round(max(ew, stats_e[k, 2]))),
                "bbox_h": int(round(max(eh, stats_e[k, 3]))),
            }
        )
    eye_infos.sort(key=lambda e: e["cx"])

    # Fill interior & edge-touching pupil cutouts cleanly with sclera green
    pupil_fill = (eye_solid > 0) & (~green_eye)
    pupil_dil = (cv2.dilate(pupil_fill.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & (eye_solid > 0)
    head[pupil_dil, :3] = eye_rgb
    head[pupil_dil, 3] = 255

    # Build squinted variant matching the exact eye centers & head tilt of frame 6
    squint = head.copy()
    eye_erase = cv2.dilate(eye_solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0
    inpaint_dark_fur(squint, eye_erase, seed=seed)
    for info in eye_infos:
        ecx, ecy = info["cx"], info["cy"]
        span_x = max(info["bbox_w"] * 0.44, 34.0)
        dy_tilt = span_x * squint_slope
        pts_sq = np.array(
            [
                [ecx - span_x, ecy + 2.0 - dy_tilt],
                [ecx - span_x * 0.28, ecy + 7.5 - dy_tilt * 0.28],
                [ecx + span_x * 0.32, ecy + 7.5 + dy_tilt * 0.32],
                [ecx + span_x, ecy + 2.5 + dy_tilt],
            ],
            dtype=np.float32,
        )
        t_sq = np.linspace(0, 1, 40)
        p0, p1, p2, p3 = pts_sq
        curve = (
            ((1 - t_sq) ** 3)[:, None] * p0
            + (3 * ((1 - t_sq) ** 2) * t_sq)[:, None] * p1
            + (3 * (1 - t_sq) * (t_sq**2))[:, None] * p2
            + (t_sq**3)[:, None] * p3
        )
        draw_smooth_polyline(
            squint,
            curve,
            color=(int(eye_rgb[0]), int(eye_rgb[1]), int(eye_rgb[2]), 255),
            thickness=10,
        )

    # Keep only the primary head connected component on both open & squint so diagonal cuts never capture tail-tip fragments!
    for arr_h in (head, squint):
        hc = (arr_h[:, :, 3] > 20).astype(np.uint8)
        nh, lh, sh, _ = cv2.connectedComponentsWithStats(hc)
        if nh > 1:
            best_h = max(range(1, nh), key=lambda k: sh[k, 4])
            arr_h[lh != best_h] = [0, 0, 0, 0]

    return head, squint, eye_infos[0], eye_infos[1], (int(eye_rgb[0]), int(eye_rgb[1]), int(eye_rgb[2]))


def _extract_body_from_frame(
    src: np.ndarray,
    y_bezel_top: np.ndarray,
    y_head_cut: float,
    tilt_slope: float = 0.0,
    tilt_x0: float = 0.0,
    keep_left_mouse_paw: bool = False,
) -> np.ndarray:
    """Cut head & keyboard/mouse from an aligned frame to obtain a clean torso layer."""
    side = src.shape[0]
    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    torso = src.copy()

    if keep_left_mouse_paw:
        # Remove the entire left mouse arm smoothly along the shoulder-chest tangent without jagged shoulder notch.
        kb_cut = (yy > (y_bezel_top - 3.5))
        arm_tangent = (yy >= 408.0) & (xx < 188.0 + (yy - 408.0) * 0.45)
        torso[kb_cut | arm_tangent] = [0, 0, 0, 0]
    else:
        below_kb = (yy > (y_bezel_top - 3.5)) | ((xx < 220) & (yy > 660))
        torso[below_kb] = [0, 0, 0, 0]

    head_cut = y_head_cut + tilt_slope * (xx - tilt_x0)
    torso[yy < head_cut] = [0, 0, 0, 0]

    t_comp = (torso[:, :, 3] > 25).astype(np.uint8)
    num_t, lbl_t, stats_t, _ = cv2.connectedComponentsWithStats(t_comp)
    if num_t > 1:
        best_t = max(range(1, num_t), key=lambda k: stats_t[k, 4])
        torso[lbl_t != best_t] = [0, 0, 0, 0]
    return torso


def export_parts(root: str, frames: dict[int, np.ndarray]) -> None:
    """Decompose aligned 940x940 frames into reusable layered rig parts in assets/parts."""
    import json

    parts_dir = os.path.join(root, "assets", "parts")
    os.makedirs(parts_dir, exist_ok=True)

    f1 = frames[1].copy()
    f3 = frames[3].copy()
    f4 = frames[4].copy()
    f7 = frames[7].copy()
    side = f4.shape[0]
    yy, xx = np.mgrid[0:side, 0:side]

    # 1. mouse_base.png (tight crop around crisp mouse from aligned frame 3)
    m3 = ((f3[:, :, 3] > 20) & (xx < 200) & (yy > 675)).astype(np.uint8)
    num, lbl, stats, cent = cv2.connectedComponentsWithStats(m3)
    best_m = max(range(1, num), key=lambda k: stats[k, 4])
    mx, my, mw, mh, _ = stats[best_m]
    pad_m = 6
    mx0, my0 = max(0, int(mx) - pad_m), max(0, int(my) - pad_m)
    mx1, my1 = min(side, int(mx + mw) + pad_m), min(side, int(my + mh) + pad_m)
    mouse_full = np.zeros_like(f3)
    mouse_full[lbl == best_m] = f3[lbl == best_m]
    mouse_crop = mouse_full[my0:my1, mx0:mx1]
    save_rgba(mouse_crop, os.path.join(parts_dir, "mouse_base.png"))
    mouse_cx, mouse_cy = float(cent[best_m][0]), float(cent[best_m][1])

    # 2. keyboard_base.png (from frame 4 below top bezel line, patching tiny hind-paw overlaps)
    keys_mask = (f4[:, :, 3] > 128) & (yy > 725) & (xx > 180) & (
        ((f4[:, :, 0] > 180) & (f4[:, :, 1] > 180) & (f4[:, :, 2] > 180))
        | ((f4[:, :, 0] > 200) & (f4[:, :, 1] > 110) & (f4[:, :, 2] < 80))
    )
    ky, kx = np.where(keys_mask)
    pts = np.column_stack([kx, ky])
    tl = pts[np.argmin(kx + ky)].tolist()
    br = pts[np.argmax(kx + ky)].tolist()
    tr = pts[np.argmax(kx - ky)].tolist()
    bl = pts[np.argmin(kx - ky)].tolist()

    left_ys = [int(np.where(keys_mask[:, x])[0].min()) for x in range(230, 275) if np.any(keys_mask[:, x])]
    right_ys = [int(np.where(keys_mask[:, x])[0].min()) for x in range(760, 815) if np.any(keys_mask[:, x])]
    yL_key, yR_key = float(np.median(left_ys)), float(np.median(right_ys))
    slope_top = (yR_key - yL_key) / (787.5 - 252.5)
    y_bezel_top = (yL_key - 10.0) + slope_top * (xx - 252.5)

    kb = np.zeros_like(f4)
    in_kb_zone = (xx > 170) & (yy >= y_bezel_top)
    kb[in_kb_zone] = f4[in_kb_zone]
    kb_dark = f4[(yy > 880) & (yy < 908) & (xx > 300) & (xx < 700) & (f4[:, :, 3] > 220)]
    bezel_col = np.median(kb_dark[:, :3], axis=0).astype(np.uint8) if len(kb_dark) else np.array([20, 20, 20], dtype=np.uint8)
    kb_comp = (kb[:, :, 3] > 30).astype(np.uint8)
    num_k, lbl_k, stats_k, _ = cv2.connectedComponentsWithStats(kb_comp)
    best_k = max(range(1, num_k), key=lambda k: stats_k[k, 4])
    kb[lbl_k != best_k] = [0, 0, 0, 0]
    # Ensure continuous clean dark top keyboard bezel (~8.5px tall) across the full top edge
    # so white idle front paws sit crisply against dark bezel instead of merging into white keycaps
    bezel_band = (xx > 215) & (xx < 785) & (yy >= y_bezel_top + 0.5) & (yy <= y_bezel_top + 9.0)
    kb[bezel_band, :3] = bezel_col
    kb[bezel_band, 3] = 255

    # Merge top-row (Spacebar row, closest to cat) center vertical divider slots into ONE solid wide Spacebar key
    white_kb = (kb[:, :, 3] > 200) & (kb[:, :, 0] > 210) & (kb[:, :, 1] > 210)
    kb_key_white = np.median(kb[white_kb, :3], axis=0).astype(np.uint8) if np.any(white_kb) else np.array([253, 253, 253], dtype=np.uint8)
    y_tops = np.array([int(np.where(white_kb[:, x])[0].min()) if np.any(white_kb[:, x]) else 940 for x in range(230, 815)])
    xs_fit = np.arange(230, 815)
    valid_t = y_tops < 900
    coef_top = np.polyfit(xs_fit[valid_t], y_tops[valid_t], 1)
    y_top_white = coef_top[0] * xx + coef_top[1]
    # Center 5 top-row divider lines lie between x=374 and x=624 (preserving outer bezel above and Z..M dots below)
    sp_mask = (
        (xx >= 374.0)
        & (xx <= 624.0)
        & (yy >= y_top_white + 3.5)
        & (yy <= y_top_white + 29.0)
        & (kb[:, :, 3] > 180)
        & (kb[:, :, 0] < 190)
    )
    sp_dil = cv2.dilate(sp_mask.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    kb[sp_dil, :3] = kb_key_white
    kb[sp_dil, 3] = 255

    save_rgba(kb, os.path.join(parts_dir, "keyboard_base.png"))

    def _anti_alias_fur_edges(
        arr: np.ndarray,
        fur_rgb: tuple[int, int, int],
        protect_mask: np.ndarray | None = None,
    ) -> None:
        """Rebuild subpixel-smooth contour curves & ~3.4px AA ramp so downscaled 240px windows never show jaggies."""
        a = arr[:, :, 3]
        bin_a = (a > 128).astype(np.uint8) * 255
        # Larger Gaussian kernel smooths away 1-2px extraction stair-steps across ears, torso & tail,
        # paired with a gentle ramp (/ 112.0) producing ~3.4px AA border at 940px (~0.9px at 240px).
        smoothed = cv2.GaussianBlur(bin_a.astype(np.float32), (15, 15), 2.8)
        smooth_a = np.clip((smoothed - 72.0) / 112.0 * 255.0, 0.0, 255.0).astype(np.uint8)
        # Protect whiskers, green eyes, interior white paw outlines, and feathered neck edges from alteration
        bright_feat = (arr[:, :, 0] > 75) | (arr[:, :, 1] > 75) | (arr[:, :, 2] > 75)
        keep = bright_feat if protect_mask is None else (bright_feat | protect_mask)
        edge_band = (
            cv2.dilate((bin_a > 0).astype(np.uint8), np.ones((11, 11), np.uint8))
            - cv2.erode((bin_a > 0).astype(np.uint8), np.ones((11, 11), np.uint8))
        ) > 0
        apply_mask = edge_band & (~keep)
        arr[apply_mask, 3] = smooth_a[apply_mask]
        # Clamp all semi-transparent rim RGB to dark fur so crisp white halos never bleed
        rim_tint = apply_mask & (smooth_a > 0) & ((arr[:, :, 0] > fur_rgb[0] + 10) | (a == 0))
        arr[rim_tint, :3] = fur_rgb

    # Strict keyboard eraser mask (kb solid pixels + 4px upward margin) so NO keyboard bezel strip stays glued under paws
    kb_erase = cv2.dilate((kb[:, :, 3] > 20).astype(np.uint8), np.ones((9, 5), np.uint8)) > 0

    def _clean_cat_kb_seam(body_arr: np.ndarray, pad_top: float = 0.0) -> None:
        # Erase any pixels falling into keyboard bezel zone
        erase_zone = kb_erase & (yy >= (y_bezel_top - 4.0 - pad_top))
        body_arr[erase_zone] = [0, 0, 0, 0]
        # Erase thin horizontal bezel/outline slivers near keyboard top that don't connect solidly into vertical legs (>10px tall)
        near_kb = (yy >= (y_bezel_top - 16.0)) & (xx > 180)
        solid_body = ((body_arr[:, :, 3] > 60) & (body_arr[:, :, 0] < 100)).astype(np.uint8)
        tall_core = cv2.morphologyEx(solid_body, cv2.MORPH_OPEN, np.ones((11, 3), np.uint8)) > 0
        # Restore thin interior white paw lines above y_bezel_top - 10 that sit inside legs/silhouette, kill thin dark bars below legs
        sliver = near_kb & (body_arr[:, :, 3] > 0) & (~cv2.dilate(tall_core.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool))
        body_arr[sliver] = [0, 0, 0, 0]
        # Keep only single largest cohesive body component
        comp = (body_arr[:, :, 3] > 25).astype(np.uint8)
        nc, lc, sc, _ = cv2.connectedComponentsWithStats(comp)
        if nc > 1:
            best = max(range(1, nc), key=lambda k: sc[k, 4])
            body_arr[lc != best] = [0, 0, 0, 0]

        # Strip bright white/grey cutout halos along the lower hind-paw rim (y >= 668), leaving interior paw lines intact
        bottom_zone = (yy >= 668.0) & (body_arr[:, :, 3] > 0)
        opaque_dark = ((body_arr[:, :, 3] > 200) & (body_arr[:, :, 0] < 50)).astype(np.uint8)
        interior_safe = cv2.erode(opaque_dark, np.ones((7, 7), np.uint8)) > 0
        outer_rim = bottom_zone & (~interior_safe)
        bright_speck = outer_rim & ((body_arr[:, :, 0] > 42) | (body_arr[:, :, 3] < 160))
        body_arr[bright_speck] = [0, 0, 0, 0]
        # Re-run single-component filter so no detached tiny dots remain around feet
        comp2 = (body_arr[:, :, 3] > 30).astype(np.uint8)
        nc2, lc2, sc2, _ = cv2.connectedComponentsWithStats(comp2)
        if nc2 > 1:
            best2 = max(range(1, nc2), key=lambda k: sc2[k, 4])
            body_arr[lc2 != best2] = [0, 0, 0, 0]

    def _smooth_tail_notch(body_arr: np.ndarray, fur_rgb: tuple[int, int, int], trim_bulge_curve: bool = True) -> None:
        """Trim residual lower-tail step on crouched/mouse frames and smooth bottom tail curve cleanly."""
        roi_y0, roi_y1 = 505, 645
        roi_x0, roi_x1 = 665, 790
        yy_s, xx_s = np.mgrid[roi_y0:roi_y1, roi_x0:roi_x1].astype(np.float32)
        if trim_bulge_curve:
            t_curve = np.clip((xx_s - 672.0) / (752.0 - 672.0), 0.0, 1.0)
            y_lower_bound = (
                (1 - t_curve) ** 2 * 602.0
                + 2.0 * (1 - t_curve) * t_curve * 586.0
                + t_curve ** 2 * 538.0
            )
            trim_bulge = (xx_s >= 682) & (xx_s <= 754) & (yy_s > y_lower_bound) & (yy_s <= 610)
            body_arr[roi_y0:roi_y1, roi_x0:roi_x1][trim_bulge] = [0, 0, 0, 0]

        sub_a = body_arr[roi_y0:roi_y1, roi_x0:roi_x1, 3].copy()
        closed = cv2.morphologyEx((sub_a > 128).astype(np.uint8) * 255, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        blurred = cv2.GaussianBlur(closed.astype(np.float32), (17, 17), 5.0)
        new_a = np.clip((blurred - 118.0) / 22.0 * 255.0, 0.0, 255.0).astype(np.uint8)
        in_fix = (xx_s >= 682) & (xx_s <= 776) & (yy_s >= 530)
        gain = (new_a > sub_a) & in_fix
        body_arr[roi_y0:roi_y1, roi_x0:roi_x1, :3][gain] = fur_rgb
        body_arr[roi_y0:roi_y1, roi_x0:roi_x1, 3][in_fix] = new_a[in_fix]

    yy_f, xx_f = np.mgrid[0:side, 0:side].astype(np.float32)

    def _make_head_silhouette(
        src_squint: np.ndarray,
        fur_rgb: tuple[int, int, int],
        protect_expr: np.ndarray,
        upper_cut: np.ndarray,
        y_eye_max: float = 320.0,
        y_whisk_range: tuple[float, float] = (220.0, 380.0),
        smooth_left_cheek: bool = False,
        chin_taper: tuple[float, float, float, float] | None = None,
        seed: int = 109,
    ) -> np.ndarray:
        """Erase green eyes and white whiskers cleanly into a solid smooth dark fur head silhouette."""
        sil = src_squint.copy()
        sq_green = (
            (sil[:, :, 3] > 80)
            & (sil[:, :, 1] > 150)
            & (sil[:, :, 0] > 100)
            & (sil[:, :, 2] < 140)
            & (yy_f < y_eye_max)
        )
        whisk_mask = (
            (sil[:, :, 3] > 50)
            & (sil[:, :, 0] > 90)
            & (sil[:, :, 1] > 90)
            & (sil[:, :, 2] > 90)
            & (yy_f >= y_whisk_range[0])
            & (yy_f <= y_whisk_range[1])
        )
        erase = cv2.dilate((sq_green | whisk_mask).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        solid = (
            cv2.morphologyEx(
                (sil[:, :, 3] > 180).astype(np.uint8),
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)),
            )
            > 0
        )
        inpaint_dark_fur(sil, (erase & solid) & (sil[:, :, 3] > 60), seed=seed)

        # Strip stray bright whisker pixels on cheeks cleanly without carving notches into cheek curvature
        dark_only = ((sil[:, :, 3] > 165) & (sil[:, :, 0] < 48) & (sil[:, :, 1] < 48)).astype(np.uint8)
        if smooth_left_cheek:
            left_cheek_zone = (xx_f < 155) & (yy_f >= 225) & (yy_f <= 335)
            smooth_ch = (
                cv2.morphologyEx(dark_only, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
                > 0
            )
            sil[left_cheek_zone & ((~smooth_ch) | (xx_f < 103))] = [0, 0, 0, 0]
        else:
            # Remove tiny exterior whisker needle tips cleanly while keeping cheek silhouette smooth and full
            cheek_band = (yy_f >= y_whisk_range[0] - 8.0) & (yy_f <= y_whisk_range[1] + 8.0)
            opened = cv2.morphologyEx(dark_only, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
            closed_cheek = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))) > 0
            sil[cheek_band & (~closed_cheek)] = [0, 0, 0, 0]
            stray_bright = cheek_band & (sil[:, :, 3] > 20) & (sil[:, :, :3].max(axis=2) > 55)
            sil[stray_bright, :3] = fur_rgb

        # Taper wide lower neck skirt inward into a rounded ball-joint chin so rotated head corners never poke out
        if chin_taper is not None:
            if len(chin_taper) == 5:
                y_ch_l, xl_ch, y_ch_r, xr_ch, slope_ch = chin_taper
            else:
                y_ch_l, xl_ch, xr_ch, slope_ch = chin_taper
                y_ch_r = y_ch_l
            dy_l = np.maximum(0.0, yy_f - y_ch_l)
            dy_r = np.maximum(0.0, yy_f - y_ch_r)
            trim_l = (yy_f > y_ch_l) & (xx_f < (xl_ch + dy_l * slope_ch))
            trim_r = (yy_f > y_ch_r) & (xx_f > (xr_ch - dy_r * slope_ch))
            sil[trim_l | trim_r] = [0, 0, 0, 0]

        sil_bin = ((sil[:, :, 3] > 128) & upper_cut).astype(np.float32) * 255.0
        sil_blur = cv2.GaussianBlur(sil_bin, (11, 11), 3.0)
        sil_smooth_a = np.clip((sil_blur - 115.0) / 26.0 * 255.0, 0.0, 255.0).astype(np.uint8)
        gain = (sil_smooth_a > sil[:, :, 3]) & upper_cut
        sil[gain, :3] = fur_rgb
        sil[upper_cut, 3] = sil_smooth_a[upper_cut]

        # Keep strictly the single head connected component (eliminates stray outer pixels)
        hs_c = (sil[:, :, 3] > 15).astype(np.uint8)
        nhs, lhs, shs, _ = cv2.connectedComponentsWithStats(hs_c)
        if nhs > 1:
            best_hs = max(range(1, nhs), key=lambda k: shs[k, 4])
            sil[lhs != best_hs] = [0, 0, 0, 0]
        _anti_alias_fur_edges(sil, fur_rgb, protect_mask=protect_expr)
        return sil

    def _add_feet_white_outline(
        body_arr: np.ndarray,
        foot_boxes: list[tuple[int, int, int, int]],
    ) -> None:
        """Draw crisp smooth white outline along each foot/paw bottom outer rim, tapering toward both ends."""
        for x0, x1, y0, y1 in foot_boxes:
            sub = body_arr[y0:y1, x0:x1]
            fur = ((sub[:, :, 3] > 140) & (sub[:, :, :3].mean(axis=2) < 65)).astype(np.uint8)
            if not fur.any():
                continue
            h_s, w_s = fur.shape
            shifted_down = np.zeros_like(fur)
            for dx in (-2, -1, 0, 1, 2):
                for dy in (1, 2, 3):
                    src_y0, src_y1 = max(0, -dy), min(h_s, h_s - dy)
                    dst_y0, dst_y1 = max(0, dy), min(h_s, h_s + dy)
                    src_x0, src_x1 = max(0, -dx), min(w_s, w_s - dx)
                    dst_x0, dst_x1 = max(0, dx), min(w_s, w_s + dx)
                    shifted_down[dst_y0:dst_y1, dst_x0:dst_x1] |= fur[src_y0:src_y1, src_x0:src_x1]

            cols_with_fur = np.where(fur.any(axis=0))[0]
            if len(cols_with_fur) < 6:
                continue
            c_min, c_max = int(cols_with_fur.min()), int(cols_with_fur.max())
            span = max(1.0, float(c_max - c_min))

            bottom_band = np.zeros_like(fur, dtype=np.float32)
            taper_weight = np.zeros_like(fur, dtype=np.float32)
            for col in range(w_s):
                ys_c = np.where(fur[:, col] > 0)[0]
                if len(ys_c):
                    yb = int(ys_c.max())
                    if yb >= 14:
                        u_arc = (col - c_min) / span
                        # Taper down smoothly near left/right tips of each paw rim
                        taper = float(np.sin(np.pi * max(0.0, min(1.0, u_arc))) ** 0.72)
                        bottom_band[max(0, yb - 4) : min(h_s, yb + 4), col] = 1.0
                        taper_weight[:, col] = taper
            rim = (shifted_down > 0) & (fur == 0) & (bottom_band > 0.5)
            rim_a = cv2.GaussianBlur(rim.astype(np.float32) * 255.0, (3, 3), 0.75) * taper_weight
            paint = rim_a > 18.0
            if paint.any():
                new_a = np.maximum(sub[:, :, 3], np.clip(rim_a * 1.15, 0.0, 255.0).astype(np.uint8))
                sub[paint, :3] = (250, 250, 252)
                sub[paint, 3] = new_a[paint]

    # 3A. Idle sitting pose from frame 1 (hind feet + unified front paws elevated clearly above keyboard)
    body_idle = _extract_body_from_frame(f1, y_bezel_top, y_head_cut=336.0, keep_left_mouse_paw=False)
    # Taper upper neck core (y=336..415) inward so dynamic tangent neck bridge owns the smooth outer neck contour
    id_neck = (yy >= 336.0) & (yy <= 415.0)
    id_in_l = id_neck & (xx < 366.0 - (yy - 336.0) * 0.72)
    id_in_r = id_neck & (xx > 594.0 + (yy - 336.0) * 0.62)
    body_idle[id_in_l | id_in_r] = [0, 0, 0, 0]
    _clean_cat_kb_seam(body_idle)
    # Erase baked half-length white leg lines & any chest/belly bright dots (up to x=595) from body_idle
    # so draw_idle_front_paws renders ONE unified arm+paw contour with zero stray white specks
    idle_leg_lines = (
        (xx >= 365)
        & (xx <= 595)
        & (yy >= 490)
        & (yy <= 725)
        & (body_idle[:, :, 3] > 35)
        & ((body_idle[:, :, 0] > 40) | (body_idle[:, :, 1] > 40) | (body_idle[:, :, 2] > 40))
    )
    il_dil = (cv2.dilate(idle_leg_lines.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0) & (
        body_idle[:, :, 3] > 90
    )
    inpaint_dark_fur(body_idle, il_dil, seed=103)
    # Catch any isolated bright pixel across upper body above y=665 (e.g. stray dust speck in original sprite)
    stray_speck = (yy < 665) & (body_idle[:, :, 3] > 20) & (body_idle[:, :, :3].mean(axis=2) > 40)
    if np.any(stray_speck):
        sp_dil = cv2.dilate(stray_speck.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        inpaint_dark_fur(body_idle, sp_dil & (body_idle[:, :, 3] > 90), seed=104)

    # Graft the pristine badge-free tail from f4 (shifted dx=+3, dy=-1) starting at x >= 675 so f1's torso hip is untouched,
    # then fill a smooth concave upper hip-to-tail fillet across x=652..695 so no vertical cliff or missing notch appears.
    f4_tail_src = _extract_body_from_frame(f4, y_bezel_top, y_head_cut=358.0, keep_left_mouse_paw=False)
    m_shift = np.float32([[1, 0, 3], [0, 1, -1]])
    f4_tail_shifted = cv2.warpAffine(f4_tail_src, m_shift, (side, side), flags=cv2.INTER_LINEAR)
    tail_zone = (xx >= 675) & (yy >= 440) & (yy <= 645)
    t_mask = tail_zone & (f4_tail_shifted[:, :, 3] > 0)
    body_idle[tail_zone] = [0, 0, 0, 0]
    body_idle[t_mask, :3] = (24, 24, 23)
    body_idle[t_mask, 3] = f4_tail_shifted[t_mask, 3]

    # Upper hip-to-tail smooth concave fillet: tangentially bridges right hip (652, 446) into tail top (694, 565)
    t_fillet = np.linspace(0.0, 1.0, 96)
    p0_f, p1_f, p2_f, p3_f = (
        np.array([652.0, 446.0]),
        np.array([660.0, 520.0]),
        np.array([665.0, 567.0]),
        np.array([694.0, 565.0]),
    )
    fillet_pts = (
        ((1 - t_fillet) ** 3)[:, None] * p0_f
        + (3 * ((1 - t_fillet) ** 2) * t_fillet)[:, None] * p1_f
        + (3 * (1 - t_fillet) * (t_fillet**2))[:, None] * p2_f
        + (t_fillet**3)[:, None] * p3_f
    )
    in_fx = (xx >= 652.0) & (xx <= 694.0) & (yy >= 446.0) & (yy <= 585.0)
    fy_curve = np.interp(xx, fillet_pts[:, 0], fillet_pts[:, 1])
    fillet_fill = in_fx & (yy >= fy_curve) & (body_idle[:, :, 3] < 250)
    body_idle[fillet_fill, :3] = (24, 24, 23)
    body_idle[fillet_fill, 3] = 255

    # Smooth entire hip-tail junction region (x=618..714, y=440..662) for seamless upper & lower AA curves
    j_y0, j_y1, j_x0, j_x1 = 440, 662, 618, 714
    j_sub = body_idle[j_y0:j_y1, j_x0:j_x1, 3].copy()
    j_closed = cv2.morphologyEx(
        (j_sub > 128).astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)),
    )
    j_blur = cv2.GaussianBlur(j_closed.astype(np.float32), (15, 15), 3.6)
    j_new = np.clip((j_blur - 115.0) / 26.0 * 255.0, 0.0, 255.0).astype(np.uint8)
    j_yy, j_xx = np.mgrid[j_y0:j_y1, j_x0:j_x1]
    j_fix = (j_yy >= 445) & (j_xx >= 622) & (j_xx <= 708)
    j_gain = (j_new > j_sub) & j_fix
    body_idle[j_y0:j_y1, j_x0:j_x1, :3][j_gain] = (24, 24, 23)
    body_idle[j_y0:j_y1, j_x0:j_x1, 3][j_fix] = j_new[j_fix]

    # 1) Rebuild clearly curved convex belly arch between left & right hind feet (x=374..544) FIRST
    # so subsequent left/right leg circular smoothing isn't chopped at x=374 or x=544.
    u_belly = np.clip((xx - 374.0) / (544.0 - 374.0), 0.0, 1.0)
    y_belly_smooth = 681.5 + 17.0 * np.sin(np.pi * u_belly) ** 0.85
    in_belly_x = (xx >= 374.0) & (xx <= 544.0)
    belly_fill = in_belly_x & (yy >= 655.0) & (yy <= y_belly_smooth) & (body_idle[:, :, 3] < 250)
    body_idle[belly_fill, :3] = (24, 24, 23)
    body_idle[belly_fill, 3] = 255
    belly_trim = in_belly_x & (yy > y_belly_smooth)
    body_idle[belly_trim] = [0, 0, 0, 0]

    # 2) Rebuild screen-left hind leg into a clean, plump circular oval (center=(347.5, 675.0), rx=36.0, ry=33.0)
    # seamlessly bridging the outer ankle pinch (y=652..670) and inner cliff (x=371..377)!
    lh_dx = (xx - 347.5) / 36.0
    lh_dy = (yy - 675.0) / 33.0
    lh_circ = (lh_dx * lh_dx + lh_dy * lh_dy) <= 1.0
    lh_zone = (xx >= 306.0) & (xx <= 376.0) & (yy >= 658.0)
    body_idle[lh_zone & (~lh_circ)] = [0, 0, 0, 0]
    lh_thigh_bridge = (xx >= 306.0) & (xx <= 376.0) & (yy >= 618.0) & (yy <= 676.0) & (
        xx >= (300.0 + (yy - 615.0) * 0.21)
    )
    lh_fill = (lh_circ | lh_thigh_bridge) & (body_idle[:, :, 3] < 250)
    body_idle[lh_fill, :3] = (24, 24, 23)
    body_idle[lh_fill, 3] = 255

    # 3) Rebuild screen-right hind leg into a clean, plump circular oval (center=(581.0, 684.5), rx=38.5, ry=36.0)
    # seamlessly meeting belly crease at (542.5, 684.5) and rounding cleanly down to y=720.5 with zero inner/outer notch!
    rh_dx = (xx - 581.0) / 38.5
    rh_dy = (yy - 684.5) / 36.0
    rh_circ = (rh_dx * rh_dx + rh_dy * rh_dy) <= 1.0
    rh_zone = (xx >= 542.5) & (xx <= 628.0) & (yy >= 668.0)
    body_idle[rh_zone & (~rh_circ)] = [0, 0, 0, 0]
    rh_thigh_bridge = (xx >= 544.0) & (xx <= 626.0) & (yy >= 632.0) & (yy <= 686.0) & (
        xx <= (634.0 - (yy - 630.0) * 0.28)
    )
    rh_fill = (rh_circ | rh_thigh_bridge) & (body_idle[:, :, 3] < 250)
    body_idle[rh_fill, :3] = (24, 24, 23)
    body_idle[rh_fill, 3] = 255

    # Smooth entire lower belly + both hind legs bottom contours in one clean pass (x=298..634, y=612..728)
    rh_y0, rh_y1, rh_x0, rh_x1 = 612, 728, 298, 636
    rh_sub = body_idle[rh_y0:rh_y1, rh_x0:rh_x1, 3].copy()
    rh_closed = cv2.morphologyEx(
        (rh_sub > 128).astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
    )
    rh_blur = cv2.GaussianBlur(rh_closed.astype(np.float32), (11, 11), 2.8)
    rh_new = np.clip((rh_blur - 115.0) / 26.0 * 255.0, 0.0, 255.0).astype(np.uint8)
    rh_yy, rh_xx = np.mgrid[rh_y0:rh_y1, rh_x0:rh_x1]
    rh_fix = (
        ((rh_yy >= 618) & (rh_xx >= 302) & (rh_xx <= 378))
        | ((rh_yy >= 662) & (rh_xx >= 378) & (rh_xx <= 542))
        | ((rh_yy >= 628) & (rh_xx >= 542) & (rh_xx <= 630))
    )
    rh_gain = (rh_new > rh_sub) & rh_fix
    body_idle[rh_y0:rh_y1, rh_x0:rh_x1, :3][rh_gain] = (24, 24, 23)
    body_idle[rh_y0:rh_y1, rh_x0:rh_x1, 3][rh_fix] = rh_new[rh_fix]

    _smooth_tail_notch(body_idle, (24, 24, 23), trim_bulge_curve=False)
    _anti_alias_fur_edges(body_idle, (24, 24, 23), protect_mask=(yy >= y_bezel_top - 4.0) | (yy < 342.0))
    _add_feet_white_outline(
        body_idle,
        [
            (312, 376, 645, 718),  # full rounded left hind foot
            (548, 622, 645, 726),  # circular right hind foot
        ],
    )
    # Remove any isolated stray dot (keeping single cohesive silhouette)
    id_c = (body_idle[:, :, 3] > 10).astype(np.uint8)
    nid, lid, sid, _ = cv2.connectedComponentsWithStats(id_c)
    if nid > 1:
        best_id = max(range(1, nid), key=lambda k: sid[k, 4])
        body_idle[lid != best_id] = [0, 0, 0, 0]
    save_rgba(body_idle, os.path.join(parts_dir, "body_idle.png"))
    head_idle_open, head_idle_squint, idle_le, idle_re, eye_rgb_tup = _extract_head_pair(
        f1, y_cut=376.0, feather_px=18.0, seed=105
    )
    _anti_alias_fur_edges(head_idle_open, (24, 24, 23), protect_mask=(yy >= 352.0))
    _anti_alias_fur_edges(head_idle_squint, (24, 24, 23), protect_mask=(yy >= 352.0))
    save_rgba(head_idle_open, os.path.join(parts_dir, "head_idle_open.png"))
    save_rgba(head_idle_squint, os.path.join(parts_dir, "head_idle_squint.png"))
    head_idle_sil = _make_head_silhouette(
        head_idle_squint,
        (24, 24, 23),
        protect_expr=(yy_f >= 352.0),
        upper_cut=(yy_f < 358.0),
        y_eye_max=260.0,
        y_whisk_range=(215.0, 325.0),
        chin_taper=(282.0, 348.0, 626.0, 0.75),
        seed=111,
    )
    save_rgba(head_idle_sil, os.path.join(parts_dir, "head_idle_sil.png"))

    # 3B. Typing crouch pose from frame 4 (torso + angled-eye head from f4 itself!)
    body_typing = _extract_body_from_frame(f4, y_bezel_top, y_head_cut=358.0, keep_left_mouse_paw=False)
    # Taper upper neck core (y=358..435) inward into a socket so rotated head & tangent neck bridge never step or notch!
    neck_rows = (yy >= 358.0) & (yy <= 435.0)
    inward_left = neck_rows & (xx < 356.0 - (yy - 358.0) * 0.78)
    inward_right = neck_rows & (xx > 588.0 + (yy - 358.0) * 0.68)
    body_typing[inward_left | inward_right] = [0, 0, 0, 0]
    _clean_cat_kb_seam(body_typing)
    _smooth_tail_notch(body_typing, (25, 25, 25), trim_bulge_curve=False)
    curl_mask = (
        (yy >= 518)
        & (yy <= 628)
        & (xx >= 280)
        & (xx <= 645)
        & (body_typing[:, :, 3] > 60)
        & ((body_typing[:, :, 0] > 70) | (body_typing[:, :, 1] > 70) | (body_typing[:, :, 2] > 70))
    )
    dk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    curl_dil = (cv2.dilate(curl_mask.astype(np.uint8), dk) > 0) & (body_typing[:, :, 3] > 120)
    inpaint_dark_fur(body_typing, curl_dil, seed=101)
    _anti_alias_fur_edges(body_typing, (25, 25, 25), protect_mask=(yy >= y_bezel_top - 4.0) | (yy < 364.0))
    _add_feet_white_outline(body_typing, [(302, 392, 645, 712), (534, 624, 645, 724)])
    save_rgba(body_typing, os.path.join(parts_dir, "body_typing.png"))
    save_rgba(body_typing, os.path.join(parts_dir, "body_torso.png"))  # legacy alias

    head_typing_open, head_typing_squint, typ_le, typ_re, _ = _extract_head_pair(
        f4, y_cut=428.0, feather_px=20.0, seed=106
    )
    _anti_alias_fur_edges(head_typing_open, (25, 25, 25), protect_mask=(yy >= 402.0))
    _anti_alias_fur_edges(head_typing_squint, (25, 25, 25), protect_mask=(yy >= 402.0))
    save_rgba(head_typing_open, os.path.join(parts_dir, "head_typing_open.png"))
    save_rgba(head_typing_squint, os.path.join(parts_dir, "head_typing_squint.png"))
    save_rgba(head_typing_open, os.path.join(parts_dir, "head_open.png"))  # legacy alias
    save_rgba(head_typing_squint, os.path.join(parts_dir, "head_squint.png"))  # legacy alias
    head_typing_sil = _make_head_silhouette(
        head_typing_squint,
        (25, 25, 25),
        protect_expr=(yy_f >= 402.0),
        upper_cut=(yy_f < 406.0),
        y_eye_max=325.0,
        y_whisk_range=(280.0, 390.0),
        chin_taper=(302.0, 326.0, 621.0, 0.85),
        seed=112,
    )
    save_rgba(head_typing_sil, os.path.join(parts_dir, "head_typing_sil.png"))

    # 3C. Mouse-lean pose from frame 7 (exact video silhouette + separable resting right arm)
    body_mouse = _extract_body_from_frame(
        f7, y_bezel_top, y_head_cut=305.0, tilt_slope=0.14, tilt_x0=280.0, keep_left_mouse_paw=True
    )
    # Erase original right arm white lines completely from body_mouse BEFORE _clean_cat_kb_seam so belly rim stays solid
    right_arm_wipe = (
        (xx >= 390)
        & (xx <= 595)
        & (yy >= 475)
        & (yy <= y_bezel_top + 2.0)
        & (~((xx >= 565) & (yy >= 675)))
        & (body_mouse[:, :, 3] > 60)
        & ((body_mouse[:, :, 0] > 50) | (body_mouse[:, :, 1] > 50) | (body_mouse[:, :, 2] > 50))
    )
    rm_dil = (cv2.dilate(right_arm_wipe.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))) > 0) & (
        body_mouse[:, :, 3] > 100
    )
    inpaint_dark_fur(body_mouse, rm_dil, seed=107)

    # Trim lower-left cheek overhang & taper upper neck core inward so tangent neck bridge owns outer neck contour
    body_mouse[(xx < 175) & (yy < 322)] = [0, 0, 0, 0]
    t_in_l = (yy >= 305.0) & (yy <= 395.0) & (xx < 210.0 - (yy - 305.0) * 0.25)
    t_in_r = (
        (yy >= 305.0)
        & (yy <= 455.0)
        & (xx < 620.0)
        & (xx > 370.0 + (yy - 305.0) * ((554.0 - 370.0) / (455.0 - 305.0)))
    )
    body_mouse[t_in_l | t_in_r] = [0, 0, 0, 0]
    # Trim baked static right-paw block (x=450..544) smoothly along natural belly tangent so procedural right arm stands cleanly
    y_mouse_belly = 690.5 + np.clip((xx - 450.0) / 94.0, 0.0, 1.0) * 4.5
    body_mouse[(xx >= 450) & (xx <= 544) & (yy > y_mouse_belly)] = [0, 0, 0, 0]
    # Smooth the left shoulder-neck contour (x=155..225, y=325..475) and tail curve seamlessly
    sh_y0, sh_y1, sh_x0, sh_x1 = 325, 480, 150, 235
    sh_a = body_mouse[sh_y0:sh_y1, sh_x0:sh_x1, 3].copy()
    sh_blur = cv2.GaussianBlur((sh_a > 128).astype(np.float32) * 255.0, (13, 13), 4.0)
    sh_new = np.clip((sh_blur - 115.0) / 25.0 * 255.0, 0.0, 255.0).astype(np.uint8)
    sh_fix = (np.mgrid[sh_y0:sh_y1, sh_x0:sh_x1][0] >= 332) & (np.mgrid[sh_y0:sh_y1, sh_x0:sh_x1][1] <= 215)
    gain_sh = (sh_new > sh_a) & sh_fix
    body_mouse[sh_y0:sh_y1, sh_x0:sh_x1, :3][gain_sh] = (12, 12, 12)
    body_mouse[sh_y0:sh_y1, sh_x0:sh_x1, 3][sh_fix] = sh_new[sh_fix]

    _clean_cat_kb_seam(body_mouse)
    _smooth_tail_notch(body_mouse, (12, 12, 12))
    # Extract clean pure-white parallel stroke highlights for BOTH sides of the resting right arm
    arm_mask_f7 = (
        (xx >= 425)
        & (xx <= 592)
        & (yy >= 492)
        & (yy <= y_bezel_top + 2.0)
        & (f7[:, :, 3] > 60)
        & ((f7[:, :, 0] > 62) | (f7[:, :, 1] > 62) | (f7[:, :, 2] > 62))
    )
    # Exclude hind-paw foot rim area on far right (x > 578 and y > 690)
    arm_mask_f7 &= ~((xx >= 578) & (yy >= 688))
    arm_rest = np.zeros_like(f7)
    arm_lum = f7[:, :, :3].mean(axis=2)
    stroke_alpha = np.clip((arm_lum - 38.0) / 115.0 * 255.0, 0.0, 255.0).astype(np.uint8)
    arm_dil = cv2.dilate(arm_mask_f7.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0
    arm_band = arm_dil & (f7[:, :, 3] > 60) & (yy <= 708.0)
    arm_rest[arm_band, :3] = (250, 250, 252)
    arm_rest[arm_band, 3] = stroke_alpha[arm_band]
    # Crisp bright white tone on the resting right arm stroke highlights, tapering gently at top/bottom tips
    arm_rest_y_taper = np.clip((yy - 492.0) / 36.0, 0.25, 1.0) * np.clip((710.0 - yy) / 26.0, 0.25, 1.0)
    arm_rest[arm_band, 3] = np.clip(stroke_alpha[arm_band] * arm_rest_y_taper[arm_band], 0.0, 255.0).astype(np.uint8)
    ar_c = (arm_rest[:, :, 3] > 20).astype(np.uint8)
    na, la, sa, _ = cv2.connectedComponentsWithStats(ar_c)
    for k in range(1, na):
        if sa[k, 4] < 45:
            arm_rest[la == k] = [0, 0, 0, 0]
    # Add tapered curved white bottom outline under the resting right paw tip using body_mouse paw mask
    paw_f7 = np.zeros_like(arm_rest)
    paw_f7[668:720, 492:582] = body_mouse[668:720, 492:582]
    _add_feet_white_outline(paw_f7, [(492, 582, 668, 720)])
    # Keep only the newly painted white rim pixels and copy into arm_rest
    new_rim = (paw_f7[:, :, 0] > 200) & (paw_f7[:, :, 3] > 20) & (body_mouse[:, :, 0] < 100)
    arm_rest[new_rim] = paw_f7[new_rim]
    save_rgba(arm_rest, os.path.join(parts_dir, "arm_mouse_right_rest.png"))

    _anti_alias_fur_edges(body_mouse, (12, 12, 12), protect_mask=(yy >= y_bezel_top - 4.0) | (yy < 312.0 + 0.14 * (xx - 280.0)))
    # Rebuild screen-right hind leg into a clean, plump circular oval (center=(575.5, 681.5), rx=31.0, ry=33.5),
    # eliminating the dangling extra old-paw bulge at x=546..570 (y=718..723) and outer thigh pinch at y=656!
    rmh_dx = (xx - 575.5) / 31.0
    rmh_dy = (yy - 681.5) / 33.5
    rmh_circ = (rmh_dx * rmh_dx + rmh_dy * rmh_dy) <= 1.0
    rmh_zone = (xx >= 543.0) & (xx <= 616.0) & (yy >= 655.0)
    body_mouse[rmh_zone & (~rmh_circ)] = [0, 0, 0, 0]
    rmh_bridge = (xx >= 545.0) & (xx <= 612.0) & (yy >= 612.0) & (yy <= 682.0) & (
        xx <= (614.0 - (yy - 605.0) * 0.12)
    )
    rmh_fill = (rmh_circ | rmh_bridge) & (body_mouse[:, :, 3] < 250)
    body_mouse[rmh_fill, :3] = (12, 12, 12)
    body_mouse[rmh_fill, 3] = 255
    # Smooth right thigh + rounded foot contour cleanly (x=538..618, y=608..724)
    rmh_y0, rmh_y1, rmh_x0, rmh_x1 = 608, 726, 538, 618
    rmh_sub = body_mouse[rmh_y0:rmh_y1, rmh_x0:rmh_x1, 3].copy()
    rmh_closed = cv2.morphologyEx(
        (rmh_sub > 128).astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
    )
    rmh_blur = cv2.GaussianBlur(rmh_closed.astype(np.float32), (11, 11), 2.8)
    rmh_new = np.clip((rmh_blur - 115.0) / 26.0 * 255.0, 0.0, 255.0).astype(np.uint8)
    rmh_yy, rmh_xx = np.mgrid[rmh_y0:rmh_y1, rmh_x0:rmh_x1]
    rmh_fix = (rmh_yy >= 614) & (rmh_xx >= 543) & (rmh_xx <= 612)
    rmh_gain = (rmh_new > rmh_sub) & rmh_fix
    body_mouse[rmh_y0:rmh_y1, rmh_x0:rmh_x1, :3][rmh_gain] = (12, 12, 12)
    body_mouse[rmh_y0:rmh_y1, rmh_x0:rmh_x1, 3][rmh_fix] = rmh_new[rmh_fix]

    _add_feet_white_outline(body_mouse, [(302, 382, 645, 712), (546, 608, 650, 720)])
    save_rgba(body_mouse, os.path.join(parts_dir, "body_mouse.png"))

    head_mouse_open, head_mouse_squint, ms_le, ms_re, _ = _extract_head_pair(
        f7, y_cut=376.0, feather_px=20.0, seed=108, tilt_slope=0.14, tilt_x0=280.0, squint_slope=0.10
    )
    save_rgba(head_mouse_open, os.path.join(parts_dir, "head_mouse_open.png"))
    save_rgba(head_mouse_squint, os.path.join(parts_dir, "head_mouse_squint.png"))

    # Build round, smooth black head silhouette covering upper neck nicely so turning head left/right stays seamless
    head_mouse_sil = _make_head_silhouette(
        head_mouse_squint,
        (13, 13, 13),
        protect_expr=(yy_f >= 352.0 + 0.14 * (xx_f - 280.0)),
        upper_cut=(yy_f < (366.0 + 0.14 * (xx_f - 280.0))),
        y_eye_max=320.0,
        y_whisk_range=(230.0, 335.0),
        smooth_left_cheek=True,
        chin_taper=(312.0, 154.0, 278.0, 422.0, 0.78),
        seed=109,
    )
    save_rgba(head_mouse_sil, os.path.join(parts_dir, "head_mouse_sil.png"))

    # Export clean white left & right whiskers from f7 (preserving exact stroke crispness for live head turn)
    w_src = head_mouse_open.copy()
    w_white = (
        (w_src[:, :, 3] > 50)
        & (w_src[:, :, 0] > 165)
        & (w_src[:, :, 1] > 165)
        & (w_src[:, :, 2] > 165)
        & (yy_f >= 235)
        & (yy_f <= 332)
    )
    # Also draw crisp symmetric whisker crops by splitting around x=215
    def _save_whisker_crop(mask_side: np.ndarray, out_name: str) -> list[int]:
        wy, wx = np.where(mask_side)
        x0, x1 = int(wx.min()) - 4, int(wx.max()) + 5
        y0, y1 = int(wy.min()) - 4, int(wy.max()) + 5
        crop = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
        sub_src = w_src[y0:y1, x0:x1]
        # Alpha proportional to whiteness so anti-aliased white strokes lift cleanly off black fur!
        whiteness = np.clip((sub_src[:, :, :3].mean(axis=2) - 45.0) / 185.0, 0.0, 1.0)
        mask_dil = cv2.dilate(mask_side[y0:y1, x0:x1].astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        alpha = np.where(mask_dil, (whiteness * 255.0).astype(np.uint8), 0)
        crop[:, :, :3] = 252
        crop[:, :, 3] = alpha
        save_rgba(crop, os.path.join(parts_dir, out_name))
        return [x0, y0, x1 - x0, y1 - y0]

    w_left_rect = _save_whisker_crop(w_white & (xx_f < 215), "whiskers_mouse_left.png")
    w_right_rect = _save_whisker_crop(w_white & (xx_f >= 215), "whiskers_mouse_right.png")

    # Save exact calibration metadata for all 3 rig modes
    meta = {
        "canvas_size": side,
        "left_eye": typ_le,
        "right_eye": typ_re,
        "eye_green_rgb": list(eye_rgb_tup),
        "modes": {
            "idle": {
                "left_eye": idle_le,
                "right_eye": idle_re,
                "neck_pivot": [488.0, 365.0],
                "hip_pivot": [485.0, 712.0],
            },
            "typing": {
                "left_eye": typ_le,
                "right_eye": typ_re,
                "neck_pivot": [485.0, 405.0],
                "hip_pivot": [485.0, 715.0],
                "left_shoulder": [355.0, 505.0],
                "right_shoulder": [592.0, 512.0],
            },
            "mouse": {
                "left_eye": ms_le,
                "right_eye": ms_re,
                "head_cx": 260.0,
                "whisker_left_rect": w_left_rect,
                "whisker_right_rect": w_right_rect,
                "neck_pivot": [290.0, 342.0],
                "hip_pivot": [472.0, 710.0],
                "left_shoulder": [204.0, 456.0],
                "right_shoulder": [445.0, 515.0],
                "mouse_grip_center": [98.0, 726.0],
            },
        },
        "neck_pivot": [485.0, 405.0],
        "hip_pivot": [485.0, 715.0],
        "left_shoulder": [355.0, 505.0],
        "right_shoulder": [592.0, 512.0],
        "kb_quad": [tl, tr, br, bl],
        "mouse_rect": [mx0, my0, mx1 - mx0, my1 - my0],
        "mouse_center": [mouse_cx, mouse_cy],
    }
    with open(os.path.join(parts_dir, "parts_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print("Exported layered rig parts to", parts_dir)


if __name__ == "__main__":
    main()
