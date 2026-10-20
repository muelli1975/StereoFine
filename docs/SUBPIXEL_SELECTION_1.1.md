# StereoFine 1.1 – unabhängige Auswahl und Kontrolle gegen den tatsächlichen RC3-Stand

Stand: 20. Oktober 2026, nach dem [Subpixel-Piloten](SUBPIXEL_PILOT_1.1.md).
Keine Änderung an produktiver Justage, `.sfin`-Schema oder veröffentlichten Paketen.

## Entscheidung

**Keine pauschale Subpixel-Integration auf Grundlage dieses Versuchs.**
Von 29 Paaren bestehen zwei Kandidaten die räumlich getrennte Auswahl- und
Bestätigungsprüfung einschließlich regionaler Zusatzkontrolle. Beide haben
jedoch keinen belastbaren Vorteil gegenüber dem tatsächlichen gespeicherten
RC3-Ergebnis, das alle verfügbaren Anpassungspunkte nutzen durfte. Mit dieser
zusätzlichen konservativen Gegenprüfung bleiben **0 von 29 Kandidaten** übrig.

Die frühere Zahl „22 von 29 mit niedrigerem globalem P95“ ist weiterhin korrekt
für den damaligen kontrollierten Vergleich zweier **neu angepasster** Geometrien
auf einem reduzierten Trainingssatz. Sie ist **kein** Nachweis von 22 verbesserten
Bildern gegenüber der veröffentlichten RC3-Version. Das Weglassen ganzer
Prüfbereiche kann bei der vorhandenen Modellwahl ein anderes Ausgangsmodell
erzeugen. Der zusätzliche Vergleich verhindert, dass eine solche relative
Verbesserung als produktiver Fortschritt missverstanden wird.

## Durchführung

- Dieselben eingefrorenen SIFT-Matches, Korrekturen und Kontrollmessungen wie
  im Pilot. Alle 29 Ausgangs- und Kandidatenmetriken wurden exakt reproduziert.
- Die Anpassung beider Vergleichsgeometrien sah weiterhin keine Punkte aus
  den reservierten 128-Pixel-Blöcken einschließlich 16-Pixel-Trainingsabstand.
- Die reservierten Blöcke werden durch ihren festen Hash modulo 10 in zwei
  Gruppen geteilt: 0 für Auswahl, 5 für Bestätigung. Kein ganzer Block gehört
  beiden Gruppen an. Keine Nachanpassung nach Einsicht in Bestätigungsfehler.
- Jede Gruppe muss die vorhandenen strikten RC3-Gewinnkriterien und regionalen
  Prüfungen sowohl im 3×3- als auch im 5×5-Raster bestehen. Keine nachträgliche
  Lockerung auf die früher separat untersuchten Qualitätsobergrenzen.
- Zusätzlich muss die Vereinigung der Prüfgruppen bestehen. Damit können
  beispielsweise je vier Eckpunkte pro Teilgruppe nicht zwei Prüfungen
  unterlaufen, obwohl ihre acht Punkte gemeinsam eine Verschlechterung belegen.
- Nicht ausreichend besetzte Ecken bleiben ausdrücklich ungeprüft. Sie werden
  nicht durch eine günstige globale Zahl als bestanden umgedeutet.
- Anschließend derselbe strikte Vergleich des Kandidaten gegen die **wirklich
  gespeicherte RC3-Korrektur mit allen Anpassungspunkten**. Dieser zusätzliche
  Vergleich ist ein konservatives Veto, kein neuer unabhängiger Trainingsversuch:
  Die RC3-Referenz wurde nicht räumlich von diesen Prüfblöcken ferngehalten.

Der Selektor und seine Grenzen wurden aus den bereits vorhandenen Kriterien
übernommen, nicht an Bildnummern oder neue Ergebnisse angepasst. Die Messungen
sind photometrisch bestätigte LK/NCC-Punkte, keine manuelle Ground Truth.

## Ergebnis

| Prüfung | Bestandene Kandidaten |
| --- | ---: |
| Getrennte Auswahl und Bestätigung sowie gemeinsame regionale Kontrolle | 2 / 29 |
| Zusätzlich belastbarer Gewinn gegenüber tatsächlichem RC3 | 0 / 29 |

Die erste Stufe akzeptiert S95 038 und NX1000 023. Drei andere Fälle scheitern
an regionalen Verschlechterungen, 24 am fehlenden strikten globalen Gewinn.

P95 auf denselben reservierten Quellpunkten in Eingabepixeln:

| Paar | Neu angepasste Vergleichsgeometrie | Subpixel-Kandidat | Tatsächlich gespeicherter RC3-Stand |
| --- | ---: | ---: | ---: |
| S95 038 | 4,869 | 1,795 | 1,217 |
| NX1000 023 | 0,851 | 0,3972 | 0,3974 |

