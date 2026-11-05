"""Optional Full-SBS filename markers; menu labels never enter filenames."""
from __future__ import annotations

import re


SBS_SUFFIXES = (
    ("_sbs", "StereoFine"),
    ("_s", "m.objects"),
    ("_cs", "COSIMA"),
    ("-lr", "Bino"),
)


def suffix_labels(language: str = "de") -> list[str]:
    return [f"{suffix} ({program})" for suffix, program in SBS_SUFFIXES] + [
        "Ohne Zusatz" if language == "de" else "No suffix"
    ]


def suffix_value(label: str, language: str = "de") -> str:
    for (suffix, _), choice in zip(SBS_SUFFIXES, suffix_labels(language)):
        if label == choice:
            return suffix
    return "" if label == suffix_labels(language)[-1] else label


def suffix_label(value: str, language: str = "de") -> str:
    for (suffix, _), label in zip(SBS_SUFFIXES, suffix_labels(language)):
        if value == suffix:
            return label
    return suffix_labels(language)[-1] if value == "" else value


def validate_sbs_suffix(value: str) -> str:
    """Use the same portable filename restrictions as TransCora's suffixes."""
    if (not isinstance(value, str) or len(value) > 80 or value in {".", ".."}
            or value.endswith((" ", "."))
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)):
        raise ValueError("Invalid SBS filename suffix.")
    return value
