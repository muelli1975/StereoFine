# StereoFine 1.0

[English](README_EN.md)

StereoFine ist ein lokales Desktop-Werkzeug zum automatischen Ausrichten, Prüfen, Rahmen und Ausgeben stereoskopischer Bildpaare. Es soll möglichst viel zuverlässig automatisch erledigen, ohne die manuelle Kontrolle aus der Hand zu nehmen. Die Oberfläche bleibt deshalb bewusst schlank und tastaturfreundlich.

StereoFine arbeitet vollständig lokal: kein Konto, keine Cloud, kein Tracking und kein automatischer Download während der Nutzung.

## Portable Windows-Version

Die veröffentlichte Windows-Version ist portabel:

1. `StereoFine_1.0.zip` vollständig in einen normalen beschreibbaren Ordner entpacken.
2. `StereoFine.exe` starten.
3. Den Programmordner zusammenlassen; `tools`, `_internal` und die übrigen mitgelieferten Dateien gehören zur Anwendung.

Eine Python-Installation ist für die portable Version nicht erforderlich. Globale Einstellungen werden als `settings.json` direkt neben `StereoFine.exe` gespeichert.

## macOS- und Linux-Builds

Derselbe Quellcode kann zusätzlich für macOS (Apple Silicon und Intel) sowie Linux x64 paketiert werden. GitHub Actions erzeugt diese Varianten aus demselben getaggten Quellstand. Windows bleibt die praktisch geprüfte Referenzplattform von 1.0; die macOS-/Linux-Binärdateien gelten bis zu einem realen Desktop-Sichttest auf diesen Systemen als Plattform-Builds. Stereo-, Geometrie- und Farbverarbeitung sind plattformübergreifend identisch. Die Plattformpakete enthalten ExifTool für die Metadatenübernahme; unter macOS/Linux basiert die offizielle ExifTool-Distribution auf Perl und setzt daher einen funktionierenden Perl-Interpreter auf dem Zielsystem voraus. Ist die Metadatenübernahme nicht verfügbar, bleibt das erfolgreich geschriebene Bild erhalten und StereoFine meldet lediglich eine nicht fatale Warnung.

## Schnellstart

1. Über **Links/Rechts** ein Bild aus einem Stereo-Paar wählen oder über **Full-SBS/MPO** eine Stereo-Datei öffnen.
2. **Justage starten**. StereoFine analysiert die Geometrie, bestimmt Nahpunkt, Fernpunkt und Gesamtdeviation und rahmt den erkannten Nahpunkt standardmäßig knapp hinter das Scheinfenster.
3. Ergebnis in der Anaglyphenvorschau prüfen und bei Bedarf per Tastatur feinjustieren.
4. **Speichern**. StereoFine schreibt immer ein SBS-JPEG und eine Anaglyphe. Über die Vorschauwahl bestimmst du nur, ob die Anaglyphe farbig oder in Graustufen erzeugt wird.

Für ganze Ordner steht derselbe Rechenkern als Stapelverarbeitung zur Verfügung.

## Unterstützte Eingaben

Offiziell unterstützt werden:

- JPEG/JPG
- PNG
- TIFF/TIF
- MPO
- Full-SBS in JPEG, PNG oder TIFF
- getrennte Links/Rechts-Paare als `*_l` / `*_r`
- getrennte Paare in den Unterordnern `l` und `r`

HEIC/HEIF und RAW gehören bewusst nicht zum Funktionsumfang von StereoFine 1.0 und sollten vorher konvertiert werden.

16-Bit-PNG und 16-Bit-TIFF werden nicht bereits beim Laden auf 8 Bit reduziert. Für Feature-/Disparitätsanalyse und Vorschau erzeugt StereoFine getrennte 8-Bit-Proxys. Die fertigen JPEG-Ausgaben sind bewusst 8 Bit.

## Automatische Justage

StereoFine verwendet eine konservative Modellhierarchie:

- **AKAZE** ist die schnelle Standardmethode für Merkmalspunkte.
- **SIFT** steht als langsamere manuelle Alternative zur Verfügung.
- Eine symmetrische affine Korrektur behandelt Höhenverschiebung, Rotation und relative Größenabweichung.
- Eine kontrollierte **Vergence-/Trapezkorrektur** wird nur zugelassen, wenn sie auf unabhängigen Prüfpunkten tatsächlich besser ist als das einfachere Modell.
- **Y-Polish** kann verbleibende vertikale Restfehler korrigieren, wird aber ebenfalls nur eingesetzt, wenn er einen messbaren zusätzlichen Nutzen bringt.

