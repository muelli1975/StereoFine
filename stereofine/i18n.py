from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

Language = str

TEXTS: dict[str, dict[str, str]] = {
    "de": {
        "subtitle": "Stereofotos ausrichten und feinjustieren",
        "language": "Sprache",
        "fullscreen": "Vollbild",
        "windowed": "Fensteransicht",
        "input": "Input",
        "single_edit": "Einzelbildbearbeitung",
        "batch_processing": "Stapelverarbeitung",
        "left_right": "Links/Rechts",
        "full_sbs_mpo": "Full-SBS/MPO",
        "analysis_only": "Nur Analyse · Textbericht",
        "favorites_only": "Nur Favoriten ausgeben",
        "alignment": "Ausrichtung",
        "left": "Links",
        "right": "Rechts",
        "mirror": "Spiegeln",
        "swap_eyes": "Links/Rechts tauschen",
        "analysis_method": "Analyseverfahren",
        "image_output": "Bild und Ausgabe",
        "aspect_ratio": "Seitenverhältnis",
        "color_match": "Symmetrische Farbangleichung",
        "output": "Ausgabe",
        "use_input_subfolder": "Unterordner im Input-Ordner verwenden",
        "custom_output_folder": "Eigener Ausgabeordner",
        "choose": "Auswählen",
        "preview": "Vorschau",
        "preview_color": "Farbig",
        "preview_gray": "Graustufen",
        "grid": "Gitter",
        "grid_off": "Aus",
        "grid_white": "Weiß",
        "grid_black": "Schwarz",
        "grid_spacing": "Gitterabstand",
        "grid_hint": "G schaltet Farbe und Raster durch · Shift+G aus",
        "settings_none": "Einstellungen: –",
        "previous": "◀ Vorheriges",
        "next": "Nächstes ▶",
        "start_single": "Justage starten",
        "start_analysis": "Ordner analysieren",
        "start_favorites": "Favoriten ausgeben",
        "start_batch": "Alle justieren",
        "cancel": "Abbrechen",
        "cancelling": "Abbruch läuft…",
        "save": "Speichern",
        "help_footer": "F1 · Tastaturhilfe",
        "output_folder_dialog": "Eigenen Ausgabeordner auswählen",
        "single_pair_dialog": "Linkes oder rechtes Bild auswählen",
        "single_stereo_dialog": "Full-SBS/MPO-Datei auswählen",
        "batch_pair_dialog": "Links/Rechts-Bildordner auswählen",
        "batch_stereo_dialog": "Full-SBS/MPO-Bildordner auswählen",
        "no_pair_files": "Im gewählten Ordner wurden keine unterstützten Links/Rechts-Bildpaare gefunden.",
        "no_stereo_files": "Im gewählten Ordner wurden keine unterstützten Full-SBS/MPO-Dateien gefunden.",
        "select_output_folder": "Bitte einen Ausgabeordner auswählen.",
        "internal_preview_error": "Interner Fehler: Analyse lieferte kein Vorschaubild.",
        "preview_error": "Vorschaufehler:\n{text}",
        "start_image_error": "Startbild konnte nicht geladen werden:\n{text}",
        "processing_failed_count": "Verarbeitung beendet, aber {count} Fehler sind aufgetreten.\n\n{details}",
        "metadata_warnings": "Bildausgabe abgeschlossen, aber Metadaten konnten nicht vollständig übernommen werden.\n\n{details}",
        "saved": "Gespeichert.",
        "analysis_complete": "Analyse abgeschlossen. {images} analysiert.\nBericht: {report}",
        "favorites_complete": "Favoriten-Ausgabe abgeschlossen. {images} ausgegeben.",
        "batch_complete": "Stapelverarbeitung abgeschlossen. {images} ausgegeben.",
        "nonfavorites_skipped": "{images} nicht ausgegeben.",
        "processing_cancelled": "Verarbeitung abgebrochen.",
        "processing_failed": "Verarbeitung fehlgeschlagen:\n\n{text}",
        "close_busy": "Eine Verarbeitung läuft noch. Wirklich beenden?",
        "help_title": "StereoFine – Tastaturhilfe",
        "help_heading": "Tastaturhilfe",
        "help_key_column": "Taste",
        "help_action_column": "Funktion",
        "help_text": (
            "Navigation\n"
            "  Page Up / Page Down     Vorheriges / nächstes Bild\n"
            "  Leertaste               Justage bzw. Stapel starten\n"
            "  Enter                   Aktuelles Bild speichern\n\n"
            "Manuelle Justage\n"
            "  ← / →                   Horizontal verschieben\n"
            "  ↑ / ↓                   Vertikal verschieben\n"
            "  Shift + Pfeiltaste      5 px\n"
            "  Strg + Pfeiltaste       10 px\n"
            "  Strg + R                 Manuelle Bearbeitung zurücksetzen\n\n"
            "Ausschnitt\n"
            "  Alt + Pfeiltaste        Ausschnitt verschieben\n"
            "  Strg + Shift + ↑/↓      Zoom\n\n"
            "Schwebendes Scheinfenster\n"
            "  S                        Links/Rechts gekoppelt/separat\n"
            "  L/R/T/B halten + ←/→    Gewählte Kante -/+ 1‰\n\n"
            "Vorschau\n"
            "  A                        Farbig/Graustufen\n"
            "  G                        Gitter durchschalten\n"
            "  Shift + G                Gitter aus\n"
            "  M halten                 Messkreuz anzeigen\n"
            "  M + Pfeiltasten          Messkreuz bewegen\n"
            "  F11                      Vollbild\n"
            "  F1                       Diese Hilfe\n"
            "  Esc                      Vollbild/Hilfe schließen"
        ),
        "status_ready": "Bereit",
        "status_analysis": "Analyse",
        "status_deviation_open": "Deviation offen",
        "status_not_analyzed": "Nicht analysiert",
        "status_active": "aktiv",
        "status_stale": "Deviation nach Änderung erneut analysieren.",
        "status_uncertain": "Einschätzung unsicher – bitte prüfen!",
        "status_input": "Input",
        "status_batch_preview": "Batch: {count} · Vorschau {index}/{count}",
        "loading": "Lädt…",
        "alignment_running": "Justage läuft…",
        "analysis_running": "Analyse läuft…",
        "batch_running": "Stapel läuft…",
        "batch_progress": "Stapel {index}/{total}…",
        "analysis_progress": "Analyse {index}/{total}…",
        "saving": "Speichert…",
        "completed_short": "Abgeschlossen",
        "progress_analyzed": "Analysiert",
        "progress_exported": "Exportiert",
        "unknown_error": "Unbekannter Fehler",
        "status_model": "Modell",
        "status_vertical_error": "Mittlerer Höhenfehler",
        "status_vertical_shift": "Höhenverschiebung",
        "status_rotation": "Rotation",
        "status_vergence": "Vergenz (Trapezkorrektur)",
        "status_total_deviation": "Gesamtdeviation",
        "status_near": "Nahpunkt",
        "status_far": "Fernpunkt",
        "status_floating": "Schwebendes Scheinfenster",
        "status_lr": "Links / Rechts",
        "status_tb": "Oben / Unten",
        "traffic_green": "grün",
        "traffic_orange": "orange",
        "traffic_red": "rot",
        "traffic_gray": "unsicher",
        "sidecar_new": "Einstellungen: Neu",
        "sidecar_loaded": "Einstellungen: Geladen",
        "sidecar_partial": "Einstellungen: Geladen · Teilanalyse veraltet",
        "sidecar_legacy": "Einstellungen: Legacy geladen · Prüfung nötig",
        "sidecar_stale": "Einstellungen: Quelle geändert",
        "sidecar_invalid": "Einstellungen: Ungültig",
        "report_title": "Analysebericht",
        "report_created": "Erstellt",
        "report_input": "Input",
        "report_width": "Deviation-Analysebreite: Max. {width} px",
        "report_file": "Datei",
        "report_traffic": "Ampel",
        "report_note": "Anmerkung",
        "report_vergence": "Vergenz",
        "yes": "ja",
        "no": "nein",
        "status_unavailable": "nicht verfügbar",
        "error": "Fehler",
        "unknown": "–",
    },
    "en": {
        "subtitle": "Align and fine-tune stereo photos",
        "language": "Language",
        "fullscreen": "Fullscreen",
        "windowed": "Windowed",
        "input": "Input",
        "single_edit": "Single image",
        "batch_processing": "Batch processing",
        "left_right": "Left/Right",
        "full_sbs_mpo": "Full-SBS/MPO",
        "analysis_only": "Analysis only · Text report",
        "favorites_only": "Export favorites only",
        "alignment": "Alignment",
        "left": "Left",
        "right": "Right",
        "mirror": "Mirror",
        "swap_eyes": "Swap Left/Right",
        "analysis_method": "Analysis method",
        "image_output": "Image and output",
        "aspect_ratio": "Aspect ratio",
        "color_match": "Symmetric color matching",
        "output": "Output",
        "use_input_subfolder": "Use subfolder in input folder",
        "custom_output_folder": "Custom output folder",
        "choose": "Choose",
        "preview": "Preview",
        "preview_color": "Color",
        "preview_gray": "Grayscale",
        "grid": "Grid",
        "grid_off": "Off",
        "grid_white": "White",
        "grid_black": "Black",
        "grid_spacing": "Grid spacing",
        "grid_hint": "G cycles color and spacing · Shift+G off",
        "settings_none": "Settings: –",
        "previous": "◀ Previous",
        "next": "Next ▶",
        "start_single": "Start alignment",
        "start_analysis": "Analyze folder",
        "start_favorites": "Export favorites",
        "start_batch": "Align all",
        "cancel": "Cancel",
        "cancelling": "Cancelling…",
        "save": "Save",
        "help_footer": "F1 · Keyboard help",
        "output_folder_dialog": "Choose custom output folder",
        "single_pair_dialog": "Choose left or right image",
        "single_stereo_dialog": "Choose Full-SBS/MPO file",
        "batch_pair_dialog": "Choose Left/Right image folder",
        "batch_stereo_dialog": "Choose Full-SBS/MPO image folder",
        "no_pair_files": "No supported Left/Right image pairs were found in the selected folder.",
        "no_stereo_files": "No supported Full-SBS/MPO files were found in the selected folder.",
        "select_output_folder": "Please choose an output folder.",
        "internal_preview_error": "Internal error: Analysis returned no preview image.",
        "preview_error": "Preview error:\n{text}",
        "start_image_error": "Start image could not be loaded:\n{text}",
        "processing_failed_count": "Processing finished, but {count} errors occurred.\n\n{details}",
        "metadata_warnings": "Image export completed, but metadata could not be copied completely.\n\n{details}",
        "saved": "Saved.",
        "analysis_complete": "Analysis complete. {images} analyzed.\nReport: {report}",
        "favorites_complete": "Favorite export complete. {images} exported.",
        "batch_complete": "Batch processing complete. {images} exported.",
        "nonfavorites_skipped": "{images} not exported.",
        "processing_cancelled": "Processing cancelled.",
        "processing_failed": "Processing failed:\n\n{text}",
        "close_busy": "Processing is still running. Quit anyway?",
        "help_title": "StereoFine – Keyboard help",
        "help_heading": "Keyboard help",
        "help_key_column": "Key",
        "help_action_column": "Action",
        "help_text": (
            "Navigation\n"
            "  Page Up / Page Down     Previous / next image\n"
            "  Space                   Start alignment or batch\n"
            "  Enter                   Save current image\n\n"
            "Manual alignment\n"
            "  ← / →                   Shift horizontally\n"
            "  ↑ / ↓                   Shift vertically\n"
            "  Shift + Arrow           5 px\n"
            "  Ctrl + Arrow            10 px\n"
            "  Ctrl + R                Reset manual editing\n\n"
            "Crop\n"
            "  Alt + Arrow             Move crop\n"
            "  Ctrl + Shift + ↑/↓      Zoom\n\n"
            "Floating Window\n"
            "  S                        Left/Right linked/separate\n"
            "  Hold L/R/T/B + ←/→      Selected edge -/+ 1‰\n\n"
            "Preview\n"
            "  A                        Color/Grayscale\n"
            "  G                        Cycle grid\n"
            "  Shift + G                Grid off\n"
            "  Hold M                   Show measurement cross\n"
            "  M + Arrow keys           Move measurement cross\n"
            "  F11                      Fullscreen\n"
            "  F1                       This help\n"
            "  Esc                      Close fullscreen/help"
        ),
        "status_ready": "Ready",
        "status_analysis": "Analysis",
        "status_deviation_open": "Deviation pending",
        "status_not_analyzed": "Not analyzed",
        "status_active": "active",
        "status_stale": "Re-analyze deviation after this change.",
        "status_uncertain": "Estimate uncertain – please check!",
        "status_input": "Input",
        "status_batch_preview": "Batch: {count} · Preview {index}/{count}",
        "loading": "Loading…",
        "alignment_running": "Alignment running…",
        "analysis_running": "Analysis running…",
        "batch_running": "Batch running…",
        "batch_progress": "Batch {index}/{total}…",
        "analysis_progress": "Analysis {index}/{total}…",
        "saving": "Saving…",
        "progress_analyzed": "Analyzed",
        "progress_exported": "Exported",
        "unknown_error": "Unknown error",
        "status_model": "Model",
        "status_vertical_error": "Mean vertical error",
        "status_vertical_shift": "Vertical shift",
        "status_rotation": "Rotation",
        "status_vergence": "Vergence (trapezoid correction)",
        "status_total_deviation": "Total deviation",
        "status_near": "Near point",
        "status_far": "Far point",
        "status_floating": "Floating Window",
        "status_lr": "Left / Right",
        "status_tb": "Top / Bottom",
        "traffic_green": "green",
        "traffic_orange": "orange",
        "traffic_red": "red",
        "traffic_gray": "uncertain",
        "sidecar_new": "Settings: New",
        "sidecar_loaded": "Settings: Loaded",
        "sidecar_partial": "Settings: Loaded · Partial analysis outdated",
        "sidecar_legacy": "Settings: Legacy loaded · Check required",
        "sidecar_stale": "Settings: Source changed",
        "sidecar_invalid": "Settings: Invalid",
        "report_title": "Analysis report",
        "report_created": "Created",
        "report_input": "Input",
        "report_width": "Deviation analysis width: Max. {width} px",
        "report_file": "File",
        "report_traffic": "Traffic light",
        "report_note": "Note",
        "report_vergence": "Vergence",
        "yes": "yes",
        "no": "no",
        "status_unavailable": "unavailable",
        "error": "Error",
        "unknown": "–",
    },
}

