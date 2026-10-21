"""Summarize paired range pilots without treating agreement as depth truth."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics


def summarize(folder, reference=None):
    rows = []
    reasons = Counter()
    times = []
    transitions = Counter()
    for path in sorted(Path(folder).glob('*_range.json')):
        r = json.loads(path.read_text())
        entries = [r['measurements'][str(width)] for width in [1500, 1000]]
        evidence = [m['evidence'] for m in entries]
        spans = [m['observed_span_permille'] for m in evidence]
        span_delta = None if None in spans else abs(spans[0]-spans[1])
        deltas = {}
        for end in ['far', 'near']:
            values = [m['endpoints'][end]['edge_permille'] for m in evidence]
            deltas[end] = None if None in values else abs(values[0]-values[1])
        stable = (all(m['endpoints_confirmed'] for m in evidence) and span_delta <= 1.5
                  and all(v is not None and v <= 1.5 for v in deltas.values()))
        baseline = entries[0]['baseline']
        old_stable = None
        if reference:
            refpath = Path(reference)/path.name
            if refpath.exists():
                previous = summarize_file(refpath)
                old_stable = previous
                transitions[f'{previous}->{stable}'] += 1
        for m in entries:
            times.append(m['evidence_seconds'])
            for end, e in m['evidence']['endpoints'].items():
                for reason in e['reasons']:
                    reasons[end+':'+reason] += 1
        rows.append(dict(name=r['name'], model=r['model'], baseline_deviation_permille=baseline.get('deviation_permille'),
            baseline_uncertainty=baseline.get('uncertain_reasons'), observed_spans_permille=spans,
            endpoints=[{end: {key: value for key, value in e.items() if key != 'native_locations'}
                        for end, e in m['endpoints'].items()} for m in evidence],
            span_difference_permille=span_delta, endpoint_differences_permille=deltas,
            stable_endpoints_at_both_scales=stable, previous_stable=old_stable,
            input_files_unchanged=r['input_files_unchanged']))
    return dict(scope='Observed span only; no ground truth or completeness claim on original images',
        protocol='range-evidence-3; both endpoints and span must agree within 1.5 permille',
        cases=len(rows), image_pairs=len({r['name'].rsplit('_', 1)[0] for r in rows}),
        stable=sum(r['stable_endpoints_at_both_scales'] for r in rows),
        transitions=dict(transitions), unresolved_reasons=dict(reasons),
        all_input_files_unchanged=all(r['input_files_unchanged'] for r in rows),
        evidence_seconds=dict(median=statistics.median(times), maximum=max(times)) if times else {},
        results=rows)


def summarize_file(path):
    r = json.loads(path.read_text())
    evidence = [r['measurements'][str(w)]['evidence'] for w in [1500, 1000]]
    if not all(m['endpoints_confirmed'] for m in evidence):
        return False
    for field in ['far', 'near']:
        values = [m['endpoints'][field]['edge_permille'] for m in evidence]
        if None in values or abs(values[0]-values[1]) > 1.5:
            return False
    spans = [m['observed_span_permille'] for m in evidence]
    return None not in spans and abs(spans[0]-spans[1]) <= 1.5


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('--reference', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = summarize(args.folder, args.reference)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False))
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}, indent=2))


if __name__ == '__main__':
    main()
