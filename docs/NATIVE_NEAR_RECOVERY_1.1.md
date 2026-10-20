# Native-confirmed recovery of missed near-point measurements

Status: 20 October 2026. Unreleased StereoFine 1.1 development, following
[renderer-consistent model scoring](APPLIED_MODEL_SCORING_1.1.md).

## Integrated change

An unconfirmed near edge can now receive a bounded additional measurement pass.
The existing search can spend its few near-component seeds on flat, mixed or
otherwise unsuitable patches. It may therefore miss usable foreground features
even when the image contains enough evidence. The earlier
[RC3 investigation](RC3_EDGE_NEAR_REVIEW.md) established this selection gap, but
also showed that extra analysis-resolution matches alone were insufficient.

The new pass retains all original contrast, correlation, uniqueness, reciprocal
matching, spatial-support and uncertainty checks. It additionally requires
agreement at native image resolution. Already confirmed results follow the
existing path unchanged. Geometric alignment, quadratic/cubic correction and
their calculation version are unchanged by this step.

## Measurement and admission

1. Only for an unconfirmed near edge, distribute at most **128** additional seeds
   over 16-analysis-pixel cells in the confident SGBM P98 tail. Reuse the existing
   17×17-patch verifier: contrast, NCC at least 0.85, uniqueness margin at least
   0.05, a global horizontal strip search and reciprocal checking.
2. The resulting analysis measurements must spatially corroborate the near edge.
   Unsupported extremes remain a veto. A higher P99 baseline is never lowered
   to obtain confirmation.
3. Check at most **24** of the strongest candidate locations at native resolution,
   using the previously investigated 41×41 patches, global horizontal searches,
   a ±6-native-pixel vertical search band, contrast/uniqueness checks and a
   reciprocal match within one native pixel. No SGBM horizontal search interval
   is supplied to this native verifier.
4. Associate each native result with the **same source location**, using actual
   per-axis resized dimensions and pixel-center mapping. Its disparity must
   agree within one analysis pixel. Native evidence must itself have nearby
   supporting measurements under the existing spatial-support rule.
5. An unresolved analysis-supported surface more than one analysis pixel nearer
   than the native-supported surface **vetoes recovery**. Confirmed farther
   points cannot silently replace unresolved nearer evidence.
6. Retain original evidence and the more conservative of the supported analysis
   and native near envelopes. Preserve the existing half-analysis-pixel reserve
   for a newly extended near edge. Apply all other disparity uncertainty checks,
   including the search-range limit, in the unchanged downstream code.

Native dimensions must be at least 1.5 times the analysis dimensions in both
axes; otherwise the old uncertain result is retained. The pixel layout and
analysis images remain grayscale 8-bit working copies. Native resolution here
means original spatial resolution, not a new high-bit-depth matching algorithm.
The helper explicitly converts 16-bit native inputs through the existing
full-range proxy, avoiding saturation in diagnostic calls.

This is additional photometric evidence from the same photographs. The two
resolutions are not independent depth ground truth, and the measurements cannot
guarantee that every occluded or textureless foreground feature has been found.

## Original-image comparison

All **29 private original pairs × AKAZE/SIFT = 58 cases** reproduce the saved RC3
near value, complete confirmation object and uncertainty reasons before the new
pass is enabled. For every previously unconfirmed case, the real integrated
disparity path reproduces the candidate. Dense SGBM values and confidence masks
are identical before and after; only additional near evidence is introduced.

| Outcome | Cases |
| --- | ---: |
| Already confirmed result unchanged | 50 |
| Previously unconfirmed edge confirmed at both resolutions | 5 |
| Contradictory or insufficient evidence remains uncertain | 3 |

Recovered cases, with raw near disparity before automatic window placement:

| Case | Previous estimate | Native-confirmed estimate | Native matches / spatially supported |
| --- | ---: | ---: | ---: |
| IXUS 008 / AKAZE | 12.333‰ | 13.167‰ | 18 / 15 |
| IXUS 008 / SIFT | 12.292‰ | 13.037‰ | 17 / 16 |
| S95 054 / AKAZE | 32.667‰ | 33.355‰ | 19 / 17 |
| NX1000 008 / AKAZE | 16.000‰ | 17.628‰ | 10 / 10 |
| NX1000 008 / SIFT | 16.000‰ | 17.646‰ | 10 / 10 |

