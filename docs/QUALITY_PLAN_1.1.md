# StereoFine 1.1: Qualitätsplan

Stand: 20.10.2026. Entwicklungszweig `development/1.1`, Ausgangspunkt
`ae7073cf8abce0d2259f1a4fb77050dda5117ac4`. Dies ist ein Arbeitsplan,
keine Freigabe oder Zusicherung bereits implementierter Verbesserungen.

## Nachgewiesene Probleme

- Beim externen Testpaar bild005 liefert AKAZE eine deutlich schlechtere
  Höhenkorrektur als die bereits berechnete yQuad-Alternative. Eine einzelne
  Verschlechterung des Holdout-Maximums um rund 0,066 Vollauflösungspixel
  verhindert deren Verwendung, obwohl die übrigen Kennzahlen stark profitieren.
  Unabhängige Vorwärts-/Rückwärts-LK-Messungen am gerasterten Ergebnis bestätigen
  die Verbesserung. Das bloße Entfernen der Schutzprüfung ist noch keine Lösung.
- Das globale P99 der Disparität schließt echten nahen Sand im rechten unteren
  Vordergrund aus. Unabhängige Patchkorrelation bestätigt dort rund 34 Promille,
  gegenüber rund 30 Promille P99. Der nominelle Sicherheitsabstand von 3 Promille
  wird deshalb verfehlt. Einzelne falsche Extremdisparitäten existieren ebenfalls;
  das absolute Maximum wäre kein sicherer Ersatz.
- TIFF-Orientation 2 bis 8 wird im untersuchten OpenCV-Pfad doppelt angewendet.
  bild005 hat Orientation 1 und ist davon nicht betroffen. Ein unabhängiger
  TIFF-Writer im Regressionstest sichert die tatsächlichen gespeicherten Pixel
  und alle acht Ausrichtungen in 8 und 16 Bit ab.

Kundenbilder bleiben außerhalb des öffentlichen Repositories. Ein grüner
synthetischer Testlauf ersetzt keine Prüfung der Originalpaare.

## Umsetzung in getrennten, überprüfbaren Schritten

1. Frühere vier Korrekturen aus `4d4fe3ec7314da5daf591624e35cf4be047427af`
   einzeln übernehmen: Original-Seitenverhältnis, Namenskollisionen, farblich
   identische Integer-LUTs, ergebnisgleiche Beschleunigung des gültigen Rechtecks.
   Die bisherigen Vergleichstests erneut ausführen.
2. TIFF-Ausrichtung korrigieren. JPEG, PNG, MPO, 8/16 Bit und unterschiedliche
   TIFF-Kompressionen gegenprüfen; Präzision und Kanalreihenfolge erhalten.
3. Höhenmodellwahl mit unabhängigen und räumlich verteilten Prüfstellen absichern.
   Ränder, Vordergrund und einzelne Ausreißer getrennt bewerten. Keine Freigabe
   allein aufgrund kleinerer Fehler auf den zum Fit verwendeten Punkten.
4. Nahpunktwahl um räumlich gestützte, geprüfte nahe Regionen ergänzen. Kleine
   echte Vordergründe müssen erhalten bleiben, isolierte Fehlmatches dürfen das
   Fenster nicht bestimmen. Suchbereichsgrenzen und fehlende Evidenz erkennen.
   Tatsächliches gerendertes Ergebnis nach Verschiebung und Beschnitt prüfen.
5. Analyseversionen/Cache invalidieren, wo Berechnungen oder Eingabeinterpretation
   geändert wurden. Manuelle Einstellungen, Favoriten und bestehende Dateien
   erhalten; Tests mit und ohne bestehende .sfin-Dateien.
6. Erst nach Bildvergleich und Regressionen einen klar gekennzeichneten
   1.1-Testbuild erstellen. Abschließende reale Anwendung mit Nutzerfeedback,
   anschließend eigene 1.1-Veröffentlichung. 1.0 nicht durch Testbuilds ersetzen.

## Freigabekriterien und Messgrenzen

- Für bild005 beide Detektoren testen. Unabhängige gut belegte Korrespondenzen
  sollten im gerenderten Vollauflösungsbild im 95. Perzentil höchstens rund
  1,5 Pixel vertikal abweichen, auch separat im Boot und Vordergrund. Dies ist
  ein vorläufiges Ziel für dieses Paar, keine Zusicherung für beliebige Motive.
- Die bestätigte nahe Sandregion muss bei automatischer Grundeinstellung mit
  dem vorgesehenen Abstand hinter dem Fenster liegen. Die Prüfung muss das
  endgültige Koordinatensystem und die Messunsicherheit berücksichtigen.