# Internal core messages stay independent from the GUI language.  Translate only
# at presentation boundaries so algorithms, sidecars and tests remain canonical.
DIAGNOSTIC_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "low_valid_area": "zu wenig gültige Disparitätsfläche",
        "low_edge_cluster_missing": "niedriger Disparitätsrand nicht als Cluster sichtbar – Perzentilwert verwendet",
        "high_edge_cluster_missing": "hoher Disparitätsrand nicht als Cluster sichtbar – Perzentilwert verwendet",
        "disparity_range_unreliable": "Disparitätsspanne zu klein oder nicht belastbar",
        "outer_range_wider": "Grenzbereich P0,5/P99,5 deutlich größer als P1/P99",
        "inner_range_narrower": "innerer Bereich P2/P98 deutlich kleiner als P1/P99",
        "low_valid_area_warning": "geringe gültige Disparitätsfläche",
    },
    "en": {
        "low_valid_area": "too little valid disparity area",
        "low_edge_cluster_missing": "low disparity edge not visible as a cluster – percentile used",
        "high_edge_cluster_missing": "high disparity edge not visible as a cluster – percentile used",
        "disparity_range_unreliable": "disparity range too small or unreliable",
        "outer_range_wider": "outer P0.5/P99.5 range clearly larger than P1/P99",
        "inner_range_narrower": "inner P2/P98 range clearly smaller than P1/P99",
        "low_valid_area_warning": "low valid disparity area",
        # Legacy localized presentation strings accepted when older sidecars are read.
        "zu wenig gültige Disparitätsfläche": "too little valid disparity area",
        "niedriger Disparitätsrand nicht als Cluster sichtbar – Perzentilwert verwendet": "low disparity edge not visible as a cluster – percentile used",
        "hoher Disparitätsrand nicht als Cluster sichtbar – Perzentilwert verwendet": "high disparity edge not visible as a cluster – percentile used",
        "Disparitätsspanne zu klein oder nicht belastbar": "disparity range too small or unreliable",
        "Grenzbereich P0,5/P99,5 deutlich größer als P1/P99": "outer P0.5/P99.5 range clearly larger than P1/P99",
        "innerer Bereich P2/P98 deutlich kleiner als P1/P99": "inner P2/P98 range clearly smaller than P1/P99",
        "geringe gültige Disparitätsfläche": "low valid disparity area",
        "Ausschnitt geändert.": "Crop changed.",
        "Ausschnitt verschoben.": "Crop moved.",
        "Seitenverhältnis geändert.": "Aspect ratio changed.",
        "Vertikale Feinjustage geändert.": "Vertical fine adjustment changed.",
        "Eingabeausrichtung geändert.": "Input orientation changed.",
        "Nach Eingabeänderung neu analysieren.": "Re-analyze after changing the input.",
        "Nahpunkt nicht belastbar verfügbar.": "Near point is not reliably available.",
        "Zu wenig belastbare Disparitätsdaten.": "Too little reliable disparity data.",
        "Nah-/Fernpunkt unsicher – manuelle Kontrolle empfohlen.": "Near/far point uncertain – manual check recommended.",
        "Deviation im grünen Bereich.": "Deviation within the green range.",
        "Deviation erhöht – Kontrolle empfohlen.": "Deviation elevated – check recommended.",
        "Deviation zu hoch – Korrektur/Scheinfenster prüfen.": "Deviation too high – check correction/window placement.",
    },
}

