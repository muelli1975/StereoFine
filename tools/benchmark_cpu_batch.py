"""Measure the unmodified 1.3 batch with ordered, two-worker analysis lookahead."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import platform
import resource
import shutil
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Lock, local
from time import perf_counter, sleep
from unittest.mock import patch
from urllib.request import urlopen

import cv2
from PIL import Image

from stereofine import batch, export, processing
from stereofine.metadata import find_exiftool_path
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
    "serial-2cv": (1, 2),
    "parallel-2cv": (2, 2),
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
    """Hold at most two pairs, including the one currently being exported."""

    def __init__(self, sources, pool, analyze):
        self.sources = sources
        self.pool = pool
        self.analyze = analyze
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
        if source not in self.pending:
            self._submit(index, options, cancellation)
        if index + 1 < len(self.sources):
            self._submit(index + 1, options, cancellation)
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


def run(root, output, mode, cancel=False):
    workers, cv_threads = MODES[mode]
    cv2.ocl.setUseOpenCL(False)
    if cv_threads is not None:
        cv2.setNumThreads(cv_threads)
    sources = make_sources(root)
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
            analyze = OrderedAnalysis(sources, pool, analyze)
        stack.enter_context(patch.object(batch, "process_source", analyze))
        start = perf_counter()
        cpu = resource.getrusage(resource.RUSAGE_SELF)
        try:
            result = batch.run_batch(sources, options, cancellation=token, progress=progress)
        except JobCancelled:
            if not cancel:
                raise
            result = None
    seconds = perf_counter() - start
    usage = resource.getrusage(resource.RUSAGE_SELF)
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
            record=asdict(p.analysis_record),
            framing=asdict(p.state.framing),
            sbs=output_signature(e.sbs_path), anaglyph=output_signature(e.anaglyph_path),
        ))
    expected = [(index, phase) for index in range(1, len(sources) + 1)
                for phase in ("analysis", "measured", "export", "preview")]
    assert events == expected, events
    return dict(seconds=seconds, cpu=(usage.ru_utime - cpu.ru_utime) + (usage.ru_stime - cpu.ru_stime),
                peak_mib=usage.ru_maxrss / 1024, cv_threads=cv2.getNumThreads(),
                cache=cache, stages=timings, signature=signature)


def child(root, output, mode, cancel=False):
    cmd = [sys.executable, "-m", "tools.benchmark_cpu_batch", "--child",
           str(root), str(output), mode]
    if cancel:
        cmd.append("--cancel")
    p = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=240)
    if p.returncode:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        p.check_returncode()
    return json.loads(p.stdout.splitlines()[-1])


def compare(reference, candidate):
    keys = ("framing", "near_permille", "far_permille", "total_permille", "traffic",
            "status", "uncertain", "sbs_size", "anaglyph_size", "sbs_pixels",
            "anaglyph_pixels", "sbs_file", "anaglyph_file")
    counts = Counter({key: 0 for key in keys})
    details = []
    for a, b in zip(reference["signature"], candidate["signature"], strict=True):
        assert a["source"] == b["source"]
        observed = {"framing": a["framing"] == b["framing"]}
        for key in keys[1:7]:
            observed[key] = a["record"][key] == b["record"][key]
        for kind in ("sbs", "anaglyph"):
            for field in ("size", "pixels", "file"):
                observed[f"{kind}_{field}"] = a[kind][field] == b[kind][field]
        different = [key for key in keys if not observed[key]]
        if different:
            details.append(dict(source=a["source"], different=different))
        counts.update(key for key in keys if observed[key])
    return dict(counts=counts, differences=details)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", nargs=3)
    parser.add_argument("--cancel", action="store_true")
    args = parser.parse_args()
    if args.child:
        root, output, mode = args.child
        print(json.dumps(run(Path(root), Path(output), mode, cancel=args.cancel)))
        return
    assert find_exiftool_path(), "ExifTool is required for the timed export"
    hw = {
        "cpu": platform.processor(), "cpus": len(os.sched_getaffinity(0)),
        "opencv": cv2.__version__, "python": platform.python_version(),
        "platform": platform.platform(),
        "exiftool": subprocess.check_output(["exiftool", "-ver"], text=True).strip(),
    }
    print("HOST", json.dumps(hw), flush=True)
    measurements = {}
    comparisons = {}
    with TemporaryDirectory(prefix="stereofine-cpu-bench-") as tmp:
        root = Path(tmp) / "inputs"
        dims = prepare(root)
        sources = make_sources(root)
        cache_seed = None
        orders = (
            ("serial-default", "parallel-2cv", "serial-2cv"),
            ("serial-2cv", "serial-default", "parallel-2cv"),
            ("parallel-2cv", "serial-2cv", "serial-default"),
        )
        for phase in ("fresh", "cached"):
            runs = {mode: [] for mode in MODES}
            for repetition, order in enumerate(orders, 1):
                one_round = {}
                for mode in order:
                    for source in sources:
                        source.sidecar_path.unlink(missing_ok=True)
                    if phase == "cached":
                        for source in sources:
                            source.sidecar_path.write_bytes(cache_seed[source])
                    output = Path(tmp) / "outputs"
                    summary = child(root, output, mode)
                    if cache_seed is None:
                        cache_seed = {s: s.sidecar_path.read_bytes() for s in sources}
                    shutil.rmtree(output)
                    one_round[mode] = summary
                    runs[mode].append(summary)
                    short = {k: v for k, v in summary.items() if k != "signature"}
                    print("RUN", phase, repetition, mode, json.dumps(short), flush=True)
                for mode in MODES:
                    comparison = compare(one_round["serial-default"], one_round[mode])
                    comparisons[f"{phase}/{repetition}/{mode}"] = comparison
                    print("CHECK", phase, repetition, mode, json.dumps(comparison), flush=True)
            measurements[phase] = runs

        for source in sources:
            source.sidecar_path.unlink(missing_ok=True)
        output = Path(tmp) / "outputs"
        cancel = child(root, output, "parallel-2cv", cancel=True)
        shutil.rmtree(output)
        resumed = child(root, output, "parallel-2cv")
        resume_check = compare(measurements["fresh"]["serial-default"][0], resumed)
        print("CANCEL_AND_RESTART", json.dumps([cancel, resumed["cache"], resume_check]), flush=True)
    aggregates = {}
    for phase, modes in measurements.items():
        aggregates[phase] = {
            mode: {
                "median_s": median(r["seconds"] for r in runs),
                "peak_mib": max(r["peak_mib"] for r in runs),
                "seconds": [r["seconds"] for r in runs],
                "cv_threads": runs[0]["cv_threads"],
                "stage_medians": {k: median(r["stages"].get(k, 0) for r in runs)
                                  for k in set().union(*(r["stages"] for r in runs))},
            }
            for mode, runs in modes.items()
        }
    print("TOTALS", json.dumps(aggregates), flush=True)
    Path("cpu-batch-results.json").write_text(json.dumps(
        dict(host=hw, inputs=dims, measurements=measurements, comparisons=comparisons,
             aggregates=aggregates, cancel=cancel, resumed=resumed, resume_check=resume_check),
        indent=2, sort_keys=True,
    ) + "\n")


if __name__ == "__main__":
    main()
