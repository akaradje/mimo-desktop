"""Separate transport completion, input delivery, and semantic verification."""
INPUT_OPERATIONS = {'click', 'click_element', 'type_text', 'paste_text', 'press_key',
                    'scroll', 'drag', 'drag_between'}


def annotate(method, result):
    if result.get('ok') and method in INPUT_OPERATIONS:
        result['outcome'] = 'input_delivered'
        result['verification'] = 'not_performed'
        result['retry_automatically'] = False
    elif result.get('ok') and method == 'verify_text':
        result['outcome'] = result.get('verification', 'unavailable')
    elif result.get('ok') and method == 'set_window_rect':
        result['outcome'] = 'geometry_verified' if result.get('matched') else 'geometry_mismatch'
    return result
