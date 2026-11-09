"""Public fixture preparation and ordered batch measurement for StereoFine 1.3."""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
from io import BytesIO
import json
from pathlib import Path
from sys import platform as sys_platform
if sys_platform != "win32":
    import resource
import psutil
from threading import Lock, local
from time import perf_counter, sleep
from unittest.mock import patch
from urllib.request import urlopen

import cv2
from PIL import Image

from stereofine import batch, export, processing
from stereofine.sources import SourceDirectoryIndex, source_from_pair, source_from_stereo_file
from stereofine.worker import CancellationToken, JobCancelled

RAW = "https://raw.githubusercontent.com"
HIGH_RES = f"{RAW}/gengshan-y/high-res-stereo/bd657d4e855c8dfa3ba1eeb7b894111b9ac14646/data-mbtest"
FOUNDATION = f"{RAW}/NVlabs/FoundationStereo/6e8806816b533e4d13ddbb95ffa907b797060a62/assets"
OPENCV = f"{RAW}/opencv/opencv/4.13.0/samples/data"
SCENES = (
    ("Aloe", "lr-jpg", f"{OPENCV}/aloeL.jpg", f"{OPENCV}/aloeR.jpg"),
    ("CrusadeP", "sbs-png", f"{HIGH_RES}/CrusadeP/im0.png", f"{HIGH_RES}/CrusadeP/im1.png"),
    ("DanceA", "lr-png", f"{HIGH_RES}/0593_8_0661_1/im0.png", f"{HIGH_RES}/0593_8_0661_1/im1.png"),
    ("Foundation", "lr-jpg", f"{FOUNDATION}/left.png", f"{FOUNDATION}/right.png"),
    ("DanceB", "sbs-jpg", f"{HIGH_RES}/0600_4_0641_1/im0.png", f"{HIGH_RES}/0600_4_0641_1/im1.png"),
)
MODES = {
    "serial-default": (1, None),
    "serial-4cv": (1, 4),
    "parallel-1cv": (2, 1),
    "parallel-2cv": (2, 2),
    "parallel-4cv": (2, 4),
    "parallel-8cv": (2, 8),
    "workers3-2cv": (3, 2),
    "workers3-4cv": (3, 4),
    "workers3-8cv": (3, 8),
    "workers4-1cv": (4, 1),
    "workers4-2cv": (4, 2),
    "workers4-4cv": (4, 4),
}
MAKE = "StereoFine Benchmark"


def read_view(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=40) as response:
                with Image.open(BytesIO(response.read())) as image:
                    return image.convert("RGB")
        except OSError:
            if attempt == 2:
                raise
            sleep(2 ** attempt)


def make_sources(root):
    sources = []
    for scene, layout, _, _ in SCENES:
        suffix = layout.split("-")[1]
        if layout.startswith("lr-"):
            left = root / f"{scene}_L.{suffix}"
            right = root / f"{scene}_R.{suffix}"
            sources.append(source_from_pair(left, right, root))
        else:
            path = root / f"{scene}.{suffix}"
            sources.append(source_from_stereo_file(path, root))
    return sources


def prepare(root):
    root.mkdir()
    dimensions = {}
    exif = Image.Exif()
    exif[271] = MAKE
    exif[306] = "2026:11:08 10:12:00"
    for (scene, layout, left_url, right_url), source in zip(SCENES, make_sources(root), strict=True):
        left, right = read_view(left_url), read_view(right_url)
        assert left.size == right.size, (scene, left.size, right.size)
        dimensions[scene] = dict(size=left.size, layout=layout, urls=[left_url, right_url])
        if source.kind == "pair":
            left.save(source.left_path, quality=97, subsampling=0, exif=exif)
            right.save(source.right_path, quality=97, subsampling=0, exif=exif)
        else:
            sbs = Image.new("RGB", (left.width * 2, left.height))
            sbs.paste(left, (0, 0))
            sbs.paste(right, (left.width, 0))
            sbs.save(source.left_path, quality=97, subsampling=0, exif=exif)
        print("Input", scene, left.size, layout, flush=True)
    return dimensions


