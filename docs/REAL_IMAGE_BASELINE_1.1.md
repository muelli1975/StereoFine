# Reale Vergleichsbilder für 1.1

20.10.2026, zusätzlicher externer Satz `stereos2.zip`: fünf Paare, ergänzend
zum Boot bild005. Originalbilder werden nicht im Repository veröffentlicht.
Alle zehn TIFFs stammen laut Metadaten von der Canon PowerShot S110, 5,2 mm,
8 Bit RGB, DxO PhotoLab 10.0.1, TIFF-Orientation 1. Das beweist keine bestimmte
aktivierte oder deaktivierte Objektivkorrektur. bild089 hat 3782×2522 Pixel,
die übrigen Paare 4285×2857. `bild023R.tif` wurde ausdrücklich dem linken
`bild023_l.tif` zugeordnet; Originaldateien wurden nicht umbenannt.

## Messverfahren

Baseline: unveränderter Analysecode aus `ae7073cf8abce0d2259f1a4fb77050dda5117ac4`,
AKAZE und SIFT, Geometriebreite 3000, Disparitätsbreite 1500, automatische
Grundeinstellung, maximaler Bildausschnitt, Farbe und schwebende Fenster aus.
Analyse erzwungen, keine Sidecars geschrieben oder wiederverwendet.
Python 3.12, OpenCV 4.13.0, NumPy 2.4.6, vier OpenCV-Threads.

Unabhängige Prüfung am tatsächlichen Vollauflösungsrender: auf 1500 Pixel
Breite verkleinert, bis zu 3000 Shi-Tomasi-Punkte, Mindestabstand 8,
LK-Fenster 31×31, vier Pyramidenstufen, Vorwärts-/Rückwärtsabweichung <0,35
Analysepixel und LK-Fehler <10. Höhenfehler zurück auf Vollauflösung umgerechnet.
Punkte wurden separat für neun Bildregionen ausgewertet. Das ist eine
Kontrollmessung mit begrenzter Genauigkeit, kein exaktes Ground Truth. Nach
verbesserter Justage können andere und mehr Punkte die Konsistenzprüfung
bestehen; die Kennzahlen sind deshalb keine paarweise identischen Stichproben.

Das Diagnoseexperiment aktiviert ausschließlich das bereits berechnete
affine yQuad-Feld. Es schaltet eine etwaige Trapezkorrektur dafür ab, verändert
aber keine Produktentscheidung. Seine Verwendung setzt keine Freigabe voraus.

## Höhenlage

Alle Werte in Vollauflösungspixeln, gerundet. N ist die Zahl der gültigen
unabhängigen Baseline-Prüfpunkte.

| Bild | Verfahren | N | Baseline Mittel | Baseline P95 | Experiment Mittel | Experiment P95 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| bild023 | AKAZE | 483 | 3,670 | 11,461 | 0,397 | 1,139 |
| bild023 | SIFT | 499 | 2,884 | 7,264 | 0,295 | 0,745 |
| bild026 | AKAZE | 448 | 3,925 | 11,711 | 0,976 | 2,630 |
| bild026 | SIFT | 419 | 7,296 | 21,656 | 1,798 | 4,715 |
| bild087 | AKAZE | 1069 | 1,147 | 3,158 | 0,319 | 0,813 |
| bild087 | SIFT | 1024 | 1,264 | 3,251 | 0,354 | 0,884 |
| bild089 | AKAZE | 1070 | 2,585 | 7,716 | 0,300 | 0,902 |
| bild089 | SIFT | 1555 | 0,318 | 0,975 | 0,318 | 0,975 |
| bild090 | AKAZE | 1553 | 2,135 | 5,788 | 0,377 | 0,978 |
| bild090 | SIFT | 1527 | 2,078 | 5,374 | 0,367 | 0,929 |

Nur bild089/SIFT wählt in der Baseline yQuad; die anderen neun wählen Affine.
Der bislang benutzte interne Fit-Mittelwert unterschätzt unter anderem die
Rand-/Vordergrundfehler in bild023 und bild026 erheblich. SIFT ist kein
allgemeiner Ersatz für die Modellkorrektur: Beim Campingplatz bild026 ist es
in dieser Prüfung schlechter als AKAZE. Dort bleiben selbst nach yQuad regionale
Restfehler (SIFT rechts rund vier Pixel im Mittel). Das muss vor Freigabe
untersucht werden. bild089/SIFT dient zugleich als schon guter Vergleichsfall.

## Nahpunkt im ausgegebenen Bild

Zusätzliche unabhängige Kontrolle der zehn jeweils nahesten LK-Kandidaten:
25×25-Patchkorrelation über die gesamte horizontale Bildbreite, vertikal ±10
Analysepixel; NCC >0,85, Abstand zum zweitbesten Peak >0,05 außerhalb der
lokalen Peak-Nachbarschaft, reziproke Suche ≤1 Pixel und Übereinstimmung mit
dem LK-Match <2 Pixel. Dies ist ein lokaler Beleg, keine vollständige Tiefenkarte.
Durch die ganzzahlige Patchsuche ist die horizontale Auflösung rund 0,667‰.
Positive Disparität bedeutet hier vor dem Fenster.

Beispiele bestätigter Restdisparitäten nach automatischer Baseline:

| Bild/Verfahren | Linker Analysepunkt (x,y) | Restdisparität | NCC |
| --- | --- | ---: | ---: |
| bild023/AKAZE | (1406,924) | +4,667‰ | 0,891 |
| bild087/AKAZE | (1470,986) | +0,667‰ | 0,971 |
| bild089/SIFT | (1484,972) | +1,333‰ | 0,981 |
| bild090/SIFT | (1485,922) | +2,000‰ | 0,974 |

Damit ist die Nahpunktschwäche auch jenseits des Boots belegt. Eine gute
Höhenjustage allein beseitigt sie nicht: bild089/SIFT ist bereits gut justiert.
Das Fehlen positiver Treffer in einem der anderen Läufe beweist umgekehrt
keine vollständig sichere Nahpunktwahl.

## Folgerungen für die Umsetzung

- Modellwahl anhand robuster UND räumlich verteilter unabhängiger Evidenz
  absichern; ein einzelnes Maximum ist kein ausreichendes Veto oder Gütesiegel.
- Campingplatz gesondert auf Unterstützung/Extrapolation und Restverzeichnung
  untersuchen, bevor pauschal größere Modelle oder gelockerte Schranken
  eingeführt werden.
- Nahpunktalgorithmus muss kleine echte nahe Regionen erfassen und Fehlmatches
  unterscheiden; ein globales P99 und ein absolutes Maximum reichen nicht.
- Gute Höhenlage und sichere Nahpunktlage getrennt beurteilen. Zusätzliche
  andere Gespanne bleiben hilfreich, verhindern aber nicht die Arbeit an den
  nun belegten Fehlern.
