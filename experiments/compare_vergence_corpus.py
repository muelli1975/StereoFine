"""Read-only recovery and guarded comparison of the historical stereo pairs."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from zipfile import ZipFile

import cv2
import numpy as np

from compare_rectification import withheld
from compare_vergence_seeds import WIDTH, alignment, measured_render, run_pair, stats
from native_subpixel import map_pixel_centers, refine_native_correspondences
from select_neural_candidate import assess_measurements, control_points
from select_subpixel_candidate import confirmation_split
from stereofine.config import SUPPORTED_IMAGE_EXTENSIONS
from stereofine.geometry import apply_orientation
from stereofine.inputs import master_to_uint8
from stereofine.sources import load_source, source_from_pair

REFERENCE = Path(__file__).resolve().parents[1] / 'docs/CORRESPONDENCE_COVERAGE_1.1_RESULTS.json'


@dataclass(frozen=True)
class InputFile:
    path: Path
    member: str | None = None

    @property
    def suffix(self):
        return Path(self.member or self.path.name).suffix.lower()

    @contextmanager
    def open(self):
        if self.member is None:
            with self.path.open('rb') as file:
                yield file
        else:
            with ZipFile(self.path) as archive, archive.open(self.member) as file:
                yield file


def load_reference(path):
    pairs = {}
    for row in json.loads(path.read_text(encoding='utf-8'))['cases']:
        name, method = row['name'].rsplit('_', 1)
        hashes = {eye: row['inputs_sha256'][eye] for eye in ('left', 'right')}
        record = pairs.setdefault(name, dict(hashes=hashes, shape=row['native_shape'], methods=[]))
        if record['hashes'] != hashes or record['shape'] != row['native_shape']:
            raise ValueError(f'Inconsistent source record for {name}')
        record['methods'].append(method)
    return pairs


def index_inputs(folder, wanted):
    """Match exact bytes regardless of the archive and entry filenames."""
    found = {}
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() == '.zip':
            with ZipFile(path) as archive:
                inputs = [InputFile(path, entry.filename) for entry in archive.infolist() if not entry.is_dir()]
        else:
            inputs = [InputFile(path)]
        for source in inputs:
            if source.suffix not in SUPPORTED_IMAGE_EXTENSIONS:
                continue
            with source.open() as file:
                digest = hashlib.file_digest(file, 'sha256').hexdigest()
            if digest in wanted:
                found.setdefault(digest, source)
    return found


def load_pair(name, record, found, temporary_root):
    # Decode a fresh copy of each verified eye through the production loader.
    # Do not extract archive paths or open/write any uploaded sidecars.
    with tempfile.TemporaryDirectory(prefix='pair-', dir=temporary_root) as folder:
        root = Path(folder)
        paths = []
        for eye, digest in record['hashes'].items():
            source = found[digest]
            with source.open() as file:
                payload = file.read()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f'{name}: source changed after inventory')
            target = root / (eye + source.suffix)
            target.write_bytes(payload)
            paths.append(target)
        pair = load_source(source_from_pair(*paths, root))
    left = apply_orientation(pair.left, '180' if name.startswith('ixus_') else '0')
    if tuple(left.shape[:2]) != tuple(record['shape']) or left.shape != pair.right.shape:
        raise ValueError(f'{name}: source dimensions differ from reference')
    return tuple(np.ascontiguousarray(master_to_uint8(eye)) for eye in (left, pair.right))


def confirmation_points(left, right):
    """Native photometric controls from the half of the reserved blocks not used for selection."""
    lg, rg, scale = alignment.resize_pair_for_analysis(left, right, WIDTH)
    lp, rp, _ = control_points(lg, rg)
    reserved = withheld(lp)
    lp, rp = lp[reserved], rp[reserved]
    confirmation = confirmation_split(lp) == 1
    lp, rp = (map_pixel_centers(points[confirmation], lg.shape, left.shape) for points in (lp, rp))
    native = [cv2.cvtColor(eye, cv2.COLOR_RGB2GRAY) for eye in (left, right)]
    refined, valid, _ = refine_native_correspondences(*native, lp, rp)
    return lp[valid], refined[valid], scale


def measure(left, right, fit, lp, rp):
    pair, p, q, valid = measured_render(left, right, fit['correction'], lp, rp)
    return q[:, 1] - p[:, 1], p[:, 0] - q[:, 0], valid, pair[0].shape[:2]


def evaluate(left, right, methods):
    lp, rp, scale = confirmation_points(left, right)
    area = np.prod(left.shape[:2])
    for method in methods:
        cv2.setRNGSeed(1337)
        fits, info = run_pair(left, right, method, screen=True, screen_fold=0)
        baseline, base_dx, valid, base_shape = measure(left, right, fits['baseline'], lp, rp)
        row = dict(method=method, selected='baseline', baseline_model=fits['baseline']['model'],
                   native_confirmation_points=len(lp), baseline_retained=int(valid.sum()),
                   baseline_native=stats(baseline[valid]), fit=info)
        if info.get('screen', {}).get('accepted'):
            trial, trial_dx, retained, trial_shape = measure(left, right, fits['bilinear'], lp, rp)
            common = valid & retained
            loss = int((valid & ~retained).sum())
            area_loss = float(max(0, np.prod(base_shape) - np.prod(trial_shape)) / area)
            decision = assess_measurements(lp[common], baseline[common], trial[common], left.shape, scale)
            if loss > .02 * valid.sum() or area_loss > .03:
                decision.update(accepted=False, reason='additional_crop_loss')
            difference = (trial_dx - base_dx)[common]
            row.update(native_confirmation=decision, candidate_model=fits['bilinear']['model'],
                       lost_controls=loss, additional_area_loss=area_loss,
                       horizontal_change=stats(difference - np.median(difference) if len(difference) else difference))
            if decision['accepted']:
                row['selected'] = 'candidate_for_review'
        yield row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('uploads', type=Path, help='Folder containing original ZIPs or individual images')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, default=REFERENCE)
    parser.add_argument('--inventory-only', action='store_true')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    pairs = load_reference(args.reference)
    wanted = {digest for record in pairs.values() for digest in record['hashes'].values()}
    found = index_inputs(args.uploads, wanted)
    missing = {name: [eye for eye, digest in record['hashes'].items() if digest not in found]
               for name, record in pairs.items()}
    available = [name for name, eyes in missing.items() if not eyes]
    report = dict(verified_images=len(found), expected_images=len(wanted),
                  available_pairs=available, missing_eyes={name: eyes for name, eyes in missing.items() if eyes},
                  cases=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n', encoding='utf-8')

    save()
    print(f'{len(available)}/{len(pairs)} pairs verified by SHA-256', flush=True)
    if args.inventory_only:
        return
    for name in available:
        record = pairs[name]
        left, right = load_pair(name, record, found, args.output.parent)
        for row in evaluate(left, right, record['methods']):
            report['cases'].append(dict(name=name, **row))
            save()
            print(name, row['method'], row['selected'], flush=True)


if __name__ == '__main__':
    main()
