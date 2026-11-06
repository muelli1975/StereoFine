# Final-width near-reserve audit

6 November 2026. Read-only investigation of released StereoFine 1.2, source `29d41ad2c29c2704a1e8ddd6d1bdb646ab35a95f`.

The selected output aspect is already applied before the first disparity measurement. However, `compute_auto_near_framing` calculates the 3-permille reserve using that pre-shift crop width. Applying the horizontal baseline can reduce the final overlap/crop width. The final independent disparity measurement does not change framing.

The geometric counterexample is independent of a matcher: with a known near disparity of 600 pixels and a 6000-pixel initial selected width, the current baseline is 618 pixels. The final Original-aspect width is 5382 pixels, so its reserve is 3.34448 permille. The smallest integer baseline satisfying a 3-permille reserve on the final crop is 617 pixels, yielding 5383 pixels and 3.15809 permille. The remaining excess is pixel quantization. The current result is therefore not always the minimum integer placement for the requested final-width reserve.

For square crops that retain their width, the same pure-geometry tests retain the correct 3-permille basis. This is not evidence of a general aspect-ratio omission or a sign error.

Four additional synthetic-plane tests ran actual SGBM before and after framing. Final status equalled the independent final measurement; the framing was not subtracted twice. Weak texture produced uncertain endpoints that differed from the known geometric truth. Consequently, independent remeasurement is not proof of greater accuracy on uncertain photographs.

These tests do not reproduce Christoph's particular reported near values of 1 or 4. Their cause and sign cannot be established without those image cases. Positive near disparity denotes a position in front of the stereo window; negative denotes behind it.

No production correction, cache migration or release change was made by this audit. A correction must distinguish the geometric final-width reserve, uncertain endpoint estimates and preservation of saved/manual framing. Merely forcing the displayed near value to -3 would conceal rather than fix the issue.

[Execution evidence](https://github.com/muelli1975/StereoFine/actions/runs/42218982271) · [Complete numeric results](FINAL_NEAR_WIDTH_AUDIT_20261106.json)
