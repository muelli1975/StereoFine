# Independent far-end recovery after 1.1

Status: development change after the published v1.1 release. The published tag
and downloadable archives are unchanged. Calculation version: `sf-disparity-6`.

## Problem and behavior

In bild124 the dense estimate includes an unverified sky tail, producing
113.052 permille with AKAZE and 114.560 with SIFT. The primary native endpoint
search confirms a span around 30 permille. Its far endpoint also agrees with
the control resolution, but an unresolved control near surface previously
rejected the entire recovery.

The new admission path retains the existing supported baseline near endpoint
and requires both primary native endpoints to be confirmed. It then permits
a far correction when the control far endpoint is also confirmed and agrees
within the existing 1.5-permille tolerance, even if the control near endpoint
is unconfirmed. The normal complete two-scale path remains unchanged.

The partial path:

- Keeps `near_control_unconfirmed`, including when the control near value is
  absent. It never certifies the complete near/far range.
- Uses only the confirmed primary native near endpoint and the supported
  baseline near estimate. An unconfirmed control near value cannot extend or
  narrow the near estimate or drive automatic framing.
- Keeps the existing half-analysis-pixel reserve and only extends the near
  estimate when confirmed primary evidence exceeds the baseline plus reserve.
- Still rejects a confirmed but conflicting control near endpoint, an
  unconfirmed/disagreeing control far endpoint, or a correction that would
  discard previously supported farther evidence.
- Retains `range_completeness_unconfirmed` when replacing a wider unverified
  dense tail with a smaller observed span. Other uncertainty reasons survive.
- Leaves confirmed baseline results and uncertain baseline near endpoints
  outside recovery, as before.

No sky mask, disparity cap, new matcher, altered match threshold or additional
geometric deformation is introduced. Geometry stays at 3000 pixels and dense
disparity at 1500, with the existing 1000-pixel control and native point checks.
The 3-permille window reserve remains unchanged.

## Warning and persistence

The German warning is exactly:

> ⚠ Einschätzung unsicher – bitte mit M prüfen!

The English equivalent is “⚠ Estimate uncertain – please check with M!”. The
warning uses light gold `#c6a95e`, bold text and the warning triangle, following
TransCora's attention style. The warning uses the entire status row, including
the space occupied by symbols in other rows: 292 logical pixels for text.
Both translations have an explicit line break after the dash in the GUI and
reserve 32 logical pixels on every platform, even while empty. This is 13
logical pixels taller than the released single-line slot; the scrollable
settings area has that much less height while the bottom action buttons stay
fixed. The sidebar width and symbols in other rows are unchanged. The line
break is GUI formatting only; text reports retain a single-line table entry.
The existing keyboard help explains that M is held to display the cross.

`sf-disparity-5` measurements recompute on the next processing pass. Alignment
caches, favorites and explicit manual edits remain reusable. The saved method
and scope identify the partial recovery; its uncertainty survives reloading.

## Validation

The [machine-readable comparison](FAR_ENDPOINT_RECOVERY_RESULTS.json) covers
32 original pairs with AKAZE and SIFT, using frozen previously recorded
geometric corrections and checking original file hashes. This isolates the
measurement change from alignment variability.

| Check | Result |
| --- | ---: |
| Released results unchanged, including uncertainty reasons | 60 / 64 |
| Previously confirmed released results unchanged | 37 / 37 |
| Previous complete two-scale recoveries unchanged | 15 / 15 |
| Dense arrays unchanged | 64 / 64 |
| Source hash checks unchanged | 64 / 64 |

Only four cases change:

| Image / method | Released deviation | Development deviation | Near estimate |
| --- | ---: | ---: | --- |
| bild090 / AKAZE | 28.141 | 28.827 | Unchanged |
| bild090 / SIFT | 27.647 | 28.585 | Unchanged |
| bild124 / AKAZE | 113.052 | 30.120 | Extended by 1.950 permille |
| bild124 / SIFT | 114.560 | 30.796 | Unchanged |

All four remain uncertain. Bild124/AKAZE's automatic offset changes from
174 to 183 native pixels due to the confirmed primary near evidence. Its
alignment coefficients remain unchanged. Bild128 remains at 25.045 / 22.750
permille, with its previous uncertainty and framing. The 27 remaining uncertain
cases are not promoted to certain merely because the displayed value improves.

Fresh end-to-end processing of bild124/AKAZE and bild128 with both methods
also reproduces these measurements and the original alignment coefficients
(excluding run timings). Real sidecar reloads preserve the new method, scope,
uncertainty, a manual horizontal edit and the favorite flag. Both bild128
automatic framing results remain identical to the released calculation.

Local checks: 203 application tests, 48 research tests, German/English real GUI
processing/export smoke, Python compilation, original asset hashes and equal
default/English READMEs. New regression cases cover a missing control near
value, an extreme unconfirmed control near value, failed control far support,
far disagreement, primary near failure and the previous calculation cache.
Synthetic pixel-based checks continue to cover known shifts, sky, small
surfaces, occlusion, repeated patterns and exposure differences.

The full warning was rendered on Linux/Xvfb with Tk 8.6.14 at 100, 125, 150 and
200 percent scaling, in German and English, at 1100x700 and 1400x850 logical
window sizes. All 16 combinations fit without clipping or moving the action
buttons when the warning changes. These are application-scaling checks with
the Linux font fallback. Native platform checks and development-package
verification run again for the uniform two-line presentation; the final
receipt identifies their exact source commit and workflow run.

This is evidence of a narrower, more useful decision rule, not calibrated
whole-scene ground truth or proof that every sky/foreground case is solved.

## Reproduction

Original photographs and full native-location diagnostics stay outside the
repository. With the private 64-case manifest and frozen baseline directory:

```sh
python experiments/validate_observed_range.py MANIFEST.json \
  --baseline FROZEN_BASELINE --output VALIDATED_RESULTS
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
PYTHONPATH=. xvfb-run -a -s '-screen 0 4096x2400x24' \
  python tests/gui_warning_xvfb.py --scale 1.5
```