CORE_MESSAGE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "Zu wenige Inlier für LMS-Affine-Schätzung.": "Too few inliers for LMS affine estimation.",
        "LMS-Schätzung ist geometrisch unplausibel; automatische Korrektur abgebrochen.": "LMS estimate is geometrically implausible; automatic correction aborted.",
        "Zu wenige gültige Punkte für Trapez-Least-Squares-Fit.": "Too few valid points for the trapezoid least-squares fit.",
        "OpenCV ist nicht installiert oder konnte nicht geladen werden.": "OpenCV is not installed or could not be loaded.",
        "SIFT ist in dieser OpenCV-Version nicht verfügbar.": "SIFT is not available in this OpenCV version.",
        "Zu wenige Merkmale für eine zuverlässige Analyse gefunden.": "Too few features found for a reliable analysis.",
        "Zu wenige stabile Übereinstimmungen nach dem Matching gefunden.": "Too few stable matches found after feature matching.",
        "y-RANSAC konnte keine stabile Inlier-Gruppe bestimmen.": "y-RANSAC could not determine a stable inlier group.",
        "Zu wenige Inlier für eine stabile Analyse gefunden (y-RANSAC).": "Too few inliers found for a stable analysis (y-RANSAC).",
        "Anaglyphen-Eingaben müssen uint8-RGB-Bilder sein.": "Anaglyph inputs must be uint8 RGB images.",
        "block_rows muss mindestens 1 sein.": "block_rows must be at least 1.",
        "Für Bildausgabe ist ein Ausgabeordner erforderlich.": "An output folder is required for image export.",
        "Interner Fehler: Masterbild für Ausgabe nicht verfügbar.": "Internal error: Master image is not available for export.",
        "max_samples muss mindestens 1 sein.": "max_samples must be at least 1.",
        "Mindestens ein Perzentil wird benötigt.": "At least one percentile is required.",
        "Perzentile müssen strikt steigend zwischen 0 und 100 liegen.": "Percentiles must be strictly increasing between 0 and 100.",
        "Farbangleich-Stärke muss zwischen 0 und 1 liegen.": "Color-matching strength must be between 0 and 1.",
        "Kein vollständiges Bildpaar.": "No complete stereo pair.",
        "Analysebild zu klein.": "Analysis image is too small.",
        "Zu wenig belastbare Disparitätsdaten.": "Too little reliable disparity data.",
        "Nahpunkt nicht belastbar verfügbar.": "Near point is not reliably available.",
        "Die Halbbilder besitzen keinen gemeinsamen gültigen Bildbereich.": "The half-images have no common valid image area.",
        "Full-SBS-Datei ist zu schmal.": "Full-SBS file is too narrow.",
        "Full-SBS-Datei enthält keine zwei gültigen Halbbilder.": "Full-SBS file does not contain two valid half-images.",
        "MPO-Datei enthält kein zweites Halbbild.": "MPO file does not contain a second half-image.",
        "Keine gültige Metadatenquelle.": "No valid metadata source.",
        "Zieldatei existiert nicht.": "Target file does not exist.",
        "ExifTool nicht gefunden.": "ExifTool not found.",
        "ExifTool meldete einen Fehler.": "ExifTool reported an error.",
        "Kein passendes Links/Rechts-Bildpaar gefunden. Erwartet werden l/r-Unterordner oder Dateien mit _l/_r im selben Ordner.": "No matching Left/Right image pair found. Expected: l/r subfolders or files using _l/_r in the same folder.",
        "Quelldatei stimmt nicht mit Sidecar überein.": "Source file does not match the sidecar.",
        "Legacy-Sidecar v2 importiert; Quelle erneut prüfen.": "Legacy v2 sidecar imported; please check the source again.",
        "Kein vollständiges Bildpaar für Deviation-Analyse.": "No complete stereo pair for deviation analysis.",
        "Unbekanntes Sidecar-Schema.": "Unknown sidecar schema.",
    }
}