Die Geometrieanalyse arbeitet mit maximal 3000 px Breite. Alle ausgewählten geometrischen Korrekturen – affine Justage, Vergenz-/Trapezkorrektur und Y-Polish – werden zu einer einzigen Abbildung zusammengesetzt. Jedes Halbbild wird anschließend nur einmal mit hochwertiger Lanczos-Interpolation neu abgetastet; so werden kumulative Interpolationsverluste durch mehrere aufeinanderfolgende Verformungen vermieden.

## Deviation, Nahpunkt und Fernpunkt

Nach der geometrischen Korrektur erfolgt eine separate halb-dichte horizontale Disparitätsanalyse mit maximal 1500 px Breite. Hauptwerte sind robuste P1/P99-Grenzen; zusätzliche robuste Bereiche dienen der Unsicherheitsbewertung.

Die Ampel ist eine praktische Orientierung:

- **grün:** bis 33‰ Gesamtdeviation
- **orange:** über 33‰ bis 40‰
- **rot:** über 40‰
- **grau:** Messung nicht verfügbar oder als unsicher bewertet

Die Farben sind eine Arbeitshilfe und keine harte physiologische Grenze.

### Automatische Nahpunktrahmung

Bei belastbarer Analyse verschiebt StereoFine das Paar horizontal so, dass der erkannte Nahpunkt standardmäßig mindestens **3‰ hinter dem Scheinfenster** liegt. Wegen ganzer Pixel kann der tatsächliche Wert geringfügig weiter hinten liegen.

`Strg+R` stellt genau diesen Autozustand wieder her: Auto-Justage einschließlich der 3‰-Nahpunktrahmung. Nachträgliche manuelle Korrekturen werden verworfen.

## Schwebendes Scheinfenster

Schwebende Scheinfenster dienen dazu, Scheinfensterverletzungen komfortabel zu korrigieren, ohne Tiefe oder Parallaxe der eigentlichen Szene zu verändern. Seitliche Vorhänge sowie kippende Maskierungen oben oder unten können die wahrgenommene Scheinfensterkante dort nach vorne holen, wo es nötig ist — besonders wenn nahe Bildinhalte einen Bildrand schneiden. StereoFine lässt diese Maskierungen direkt in der Vorschau einstellen und wendet sie anschließend konsistent auf die finale Stereoausgabe an.

Die Werte für links, rechts, oben und unten werden bildbezogen in der `.sfin`-Datei gespeichert.

## Symmetrische Farbangleichung

Die Farbangleichung ist optional. Sie passt nicht ein Auge an das andere an, sondern führt beide Halbbilder über robuste Perzentilkurven auf einen gemeinsamen Zielzustand. Sie liegt vollständig außerhalb der Geometrie- und Deviation-Analyse.

Bereits farblich gut übereinstimmende Paare sollen dadurch praktisch unverändert bleiben. Die Funktion kann jederzeit ein- oder ausgeschaltet werden.

## `.sfin`-Sidecars

StereoFine speichert den reproduzierbaren Zustand eines Bildpaares in einer kleinen `.sfin`-Datei im Unterordner `_stereofine` des Eingabeordners. Darin stehen nur technisch sinnvolle Zustände und Parameter, unter anderem:

- Quelle und Gültigkeitsfingerprint
- automatische Korrektur und Analysebasis
- Deviation, Nahpunkt und Fernpunkt
- automatische Nahpunktrahmung
- manuelle X/Y-Korrektur
- Ausschnitt und Seitenverhältnis
- Floating Window
- Farbangleichung
- Favoritenstatus

Technische Analyse- und Unsicherheitsdiagnosen bleiben im Sidecar nachvollziehbar; der normale Analysebericht ist bewusst auf die für die stereoskopische Qualitätskontrolle relevanten Werte reduziert. Umfangreiche Entwicklungsdiagnosen und sprachabhängige GUI-Texte werden nicht als Ballast gespeichert. Ein gültiges Sidecar kann in späteren Stapelläufen wiederverwendet werden. Geänderte Quellen oder relevante Pipeline-Versionen führen gezielt zu einer Neuberechnung der betroffenen Analyse.

## Stapelverarbeitung

StereoFine kann getrennte Paare oder Full-SBS/MPO-Ordner automatisch verarbeiten. Einzelbild und Stapel verwenden denselben Rechenkern.

### Nur Analyse · Textbericht

StereoFine analysiert den gesamten Ordner, erzeugt beziehungsweise aktualisiert die Sidecars und schreibt `stereofine_analysis.txt`. Es werden keine SBS- oder Anaglyphenbilder ausgegeben.

