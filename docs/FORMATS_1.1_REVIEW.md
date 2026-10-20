> Historical review. The implemented scope and current checks are documented in [IMAGE_FORMATS_1.1.md](IMAGE_FORMATS_1.1.md).

# Bildformate für StereoFine 1.1 im Vergleich zu TransCora

Stand: 20. Oktober 2026. Dies ist eine geprüfte Empfehlung, keine bereits
freigeschaltete Unterstützung zusätzlicher Formate.

Verglichen wurden StereoFines Forschungsstand `50d59b9` und TransCoras
1.1-Entwicklungsstand `c8f7a00b8ea0494912454e668740c2071a5c2766`.
Die tatsächlich unterstützten Endungen stammen aus `stereofine/config.py`
beziehungsweise `transcora/core/images.py` und `transcora/core/heif.py`.
TransCoras Quellstand ist nicht mit dem Funktionsumfang sämtlicher bereits
veröffentlichter TransCora-Pakete gleichzusetzen.

| Eingabe | StereoFine bisher | TransCora 1.1, Quellstand | Empfehlung für StereoFine 1.1 |
| --- | --- | --- | --- |
| JPEG, PNG, TIFF, MPO | Ja | Ja | Erhalten; StereoFine behält bei PNG/TIFF bereits 16-Bit-Masterdaten |
| JPS / PNS | Nein | Ja | Naheliegende Ergänzung als JPEG-/PNG-Endungen für Stereoquellen |
| Statisches WebP | Nein | Ja | Sinnvoll, mit klarer Behandlung von Transparenz und Farbprofilen |
| BMP | Nein | Ja | Kleine Kompatibilitätsergänzung, geringe fachliche Priorität |
| HEIC / HEIF, gekennzeichnete Stereo-HEIC und Spatial Photos | Nein | Ja, SDR | Größter zusätzlicher Nutzen; vorhandenen TransCora-Leser wiederverwenden |

## Prioritäten und Grenzen

**JPS/PNS zuerst.** Hier wird kein neuer Bildcodec benötigt. Endung, Dateisuche,
Dateidialog und Stereoquelle müssen zusammenpassen. Die Dateiendung allein ist
kein zuverlässiger Beleg für L/R-Anordnung, Full-/Half-SBS oder Over/Under.
Vorhandene eindeutige Kennzeichnungen auswerten; sonst die bewusst gewählte,
unterstützte Eingabeanordnung verwenden. Keine stumme Deutung unbekannter
Layouts und keine neue automatische Layout-Raterei.

**HEIC/HEIF als eigentliche Formaterweiterung.** TransCora besitzt bereits einen
lokalen Leser und Buildvorbereitung. Übernehmen statt eines zweiten eigenen
Containerparsers. Stereo-HEIC benötigt die echte Stereo-Gruppe und deren
Augenzuordnung; beliebige erste zwei Bilder können etwa Zusatzbilder sein.
Die offizielle pillow-heif-Dokumentation beschreibt `ster`-Entity-Gruppen:
https://pillow-heif.readthedocs.io/en/stable/heif-file.html#stereo-pairs

Zunächst denselben klaren SDR-Umfang prüfen. HDR, Gainmaps und Tiefenkarten dürfen
nicht stillschweigend als normale Bildhälften oder als korrekt tonwertgewandelte
RGB-Bilder gelten. Vor Aufnahme in StereoFine müssen Farbprofile/SDR-Farbraum,
Orientierung ohne Doppelanwendung, native Bildgrößen, L/R-Zuordnung,
Quellen-Fingerprint und `.sfin`-Wiederladen einschließlich Augen-IDs passen.
Eine neue Containerquelle kann einen erweiterten Quellvertrag benötigen;
die Gleichsetzung mit einem gewöhnlichen Full-SBS-Bild reicht nicht aus.
Decoder und Abhängigkeiten lokal mitliefern und alle Plattformpakete prüfen.
Das ist umfangreicher als zusätzliche Dateiendungen freizuschalten.

**WebP/BMP ergänzend.** Die vorhandene Laufzeit kann sie in der lokalen Probe
lesen. Animiertes WebP soll nicht versehentlich als ein normales Stereofoto
oder als zwei Stereoaugen behandelt werden. Transparenz und Profile vor einer
Freigabe ausdrücklich prüfen; die derzeitige PNG-Behandlung ist kein Nachweis
korrekter Alpha-Verarbeitung für alle neuen Formate.

**RAW ist keine Priorität für dieses Qualitätsziel.** TransCora bietet in dem
verglichenen Pfad ebenfalls keine RAW-Entwicklung. Für die vorhandenen Aufnahmen
bleibt die Entwicklung in DxO und Übergabe als TIFF ein sinnvoller Arbeitsweg.
AVIF/JPEG XL sind ebenfalls keine Formate des verglichenen TransCora-Readers.
Sie sind für die aktuelle Angleichung daher kein notwendiger Bestandteil.

Bildanordnungen wie OU, Half-SBS und Zeilenverschachtelung sind getrennt von
Dateicontainern zu betrachten. Ihre Rekonstruktion und Eingabeauswahl wären
eine zusätzliche Funktionsentscheidung, keine reine Erweiterung der Endungsliste.
Ebenso ist eine verlustfreie SBS-Ausgabe in PNG/TIFF eine eigene Exporterweiterung;
die bestehenden JPEG-Ausgaben werden in diesem Schritt nicht verändert.

## Tatsächlich ausgeführte Decoderprobe

`experiments/probe_image_formats.py` erzeugt kleine künstliche Dateien in einem
temporären Verzeichnis und verwendet die bestehenden OpenCV-Decodier- und
Orientierungsfunktionen, ohne die Produktions-Endungsliste zu ändern.

- JPEG unter `.jps`: identische Pixel wie bei Pillow-Dekodierung derselben Datei.
- PNG unter `.pns`, BMP und verlustfreies WebP: bytegleiche RGB-Pixel zum Muster.
- 16-Bit-RGB-PNG unter `.pns`: `uint16` und sämtliche Musterwerte unverändert.
- Animiertes WebP: zwei Frames erkannt; noch keine produktive Animationsbehandlung.

[Probe-Ergebnis](FORMAT_PROBE_1.1_RESULTS.json).

Diese Prüfung ist ein Linux-Lauf mit den vorhandenen gepinnten Abhängigkeiten,
kein Windows/macOS-Buildtest und kein Test aller realen Farbprofile, Orientierungen,
Alpha- oder Container-Sonderfälle. HEIC/HEIF wurde hier nicht neu integriert oder
als StereoFine-Funktion getestet. Seine Empfehlung stützt sich auf den vorhandenen
TransCora-Leser und dessen dokumentierte Prüfungen, nicht auf eine erfundene
StereoFine-Unterstützung.

```sh
python experiments/probe_image_formats.py --output format_probe.json
```

Quellen:
- https://github.com/muelli1975/TransCora/blob/c8f7a00b8ea0494912454e668740c2071a5c2766/transcora/core/images.py
- https://github.com/muelli1975/TransCora/blob/c8f7a00b8ea0494912454e668740c2071a5c2766/transcora/core/heif.py
- https://github.com/muelli1975/TransCora/blob/c8f7a00b8ea0494912454e668740c2071a5c2766/README_DE.md
