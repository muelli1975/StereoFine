"""Exact, bounded-memory L2 matching for OpenCV's quantized SIFT vectors."""
from __future__ import annotations

import numpy as np


def sift_ratio_matches(query: np.ndarray, train: np.ndarray) -> list:
    import cv2
    quantized = all(
        array.dtype == np.float32 and array.ndim == 2 and array.shape[1] == 128
        and np.isfinite(array).all() and np.all(array >= 0) and np.all(array <= 255)
        and np.array_equal(array, np.rint(array))
        for array in (query, train)
    )
    if not quantized or len(train) < 2:
        pairs = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False).knnMatch(query, train, k=2)
        return [m for pair in pairs if len(pair) == 2 for m, n in [pair] if m.distance < .75 * n.distance]
    # 128 * 255**2 and twice that value are both below 2**24. Thus dot
    # products, squared norms and distances are exact float32 integers for
    # these vectors. This is exhaustive matching, not an approximate index.
    norm = np.einsum("ij,ij->i", train, train)
    batch_size = max(1, min(512, (64 * 1024 * 1024) // (4 * len(train))))
    matches = []
    for start in range(0, len(query), batch_size):
        block = query[start:start + batch_size]
        distance = block @ train.T
        distance *= -2
        distance += norm[None, :]
        distance += np.einsum("ij,ij->i", block, block)[:, None]
        rows = np.arange(len(block))
        first = distance.argmin(axis=1)
        first_squared = distance[rows, first].copy()
        distance[rows, first] = np.inf
        second = distance.argmin(axis=1)
        first_distance = np.sqrt(np.maximum(first_squared, 0))
        second_distance = np.sqrt(np.maximum(distance[rows, second], 0))
        # Match Python/OpenCV's original float-distance ratio comparison,
        # including rounding at the threshold and lowest-index tie ordering.
        accepted = first_distance.astype(np.float64) < .75 * second_distance.astype(np.float64)
        for index in np.flatnonzero(accepted):
            matches.append(cv2.DMatch(int(start + index), int(first[index]), float(first_distance[index])))
    return matches
