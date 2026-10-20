"""Separate original-weight inference from geometric/raster evaluation.

Use only on a private manifest of full PairState diagnostic states; filenames
end in _SIFT to identify the common baseline. All inputs remain read-only.
This Linux CPU research driver is not a shipped application feature.
"""
from pathlib import Path
import json, sys, time, gc, hashlib, platform, resource, argparse
parser = argparse.ArgumentParser(description='Standalone CPU research; downloads public original model weights, never called by StereoFine')
parser.add_argument('method', choices=['lightglue_sift', 'lightglue_aliked', 'roma_fast', 'roma_precise'])
parser.add_argument('--manifest', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--lightglue-source', type=Path, required=True)
parser.add_argument('--roma-source', type=Path, required=True)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--names', nargs='*')
parser.add_argument('--limit', type=int)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
import cv2, numpy as np, torch
sys.path[:0] = [str(ROOT), str(args.lightglue_source.resolve()), str(args.roma_source.resolve() / 'src')]
from stereofine.sources import source_from_pair, load_source
from stereofine.geometry import apply_orientation
from stereofine.alignment import resize_pair_for_analysis
cv2.setNumThreads(4)
torch.set_num_threads(4)
torch.set_num_interop_threads(1)
torch.set_float32_matmul_precision('highest')
torch.manual_seed(0)
torch.hub.set_dir(str(args.cache.resolve()))
kind = args.method
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
manifest = json.loads(args.manifest.read_text())
cases = [r for r in manifest if r['name'].endswith('_SIFT') and (not args.names or r['name'] in args.names)]
if args.limit is not None:
    cases = cases[:args.limit]
start = time.monotonic()
extractor = matcher = model = None
if kind.startswith('lightglue'):
    from lightglue import LightGlue, SIFT, ALIKED
    from lightglue.utils import numpy_image_to_torch
    feature = 'sift' if kind.endswith('sift') else 'aliked'
    extractor = (SIFT if feature == 'sift' else ALIKED)(max_num_keypoints=4096).eval().cpu()
    matcher = LightGlue(features=feature).eval().cpu()
else:
    from romav2 import RoMaV2
    model = RoMaV2(RoMaV2.Cfg(setting='fast' if kind.endswith('fast') else 'precise'))
print('MODEL_READY', kind, 'load_seconds', time.monotonic() - start, 'torch', torch.__version__, 'gpu', torch.cuda.is_available(), flush=True)
for case in cases:
    tag = case['name'].rsplit('_', 1)[0] + '_' + kind
    dest = out / (tag + '.json')
    if dest.exists():
        continue
    sd = json.loads(Path(case['state']).read_text())
    t = sd['input_transform']
    loaded = load_source(source_from_pair(Path(case['left']), Path(case['right']), Path(case['left']).parent))
    if loaded.left.dtype != np.uint8 or loaded.right.dtype != np.uint8:
        raise ValueError('This pilot only supports the supplied 8-bit RGB inputs')
    a = apply_orientation(loaded.left, t['left_orientation'], t['left_mirror'])
    b = apply_orientation(loaded.right, t['right_orientation'], t['right_mirror'])
    if t['swap_eyes']:
        a, b = b, a
    a = np.ascontiguousarray(a)
    b = np.ascontiguousarray(b)
    ga, gb, scale = resize_pair_for_analysis(a, b, 3000)
    start = time.monotonic()
    try:
        with torch.inference_mode():
            if kind.startswith('lightglue'):
                fa = extractor.extract(numpy_image_to_torch(a), resize=1536)
                fb = extractor.extract(numpy_image_to_torch(b), resize=1536)
                result = matcher({'image0': fa, 'image1': fb})
                matches = result['matches'][0]
                p = fa['keypoints'][0, matches[:, 0]].numpy()
                q = fb['keypoints'][0, matches[:, 1]].numpy()
                scores = result['scores'][0].numpy()
            else:
                torch.manual_seed(0)
                pred = model.match(a, b)
                matches, overlap, _, _ = model.sample(pred, 5000)
                p, q = model.to_pixel_coordinates(matches, *a.shape[:2], *b.shape[:2])
                p, q = (p.cpu().numpy(), q.cpu().numpy())
                scores = overlap.cpu().numpy()
                del pred, matches
        elapsed = time.monotonic() - start
        p = (p + 0.5) * scale - 0.5
        q = (q + 0.5) * scale - 0.5
        np.savez_compressed(out / (tag + '_points.npz'), left=p, right=q, scores=scores, shape=ga.shape, scale=scale)
        row = {'source_roots': {'lightglue': str(args.lightglue_source), 'roma': str(args.roma_source)}, 'name': tag, 'kind': kind, 'case': case, 'points': len(p), 'seconds': elapsed, 'analysis_shape': ga.shape, 'scale': scale, 'device': 'cpu', 'torch': torch.__version__, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        dest.write_text(json.dumps(row, indent=2))
        print(tag, 'points', len(p), 'seconds', round(elapsed, 2), 'peakGiB', round(row['max_rss_kib'] / 1024 ** 2, 2), flush=True)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print('CASE_ERROR', tag, str(exc), flush=True)
    del loaded, a, b, ga, gb
    gc.collect()
