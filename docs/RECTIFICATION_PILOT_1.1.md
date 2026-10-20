# StereoFine 1.1 – kontrollierter Rektifizierungsvergleich

Stand: 20. Oktober 2026. Forschungszweig `research/neural-matching`;
kein neuer produktiver Justagepfad und keine Änderung an RC3 oder `.sfin`.

## Ergebnis

Die direkte unkalibrierte OpenCV-Rektifizierung ist in dieser Konfiguration
kein geeigneter genereller Ersatz für die bisherige RC3-Geometrie. Sie bietet
beim S95-Bild 038 einen deutlichen, auch am tatsächlichen Raster bestätigten
Vorteil. Beim S110-Bild 090 und NX1000-Bild 033 verschlechtert sie das Ergebnis.
Das ist eine Aussage über die getestete Implementierung und Datenmenge,
keine generelle Widerlegung projektiver Rektifizierung.

Alle 29 vorhandenen Paare wurden mit identischen zurückgehaltenen Messpunkten
je Paar verglichen. Das Ergebnis des globalen P95-Kriteriums:

| F-Schätzung | Niedrigerer P95 | Höherer P95 | Keine zulässige Transformation |
| --- | ---: | ---: | ---: |
| Gemeinsame anfängliche y-RANSAC-Inlier | 2 | 25 | 2 |
| Alle Trainingsmatches, MAGSAC-Ausreißerfilter | 2 | 26 | 1 |

Die beiden nominellen Gewinne betreffen S95 038 und IXUS 050. Bei IXUS 050
beträgt die Verbesserung nur 1,295 auf 1,280 beziehungsweise 1,292 Pixel;
daraus lässt sich kein belastbarer praktischer Gewinn ableiten. Die
ungültigen Fälle bleiben im Bericht: S110 005 (beide Varianten) und S95 059
(nur gemeinsame Inlier). Eine gescheiterte Transformation wird nicht entfernt
oder als Verbesserung gezählt.

## Messaufbau

- Klassische SIFT-Korrespondenzen, keine neuronalen Modelle oder GPU.
- Analyse mit maximal 3000 Pixeln Breite. Vor jeder Anpassung werden feste
  128-Pixel-Blöcke ausgewählt: `(bx*73856093 + by*19349663) % 5 == 0`.
- Trainingsmatches müssen in **beiden** Augen außerhalb dieser Blöcke und
  ihres 16-Pixel-Abstands liegen. Auch sämtliche Nachverfeinerungen des
  bisherigen Verfahrens erhalten ausschließlich diese Trainingsarrays.
- Die bisherige Geometrie wird neu angepasst: affine Justage, vorhandene
  Modellwahl, Nachgewinnung von Korrespondenzen und begrenztes kubisches Feld
  mit unveränderten Schutzbedingungen. Gespeicherte RC3-Ergebnisse mit allen
  Punkten werden nicht als vermeintlich unabhängiger Vergleich verwendet.
- Der erste OpenCV-Kandidat beginnt mit denselben anfänglichen Inliern.
  Die zweite Variante untersucht ausdrücklich einen zusätzlichen Wechsel
  der Ausreißerbehandlung und ist deshalb kein isolierter Modellvergleich.
- `findFundamentalMat(USAC_MAGSAC)`: 1 Analysepixel, Konfidenz 0,999,
  höchstens 10000 Iterationen. Danach `stereoRectifyUncalibrated` mit zwei
  Homographien. Keine Annahme identischer Kameraintrinsik, keine geschätzte
  Objektivkalibrierung und keine einzelne Homographie zur Überlagerung der Augen.
- Ein gemeinsamer isotroper Nachmaßstab normalisiert das geometrische Mittel
  der lokalen Flächenmaßstäbe in beiden Bildmitten auf 1. Dadurch kann eine
  bloße gemeinsame Verkleinerung keinen scheinbaren Präzisionsgewinn erzeugen.
  Lokale Maßstäbe und Anisotropie werden zusätzlich protokolliert; diese
  Normalisierung garantiert noch keine geringe Verzerrung im gesamten Bild.
