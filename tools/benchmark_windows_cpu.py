"""Compare CPU profiles with the 1.3 analysis and export paths."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
from statistics import median
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import cv2
import psutil

from stereofine import processing
from stereofine.gui import StereoFineApp
from stereofine.metadata import find_exiftool_path
from stereofine.session import BrowsedSource
from stereofine.sidecar import load_sidecar, source_stamp_to_dict
from stereofine.sources import build_source_stamp, load_source, source_from_pair
from stereofine.worker import CancellationToken
from tools import benchmark_cpu_batch as batch_bench


def host_info():
    return dict(platform=platform.platform(), cpu=platform.processor(), logical_cpus=cv2.getNumberOfCPUs(),
                physical_cpus=psutil.cpu_count(logical=False), default_threads=cv2.getNumThreads(),
                opencv=cv2.__version__, python=platform.python_version(),
                parallel_framework=next(line.strip() for line in cv2.getBuildInformation().splitlines()
                                        if 'Parallel framework' in line))


def serial_options(method):
    return processing.ProcessingOptions(analysis_method=method, keep_loaded_pair=True,
                                        restart_alignment=True, save_sidecar=False)


def run_single(sources, mode, threads, method):
    cv2.ocl.setUseOpenCL(False)
    if threads:
        cv2.setNumThreads(threads)
    effective = cv2.getNumThreads()
    records = []
    original_detector = cv2.AKAZE_create
    original_matcher = cv2.BFMatcher

    with ThreadPoolExecutor(max_workers=2) as workers:
        for source in sources:
            loaded = load_source(source)
            stamp = build_source_stamp(source, loaded)
            stages = defaultdict(float)
            features = {}
            accepted = []

            def timer(label, func):
                def call(*args, **kwargs):
                    start = perf_counter()
                    result = func(*args, **kwargs)
                    stages[label] += perf_counter() - start
                    return result
                return call

            def reuse(candidate, **_kwargs):
                assert candidate == source
                assert build_source_stamp(source, loaded) == stamp
                return loaded

            class Detector:
                # The benchmark has no competing OpenCV activity in this process.
                # Restore the profile only after both detections have joined.
                future = None
                def detectAndCompute(self, image, mask):
                    if self.future is not None:
                        return self.future.result()
                    left = original_detector()
                    right = original_detector()
                    if not features:
                        raise RuntimeError('Missing right analysis view')
                    cv2.setNumThreads(1)
                    try:
                        first = workers.submit(left.detectAndCompute, image, mask)
                        self.future = workers.submit(right.detectAndCompute, features['right'], mask)
                        try:
                            return first.result()
                        finally:
                            self.future.result()
                    finally:
                        cv2.setNumThreads(effective)

            def record_sift(call):
                def wrapped(*args, **kwargs):
                    matches = call(*args, **kwargs)
                    accepted.extend((m.queryIdx, m.trainIdx, m.distance) for m in matches)
                    return matches
                return wrapped

            class Matcher:
                def __init__(self, *args, **kwargs):
                    self.matcher = original_matcher(*args, **kwargs)

                def knnMatch(self, *args, **kwargs):
                    pairs = self.matcher.knnMatch(*args, **kwargs)
                    accepted.extend((a.queryIdx, a.trainIdx, a.distance) for pair in pairs
                                    if len(pair) == 2 for a,b in [pair] if a.distance < .75*b.distance)
                    return pairs

            with ExitStack() as stack:
                for attr, label in [('load_source','load'), ('analyze_pair_features','alignment'),
                                    ('analyze_horizontal_disparity','disparity')]:
                    original = reuse if attr == 'load_source' and mode == 'reuse' else getattr(processing,attr)
                    stack.enter_context(patch.object(processing, attr, timer(label, original)))
                if method == 'AKAZE':
                    stack.enter_context(patch.object(cv2, 'BFMatcher', Matcher))
                else:
                    from stereofine import feature_matching
                    stack.enter_context(patch.object(feature_matching, 'sift_ratio_matches',
                                                     record_sift(feature_matching.sift_ratio_matches)))
                if mode == 'parallel-detect':
                    from stereofine import alignment
                    resize = alignment.resize_pair_for_analysis
                    def capture(*args, **kwargs):
                        result = resize(*args, **kwargs)
                        features['right'] = result[1]
                        return result
                    stack.enter_context(patch.object(alignment, 'resize_pair_for_analysis', capture))
                    stack.enter_context(patch.object(cv2, 'AKAZE_create', Detector))
                start = perf_counter()
                token = CancellationToken()
                try:
                    processed = processing.process_source(source, serial_options(method), cancellation=token)
                except RuntimeError as error:
                    if not str(error).startswith(('LMS-Schätzung', 'Zu wenige')):
                        raise
                    records.append(dict(source=source.base_name, seconds=perf_counter()-start, stages=dict(stages),
                                        signature=dict(state={'rejected': str(error)}, matches=None, preview=None)))
                    del loaded
                    continue
                analyzed = perf_counter()
                sidecar = load_sidecar(source.sidecar_path, expected_source=processed.source_stamp)
                session = BrowsedSource(source, processed.loaded_pair, processed.source_stamp, processed.state, sidecar)
                prepared = StereoFineApp._prepare_session_preview(session, (1024, 720), token, 'Farbig')
                done = perf_counter()
            stages['preview'] = done-analyzed
            stages.update(processed.state.alignment.correction.get('timings_seconds', {}))
            document = processed.state.to_sidecar(source=source_stamp_to_dict(processed.source_stamp))
            views = prepared.native_result[4][2]
            arrays = [*prepared.native_result[1:3], *views[False], *views[True]]
            signature = dict(state=asdict(document), matches=hashlib.sha256(repr(accepted).encode()).hexdigest(),
                             preview=[hashlib.sha256(array.tobytes()).hexdigest() for array in arrays])
            records.append(dict(source=source.base_name, seconds=done-start, stages=dict(stages), signature=signature))
            del loaded, prepared, processed, session, views, arrays
    assert any(row['signature']['preview'] is not None for row in records), 'All single sources rejected'
    return dict(seconds=sum(r['seconds'] for r in records), cv_threads=effective,
                peak_mib=batch_bench.memory_peak_mib(), records=records)


def invoke(root, task, profile, *, output=None, blas=1, private=None):
    args = [sys.executable, '-m', 'tools.benchmark_windows_cpu', task, '--root', str(root), '--profile', profile]
    if output:
        args.extend(('--output', str(output)))
    if private:
        args.extend(('--private', str(private)))
    env = dict(os.environ, OPENBLAS_NUM_THREADS=str(blas), OMP_NUM_THREADS='1')
    result = subprocess.run(args, env=env, text=True, capture_output=True, timeout=450)
    if result.returncode:
        print(result.stdout, result.stderr, file=sys.stderr, flush=True)
        result.check_returncode()
    return json.loads(result.stdout.splitlines()[-1])


def profile_summaries(runs):
    return {name: dict(seconds=round(median(row['seconds'] for row in samples),3),
                       peak_mib=round(max(row['peak_mib'] for row in samples),1), cv_threads=samples[0]['cv_threads'])
            for name, samples in runs.items()}


def compare_single(reference, candidate):
    for a,b in zip(reference['records'], candidate['records'], strict=True):
        assert a['source'] == b['source']
        for key in ('state','matches','preview'):
            assert a['signature'][key] == b['signature'][key], (a['source'], key)


def single_matrix(root, repetitions, private=None):
    def matrix(profiles, method):
        runs = defaultdict(list)
        reference = None
        for i in range(repetitions):
            ordered = profiles[i:]+profiles[:i]
            for name, mode, threads, blas in ordered:
                run = invoke(root, 'single-child', f'{mode},{threads},{method}', blas=blas, private=private)
                if reference is None:
                    reference = run
                compare_single(reference,run)
                runs[name].append(run)
                print('SINGLE', method, i+1, name, round(run['seconds'],3),
                      [(row['source'], round(row['seconds'],3),
                        {k:round(v,3) for k,v in row['stages'].items()}) for row in run['records']], flush=True)
        return runs

    profiles = [('default','serial',0,1), *[(f'cv-{n}','serial',n,1) for n in (1,2,4,8)]]
    akaze = matrix(profiles,'AKAZE')
    fastest = min(akaze, key=lambda n: median(row['seconds'] for row in akaze[n]))
    threads = next(n for name,_,n,_ in profiles if name == fastest)
    candidate = matrix([('matched-control','serial',threads,1), ('parallel-detect','parallel-detect',threads,1),
                        ('reuse','reuse',threads,1)], 'AKAZE')
    compare_single(akaze[fastest][0],candidate['matched-control'][0])
    sift = matrix([(f'blas-{n}','serial',threads,n) for n in (1,2,4)], 'SIFT') if not private else {}
    summary = dict(akaze=profile_summaries(akaze), fastest_akaze=fastest,
                   candidates=profile_summaries(candidate), sift=profile_summaries(sift))
    return dict(summary=summary, akaze=akaze, candidates=candidate, sift=sift)


def batch_matrix(root, output, repetitions):
    sources = batch_bench.make_sources(root)
    seed = None
    metrics = {}
    reference = None
    for phase in ('fresh','cached'):
        runs = defaultdict(list)
        modes = tuple(batch_bench.MODES)
        for i in range(repetitions):
            for mode in modes[i:]+modes[:i]:
                for source in sources:
                    source.sidecar_path.unlink(missing_ok=True)
                    if phase == 'cached':
                        source.sidecar_path.write_bytes(seed[source])
                run = invoke(root,'batch-child',mode,output=output)
                shutil.rmtree(output)
                if seed is None:
                    seed = {s:s.sidecar_path.read_bytes() for s in sources}
                    reference = run['signature']
                assert run['signature'] == reference, (phase, mode)
                assert all(flags == [phase == 'cached']*2 for flags in run['cache']), (phase, mode, run['cache'])
                runs[mode].append(run)
                print('BATCH',phase,i+1,mode,round(run['seconds'],3),round(run['peak_mib'],1),
                      {k:round(v,3) for k,v in run['stages'].items()},flush=True)
        metrics[phase] = dict(summary=profile_summaries(runs), runs=runs)
    for source in sources:
        source.sidecar_path.unlink(missing_ok=True)
    cancel = invoke(root,'batch-child','parallel-2cv,cancel',output=output)
    shutil.rmtree(output)
    resumed = invoke(root,'batch-child','parallel-2cv',output=output)
    assert resumed['signature'] == reference
    metrics['cancel_and_restart'] = cancel
    return metrics


def private_sources(root):
    paths = [Path(p) for p in json.loads(root.read_text(encoding='utf-8'))]
    return [source_from_pair(p, p.with_name(p.name.replace('_l.', '_r.')), p.parent) for p in paths]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('task',choices=('single','batch','single-child','batch-child'))
    parser.add_argument('--root',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--profile')
    parser.add_argument('--private',type=Path)
    parser.add_argument('--repetitions',type=int,default=2)
    args = parser.parse_args()
    if args.task == 'single-child':
        mode,threads,method = args.profile.split(',')
        sources = private_sources(args.private) if args.private else batch_bench.make_sources(args.root)
        print(json.dumps(run_single(sources,mode,int(threads),method),default=str))
        return
    if args.task == 'batch-child':
        mode,_,extra = args.profile.partition(',')
        print(json.dumps(batch_bench.run(args.root,args.output,mode,cancel=extra=='cancel')))
        return
    host = host_info()
    print('HOST',json.dumps(host),flush=True)
    with TemporaryDirectory(prefix='sf14-cpu-') as temporary:
        directory = Path(temporary)
        root = directory/'inputs'
        if args.private:
            assert args.task == 'single'
            dimensions = None
        else:
            dimensions = batch_bench.prepare(root)
        if args.task == 'single':
            metrics = single_matrix(root,args.repetitions,args.private)
        else:
            exiftool = find_exiftool_path()
            assert exiftool, 'ExifTool is required for the export comparison'
            host['exiftool'] = subprocess.check_output([str(exiftool),'-ver'],text=True).strip()
            metrics = batch_matrix(root,directory/'output',args.repetitions)
        output = Path(f'sf14-{args.task}-results.json')
        output.write_text(json.dumps(dict(host=host,dimensions=dimensions,metrics=metrics),indent=2),encoding='utf-8')
        print('SUMMARY',json.dumps(metrics['summary'] if args.task=='single' else
                                   {k:v['summary'] for k,v in metrics.items() if k in ('fresh','cached')}),flush=True)


if __name__ == '__main__':
    main()