CORE_PREFIX_TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "Trapez-Fit nicht stabil genug: ": "Trapezoid fit not stable enough: ",
        "Unbekanntes Analyseverfahren: ": "Unknown analysis method: ",
        "Linkes und rechtes Bild müssen gleich groß sein: ": "Left and right images must have the same size: ",
        "RGB-Bild mit Form HxWx3 erwartet, erhalten: ": "Expected an HxWx3 RGB image, received: ",
        "Nicht unterstützte Bittiefe für Farbangleich: ": "Unsupported bit depth for color matching: ",
        "Halbbilder haben unterschiedliche Größen: ": "Half-images have different sizes: ",
        "RGB-Bild HxWx3 erwartet, erhalten: ": "Expected an HxWx3 RGB image, received: ",
        "Halbbilder haben unterschiedliche Datentypen: ": "Half-images have different data types: ",
        "Ungültige Farbangleich-Parameter: ": "Invalid color-matching parameters: ",
        "Unbekannte Farbangleich-Methode: ": "Unknown color-matching method: ",
        "OpenCV nicht verfügbar: ": "OpenCV unavailable: ",
        "Nicht unterstützte Ausgabebittiefe: ": "Unsupported output bit depth: ",
        "Ausgabedatei wurde nicht korrekt geschrieben: ": "Output file was not written correctly: ",
        "Unbekannter Ausgabemodus: ": "Unknown output mode: ",
        "Bild konnte nicht gelesen werden: ": "Image could not be read: ",
        "Unerwartete Bildform: ": "Unexpected image shape: ",
        "Unerwartete Kanalzahl: ": "Unexpected channel count: ",
        "Nicht unterstützte oder beschädigte Bilddatei: ": "Unsupported or damaged image file: ",
        "Nicht unterstütztes Bildformat: ": "Unsupported image format: ",
        "Nicht unterstützte Bittiefe: ": "Unsupported bit depth: ",
        "MPO-Datei konnte nicht geladen werden: ": "MPO file could not be loaded: ",
        "Metadaten SBS: ": "SBS metadata: ",
        "Metadaten Anaglyphe: ": "Anaglyph metadata: ",
        "Neu berechnen: ": "Recompute: ",
        "Unbekannte Stereoquelle: ": "Unknown stereo source: ",
    }
}


