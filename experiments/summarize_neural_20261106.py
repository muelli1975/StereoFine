"""Persist public, numeric-only benchmark evidence on the research branch."""
import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('--run', required=True)
    args = parser.parse_args()
    reports = json.loads((args.input/'COMPARISON.json').read_text())
    methods = {r['method']: r for r in reports}
    baseline = {r['name']: r for r in methods.get('baseline', {}).get('cases', []) if r['method'] == 'SIFT'}
    rows = ['# LoMa and FlexGlue: public stereo CPU pilot', '',
        'Measured on 6 November 2026 against released StereoFine 1.2.', '',
        '[Protocol](NEURAL_20261106_PROTOCOL.md) | [Complete results](NEURAL_20261106_RESULTS.json) | '
        f'[Execution evidence](https://github.com/muelli1975/StereoFine/actions/runs/{args.run})', '',
        'Three public Middlebury 2014 scenes, each as an aligned control and as an alternate-lighting '
        'challenge with a known right-eye affine transform. The six images pairs use a 1600-pixel long side. '
        'Between 26,916 and 34,264 independent GT points are used per case; none is passed into a matcher or fit.', '',
        '## Vertical error after the unchanged StereoFine correction', '',
        'P95 is the absolute vertical error below which 95% of the independent control points lie. '
        'All values are pixels at the stated input resolution; lower is better.', '',
        '| Case | AKAZE | SIFT | LoMa-B | FlexGlue | FlexGlue + refinement |',
        '|---|---:|---:|---:|---:|---:|']
    all_rows = [x for r in reports for x in r.get('cases', [])]
    for name in sorted({x['name'] for x in all_rows}):
        vals = []
        for method in ('AKAZE', 'SIFT', 'loma_b', 'flexglue', 'flexglue_refined'):
            row = next((x for x in all_rows if x['name'] == name and x['method'] == method), None)
            vals.append(f"{row['after']['global_error']['p95']:.4f}" if row and row['status'] == 'ok' else 'not measured')
        rows.append('| '+name+' | '+' | '.join(vals)+' |')
    rows += ['', '## Regional differences versus SIFT', '',
        'These are exact signed differences in P95, not an admission rule. Positive values mean '
        'more vertical error than SIFT. Only regions with at least 20 GT points in both methods are compared.', '',
        '| Case | Candidate | Global delta | Largest 5x5-cell increase | Largest corner increase |',
        '|---|---|---:|---:|---:|']
    for report in reports:
        if report['method'] == 'baseline':
            continue
        for row in report.get('cases', []):
            ref = baseline.get(row['name'])
            if row['status'] != 'ok' or not ref or ref['status'] != 'ok':
                continue
            a, b = row['after'], ref['after']
            diffs = {}
            for kind in ('grid_5x5', 'corners'):
                deltas = [x['p95']-b[kind][key]['p95'] for key, x in a[kind].items()
                    if min(x['count'], b[kind][key]['count']) >= 20]
                diffs[kind] = max(deltas) if deltas else None
            delta = a['global_error']['p95'] - b['global_error']['p95']
            cells = '-' if diffs['grid_5x5'] is None else f"{diffs['grid_5x5']:+.4f}"
            corners = '-' if diffs['corners'] is None else f"{diffs['corners']:+.4f}"
            rows.append(f"| {row['name']} | {row['method']} | {delta:+.4f} | {cells} | {corners} |")
    rows += ['', '## Observed resources', '',
        'Wall times include point matching and StereoFine fitting. They exclude initial model loading '
        'and downloads. Different GitHub VMs and method-specific point budgets prevent a controlled '
        'speed ranking. The first inference includes warmup. RSS includes the complete Python process.', '',
        '| Method | Completed cases | Median time (s) | Range (s) | Peak process RSS (GiB) |',
        '|---|---:|---:|---:|---:|']
    for method in ('AKAZE', 'SIFT', 'loma_b', 'flexglue', 'flexglue_refined'):
        rr = [x for x in all_rows if x['method'] == method and x['status'] == 'ok']
        report = methods.get('baseline' if method in ('AKAZE','SIFT') else method)
        if not rr:
            rows.append(f'| {method} | 0 | - | - | - |')
            continue
        tt = [x['total_seconds'] for x in rr]
        rss = report.get('process_peak_rss_bytes', max(x['peak_rss_bytes'] for x in rr))/2**30
        rows.append(f'| {method} | {len(rr)} | {statistics.median(tt):.2f} | {min(tt):.2f}–{max(tt):.2f} | {rss:.3f} |')
    errors = [(r['method'],r.get('error')) for r in reports if r.get('status') != 'completed']
    errors += [(x['method']+'/'+x['name'],x.get('error')) for x in all_rows if x['status'] != 'ok']
    if errors:
        rows += ['', '## Incomplete measurements', '']
        rows += ['- '+m+': '+str(e) for m,e in errors]
    rows += ['', '## Limits', '',
        '- The earlier 29 private StereoFine camera-rig pairs were unavailable and were not used.',
        '- These controlled indoor scenes do not establish accuracy on real lens errors, outdoor/night scenes, or new cameras.',
        '- Public scenes may have been used during model training or development; no unseen-data claim is made.',
        '- Raw match precision is diagnostic and can be affected by sampling near depth boundaries. GT never filters fitted matches.',
        '- The score evaluates the actual correction point map; raster rendering was exercised, but full export/deviation/session behaviour was not tested.',
        '- No automatic candidate selection or product integration occurred. Different budgets: LoMa-B 2048 keypoints; FlexGlue 4096 samples.',
        '- Official model code and weights were used. FlexGlue uses fp32 transformers on CPU; refinement retains its official implementation.',
        '- Input/model hashes, source commit, exact configuration, versions and machine metadata are in the complete results.',
        '- Source images and weight files are not redistributed in this repository.']
    out = Path('docs')
    out.mkdir(exist_ok=True)
    (out/'NEURAL_20261106_RESULTS.json').write_text(json.dumps(reports,indent=2)+'\n')
    (out/'NEURAL_20261106_RESULTS.md').write_text('\n'.join(rows)+'\n')
    print('\n'.join(rows))


if __name__ == '__main__':
    main()
