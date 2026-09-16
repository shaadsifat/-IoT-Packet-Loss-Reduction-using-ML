"""
STEP 3 - Live network congestion, measured at the moment each packet is
actually being sent during a running stream.

This is the piece that makes sending pace matter, which a fixed-in-advance
simulation could never do: congestion is pulled toward a target that
depends on the ACTUAL speed_ms this specific run is using right now (fast
pacing -> more congestion -> more loss; slow pacing -> less congestion ->
less loss), plus small live jitter so it isn't a flat constant either.

Called once per packet, live, from transmission.py - never precomputed for
a whole batch in advance.
"""

def clip(x, lo, hi):
    return max(lo, min(hi, x))


def next_congestion(prev_congestion, speed_ms, rng):
    target = clip(1.4 - (speed_ms / 120.0) * 0.8, 0.6, 1.4)
    pulled = prev_congestion + (target - prev_congestion) * 0.15
    return clip(pulled + rng.uniform(-0.06, 0.06), 0.5, 1.5)
