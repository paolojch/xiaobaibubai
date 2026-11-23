"""Unit tests for CatStateMachine and key partitioning."""

import unittest

from src.input_hook import is_ignored_vk, vk_to_bubble_label, vk_to_label
from src.rig import MIRRORED_KEY_LAYOUT, get_key_spec
from src.state_machine import CatStateMachine, HandSide, classify_vk_side


class TestStateMachine(unittest.TestCase):
    def test_hand_classification_and_labels(self) -> None:
        self.assertEqual(classify_vk_side(ord("A")), HandSide.LEFT)
        self.assertEqual(classify_vk_side(ord("J")), HandSide.RIGHT)
        self.assertEqual(vk_to_label(ord("A")), "A")
        self.assertEqual(vk_to_label(0x20), "Space")
        self.assertEqual(vk_to_label(0x0D, flags=0x01), "NumEnter")
        self.assertEqual(vk_to_label(0x0D, flags=0x00), "Enter")

    def test_typing_poses_and_minimum_hold(self) -> None:
        sm = CatStateMachine(idle_frame=4, blink_enabled=False, mouse_react_enabled=True)
        self.assertEqual(sm.current_frame(0), 4)

        self.assertTrue(sm.on_key_down(ord("A"), 100))
        self.assertEqual(sm.current_frame(110), 3)
        self.assertFalse(sm.on_key_down(ord("A"), 130))

        self.assertTrue(sm.on_key_down(ord("L"), 140))
        self.assertEqual(sm.current_frame(150), 5)

        self.assertTrue(sm.on_key_up(ord("A"), 200))
        self.assertEqual(sm.current_frame(280), 2)

        self.assertTrue(sm.on_key_up(ord("L"), 300))
        self.assertEqual(sm.current_frame(2000), 4)

    def test_fast_tap_min_hold_stays_visible(self) -> None:
        sm = CatStateMachine(idle_frame=1, blink_enabled=False)
        sm.on_key_down(ord("F"), 1000)
        sm.on_key_up(ord("F"), 1015)
        self.assertEqual(sm.current_frame(1040), 3)
        self.assertEqual(sm.current_frame(1120), 1)
        self.assertEqual(sm.current_frame(3000), 1)

        sm4 = CatStateMachine(idle_frame=4, blink_enabled=False)
        sm4.on_key_down(ord("F"), 1000)
        sm4.on_key_up(ord("F"), 1015)
        self.assertEqual(sm4.current_frame(1040), 3)
        self.assertEqual(sm4.current_frame(3000), 4)

    def test_mouse_and_blink_and_sleep(self) -> None:
        sm = CatStateMachine(idle_frame=1, blink_enabled=True, mouse_react_enabled=True)
        sm.on_mouse_button("left", True, 500)
        self.assertEqual(sm.current_frame(600), 7)
        sm.on_mouse_button("left", False, 650)
        self.assertEqual(sm.current_frame(900), 7)

        sm.on_key_down(ord("K"), 1400)
        self.assertEqual(sm.current_frame(1410), 2)
        sm.on_key_up(ord("K"), 1450)

        self.assertEqual(sm.current_frame(50000), 6)

        sm.on_key_down(ord("Q"), 50100)
        sm.reset_inputs()
        self.assertEqual(sm.current_frame(50200), 1)

    def test_decoupled_mouse_plus_typing_and_petting(self) -> None:
        sm = CatStateMachine(mirror_keyboard=True, petting_enabled=True, blink_enabled=False)
        self.assertEqual(vk_to_bubble_label(0xA0), "⇧")
        self.assertGreater(get_key_spec(ord("A"), mirror=True).u, 0.7)
        self.assertLess(get_key_spec(ord("A"), mirror=False).u, 0.3)

        # Move mouse left while typing a right-side key ('S'):
        # 1) Pressing 'S' cancels mouse glance and immediately snaps head & pupils right toward 'S'!
        sm.on_mouse_move(1000, dir_x=-0.85, dir_y=0.0)
        sm.on_key_down(ord("S"), 1020, bubble_label="S")
        for dt in range(20, 260, 20):
            snap = sm.snapshot(1020 + dt)
        self.assertEqual(snap.pose_mode, "mouse_typing")
        self.assertTrue(snap.viewer_left_on_mouse)
        self.assertIsNotNone(snap.viewer_right_target)
        self.assertGreater(snap.eye_dx, 0.35)
        self.assertGreater(snap.head_turn_x, 0.35)
        self.assertEqual(len(snap.chest_bubbles), 1)
        self.assertEqual(snap.chest_bubbles[0][0], "S")

        # 2) Moving mouse again glances left toward mouse, then snaps back right to 'S' after glance (~360ms)!
        sm.on_mouse_move(1300, dir_x=-0.90, dir_y=0.0)
        for dt in range(20, 220, 20):
            glance_snap = sm.snapshot(1300 + dt)
        self.assertLess(glance_snap.eye_dx, -0.35)
        self.assertLess(glance_snap.head_turn_x, -0.25)

        for t in range(1670, 1950, 25):
            back_snap = sm.snapshot(t)
        self.assertGreater(back_snap.eye_dx, 0.35)
        self.assertGreater(back_snap.head_turn_x, 0.35)

        # 3) Hovering cursor over cat's head NEVER closes eyes; clicking cat's head closes eyes & reopens after release
        sm.on_mouse_move(2100, dir_x=0.0, dir_y=-0.3, local_norm=(0.45, 0.20))
        self.assertFalse(sm.snapshot(2500).squint)
        sm.on_head_click(True, 2600)
        self.assertTrue(sm.snapshot(2650).squint)
        sm.on_head_click(False, 2700)
        self.assertTrue(sm.snapshot(2900).squint)
        self.assertFalse(sm.snapshot(3350).squint)

    def test_typing_blinks_and_looks_down_at_keyboard(self) -> None:
        sm = CatStateMachine(blink_enabled=True, mouse_react_enabled=True)
        # Continuous typing past _next_blink_ms (~3600ms) MUST still blink
        for t in range(100, 3800, 120):
            sm.on_key_down(ord("A"), t, "A")
            sm.on_key_up(ord("A"), t + 60)
        saw_blink = any(sm.snapshot(t).squint for t in range(3400, 4200, 40))
        self.assertTrue(saw_blink, "Cat must still blink naturally during continuous typing")

        # While actively typing, eyes look downward at keyboard & head drops
        sm.on_key_down(ord("A"), 5000, "A")
        for _ in range(12):
            snap = sm.snapshot(5020)
        self.assertGreater(snap.eye_dy, 0.5)
        self.assertGreater(snap.head_drop, 0.6)

        # No keyboard or mouse input -> upright sitting idle pose ("idle", frame 1)
        idle_sm = CatStateMachine(blink_enabled=False, mouse_react_enabled=True)
        self.assertEqual(idle_sm.idle_frame, 1)
        self.assertEqual(idle_sm.snapshot(5000).pose_mode, "idle")
        self.assertEqual(idle_sm.current_frame(5000), 1)

        # Mouse movement without typing triggers mouse-lean pose ("mouse", 7.png silhouette) & head turn
        sm.on_key_up(ord("A"), 5040)
        sm.on_mouse_move(7500, dir_x=-0.9, dir_y=-0.2)
        for _ in range(16):
            msnap = sm.snapshot(7520)
        self.assertEqual(msnap.pose_mode, "mouse")
        self.assertTrue(msnap.viewer_left_on_mouse)
        self.assertIsNone(msnap.viewer_right_target)
        self.assertLess(msnap.head_turn_x, -0.5)

        # All mapped keys must lie within [0, 1] x [0, 1] normalized keyboard bounds
        for vk in MIRRORED_KEY_LAYOUT:
            spec = get_key_spec(vk, mirror=True)
            self.assertTrue(0.0 <= spec.u <= 1.0 and 0.0 <= spec.v <= 1.0)

    def test_arm_extension_and_retraction_kinematics(self) -> None:
        sm = CatStateMachine(idle_frame=1, blink_enabled=False, mouse_react_enabled=True)
        # Pressing a right-side key extends right_arm_ext progressively toward 1.0, then retracts toward 0.0
        sm.on_key_down(ord("A"), 1000, "A")
        s1 = sm.snapshot(1016)
        s2 = sm.snapshot(1032)
        s_full = sm.snapshot(1120)
        self.assertGreater(s1.right_arm_ext, 0.0)
        self.assertLess(s1.right_arm_ext, 1.0)
        self.assertGreater(s2.right_arm_ext, s1.right_arm_ext)
        self.assertEqual(s_full.right_arm_ext, 1.0)

        sm.on_key_up(ord("A"), 1140)
        s_ret = sm.snapshot(1250)  # past min_tap_hold_ms (~150ms since press)
        self.assertLess(s_ret.right_arm_ext, 1.0)
        self.assertGreater(s_ret.right_arm_ext, 0.0)
        s_done = sm.snapshot(1360)
        s_done = sm.snapshot(1460)
        self.assertEqual(s_done.right_arm_ext, 0.0)

        # Fast consecutive typing on the same arm ('A' -> 'F') retracts sharply first before extending onto 'F'
        sm.on_key_down(ord("A"), 2000, "A")
        for dt in range(16, 80, 16):
            sm.snapshot(2000 + dt)
        a_spec = get_key_spec(ord("A"), mirror=True)
        f_spec = get_key_spec(ord("F"), mirror=True)
        self.assertEqual(sm.snapshot(2080).right_arm_ext, 1.0)
        sm.on_key_up(ord("A"), 2090)
        sm.on_key_down(ord("F"), 2095, "F")
        retracting = sm.snapshot(2115)  # +20ms: retracting back toward chest along 'A' without sliding sideways!
        self.assertLess(retracting.right_arm_ext, 0.85)
        self.assertAlmostEqual(retracting.right_arm_uv[0], a_spec.u, places=3)
        min_ext = retracting.right_arm_ext
        for t in (2135, 2155, 2175, 2195, 2215):
            cur = sm.snapshot(t)
            min_ext = min(min_ext, cur.right_arm_ext)
        self.assertLess(min_ext, 0.45)  # Clearly pulled back before striking 'F'
        self.assertEqual(cur.right_arm_ext, 1.0)
        self.assertAlmostEqual(cur.right_arm_uv[0], f_spec.u, places=2)
        sm.on_key_up(ord("F"), 2250)

        # Mouse entry smoothly extends mouse_arm_ext
        sm.on_mouse_move(3000, dir_x=-0.5, dir_y=0.0)
        m1 = sm.snapshot(3024)
        self.assertGreater(m1.mouse_arm_ext, 0.0)
        self.assertLess(m1.mouse_arm_ext, 1.0)
        m_full = sm.snapshot(3120)
        m_full = sm.snapshot(3220)
        self.assertGreater(m_full.mouse_arm_ext, 0.9)

        # Keys across left half ('J' near center-left, 'K', 'L', 'P', Backspace) aim pupils & head accurately at key
        prev_ex = 0.0
        for vk_left, lbl in ((ord("J"), "J"), (ord("K"), "K"), (ord("L"), "L"), (ord("P"), "P"), (0x08, "⌫")):
            sm.on_key_down(vk_left, 4000, lbl)
            for dt in range(20, 420, 20):
                tsnap = sm.snapshot(4000 + dt)
            self.assertEqual(tsnap.pose_mode, "typing")
            self.assertLess(tsnap.eye_dx, prev_ex, f"eye_dx should shift further left for {lbl}")
            self.assertLess(tsnap.head_turn_x, 0.0, f"head_turn_x should lean toward {lbl}")
            self.assertGreater(tsnap.eye_dy, 0.70, f"eye_dy should look down at keyboard for {lbl}")
            prev_ex = tsnap.eye_dx
            sm.on_key_up(vk_left, 4430)
        self.assertLess(prev_ex, -0.75)  # Backspace aims sharply to far left edge of keyboard

        # Continuous eyelid opening/closing process when clicking cat's head (half-open intermediate stages)
        eye_sm = CatStateMachine(blink_enabled=False, petting_enabled=True)
        eye_sm.on_mouse_move(1000, dir_x=0.0, dir_y=-0.3, local_norm=(0.45, 0.20))
        self.assertEqual(eye_sm.snapshot(1300).eye_openness, 1.0)
        eye_sm.on_head_click(True, 1320)
        closing_mid = eye_sm.snapshot(1395)  # +75ms into ~185ms smooth close -> ~0.59 openness
        self.assertTrue(closing_mid.squint)
        self.assertGreater(closing_mid.eye_openness, 0.1)
        self.assertLess(closing_mid.eye_openness, 0.9)
        for t in range(1420, 1620, 30):
            closed_full = eye_sm.snapshot(t)
        self.assertEqual(closed_full.eye_openness, 0.0)
        eye_sm.on_head_click(False, 1650)
        for t in range(1700, 2060, 40):
            mid_open = eye_sm.snapshot(t)
        self.assertFalse(mid_open.squint)
        self.assertGreater(mid_open.eye_openness, 0.1)
        self.assertLess(mid_open.eye_openness, 0.95)
        for t in range(2100, 2400, 40):
            full_open = eye_sm.snapshot(t)
        self.assertEqual(full_open.eye_openness, 1.0)

        # After typing ends without new mouse motion, cat returns to idle sit smoothly (never grabs mouse)
        sm.on_key_up(ord("P"), 4500)
        # Transition progresses continuously from 0.0 toward 1.0 over ~210ms rather than snapping in 1 frame
        t_start = sm.snapshot(6010)
        self.assertEqual(t_start.pose_mode, "idle")
        self.assertEqual(t_start.pose_transition, 0.0)
        t_mid = sm.snapshot(6080)
        self.assertEqual(t_mid.pose_mode, "idle")
        self.assertEqual(t_mid.prev_pose_mode, "typing")
        self.assertGreater(t_mid.pose_transition, 0.0)
        self.assertLess(t_mid.pose_transition, 1.0)
        after = t_mid
        for dt in range(6110, 6400, 30):
            after = sm.snapshot(dt)
        self.assertEqual(after.pose_mode, "idle")
        self.assertEqual(after.pose_transition, 1.0)
        self.assertFalse(after.viewer_left_on_mouse)

    def test_idle_grooming_paw_lick_after_long_idle(self) -> None:
        sm = CatStateMachine(idle_frame=1, blink_enabled=False)
        self.assertEqual(sm.sleep_after_idle_ms, 15000)
        s0 = sm.snapshot(1000)
        self.assertEqual(s0.pose_mode, "idle")
        self.assertEqual(s0.groom_progress, 0.0)
        self.assertFalse(s0.squint)

        # Before 15s timeout, no grooming
        for t in range(1016, 15000, 500):
            s_wait = sm.snapshot(t)
        self.assertEqual(s_wait.groom_progress, 0.0)

        # Past 15s timeout, smoothly ramps into paw-licking with closed eyes & active lick phase
        s_start = sm.snapshot(16100)
        self.assertTrue(s_start.squint)
        self.assertGreater(s_start.groom_progress, 0.0)
        for t in range(16116, 16500, 16):
            s_full = sm.snapshot(t)
        self.assertEqual(s_full.groom_progress, 1.0)
        self.assertTrue(s_full.squint)
        s_next = sm.snapshot(16800)
        self.assertNotEqual(s_next.groom_lick_phase, s_full.groom_lick_phase)

        # Any key or mouse input exits grooming promptly
        sm.on_key_down(ord("A"), 17000, "A")
        s_wake = sm.snapshot(17050)
        self.assertEqual(s_wake.pose_mode, "typing")
        self.assertLess(s_wake.groom_progress, 1.0)

        # When cat sits in bottom-right corner (dir saturated left/up at -1,-1), screen_norm still drives desk mouse glide
        sm.reset_inputs()
        for t_step, sx_val, sy_val in ((18000, -0.9, -0.8), (18500, 0.6, 0.5)):
            for dt in range(0, 260, 16):
                sm.on_mouse_move(t_step + dt, dir_x=-1.0, dir_y=-1.0, screen_norm=(sx_val, sy_val))
                cur = sm.snapshot(t_step + dt)
            if sx_val < 0:
                far_left_mx, far_left_my = cur.mouse_dx, cur.mouse_dy
            else:
                right_mx, right_my = cur.mouse_dx, cur.mouse_dy
        self.assertGreater(right_mx - far_left_mx, 0.8)
        self.assertGreater(right_my - far_left_my, 0.7)

    def test_ignored_virtual_keys_and_held_snapshots(self) -> None:
        # F13-F24 (including F22=0x85), VK_PACKET, mouse VKs, and reserved bounds must be ignored
        for ignored in (0x00, 0x01, 0x02, 0x7C, 0x85, 0x87, 0xE7, 0xFF):
            self.assertTrue(is_ignored_vk(ignored), f"Expected vk={hex(ignored)} to be ignored")
        for allowed in (ord("A"), 0x20, 0x5B, 0x5C, 0x70, 0x7B, 0xA0, 0xA2, 0xA4):
            self.assertFalse(is_ignored_vk(allowed), f"Expected vk={hex(allowed)} to be allowed")

        sm = CatStateMachine(blink_enabled=False)
        sm.on_key_down(0x5B, 1000, bubble_label="⌘")
        # OS auto-repeat updates pressed_ms, while first_pressed_ms preserves initial press timestamp
        sm.on_key_down(0x5B, 1400, bubble_label="⌘")
        self.assertEqual(sm.held_keys_snapshot(), [(0x5B, 1000)])

        sm.on_mouse_button("left", True, 1100)
        self.assertEqual(sm.held_mouse_buttons_snapshot(), [("left", 1100)])
        sm.on_head_click(True, 1200)
        self.assertEqual(sm.head_press_state(), (True, 1200))

        sm.on_key_up(0x5B, 1500)
        sm.on_mouse_button("left", False, 1500)
        sm.on_head_click(False, 1500)
        self.assertEqual(sm.held_keys_snapshot(), [])
        self.assertEqual(sm.held_mouse_buttons_snapshot(), [])
        self.assertFalse(sm.head_press_state()[0])


if __name__ == "__main__":
    unittest.main()
