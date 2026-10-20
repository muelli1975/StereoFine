"""Post-hoc sensitivity analysis, never the frozen prospective selector.

Reuses RC3 refinement's existing .5/1.5 analysis-pixel quality ceilings.
No new thresholds are optimized. Output is not a release or automatic admission.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.select_neural_candidate import select_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('selection', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    for f in sorted(args.selection.glob('*_selection.json')):
        r = json.loads(f.read_text())
        z = np.load(f.with_name(r['name']+'_controls.npz'))
        data = (z['left'], z['before'], z['after'], z['split'], tuple(r['analysis_shape']), r['analysis_scale'])
        # The frozen default must reproduce exactly after adding the explicit
        # alternative. This also checks that no measured point was dropped.
        strict = select_candidate(*data)
        assert strict['selected'] == r['selected']
        assert strict['selection'] == r['selection']
        assert strict['confirmation'] == r['confirmation']
        relaxed = select_candidate(*data, region_quality_floor_analysis=(.5, 1.5))
        rows.append(dict(name=r['name'], strict=r['selected'],
            existing_ceilings=relaxed['selected'],
            selection_reason=relaxed['selection']['reason'],
            confirmation_reason=relaxed['confirmation']['reason']))
    result = dict(kind='post_hoc_sensitivity_not_prospective_validation',
        ceilings_analysis_px=dict(mean_abs=.5, p90_abs=1.5),
        source='Unchanged existing RC3 refinement quality ceilings; no threshold search',
        strict_results_reproduced=len(rows),
        would_admit=sum(r['existing_ceilings']=='lightglue_aliked' for r in rows), cases=rows)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'}))


if __name__ == '__main__':
    main()