For these five cases, `near_edge_unconfirmed` was the sole original uncertainty
reason and is removed after confirmation. This is five method/pair outcomes,
covering three image pairs, not five independent camera scenes.

S95 012/AKAZE retains a native unsupported extreme. S95 012/SIFT retains an
analysis unsupported extreme. NX1000 004/SIFT retains an unresolved nearer
analysis surface: farther native matches do not establish that the nearer
candidate is false, so uncertainty correctly remains. None of these three
cases is automatically made certain.

## Actual window placement and persistence

All five recovered cases were rendered with the real automatic near framing and
the unchanged native renderer. Fixed source locations were then checked again
in the final images with the native strip verifier. The nearest of these
confirmed output checks lies at:

| Case | Native output checks | Maximum measured disparity after framing |
| --- | ---: | ---: |
| IXUS 008 / AKAZE | 22 | −3.581‰ |
| IXUS 008 / SIFT | 22 | −3.581‰ |
| S95 054 / AKAZE | 19 | −5.127‰ |
| NX1000 008 / AKAZE | 21 | −4.114‰ |
| NX1000 008 / SIFT | 18 | −4.114‰ |

Every checked foreground point is at least the requested **3‰ behind the
window**. These are measurements at fixed source locations in final native
pixels, not just a calculation that subtracts the requested offset. Matching
counts can change when cropping removes an ambiguous alternative. Floating-window
masks and color matching are disabled for this geometry check.

Each recovered state was saved to a real temporary `.sfin`, reloaded with the
actual source stamp, restored through `PairState.from_sidecar`, and rendered.
All five produce identical native pixels after roundtrip. The raw near value,
automatic framing, favorite and an explicit manual horizontal shift survive.
Original images and original sidecars are never written by these experiments.

The disparity calculation version advances to **`sf-disparity-3`**. Alignment
remains `sf-align-5`, and the `.sfin` schema remains 3. Old automatic disparity
and near framing are recalculated, while valid alignment and user edits remain.
A processing integration test verifies the old-version transition and later
cache reuse. Another test exercises real dense matching, native recovery,
rendered 3‰ placement and disk/cache reuse after deliberately withholding the
initial near seeds. A separate uniform-depth uncertainty reason remains intact.

## Validation and limits

Local checks: **165 application tests and 42 research tests pass**. Twelve new
application tests cover real patch recovery, native correspondence agreement,
contradictory nearer evidence, both measurement reserves, unsupported extremes,
overestimated P99, missing texture/confidence/native resolution, full-range
16-bit proxies, final framing and sidecar/cache integration. All application
modules import, sources compile and original asset hashes are preserved.

The existing cross-platform development workflow checks Windows, Linux and
macOS, plus German/English GUI smoke on Linux. Remote results will be recorded
after the code commit is checked. It publishes no application packages.

The S110 lower-right vertical alignment issue is separate and remains open.
The alternative quadratic coefficient fit remains experimental. Published RC3
and stable 1.0 packages remain unchanged. Original-file Windows application
testing is still separate from automated public-fixture CI.

## Reproduction

[Numeric evidence](NATIVE_NEAR_RECOVERY_1.1_RESULTS.json) contains input hashes,
complete-case decisions, scalar near evidence, native framing checks and raster
hashes. It excludes private source paths, original images and point coordinates.
Runtime: Python 3.12.14, OpenCV 4.13.0, NumPy 2.4.6, Pillow 12.2.0.

Use the same private `{name, left, right, state}` manifest of full PairState
diagnostic JSONs. The comparison explicitly disables only the new recovery hook
to reproduce the saved pre-recovery reference, then checks the real integrated
path. Reproduction excludes any reference mismatch rather than counting it.

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
python experiments/compare_native_near.py private_manifest.json --output private_native_near
python experiments/check_native_near_framing.py private_manifest.json --results private_native_near
python -m experiments.summarize_native_near private_manifest.json \
  --results private_native_near --output native_near_summary.json
```

The historical diagnostic script imports the shared seed/native primitives;
their algorithms are no longer duplicated. Its RC3 reference path explicitly
disables recovery and uses the same full-range 8-bit master proxies as processing.