@dataclass(frozen=True)
class Translator:
    language: Language = "de"

    def t(self, key: str, **values: object) -> str:
        language = self.language if self.language in TEXTS else "de"
        template = TEXTS[language].get(key, TEXTS["de"].get(key, key))
        return template.format(**values) if values else template

    def image_count(self, count: int) -> str:
        if self.language == "en":
            return f"{count} image" if count == 1 else f"{count} images"
        return f"{count} Bild" if count == 1 else f"{count} Bilder"

    def nonfavorite_count(self, count: int) -> str:
        if self.language == "en":
            return f"{count} non-favorite image" if count == 1 else f"{count} non-favorite images"
        return f"{count} nicht favorisiertes Bild" if count == 1 else f"{count} nicht favorisierte Bilder"

    def diagnostic(self, text: str) -> str:
        if not text:
            return text
        return DIAGNOSTIC_TRANSLATIONS.get(self.language, {}).get(text, text)

    def message(self, text: str) -> str:
        """Translate a user-facing core message without localizing core state."""
        if not text:
            return text
        if "; " in text:
            return "; ".join(self.message(part) for part in text.split("; "))
        diagnostics = DIAGNOSTIC_TRANSLATIONS.get(self.language, {})
        if text in diagnostics:
            return diagnostics[text]
        if self.language == "de":
            return text
        exact = CORE_MESSAGE_TRANSLATIONS.get(self.language, {})
        if text in exact:
            return exact[text]
        for prefix, translated_prefix in CORE_PREFIX_TRANSLATIONS.get(self.language, {}).items():
            if text.startswith(prefix):
                remainder = text[len(prefix):]
                return translated_prefix + self.message(remainder)
        return text


