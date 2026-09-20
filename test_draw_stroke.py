import unittest
from unittest.mock import Mock

from desktop_control import Desktop, absolute_move_event


class DrawStrokeTests(unittest.TestCase):
    def test_interpolate_respects_step_and_endpoints(self):
        pts = Desktop._interpolate_polyline([(0, 0), (10, 0)], step=2)
        self.assertEqual(pts[0], (0, 0))
        self.assertEqual(pts[-1], (10, 0))
        self.assertGreaterEqual(len(pts), 5)
        self.assertTrue(all(b[0] >= a[0] for a, b in zip(pts, pts[1:])))

    def test_interpolate_short_segment(self):
        pts = Desktop._interpolate_polyline([(3, 4), (4, 4)], step=2)
        self.assertEqual(pts, [(3, 4), (4, 4)])

    def test_absolute_move_event_shape(self):
        ev = absolute_move_event(100, 200)
        self.assertEqual(ev.type, 0)
        self.assertEqual(ev.payload.mi.dwFlags & 0x8001, 0x8001)
        self.assertTrue(0 <= ev.payload.mi.dx <= 65535)
        self.assertTrue(0 <= ev.payload.mi.dy <= 65535)

    def test_draw_stroke_rejects_bad_paths(self):
        d = Desktop(Mock(), Mock(), Mock())
        d.target = lambda args: {
            'hwnd': 1, 'pid': 1, 'path': 'x',
            'client': {'x': 0, 'y': 0, 'width': 100, 'height': 100},
        }
        d.point = lambda args, w, smooth=False: None
        d.check_target = lambda w, foreground=True: None
        with self.assertRaises(ValueError):
            d.draw_stroke({'paths': []})
        with self.assertRaises(ValueError):
            d.draw_stroke({'paths': [[{'x': 0, 'y': 0}]]})


if __name__ == '__main__':
    unittest.main()
