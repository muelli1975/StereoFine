"""Deterministic stereo images with known pixel disparities; no private photos."""
import cv2
import numpy as np


def scene(seed=23, sky=False, small=False, exposure=False, occlusion=False):
    rng = np.random.default_rng(seed)
    h, w = 960, 1440
    left = cv2.GaussianBlur(rng.integers(0, 256, (h, w), dtype=np.uint8), (3, 3), 0)
    right = cv2.warpAffine(left, np.float32([[1, 0, -8], [0, 1, 0]]), (w, h))
    if sky:
        left[:h//2] = 145
        right[:h//2] = 145
    for x, y, d, size in [(300, 650, -24, 100), (1180, 810, 48, 64 if small else 140)]:
        patch = cv2.GaussianBlur(rng.integers(0, 256, (size, size), dtype=np.uint8), (3, 3), 0)
        left[y:y+size, x:x+size] = patch
        right[y:y+size, x-d:x-d+size] = patch
    if occlusion:
        right[510:610, 600:700] = rng.integers(0, 256, (100, 100), dtype=np.uint8)
    if exposure:
        right = np.clip(right.astype(float)*.8+15, 0, 255).astype(np.uint8)
    return [np.repeat(a[..., None], 3, axis=2) for a in [left, right]]
