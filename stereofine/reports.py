from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .config import APP_NAME, APP_VERSION
from .i18n import Translator
from .models import AnalysisRecord


def _fmt(value: float | int | None, decimals: int = 2, suffix: str = "") -> str:
    if value is None:
        return "–"
    if isinstance(value, int):
        return f"{value}{suffix}"
    return f"{float(value):.{decimals}f}{suffix}"


def _report_traffic(value: str, tr: Translator) -> str:
    normalized = (value or "").strip().lower()
    mapping = {
        "green": "traffic_green",
        "grün": "traffic_green",
        "orange": "traffic_orange",
        "red": "traffic_red",
        "rot": "traffic_red",
        "gray": "traffic_gray",
        "grey": "traffic_gray",
        "unsicher": "traffic_gray",
    }
    key = mapping.get(normalized)
    return tr.t(key) if key else (value or "–")


def _report_vergence(record: AnalysisRecord) -> str:
    if record.vergence_applied_px is not None:
        return _fmt(record.vergence_applied_px, 3, " px")
    if record.vergence_v_px is not None or record.vergence_h_px is not None:
        v = _fmt(record.vergence_v_px, 3, " px")
        h = _fmt(record.vergence_h_px, 3, " px")
        return f"V {v} · H {h}"
    return "–"


def _report_note(record: AnalysisRecord, tr: Translator) -> str:
    if record.status in {"error", "Fehler"}:
        detail = tr.message((record.notes or "").replace("\t", " ").replace("\n", " ")).strip()
        return f"{tr.t('error')}: {detail}" if detail else tr.t("error")
    if record.uncertain:
        return tr.t("status_uncertain")
    return ""


def _aligned_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Return a compact fixed-column text table without tab-stop dependence."""
    all_rows = [headers, *rows]
    widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]

    def line(row: list[str]) -> str:
        return " | ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)).rstrip()

    separator = "-+-".join("-" * width for width in widths)
    return [line(headers), separator, *(line(row) for row in rows)]


def write_analysis_report(
    path: Path,
    records: Iterable[AnalysisRecord],
    *,
    input_description: str = "",
    language: str = "de",
) -> Path:
    """Write the concise user-facing StereoFine analysis quality report."""
    tr = Translator(language)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(records)

    headers = [
        tr.t("report_file"),
        tr.t("report_traffic"),
        tr.t("status_total_deviation"),
        tr.t("status_near"),
        tr.t("status_far"),
        tr.t("status_vertical_error"),
        tr.t("report_vergence"),
        tr.t("status_rotation"),
        tr.t("report_note"),
    ]
    table_rows: list[list[str]] = []
    for r in rows:
        table_rows.append(
            [
                r.source_name,
                _report_traffic(r.traffic, tr),
                _fmt(r.total_permille, 2, "‰"),
                _fmt(r.near_permille, 2, "‰"),
                _fmt(r.far_permille, 2, "‰"),
                _fmt(r.vertical_error_mean_px, 3, " px"),
                _report_vergence(r),
                _fmt(r.rotation_deg, 4, "°"),
                _report_note(r, tr),
            ]
        )

    lines = [
        f"{APP_NAME} {APP_VERSION} – {tr.t('report_title')}",
        f"{tr.t('report_created')}: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"{tr.t('report_input')}: {input_description or '–'}",
        "",
        *_aligned_table(headers, table_rows),
    ]
    payload = "\n".join(lines) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
    return path