def language_label(code: str) -> str:
    return {"de": "Deutsch", "en": "English"}.get(code, "Deutsch")


def language_code(label: str) -> str:
    return {"Deutsch": "de", "English": "en"}.get(label, "de")


def aspect_label(code: str, language: str) -> str:
    code = {"Maximal": "maximum", "Maximum": "maximum", "Original": "original"}.get(code, code)
    if code == "maximum":
        return "Maximal" if language == "de" else "Maximum"
    if code == "original":
        return "Original"
    return code


def aspect_code(label: str) -> str:
    return {"Maximal": "maximum", "Maximum": "maximum", "Original": "original"}.get(label, label)


def orientation_label(code: str, language: str) -> str:
    code = {
        "0°": "0", "180°": "180", "90° rechts": "90_cw", "90° links": "90_ccw",
        "90° right": "90_cw", "90° left": "90_ccw",
    }.get(code, code)
    labels = {
        "de": {"0": "0°", "180": "180°", "90_cw": "90° rechts", "90_ccw": "90° links"},
        "en": {"0": "0°", "180": "180°", "90_cw": "90° right", "90_ccw": "90° left"},
    }
    return labels.get(language, labels["de"]).get(code, code)


def orientation_code(label: str) -> str:
    return {
        "0°": "0", "180°": "180",
        "90° rechts": "90_cw", "90° links": "90_ccw",
        "90° right": "90_cw", "90° left": "90_ccw",
    }.get(label, label)


def output_mode_label(code: str, language: str) -> str:
    mapping = {
        "de": {"both": "SBS + Anaglyphe", "sbs": "SBS", "anaglyph": "Anaglyphe"},
        "en": {"both": "SBS + Anaglyph", "sbs": "SBS", "anaglyph": "Anaglyph"},
    }
    return mapping.get(language, mapping["de"]).get(code, mapping["de"]["both"])


def output_mode_code(label: str) -> str:
    return {
        "SBS + Anaglyphe": "both",
        "Anaglyphe": "anaglyph",
        "SBS + Anaglyph": "both",
        "Anaglyph": "anaglyph",
        "SBS": "sbs",
    }.get(label, "both")


def grid_spacing_label(code: str, language: str) -> str:
    if language == "en":
        return {
            "25 Promille": "25 ‰",
            "50 Promille": "50 ‰",
            "100 Promille": "100 ‰",
            "Drittel-Raster": "Rule of thirds",
        }.get(code, code)
    return code


def grid_spacing_code(label: str) -> str:
    return {
        "25 ‰": "25 Promille",
        "50 ‰": "50 Promille",
        "100 ‰": "100 Promille",
        "Rule of thirds": "Drittel-Raster",
    }.get(label, label)
