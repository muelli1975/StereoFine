"""Regressions for useful, spatially supported complete model selection."""
from __future__ import annotations

import unittest

import numpy as np

from stereofine.alignment import (
    _assess_spatial_holdout, _fit_y_residual_candidate,
    _holdout_model_is_better, _holdout_summary_is_better,
    _select_validated_pipeline,
)


def summary(mean, median=None, p90=None, p95=None, maximum=None):
    return dict(mean_abs=mean, median_abs=mean if median is None else median,
                p90_abs=mean * 1.5 if p90 is None else p90,
                p95_abs=mean * 2 if p95 is None else p95,
                max_abs=mean * 3 if maximum is None else maximum)


def zones(means, counts=None):
    counts = counts if counts is not None else [10] * len(means)
    return {"zones": [dict(label=str(i), count=count, mean_abs=mean, p90_abs=mean * 1.5)
                      for i, (mean, count) in enumerate(zip(means, counts))]}


class ModelSelectionTests(unittest.TestCase):
    def test_isolated_maximum_does_not_veto_a_large_robust_improvement(self):
        # Measured bild092/AKAZE summaries: the former maximum veto rejected
        # a result independently confirmed to improve the rendered image.
        before = summary(1.0517828, .9229586, 2.0619484, 2.5124819, 4.2636110)
        after = summary(.3949276, .2798398, .8421576, 1.1128518, 5.3976008)
        self.assertTrue(_holdout_summary_is_better(before, after))

    def test_already_good_model_is_retained_for_a_subprecision_improvement(self):
        self.assertFalse(_holdout_summary_is_better(summary(.12), summary(.10)))
        self.assertFalse(_holdout_summary_is_better(summary(10), summary(9.7)))

    def test_robust_tail_regression_is_rejected_despite_improved_mean(self):
        self.assertFalse(_holdout_summary_is_better(summary(2, p95=3), summary(1, p95=4)))

    def test_supported_regions_must_not_pay_for_an_improved_dense_centre(self):
        result = _assess_spatial_holdout(summary(2), summary(.8), zones([2, 2, .2]), zones([.4, .4, .8]), 1)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "regional_regression")

    def test_subprecision_regional_variation_is_allowed(self):
        result = _assess_spatial_holdout(summary(2), summary(.8), zones([2, 2, .2]), zones([.4, .4, .25]), 1)
        self.assertTrue(result["accepted"])

    def test_missing_or_sparse_spatial_evidence_is_rejected(self):
        for before, after in [(None, None), (zones([2, 2]), zones([.5, .5])),
                              (zones([2] * 3, [5] * 3), zones([.5] * 3, [5] * 3))]:
            with self.subTest(before=before):
                result = _assess_spatial_holdout(summary(2), summary(.5), before, after, 1)
                self.assertFalse(result["accepted"])
                self.assertEqual(result["reason"], "insufficient_spatial_holdout")

    def test_same_holdout_point_counts_are_required(self):
        result = _assess_spatial_holdout(summary(2), summary(.5), zones([2] * 3), zones([.5] * 3, [9, 10, 10]), 1)
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "different_holdout_points")

    def test_invalid_metrics_never_enable_a_model(self):
        for invalid in (None, float("nan"), float("inf"), -1):
            for key in ("mean_abs", "median_abs", "p90_abs", "p95_abs", "max_abs"):
                candidate = summary(.5); candidate[key] = invalid
                with self.subTest(key=key, invalid=invalid):
                    self.assertFalse(_holdout_summary_is_better(summary(2), candidate))
        candidate_zones = zones([.5] * 3)
        candidate_zones["zones"][1]["p90_abs"] = float("nan")
        self.assertFalse(_assess_spatial_holdout(summary(2), summary(.5), zones([2] * 3), candidate_zones, 1)["accepted"])

    def test_precision_floor_scales_with_analysis_resolution(self):
        before, after = summary(.4), summary(.32)
        self.assertTrue(_assess_spatial_holdout(before, after, zones([.4] * 3), zones([.32] * 3), 1)["accepted"])
        self.assertFalse(_assess_spatial_holdout(before, after, zones([.4] * 3), zones([.32] * 3), .5)["accepted"])

    def test_whole_chains_are_compared_and_negligible_extra_stages_omitted(self):
        candidates = [dict(label=label, holdout=summary(error), zones=zones([error] * 3))
                      for label, error in [("Affine", 2), ("Affine + Vergence", 1.5),
                                           ("Affine + yQuad", .3), ("Affine + Vergence + yQuad", .28)]]
        selected, audit = _select_validated_pipeline(candidates, 1)
        self.assertEqual(selected["label"], "Affine + yQuad")
        self.assertFalse(audit[-1]["accepted"])

    def test_unsupported_or_training_only_candidate_is_not_used(self):
        candidate = dict(ready=False, eval_mode="spatial_holdout")
        self.assertFalse(_holdout_model_is_better(candidate))
        candidate.update(ready=True, eval_mode="no_holdout_available_eval_uses_all_points")
        self.assertFalse(_holdout_model_is_better(candidate))

    def test_regional_tolerances_cannot_accumulate_across_models(self):
        candidates = [
            dict(label="Affine", holdout=summary(2), zones=zones([2, 2, .1])),
            dict(label="Trapez", holdout=summary(1), zones=zones([1, 1, .16])),
            dict(label="yQuad", holdout=summary(.5), zones=zones([.5, .5, .22])),
        ]
        selected, audit = _select_validated_pipeline(candidates, 1)
        self.assertEqual(selected["label"], "Trapez")
        self.assertEqual(audit[-1]["reason"], "regional_regression")

    def test_rank_deficient_spatial_fit_is_not_used(self):
        # A diagonal can occupy many grid cells yet cannot determine a 2D
        # quadratic field. Numerical support must also be checked.
        t = np.linspace(20, 580, 150)
        left = np.column_stack([t, t])
        right = left + [12, 3]
        candidate = _fit_y_residual_candidate("test", ["constant", "x", "y", "xy", "x2", "y2"], left, right,
                                              np.full(len(t), 3.), (600, 600), 1)
        self.assertFalse(candidate["ready"])
        self.assertFalse(candidate["design_quality"]["supported"])


if __name__ == "__main__":
    unittest.main()