Der Bericht ist als kompakte, ausgerichtete Texttabelle aufgebaut und enthält nur Datei, Ampel, Gesamtdeviation, Nahpunkt, Fernpunkt, mittleren Höhenfehler, Vergenz und Rotation. Nur bei einer unsicheren Einschätzung erscheint zusätzlich der Hinweis „Einschätzung unsicher – bitte prüfen!“.

### Nur Favoriten ausgeben

Ein praktischer Sichtungsworkflow ist:

1. Ordner in StereoFine durchsehen.
2. Einzelne Paare bei Bedarf feinjustieren und als Favorit markieren.
3. Später den gesamten Ordner starten und **Nur Favoriten ausgeben** wählen.

Die gespeicherten `.sfin`-Zustände werden wiederverwendet. Nicht favorisierte Bilder können analysiert werden, erzeugen aber keine Bildausgabe.

## Ausgabe und Ordner

Jeder Bildexport erzeugt immer beides:

- ein SBS-JPEG, Qualität 95
- eine Farb- oder Grauanaglyphe als JPEG, Qualität 90

Anaglyphen werden bei Bedarf auf maximal 2160 px Höhe verkleinert. Die Farbanaglyphe verwendet die gemeinsame StereoFine/SplatTricia-Referenzpipeline mit korrekter sRGB-Linearisation.

Standardmäßig legt StereoFine den Ordner `output` im Eingabeordner an. Alternativ kann ein eigener persistenter Ausgabeordner gewählt werden. Fertige JPEGs und Analyseberichte werden vollständig temporär geschrieben und erst danach atomar an ihren endgültigen Namen gesetzt.

Vorhandene Bildausgaben gleichen Namens werden bewusst ersetzt.

## Metadaten

Soweit möglich kopiert StereoFine Metadaten mit dem gebündelten ExifTool. Preview-, Orientation- und MPF/MPO-Containerdaten werden nicht in normale SBS-/Anaglyph-JPEGs übernommen. Scheitert nur die Metadatenkopie, bleibt ein erfolgreich geschriebenes Bild gültig und StereoFine zeigt einen Hinweis.

## Tastatur

### Navigation

- `Page Up` / `Page Down` – vorheriges / nächstes Bild
- `Leertaste` – Justage beziehungsweise Stapel starten
- `Enter` – aktuelles Bild speichern
- `F` – Favorit setzen/entfernen

### Manuelle Justage

- Pfeiltasten – horizontal/vertikal um 1 px verschieben
- `Shift` + Pfeiltaste – 5 px
- `Strg` + Pfeiltaste – 10 px
- `Strg+R` – zurück zur Auto-Justage inklusive 3‰-Rahmung

### Ausschnitt

- `Alt` + Pfeiltaste – Ausschnitt verschieben
- `Strg+Shift+↑/↓` – Zoom

### Schwebendes Scheinfenster

- `S` – Links/Rechts gekoppelt oder separat
- `L`, `R`, `T` oder `B` halten + `←/→` – gewählte Kante um 1‰ ändern

### Vorschau

- `A` – Farb-/Grauanaglyphe umschalten
- `G` – Gitter durchschalten
- `Shift+G` – Gitter aus
- `M` halten – Messkreuz anzeigen
- `M` + Pfeiltasten – Messkreuz bewegen
- `F11` – Vollbild
- `F1` – Tastaturhilfe
- `Esc` – Vollbild/Hilfe schließen

## Einstellungen und Sprache

Globale Präferenzen werden in `settings.json` direkt bei der portablen Anwendung gespeichert. Bildbezogene Einstellungen gehören ausschließlich in `.sfin`.

**Nur Analyse** und **Nur Favoriten ausgeben** sind Job-Modi und werden nicht als Dauerzustand gespeichert.

Die Oberfläche kann zwischen Deutsch und Englisch umgeschaltet werden. StereoFine-Begriffe wie Affine, Vergence, Y-Polish und Deviation bleiben fachlich konsistent.

## Source und Build

Der veröffentlichte portable Ordner enthält unter `Source/` den exakten Source-Stand, aus dem `StereoFine.exe` gebaut wurde. Der gleiche Source ist für das öffentliche GitHub-Repository vorgesehen.

Build-Hinweise stehen in [BUILD_WINDOWS.md](BUILD_WINDOWS.md). Die dokumentierten historischen Analysebaselines stehen in [docs/VALIDATION.md](docs/VALIDATION.md).

## Lizenz

Der von Christoph Müller erstellte StereoFine-Sourcecode und die eigene Dokumentation stehen unter der **MIT-Lizenz**. Drittkomponenten bleiben ausdrücklich unter ihren jeweiligen eigenen Lizenzen.

Siehe `LICENSE.txt`, `THIRD_PARTY_NOTICES.md` und `licenses/`.
