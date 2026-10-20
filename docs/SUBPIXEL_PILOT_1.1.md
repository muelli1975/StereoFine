# StereoFine 1.1 – Subpixel-Nachmessung innerhalb der bisherigen Geometrie

Stand: 20. Oktober 2026, Forschungszweig `research/neural-matching`.
Keine Änderung an der Anwendung, veröffentlichten Paketen oder `.sfin`-Dateien.

## Ergebnis und Entscheidung

Die klassische Nachmessung ist der sinnvollere nächste Untersuchungsschritt
als eine Wiederaufnahme der verworfenen Vollrektifizierung: Bei 22 von 29 Paaren
sinkt der globale P95-Fehler auf extern zurückgehaltenen Quellpunkten, bei sieben
steigt er. Viele Unterschiede sind klein. Bei S95 038 sowie mehreren NX1000-
und S110-Paaren gibt es deutliche Gewinne; vier vertiefte Rasterkontrollen
prüfen tatsächliche Ausgaben. Es wird kein neues Bildverformungsmodell eingeführt.

**Kein pauschaler Einbau:** Einzelne lokale Bereiche werden trotz globalem
Gewinn schlechter. Die vorhandenen Schutzbedingungen bleiben unverändert.
Der Pilot begründet eine weiter zu prüfende Messverbesserung, keine automatische
Freigabe für alle Motive und keine Zusicherung optimaler Justage.

## Was tatsächlich verändert wurde

Die SIFT-Merkmalspositionen sind der Startpunkt einer lokalen, pyramidenbasierten
Lucas-Kanade-Nachmessung mit OpenCV. Nur bestätigte rechte Korrespondenzpositionen
werden ersetzt; andere behalten exakt ihre ursprünglichen Werte. Es werden
weder Ausgabebilder durch Optical Flow verformt noch horizontale Disparitäten
als zu minimierender Fehler behandelt.

Feste Messbedingungen:

- Fenster 21×21, Pyramidenebene 1, maximal 40 Iterationen, Abbruch bei 0,001.
- Photometrische Korrelation vor der Nachmessung mindestens 0,85.
- Vor-/Rücklaufabweichung höchstens 0,25 Analysepixel; Verschiebung vom
  SIFT-Startpunkt höchstens 1,5 Analysepixel, damit keine freie Motivsuche entsteht.
- Nachmessung mit NCC mindestens 0,90 und mindestens so gut wie vorher.
- Keine Verschiebung in reservierte Kontrollbereiche; keine nachträgliche
  Entfernung missliebiger Kontrollpunkte und keine Änderung der Prüfkriterien.

Die so erhaltenen Messungen durchlaufen die **vorhandene** affine Justage,
kontrollierte Vergenz/Trapez-Modellwahl und Y-Restkorrektur einschließlich
bestehender kubischer Begrenzung. Der anfängliche y-RANSAC-Inlier-Satz wird
vom Originaltraining übernommen, um diesen Filter als zusätzliche Variable
festzuhalten. Nachgewinnung, interne Modellwahl und Schutzprüfungen bleiben aktiv.
Die Messänderung kann dadurch auch beeinflussen, welches bisher schon vorhandene
Modell die unveränderten Qualitätsprüfungen besteht.

## Unabhängige Prüfung

Gleiche reservierte 128-Pixel-Blöcke und 16-Pixel-Trainingsabstände wie im
[Rektifizierungspiloten](RECTIFICATION_PILOT_1.1.md). Beide Augen eines
Trainingsmatches bleiben außerhalb dieser Blöcke. Kontrollpunkte werden vor
dem Fit unabhängig vom SIFT-Detektor mit LK/NCC bestimmt; ihr linker Punkt
liegt in einem reservierten Block. Alle geometrischen Anpassungen sehen nur
die Trainingsarrays. Es werden identische Kontrollmessungen vorher/nachher
verwendet, auch wenn ein Kandidat daran schlecht abschneidet.

Die Ausgangsgeometrie wurde für alle 29 Paare neu angepasst und stimmt in allen
berichteten Metriken exakt mit der ebenfalls neu angepassten Ausgangsgeometrie
des Rektifizierungspiloten überein. **Das ist kein direkter Vergleich mit dem
veröffentlichten RC3-Paket, das alle verfügbaren Anpassungspunkte verwenden darf.**
Das Weglassen ganzer Prüfabschnitte kann Modellwahl und Ausgangsergebnis verändern.

Die Kontrollen sind photometrisch bestätigte Messungen und keine manuelle Ground
Truth. 11 bis 461 Punkte je Paar reichen nicht für jede Ecke; insbesondere
NX1000 041 ist dünn belegt. Die interne Nachmessung und externe Kontrolle
verwenden beide LK/NCC, jedoch andere Punktquellen und räumlich getrennte
Anpassungs-/Kontrolldaten. Eine manuelle Stichprobe oder weitere unabhängige
Messmethode wäre vor einer endgültigen Qualitätsaussage hilfreich.

## Konkrete Ergebnisse

P95 des absoluten vertikalen Fehlers auf identischen externen Quellpunkten,
in Eingabepixeln:

| Paar | Ausgangsgeometrie | Subpixel-Nachmessung |
| --- | ---: | ---: |
| S110 090 | 1,958 | 1,601 |
| S110 092 | 1,077 | 0,964 |
| S95 038 | 4,869 | 1,795 |
| NX1000 004 | 4,022 | 1,631 |
| NX1000 008 | 1,609 | 0,800 |
| NX1000 023 | 0,851 | 0,397 |
| NX1000 033 | 4,942 | 4,898 |
| IXUS 008 | 1,050 | 1,081 |

Beim S95-Paar wechselt die bereits vorhandene Modellwahl von
`Affine + Vergence` zu `Affine + yQuad`. Beim S110-Paar 090 besteht mit
präzisierten Messungen erstmals in diesem zurückgehaltenen Versuch die
vorhandene kubische Restkorrektur ihre unveränderten Prüfungen. Das erklärt,
warum kleine Messänderungen auch größere Ergebnisänderungen auslösen können.
Es ist kein Beleg dafür, dass diese Modelle für beliebige Motive optimal sind.

Zusätzliche Kontrolle neu gerenderter Originalauflösung, ohne Nahpunkt-/Fenster-
oder Farbkorrektur, mit unverändertem Produktionsrenderer und neuen Prüfmerkmalen:

| Paar | Ausgangsraster P95 | Subpixel-Raster P95 |
| --- | ---: | ---: |
| S110 090 | 0,922 | 0,817 |
| S95 038 | 5,681 | 1,789 |
| NX1000 004 | 1,493 | 1,317 |
| NX1000 033 | 7,962 | 7,855 |

Rasterpunkte und Ausschnitte ändern sich zwischen den Varianten. Diese Zahlen
bestätigen die Richtung des Effekts, sind aber kein identischer Punktsatz und
nicht mit den Quellpunktzahlen austauschbar. Punktzahlen und sämtliche 5×5-Zellen stehen im Zahlenbericht.

## Verbleibende Probleme

- Bei S110 090 verschlechtern sich trotz besserem globalem Ergebnis zwei
  externe 5×5-Zellen. Auch am Raster steigt ihr P95 von 0,990 auf 1,213
  beziehungsweise 0,751 auf 1,131 Pixel. Die äußerste untere rechte Ecke
  verbessert sich nur teilweise: Raster-Mittelwert 2,501 auf 2,025 Pixel,
  P95 3,725 auf 3,251, jeweils sechs bestätigte Punkte. Damit ist sie nicht gelöst.
- Bei NX1000 008 und 029 gibt es ebenfalls je eine ausreichend besetzte
  Quellpunktzelle mit einer P95-Verschlechterung größer als
  `max(0,2 Pixel, 10 % des Ausgangs-P95)`. Diese Schwelle dient hier nur der
  beschreibenden Übersicht, nicht als neu gelockerte Produktionsfreigabe.
- IXUS 008 gewinnt geometrisch nicht. Die unabhängige Nahpunktbestätigung
  ist Gegenstand eines separaten Problems und wird hier weder geändert noch
  als bestanden ausgegeben.
- Eine Messung in Analyseauflösung ersetzt noch keine geprüfte native
  Subpixel-Messung. Die jetzige Auflösungsgrenze und LK-Fenster sind feste
  Pilotparameter, keine nachgewiesen optimale universelle Wahl.

## Nächster Schritt für die produktive 1.1

Auf der vereinbarten Pipeline bleiben. Die Nachmessung als optionalen internen
Kandidaten mit unveränderten Geometriegrenzen weiter prüfen. Vor einer Integration
braucht es von Fit und Kandidatenauswahl getrennte Bestätigungsbereiche,
regionale Veto-Prüfungen, Kontrollen der Tiefeninformation und Randunterstützung
sowie die Gegenprobe des endgültigen Rasters. Verschlechterungen dürfen nicht
hinter einem besseren Mittelwert verschwinden. Keine auf Kameranamen/Bildnummern
abgestimmten Ausnahmen, keine freie Vollrektifizierung und kein GPU-Zwang.

Falls sich danach eine produktive Verfahrensänderung bewährt, deren
Berechnungsversion und `.sfin`-Cachebasis sauber anpassen. Für diese reine
Messnachverfeinerung wird kein neuer Matrixtyp im Dateiformat benötigt; vorhandene
angewendete Korrekturparameter müssen einschließlich Modellwahl reproduzierbar
bleiben. Lade-/Speicher-/Render-Rundlauf und Altdateien sind dennoch zu prüfen.

## Reproduktion

[Zahlenbericht und Eingabe-Hashes](SUBPIXEL_PILOT_1.1_RESULTS.json).
Private Originalbilder, Zustands- und Punktdateien bleiben außerhalb des
öffentlichen Repositories. Manifestformat wie im Rektifizierungspiloten.

```sh
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s experiments/tests -p 'test_*.py'
python experiments/compare_subpixel.py private_manifest.json --output private_results
python experiments/render_subpixel.py private_manifest.json --results private_results \
  --names s110_bild090 s95_bild038 nx1000_bild004 nx1000_bild033
```

139 Produktionstests und 22 isolierte Forschungstests bestanden. Drei neue
synthetische Tests prüfen die genauere Nachmessung bekannter Verschiebungen,
den Erhalt einer horizontalen Disparität von über 15 Pixeln und den unveränderten
Rückfall bei kontrastlosen Flächen. Kein unvermessener Nahpunkt wird ergänzt.