class OrderedAnalysis:
    """Bound retained pairs, including the one currently being exported."""

    def __init__(self, sources, pool, analyze, lookahead):
        self.sources = sources
        self.pool = pool
        self.analyze = analyze
        self.lookahead = lookahead
        self.pending = {}
        self.thread_state = local()

    def _submit(self, index, options, token):
        source = self.sources[index]

        def analyze():
            if not hasattr(self.thread_state, "directory_index"):
                self.thread_state.directory_index = SourceDirectoryIndex()
            return self.analyze(
                source, replace(options, save_sidecar=False), cancellation=token,
                directory_index=self.thread_state.directory_index,
            )

        self.pending[source] = self.pool.submit(analyze)

    def __call__(self, source, options, *, cancellation, directory_index):
        cancellation.raise_if_cancelled()
        index = self.sources.index(source)
        for position in range(index, min(index + self.lookahead, len(self.sources))):
            if self.sources[position] not in self.pending:
                self._submit(position, options, cancellation)
        processed = self.pending.pop(source).result()
        cancellation.raise_if_cancelled()
        if options.save_sidecar:
            batch.save_sidecar(
                source.sidecar_path, processed.state.to_sidecar(
                    source=batch.source_stamp_to_dict(processed.source_stamp)
                ),
            )
        return processed


def output_signature(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with Image.open(path) as image:
        assert image.getexif().get(271) == MAKE, path
        date = image.getexif().get(306)
        assert date == "2026:11:08 10:12:00", (path, date)
        return {
            "name": path.name, "size": image.size,
            "pixels": hashlib.sha256(image.tobytes()).hexdigest(),
            "file": digest,
        }


def memory_peak_mib():
    if sys_platform == "win32":
        return psutil.Process().memory_info().peak_wset / (1024 ** 2)
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run(root, output, mode, cancel=False, *, sources=None):
    workers, cv_threads = MODES[mode]
    cv2.ocl.setUseOpenCL(False)
    if cv_threads is not None:
        cv2.setNumThreads(cv_threads)
    sources = make_sources(root) if sources is None else sources
    options = batch.BatchRunOptions(output_folder=output)
    timings = defaultdict(float)
    lock = Lock()
    events = []
    token = CancellationToken()

    def timer(name, fn):
        def timed(*args, **kwargs):
            start = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                with lock:
                    timings[name] += perf_counter() - start
        return timed

    def progress(event):
        events.append((event.index, event.stage))
        if cancel and event.index == 2 and event.stage == "analysis":
            token.cancel()

    with ExitStack() as stack:
        for module, attr, label in (
            (processing, "load_source", "load"),
            (processing, "analyze_pair_features", "alignment"),
            (processing, "analyze_horizontal_disparity", "disparity"),
            (batch, "render_final_pair", "render"),
            (batch, "_export_preview", "preview_pair"),
            (batch, "save_pair_outputs", "export"),
            (export, "copy_metadata_without_preview_or_orientation", "metadata"),
        ):
            stack.enter_context(patch.object(module, attr, timer(label, getattr(module, attr))))
        analyze = timer("process_source", batch.process_source)
        if workers > 1:
            pool = stack.enter_context(ThreadPoolExecutor(max_workers=workers))
            analyze = OrderedAnalysis(sources, pool, analyze, workers)
        stack.enter_context(patch.object(batch, "process_source", analyze))
        start = perf_counter()
        cpu = psutil.Process().cpu_times()
        try:
            result = batch.run_batch(sources, options, cancellation=token, progress=progress)
        except JobCancelled:
            if not cancel:
                raise
            result = None
    seconds = perf_counter() - start
    usage = psutil.Process().cpu_times()
    if cancel:
        assert result is None and token.cancelled
        assert len(list(output.rglob("*.jpg"))) == 2
        assert sources[0].sidecar_path.is_file()
        assert all(not source.sidecar_path.exists() for source in sources[1:])
        return {"progress": events, "seconds": seconds, "sidecars": 1, "files": 2}

    assert not result.failed, result.failed
    assert result.exported_count == len(sources), result
    assert not result.warnings, result.warnings
    signature = []
    cache = []
    for item in result.items:
        p, e = item.processed, item.export
        cache.append([p.alignment_from_cache, p.disparity_from_cache])
        assert len(e.metadata_results) == 2 and all(r.success for r in e.metadata_results)
        signature.append(dict(
            source=p.source.base_name,
            record={k: v for k, v in asdict(p.analysis_record).items() if k in (
                'model', 'matches', 'inliers', 'vertical_error_mean_px', 'near_permille', 'far_permille',
                'total_permille', 'traffic', 'status', 'uncertain')},
            framing=asdict(p.state.framing),
            sbs=output_signature(e.sbs_path), anaglyph=output_signature(e.anaglyph_path),
        ))
    expected = [(index, phase) for index in range(1, len(sources) + 1)
                for phase in ("analysis", "measured", "export", "preview")]
    assert events == expected, events
    return dict(seconds=seconds, cpu=(usage.user - cpu.user) + (usage.system - cpu.system),
                peak_mib=memory_peak_mib(), cv_threads=cv2.getNumThreads(),
                cache=cache, stages=timings, signature=signature)

