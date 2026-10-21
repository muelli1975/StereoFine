# Native window audit and targeted resolution control

Date: 21 October 2026. Research following [two-ended range evidence](RANGE_EVIDENCE_1.1.md).
No change to regular measurement windows, application geometry or framing.

## Why this investigation

The earlier two-scale pilot qualified 29/60 cases at both 1500 and 1000 pixels.
That number must not be misread as 31 failed regular 1500px measurements:
43/60 already had confirmed observed endpoints at 1500px, while 37/60 did at
1000px. Only two cases had both endpoints confirmed at both widths but exceeded
the stability tolerance; missing or contradictory evidence accounts for most
other exclusions. The historical 150-image tests in [VALIDATION.md](VALIDATION.md)
remain the basis for the 3000/1500 limits.

The application uses 17x17 analysis-pixel windows for additional photometric
checks, and 41x41 original-pixel windows for conditional native near recovery.
Their physical scene footprints differ with resize ratio. Neither is an image
tiling or a local output warp. See [the window guide](MEASUREMENT_WINDOWS_1.1.md)
for the existing stages and their separate roles.

## Diagnostics, with identical default results

`native_patch_checks` can now optionally report why each point was rejected.
The default window remains radius 20 (41 pixels), with all thresholds unchanged.
Known source displacements, flat patches, ambiguous patterns and comparison
against saved original-image check records verify unchanged default behaviour.
The native radius argument is used only by the research fallback.

For the 60 cases, original 41px checks produced:

| Original native check outcome | 1500px seeds | 1000px seeds |
| --- | ---: | ---: |
| Accepted | 1687 | 1292 |
| Insufficient source texture | 147 | 370 |
| Forward correlation below threshold | 543 | 673 |
| Ambiguous forward match | 460 | 503 |
| Insufficient target texture | 11 | 12 |
| Reciprocal check failed | 32 | 30 |

These counts refer to attempted patches, not independent surfaces or known
correct/incorrect correspondences. A failed raw native match does not by itself
prove that the analysis correspondence is false. It is missing confirmation.

## Larger native footprint pilot

An optional research fallback retries only failed forward correlation/uniqueness
checks using a window approximating the 17px analysis footprint in native
pixels, capped at radius 64 (129px). It retains every previously accepted 41px
match. Source/target contrast, NCC, uniqueness, reverse checking, same-location
agreement and spatial-support thresholds are unchanged. Missing source texture
and reciprocity failures cannot be rescued by a larger surrounding scene.

A controlled case proves that added context can disambiguate locally identical
41px patches while retaining the exact known displacement. Separate tests
require flat source centres and periodic patterns to remain rejected.

All 60 original cases replay the frozen production geometry and reproduce the
saved production near/far/total/uncertainty values. Every previously accepted
native check is retained exactly. Results:

| Research qualification | Before | Larger-window fallback |
| --- | ---: | ---: |
| Confirmed observed endpoints at regular 1500px | 43/60 | 43/60 |
| Confirmed observed endpoints at control 1000px | 37/60 | 41/60 |
| Endpoints and span stable at both widths | 29/60 | 32/60 |

Three newly two-scale-qualified cases are S95 054/AKAZE and NX1000 012/AKAZE
and SIFT. All 29 previously qualified cases remain qualified. The regular-width
count does not improve, so the fallback is **not enabled in production**. This
is evidence of a control-measurement improvement, not a demonstrated increase
in correct complete scene ranges. Native-confirmed observed endpoints still do
not prove that every surface was found.

## Targeted 2000px control

Only the 17 cases unconfirmed at the regular 1500px width were retested at
2000px, with the unchanged 41px native check and the same saved correction. This
does not repeat the historical full-corpus resolution decision or change the
application defaults.

Six have confirmed observed endpoints at 2000px:

| Case | Observed span at 2000px |
| --- | ---: |
| S110 023/SIFT | 32.114 permille |
| S95 038/AKAZE | 11.713 permille |
| NX1000 004/SIFT | 22.239 permille |
| NX1000 008/AKAZE | 24.359 permille |
| NX1000 023/AKAZE | 19.055 permille |
| NX1000 029/SIFT | 24.194 permille |

All 17 retain their exact prior 1500px production values in the replay. A
successful 2000px observation does not resolve the original contradictory
1500px evidence automatically. The other eleven cases still lack sufficient
or consistent native endpoint support at 2000px.

## Decision and verification

Keep the 3000px geometry / 1500px disparity defaults, the 17px local analysis
check, the established conditional 41px native check and the current near
framing. Keep the larger-window and two-ended range replacements experimental.
The next narrow investigation is whether the six 2000px cases identify source
locations that can also be verified in the regular 1500px image, without
discarding contradictory or isolated more extreme evidence. Do not admit a
smaller range merely because the larger estimate cannot be confirmed.

187 application tests and 48 research tests pass locally. Original file hashes
remain unchanged. English README copies agree, and the German README explains
the measurement windows consistently. No package, tag, release, remote upload,
new user-facing setting or image asset was created or changed.

Reproduction, with private input paths outside the repository:

```sh
python experiments/compare_range_evidence.py cases.json --output footprint --replay-dir previous --native-footprint
python experiments/summarize_range_evidence.py footprint --reference previous --output footprint-summary.json
python experiments/compare_range_evidence.py unconfirmed-1500.json --output control-2000 --replay-dir previous --widths 1500 2000
python experiments/summarize_range_evidence.py control-2000 --output control-summary.json
```

The JSON summaries omit native source locations. They retain per-endpoint
confirmation counts and reasons so missing evidence remains reviewable.
