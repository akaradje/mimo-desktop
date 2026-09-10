import unittest
from motion import animate


class MotionTests(unittest.TestCase):
    def run_motion(self, overhead=0):
        now = [0.0]
        points = []
        def sleep(seconds):
            now[0] += seconds
        def guard():
            now[0] += overhead
        result = animate((-100, 20), (300, 220), 1000, lambda x,y: points.append((x,y)),
                         guard, clock=lambda: now[0], sleep=sleep)
        return points, result

    def test_exact_endpoint_and_monotonic(self):
        points, result = self.run_motion()
        self.assertEqual(points[-1], (300, 220))
        self.assertTrue(all(a[0] <= b[0] for a,b in zip(points,points[1:])))
        self.assertEqual(result['motion_elapsed_ms'], 1000)

    def test_slow_guard_skips_frames_not_duration_drift(self):
        points, result = self.run_motion(.05)
        self.assertEqual(points[-1], (300, 220))
        self.assertLess(result['frames_sent'], result['frames_planned'])
        self.assertLessEqual(result['motion_elapsed_ms'], 1060)

    def test_cancel_before_pointer_update(self):
        points = []
        def guard():
            raise RuntimeError('cancelled')
        with self.assertRaises(RuntimeError):
            animate((0,0), (10,10), 1, lambda *p: points.append(p), guard, sleep=lambda _: None)
        self.assertEqual(points, [])

    def test_easing_slower_at_ends(self):
        points, _ = self.run_motion()
        self.assertLess(points[1][0]-points[0][0], points[30][0]-points[29][0])


if __name__ == '__main__':
    unittest.main()