Beim S95-Paar ist der volle RC3-Stand deutlich besser. Beim NX-Paar bleibt
der Unterschied weit unter der bestehenden Mindestverbesserung; daraus folgt
kein verlässlicher praktischer Gewinn.

Beide experimentellen Kandidaten besitzen zudem weiterhin unzureichend
besetzte Ecken. S95 038: TL20, BL20, BR20, BR10; NX1000 023: TL20, BR20, BR10.
Die zwei ausgewählten Kandidaten sind daher auch vor dem Referenzveto keine
pauschal vollständig abgesicherten Bildflächen.

## Raster- und Dateikontrollen

Für beide experimentellen Kandidaten wurde die Geometrie in Originalauflösung
mit dem vorhandenen Renderer geprüft. Neu detektierte Rasterpunkte bestätigen
gegenüber der reduzierten Vergleichsgeometrie einen globalen P95-Gewinn:
S95 038 von 5,681 auf 1,789 Pixel, NX1000 023 von 0,786 auf 0,437 Pixel.
Die vollständigen regionalen Werte und unterschiedlichen Punktzahlen stehen
im Zahlenbericht. Diese Rasterprüfungen widerlegen nicht das Referenzveto;
sie vergleichen dieselbe reduzierte Ausgangsgeometrie und sind keine identischen
Punktsätze zwischen den Ausgaben.

Außerdem wurden für beide experimentellen Kandidaten echte temporäre `.sfin`-
Dateien geschrieben und mit dem tatsächlichen Quellenstempel wieder geladen.
Nach Wiederherstellung über `PairState.from_sidecar` erzeugt der native
Geometrie-Renderer **bytegleiche Bildpixel**. Orientierung, Favorit und eine
manuelle Bearbeitung bleiben erhalten. Alle 29 Paare bestehen zusätzlich den
Rundlauf der tatsächlich angewendeten Korrektur-Positivliste auf den Kontrollpunkten.

Das prüft den vorhandenen Parametervertrag und Dateirundlauf. Es prüft **nicht**
den vollständigen `process_source`-Cacheablauf einer zukünftigen Integration,
keinen neu berechneten Nahpunkt und keine endgültige Fenstereinpassung. Ein
produktiver Einbau benötigt weiterhin passende Berechnungsversionen, Cache-
Invalidierung und die zugehörigen Integrationstests. Das öffentliche `.sfin`-
Format wurde durch diese Forschung nicht verändert.

## Konsequenz für die weitere 1.1

Die vereinbarte Geometrie bleibt erhalten: Affine-LMS, kontrollierte symmetrische
Vergenz/Trapezkorrektur und Y-Polish. Keine freie Vollrektifizierung und keine
neuen Bildverformungsmodelle. Die begrenzte S110-Randabweichung und unsichere
IXUS-Nahpunktmessung gelten weiterhin als ungelöst beziehungsweise unsicher.

Weitere Messverbesserungen müssen einen Vorteil gegenüber dem tatsächlich
vorhandenen RC3-Stand zeigen und dürfen nicht allein eine durch Auslassen von
Daten geschwächte Referenz schlagen. Sinnvoll sind gezielte Untersuchungen der
Messauflösung und Korrespondenzpräzision innerhalb der bestehenden Verfahren.
Ein neuer Ansatz wird erst nach belegtem Vorteil integriert.

## Reproduktion

[Zahlenbericht](SUBPIXEL_SELECTION_1.1_RESULTS.json). Private Originalbilder,
Zustands-, Korrektur- und Kontrollpunktdateien bleiben außerhalb des Repositories.
Vorher den Subpixel-Piloten reproduzieren, anschließend:

```sh
python -m unittest discover -s experiments/tests -p 'test_*.py'
python experiments/select_subpixel_candidate.py private_manifest.json \
  --results private_subpixel_results --output private_selection_results
python experiments/render_subpixel.py private_manifest.json --results private_subpixel_results \
  --names s95_bild038 nx1000_bild023
python experiments/check_subpixel_sidecar.py private_manifest.json \
  --results private_subpixel_results --selection private_selection_results --experimental
python experiments/summarize_subpixel_selection.py private_selection_results \
  --results private_subpixel_results --output selection_summary.json
```

31 Forschungstests bestanden. Neun neue Selektortests prüfen getrennte Blöcke,
ein Bestätigungsveto, regionale Verschlechterung, gepoolte Evidenz, fehlende/
unsichere Messwerte und den entscheidenden Schutz vor Ersatz einer tatsächlich
besseren RC3-Referenz. Produktionscode und RC3-Pakete bleiben unverändert.