- Auf bisher guten Paaren keine relevante Verschlechterung von Höhenlage,
  Nahpunkt, Ausschnitt, Farben oder Einstellungen. Toleranzen vor der jeweiligen
  Implementierungsbewertung aus Auflösung und Messunsicherheit festlegen.
- Bei unzureichender Evidenz erkennbare Unsicherheit statt verlässlicher Wirkung
  eines nur nominell berechneten Nahpunkts. Die bestehende Ampel beschreibt den
  Disparitätsumfang; sie ist bislang kein allgemeines Gütesiegel für die Justage.
- Automatische Tests, echte Export-/Vorschaubilder, DE/EN-Bedienabläufe und
  Builds aller unterstützten Plattformen prüfen. Testzahlen und Build-Erfolg
  separat von tatsächlich nachgewiesener Bildqualität berichten.

## Benötigter externer Bildbestand

Als erste Erweiterung 3 bis 5 weitere problematische Paare des S110-Gespanns und
3 bis 5 bislang zuverlässig verarbeitete Paare, möglichst zusätzlich aus einem
anderen Gespann. Hilfreich sind unterschiedliche Brennweiten, nahe Randobjekte,
strukturlose Flächen und Motive mit Details über das ganze Bild. Originale
Eingabedateien in voller Auflösung, eindeutiges L/R und eine kurze Beschreibung
des beobachteten Fehlers; vorhandene .sfin optional. Eine sichtbar gute
Referenzjustage kann die Bewertung ergänzen. Ein größerer historischer Testsatz
wäre zusätzliche Absicherung, ersetzt aber nicht die schwierigen Rohpaare.

## Stand der Vorbereitung

- Entwicklungszweig angelegt; veröffentlichter Programmcode unverändert.
- Die vier früheren Laufzeitkorrekturen und ihre 15 Regressionstests sind wieder
  enthalten. Historische Release-Workflows und Freigabeaussagen wurden nicht
  übernommen.
- TIFF-Orientation wird nach dem OpenCV-Decoder nicht erneut angewendet. Der
  Test `tests/test_input_orientation.py` prüft alle acht Ausrichtungen in 8/16
  Bit, auch mit mehreren Kompressionen sowie Grau/RGB/RGBA und abweichender
  Dateiendung. Die Eingabepipeline ist jetzt explizit versioniert. Alte Analysen
  werden verworfen, Einstellungen unveränderter Quellen bleiben erhalten, auch
  wenn die korrigierte TIFF-Ausrichtung Breite und Höhe vertauscht.
- Fünf weitere Originalpaare in beiden Verfahren vermessen; siehe
  [REAL_IMAGE_BASELINE_1.1.md](REAL_IMAGE_BASELINE_1.1.md). Es gibt darunter einen
  bereits guten SIFT-Fall. Ein siebtes Paar bild092 ergänzt den Vergleich.
- Die automatische Modellwahl wurde jetzt überarbeitet: robuste globale und
  regionale Holdout-Prüfung sowie Vergleich vollständiger Korrekturketten;
  siehe [MODEL_SELECTION_1.1.md](MODEL_SELECTION_1.1.md). 14 reale Läufe mit
  unabhängigen Render-Kontrollen sind dokumentiert. In diesem Zwischenstand blieben die guten SIFT-Fälle
  bild089 und bild092 in den Vollauflösungsrendern pixelidentisch erhalten.
  Die Alignments-Pipeline wurde zunächst auf sf-align-3 angehoben; abhängige alte Caches
  werden verworfen, manuelle Einstellungen bleiben erhalten.
- 109 automatische Tests bestehen; Kompilierung und Original-Asset-Hashes
  geprüft. Das ist getrennt von der realen Bildqualitätsprüfung zu bewerten.
- Fortsetzung: Punkterholung mit unabhängiger Blockprüfung, bestätigter Nahpunkt
  einschließlich Randbereichen und schnelleres exaktes SIFT-Matching sind für
  1.1 RC1 integriert. Vier neue IXUS-Paare erweitern die Prüfung auf elf Paare;
  eine zusätzlich geprüfte kubische Höhenkorrektur adressiert lokale Randreste. Aktuelle Versionen sind
  sf-align-4 und sf-disparity-2. 132 automatische Tests bestehen lokal.
  Siehe [VALIDATION_1.1_RC1.md](VALIDATION_1.1_RC1.md). Ein gesonderter RC1-Build
  dient der praktischen Windows-Prüfung; eine stabile 1.1 ist noch nicht freigegeben.