- Vor dem Fit gemessene LK-/NCC-Kontrollpunkte mit linkem Punkt im reservierten
  Block prüfen anschließend alle Varianten. Vor-/Rücklauf <0,35 Pixel bei
  1500 Pixeln Prüfbreite, NCC mindestens 0,90, räumliche 5×5-Merkmalssuche.
  Keine Auswahl anhand des nachträglichen Geometriefehlers; keine nachträgliche
  Entfernung schlechter Kandidatenpunkte.
- Angegeben werden tatsächlicher unbeschnittener Mittelwert und P95 des
  absoluten vertikalen Fehlers, auf Eingabepixel zurückgerechnet. Das ist
  nicht der teilweise winsorisierte interne Produktionsmittelwert.

Die Kontrollmessungen sind unabhängig vom SIFT-Detektor, aber keine manuell
vermessene Ground Truth. Wiederholte Strukturen, Bewegung und photometrische
Abweichungen können auch diese Messungen beeinflussen. Je Paar bleiben
11 bis 461 Kontrollpunkte; besonders NX1000 041 mit 11 Punkten und dünn
besetzte Ecken erlauben keine flächendeckende Qualitätsaussage.

## Drei vertiefte Gegenprüfungen

Identische zurückgehaltene **Quellpunkte**, P95 in Eingabepixeln:

| Paar | Bisherige Geometrie | Projektiv, gemeinsame Inlier | Projektiv, rohe Trainingsmatches |
| --- | ---: | ---: | ---: |
| S110 090, 227 Punkte | 1,958 | 5,088 | 5,619 |
| S95 038, 213 Punkte | 4,869 | 1,832 | 1,718 |
| NX1000 033, 248 Punkte | 4,942 | 22,979 | 8,756 |

Zusätzlich wurden diese drei Paare in Originalauflösung gerendert: bisheriger
Produktionswarp gegen experimentelle zweiaugige Homographien, jeweils mit
Lanczos und gültigem gemeinsamem Ausschnitt. Kein Nahpunkt-/Fensterbeschnitt,
keine Farbangleichung. Die experimentellen Matrizen werden mit expliziter
Pixelmitten-Konvention in Originalkoordinaten umgerechnet.

Neue Messpunkte auf den **gerenderten Bildern**, P95 in Ausgabepixeln:

| Paar | Bisherige Geometrie | Projektiv, gemeinsame Inlier | Projektiv, rohe Trainingsmatches |
| --- | ---: | ---: | ---: |
| S110 090 | 0,922 | 3,758 | 3,796 |
| S95 038 | 5,681 | 1,727 | 1,407 |
| NX1000 033 | 7,962 | 15,796 | 7,696 |

Diese Rasterwerte verwenden neu detektierte Punkte und veränderte Ausschnitte;
sie sind zusätzliche Gegenkontrollen, kein identischer Punktsatz und keine
mit den Quellpunktwerten austauschbare Messung. Bei S95 038 bestätigt die
Variante mit gemeinsamen Inliern den Gewinn ohne auffällige Verschlechterung
in ausreichend besetzten 5×5-Zellen dieser Rasterprüfung. Die rohe Variante
verschlechtert trotz besserem globalem Raster-P95 eine Zelle von 1,438 auf
2,294 Pixel. Globale Werte allein reichen daher weiterhin nicht zur Auswahl.

Auch der Bildinhalt muss berücksichtigt werden: Die projektiven Ausschnitte
behalten bei S110 090 nur rund 69/75 %, bei NX1000 033 rund 72/86 % und bei
S95 038 rund 92/83 % der Eingabefläche. Das ist eine gemessene Flächenquote
der experimentellen Leinwand und ihres gültigen Rechtecks, keine optimierte
Produktions-Beschnittstrategie. Ein vollständiger Vergleich muss den
Inhaltsverlust und örtliche Maßstabsänderungen mit bewerten.

