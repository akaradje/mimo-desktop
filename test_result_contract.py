import unittest
from result_contract import annotate


class ContractTests(unittest.TestCase):
    def test_input_delivery_not_verification(self):
        for method in ('type_text', 'paste_text', 'drag_between', 'click'):
            result = annotate(method, {'ok': True})
            self.assertEqual(result['outcome'], 'input_delivered')
            self.assertEqual(result['verification'], 'not_performed')
            self.assertFalse(result['retry_automatically'])

    def test_verification_outcomes_preserved(self):
        for status in ('verified', 'mismatch', 'unavailable'):
            self.assertEqual(annotate('verify_text', {'ok': True, 'verification': status})['outcome'], status)

    def test_failed_input_not_delivered(self):
        self.assertNotIn('outcome', annotate('type_text', {'ok': False}))

    def test_geometry_not_task_success(self):
        self.assertEqual(annotate('set_window_rect', {'ok': True, 'matched': False})['outcome'], 'geometry_mismatch')


if __name__ == '__main__':
    unittest.main()
