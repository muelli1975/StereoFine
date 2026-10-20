from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Iterable

from .anaglyph import make_anaglyph
from .config import ANALYSIS_REPORT_FILENAME
from .export import ExportResult, save_pair_outputs
from .models import AnalysisRecord
from .processing import BatchProgress, ProcessedSource, ProcessingOptions, process_source
from .render import render_final_pair
from .reports import write_analysis_report
from .sidecar import save_sidecar, source_stamp_to_dict
from .sources import StereoSource
from .worker import CancellationToken, JobCancelled

BATCH_PREVIEW_MAX_WIDTH = 960
BATCH_PREVIEW_MAX_HEIGHT = 640


@dataclass(frozen=True)
class BatchRunOptions:
    processing: ProcessingOptions = ProcessingOptions()
    analysis_only: bool = False
    favorites_only: bool = False
    output_folder: Path | None = None
    gray_anaglyph: bool = False
    report_path: Path | None = None
    language: str = "de"


@dataclass
class BatchRunItem:
    processed: ProcessedSource
    export: ExportResult | None = None
    export_skipped_reason: str | None = None


@dataclass
class BatchRunResult:
    items: list[BatchRunItem] = field(default_factory=list)
    failed: list[tuple[StereoSource, str]] = field(default_factory=list)
    report_path: Path | None = None
    language: str = "de"

    @property
    def exported_count(self) -> int:
        return sum(1 for item in self.items if item.export is not None)

    @property
    def skipped_export_count(self) -> int:
        return sum(1 for item in self.items if item.export is None and item.export_skipped_reason is not None)

    @property
    def warnings(self) -> list[tuple[StereoSource, str]]:
        result: list[tuple[StereoSource, str]] = []
        for item in self.items:
            if item.export is None:
                continue
            for warning in item.export.warnings:
                result.append((item.processed.source, warning))
        return result


def _error_record(source: StereoSource, message: str) -> AnalysisRecord:
    return AnalysisRecord(
        source_name=source.display_name,
        model=None,
        matches=None,
        inliers=None,
        vertical_error_mean_px=None,
        near_permille=None,
        far_permille=None,
        total_permille=None,
        traffic="–",
        favorite=False,
        status="error",
        notes=message,
    )


def run_batch(
    sources: Iterable[StereoSource],
    options: BatchRunOptions = BatchRunOptions(),
    *,
    cancellation: CancellationToken | None = None,
    progress: Callable[[BatchProgress], None] | None = None,
) -> BatchRunResult:
    """Analyse and optionally export a complete source set.

    Every source goes through ``process_source`` first.  Therefore analysis-only,
    normal batch and favorites-only batch all share the identical alignment,
    disparity, automatic 3‰ framing and sidecar reuse logic.
    """

    source_list = list(sources)
    total = len(source_list)
    result = BatchRunResult(language=options.language)
    records: list[AnalysisRecord] = []

    # Build the batch preview from the already existing analysis proxies.
    # Normal image export still retains only the current master pair and drops
    # it immediately afterwards; analysis-only never retains the master pair.
    process_options = replace(
        options.processing,
        keep_loaded_pair=not options.analysis_only,
        preview_max_width=BATCH_PREVIEW_MAX_WIDTH,
        preview_max_height=BATCH_PREVIEW_MAX_HEIGHT,
    )

    for index, source in enumerate(source_list, start=1):
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        if progress:
            progress(BatchProgress(index, total, source.display_name, "analysis"))
        try:
            processed = process_source(source, process_options, cancellation=cancellation)
            records.append(processed.analysis_record)
            item = BatchRunItem(processed=processed)

            # The progress preview was prepared from the existing analysis
            # proxies, so this path performs no second full-resolution render.
            if progress and processed.preview_pair is not None:
                try:
                    preview_left, preview_right = processed.preview_pair
                    progress(
                        BatchProgress(
                            index,
                            total,
                            source.display_name,
                            "preview",
                            preview_rgb=make_anaglyph(preview_left, preview_right, gray=options.gray_anaglyph),
                        )
                    )
                except Exception:
                    pass
            # The reduced arrays are only a transient progress surface.
            processed.preview_pair = None

            if options.analysis_only:
                item.export_skipped_reason = "analysis_only"
                result.items.append(item)
                continue

            if options.favorites_only and not processed.state.favorite:
                item.export_skipped_reason = "not_favorite"
                processed.loaded_pair = None
                result.items.append(item)
                continue

            if options.output_folder is None:
                raise ValueError("Für Bildausgabe ist ein Ausgabeordner erforderlich.")
            if processed.loaded_pair is None:
                raise RuntimeError("Interner Fehler: Masterbild für Ausgabe nicht verfügbar.")

            if progress:
                progress(BatchProgress(index, total, source.display_name, "export"))
            left, right, _render_info = render_final_pair(processed.loaded_pair, processed.state)
            item.export = save_pair_outputs(
                left,
                right,
                options.output_folder,
                source.base_name,
                # StereoFine 1.0 always writes both standard outputs.
                output_mode="both",
                gray_anaglyph=options.gray_anaglyph,
                metadata_source=source.metadata_source,
            )

            # Rendering may fit/update the symmetric color-transfer parameters.
            # Persist the exact state used for the written output afterwards.
            if process_options.save_sidecar:
                save_sidecar(
                    source.sidecar_path,
                    processed.state.to_sidecar(source=source_stamp_to_dict(processed.source_stamp)),
                )
            processed.loaded_pair = None
            result.items.append(item)
        except JobCancelled:
            # Cancellation is a job state, never a per-image processing error.
            raise
        except Exception as exc:
            message = str(exc)
            result.failed.append((source, message))
            records.append(_error_record(source, message))

    if cancellation is not None:
        cancellation.raise_if_cancelled()

    report_path = options.report_path
    if report_path is None and options.analysis_only and source_list:
        report_path = source_list[0].input_root / ANALYSIS_REPORT_FILENAME
    if report_path is not None:
        input_description = str(source_list[0].input_root) if source_list else ""
        result.report_path = write_analysis_report(
            report_path, records, input_description=input_description, language=options.language
        )

    return result
