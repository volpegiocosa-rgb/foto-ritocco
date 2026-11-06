#!/usr/bin/env python3
"""Self-check without models: python test_engine.py"""
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import restore_engine as e

rng = np.random.default_rng(0)
img = rng.integers(0, 255, (700, 1100, 3), np.uint8)

# Tiling: output size follows the scale, and no tile seam or misplacement.
up = lambda t: cv2.resize(t, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
assert np.array_equal(e.tiled(img, up, scale=4, tile=256), up(img))
assert np.array_equal(e.tiled(img, lambda t: t, tile=512, pad=32), img)

# White balance: a reference patch becomes neutral.
cast = np.full((100, 100, 3), (120, 150, 200), np.uint8)
assert np.ptp(e.white_balance(cast, (10, 10, 20, 20)).reshape(-1, 3).mean(axis=0)) < 2

# White level: two different exposures of one surface reach the same gray.
for shade in ((120, 150, 200), (90, 110, 170)):
    out = e.white_balance(np.full((20, 20, 3), shade, np.uint8), (0, 0, 20, 20), 200)
    assert abs(out.mean() - 200) <= 1 and np.ptp(out.reshape(-1, 3).mean(axis=0)) < 1

# Perspective: a rectangle stays a rectangle of the same size.
assert e.perspective(img, [[0, 0], [99, 0], [99, 49], [0, 49]]).shape == (49, 99, 3)

# Gamma: above 1 brightens.
assert e.gamma(np.full((2, 2, 3), 100, np.uint8), 1.5).mean() > 100

# Polygon mask: inside set, outside clear.
p = e.build_mask((100, 100, 3), [], [[[10, 10], [30, 10], [10, 30]]], None, grow=0)
assert p[12, 12] == 1 and p[29, 29] == 0

# Tone tools: contrast spreads tones, highlights darken only above the start.
ramp = np.dstack([np.tile(np.arange(256, dtype=np.uint8), (8, 1))] * 3)
assert np.all(np.diff(cv2.cvtColor(e.contrast(ramp, 0.5), cv2.COLOR_BGR2GRAY)[0].astype(int)) >= 0)
assert e.highlights(np.full((2, 2, 3), 250, np.uint8), 0.5).mean() < 250
assert e.highlights(np.full((2, 2, 3), 80, np.uint8), 0.5).mean() == 80

# Vibrance: chroma rises, hue holds, gray stays gray.
hsv = lambda m: cv2.cvtColor(m, cv2.COLOR_BGR2HSV).reshape(-1, 3).mean(axis=0)
felt = np.full((4, 4, 3), (110, 120, 60), np.uint8)
assert hsv(e.vibrance(felt, 0.4))[1] > hsv(felt)[1] and abs(hsv(e.vibrance(felt, 0.4))[0] - hsv(felt)[0]) < 3
assert np.ptp(e.vibrance(np.full((4, 4, 3), 128, np.uint8), 0.4)) <= 1

# Mask: rectangles and growth.
m = e.build_mask((100, 100, 3), [(40, 40, 10, 10)], [], None, grow=2)
assert m[38, 38] == 1 and m[30, 30] == 0

with tempfile.TemporaryDirectory() as d:
    src = os.path.join(d, "in.png")
    e.save(img, src, 85)
    before = open(src, "rb").read()
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "restore_engine.py")

    # The original cannot be overwritten, not even through a second path.
    for target in (src, os.path.join(d, ".", "in.png")):
        r = subprocess.run([sys.executable, script, "process", src, target], capture_output=True, text=True)
        assert r.returncode != 0 and "refused" in r.stderr
    assert open(src, "rb").read() == before

    # Without options, geometry stays intact: perspective is never automatic.
    out = os.path.join(d, "out.png")
    subprocess.run([sys.executable, script, "process", src, out], check=True, capture_output=True)
    assert np.array_equal(e.load(out), img)

print("ok")