Die bekannte untere rechte S110-Ecke wird damit nicht gelöst: Die feste
Quellpunktprüfung hat dort nur fünf reservierte Punkte; auch im Raster bleibt
die Ecke schlechter. Die gute geometrische Messung von IXUS 008 ist zudem
kein Nachweis eines gesicherten Nahpunkts. Dieser Versuch ändert und prüft
die Nahpunktbestätigung nicht.

## Konsequenz für 1.1

1. Bisherige Verfahren und Schutzbedingungen beibehalten. Eine pauschale
   Ersetzung durch OpenCV oder neural erzeugte Matches ist nicht begründet.
2. Projektentscheidung nach Nutzerhinweis vom 20. Oktober 2026: Die bereits
   früher wegen sichtbarer Streckung und unnatürlicher Geometrie verworfene
   Vollrektifizierung wird nicht als produktive Korrektur weiterverfolgt.
   Der einzelne S95-Vorteil rechtfertigt keine Wiederaufnahme dieser Linie.
   Die Korrektur bleibt Affine-LMS → kontrollierte symmetrische Vergenz/Trapez
   → Y-Polish. Der nächste gezielte Versuch betrifft etablierte Subpixel-
   Nachmessung der Korrespondenzen innerhalb dieser Pipeline, keine zusätzlichen
   freien Bildverformungen. Horizontale Disparität bleibt Tiefeninformation
   und darf nicht als Justagefehler minimiert werden.
3. Eine spätere Auswahl benötigt räumlich getrennte Anpassungs-, Auswahl-
   und Bestätigungsdaten sowie regionale Qualitäts-/Inhaltskontrollen.
   Dieser Pilot hat einen externen Prüfsatz und trifft **keine** automatische
   Modellauswahl; dessen Ergebnisse dürfen nicht gleichzeitig als unabhängige
   Freigabe eines darauf optimierten Selektors ausgegeben werden.
4. Erst nach bestätigtem Gewinn den kompletten Transformationsvertrag in
   Zustand, Renderer und `.sfin` gemeinsam integrieren. Die Anforderungen
   stehen in [NEURAL_SELECTION_1.1.md](NEURAL_SELECTION_1.1.md).

## Reproduktion und Tests

Vollständige Zahlen, Laufzeitumgebung und SHA-256 der privaten Eingaben und
Punktdateien: [RECTIFICATION_PILOT_1.1_RESULTS.json](RECTIFICATION_PILOT_1.1_RESULTS.json).
Die Originalbilder, ihre Punktkoordinaten und lokalen Zustandsdateien werden
nicht öffentlich eingecheckt. Ohne diese Eingaben lassen sich die Bildzahlen
nicht unabhängig wiederholen; die synthetischen Tests sind vollständig verfügbar.

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
python experiments/compare_rectification.py private_manifest.json --output private_results
python experiments/render_rectification.py private_manifest.json --results private_results \
  --names s110_bild090 s95_bild038 nx1000_bild033
```

Manifest: Liste aus `{name, left, right, state}`, optional mit expliziter
`points`-NPZ-Datei zum Fixieren des Korrespondenzsatzes; `name` endet auf `_SIFT`,
`state` ist die vollständige zugehörige PairState-Diagnose. Vorhandene
`*_SIFT_points.npz` im Datenbaum werden mit ihrer Analyseform geprüft und
verwendet; andernfalls erzeugt der klassische SIFT-Pfad einen privaten Cache.
Der öffentliche Zahlenbericht enthält die Hashes der tatsächlich verwendeten
Dateien. Für eine Neumessung ein leeres Ergebnisverzeichnis verwenden.

Validierung: 139 Produktionstests und 19 isolierte Forschungstests bestanden.
Davon prüfen neun neue Tests zurückgehaltene Blöcke, perspektivisch projizierte
3D-Punkte mit erhaltener horizontaler Tiefenvariation, Maßstabsnormalisierung,
projektive Horizonte, fehlende Unterstützung, Pixelmitten-Umrechnung und
bytegetreues Identitätsraster innerhalb des sicheren Ausschnitts.
