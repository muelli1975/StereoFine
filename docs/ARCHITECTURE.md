# StereoFine 1.0 – architecture notes

StereoFine 1.0 deliberately separates the GUI from the reusable stereo-processing core.

## Processing flow

```text
Input discovery/load
→ input orientation / eye order
→ feature analysis (AKAZE or SIFT, max. 3000 px)
→ conservative alignment model selection
→ one composed geometric resampling per half-image
→ crop/aspect state
→ separate disparity analysis (max. 1500 px, robust P1/P99)
→ automatic near-point framing (3‰ baseline when reliable)
→ manual deltas / Floating Window mask
→ optional symmetric color matching
→ preview / SBS / anaglyph export
```

Floating Window values are presentation masks only and never alter disparity measurements.

## Main modules

- `alignment.py` – features, robust affine fit, Vergence/Trapezoid and Y-Polish selection, composed correction map.
- `disparity.py` – semi-dense horizontal disparity analysis and uncertainty diagnostics.
- `processing.py` – shared single-image/batch analysis primitive and cache reuse.
- `state.py` / `sidecar.py` – reproducible per-pair state and schema-3 `.sfin` persistence.
- `render.py` / `geometry.py` – final geometry, crop and masks.
- `color_transfer.py` – symmetric color matching outside the geometry analysis path.
- `anaglyph.py` – color/grayscale anaglyph generation.
- `batch.py` / `reports.py` – batch orchestration and analysis reports.
- `worker.py` – cancellable jobs without touching Tk from worker threads.
- `gui.py` – CustomTkinter presentation and user interaction only.

## State separation

Global user preferences belong to `settings.json`. Image-specific state belongs to `.sfin`. Job modes such as analysis-only and favorites-only are intentionally session-local.

Pipeline versions are separate from the visible application version so GUI-only changes do not invalidate expensive cached image analysis unnecessarily.
