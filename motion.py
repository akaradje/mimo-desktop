"""Deadline-based eased motion. Skip overdue frames instead of accumulating drift."""
import math
import time


def animate(start, end, duration_ms, move, guard, clock=None, sleep=None):
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    seconds = max(.001, duration_ms / 1000)
    frames = max(1, math.ceil(seconds * 60))
    started = clock()
    frame = 1
    sent = 0
    while frame <= frames:
        deadline = started + seconds * frame / frames
        sleep(max(0, deadline-clock()))
        guard()
        t = min(1, max(frame/frames, (clock()-started)/seconds))
        eased = t*t*(3-2*t)
        x = round(start[0] + (end[0]-start[0])*eased)
        y = round(start[1] + (end[1]-start[1])*eased)
        move(x, y)
        sent += 1
        if t >= 1:
            break
        frame = max(frame+1, math.floor((clock()-started)/seconds*frames)+1)
        # Always send the exact final point even when callbacks ran past deadline.
        frame = min(frame, frames)
    return {'frames_sent': sent, 'frames_planned': frames,
            'motion_elapsed_ms': round((clock()-started)*1000)}
