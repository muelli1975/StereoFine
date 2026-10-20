# Modellwahl: Umsetzung und reale Prüfung für 1.1

20.10.2026. Entwicklungsstand, keine 1.1-Freigabe. Die bisherigen
[Baseline-Messungen](REAL_IMAGE_BASELINE_1.1.md) bleiben als Ausgangspunkt erhalten.

## Nachgewiesene Auswahlfehler

Bei bild092/AKAZE verbessert das bereits vorhandene yQuad den unabhängigen
Höhenfehler am gerenderten Bild von 1,237 auf 0,260 Vollauflösungspixel im Mittel.
Der alte Holdout-Maximalwert steigt jedoch von 4,264 auf 5,398 Pixel. Alle
robusten globalen Kennzahlen verbessern sich, trotzdem verhindert genau dieses
Maximum die Aktivierung. SIFT aktiviert die Korrektur bei demselben Motiv und
liefert bereits ein gutes Ergebnis.

Zusätzlich war die Auswahl gierig: Sobald Trapez allein bestand, verdrängte
dies die direkte Affine+yQuad-Alternative. Trapez+yQuad wurde nur untersucht,
wenn Trapez allein das Gütekriterium erfüllte. Vollständige Alternativen wurden
nicht untereinander verglichen.

## Implementierter Stand

- Gemeinsame, deterministisch räumlich verteilte Holdout-Identitäten für alle
  Alternativen; deren Residuen werden für die Kettenauswahl in denselben
  Bildregionen verglichen.
- Eine Zusatzstufe benötigt mindestens 5 % Verbesserung des Holdout-Mittels
  und mindestens 0,05 Analysepixel absolute Verbesserung. Median, P90 und P95
  dürfen sich um höchstens 0,05 Analysepixel verschlechtern. Das Maximum bleibt
  eine endliche Diagnosegröße und ist kein alleiniger Aktivierungsblocker mehr.
- Mindestens 24 Holdout-Punkte und drei Regionen mit jeweils mindestens sechs
  Punkten. In jeder belegten Region werden Mittel und P90 vor Verschlechterung
  über max(0,10 Analysepixel, 10 % des bisherigen Werts) geschützt. Die Grenzen
  werden durch die Analyseskalierung auf Vollauflösung umgerechnet.
- Diese Werte sind technische Auswahl-/Präzisionsgrenzen, keine kalibrierten
  Konfidenzintervalle oder Zusicherung einer universellen Bildgenauigkeit.
- Beide bisherigen Zusatzmodelle behalten ihre Unterstützungskriterien und
  geometrischen Grenzen. Für die quadratische Designmatrix werden zusätzlich
  Rang und Kondition geprüft. Numerisch unterbestimmte Fits werden verworfen.
- Affine, Affine+Trapez, Affine+yQuad und Affine+Trapez+yQuad werden als ganze
  Ketten verglichen. Die kombinierte Alternative wird bei geometrisch plausiblem
  Trapez auch untersucht, wenn Trapez allein keinen messbaren Gewinn bringt.
  Bei geringfügigen Unterschieden bleibt die einfachere Kette erhalten.
- Jede Alternative muss sowohl gegenüber Affine als auch gegenüber dem bereits
  ausgewählten Modell bestehen. Regionale Toleranzen dürfen sich dadurch nicht
  über mehrere Vergleiche summieren. Die Entscheidung enthält ein Audit mit
  Gründen und Holdout-Kennzahlen.
- Kein neuer Warp, keine freie Homographie, keine zusätzliche horizontale
  Optimierung und keine Änderung der Bedienung. Die gewählten vorhandenen
  Korrekturen werden weiterhin mit einem Resampling pro Auge angewendet.
- sf-align-3 invalidiert alte Geometrie sowie abhängige Disparitäts-/Farb-Caches.
  Beim Browsen werden obsolete automatische Verschiebungen entfernt; explizite
  manuelle Werte und Favoriten bleiben erhalten.

## Reale gerenderte Ergebnisse

Sieben Originalpaare, jeweils AKAZE und SIFT, frisch analysiert. Einstellungen
und unabhängige LK-Kontrollmethode entsprechen der Baseline-Dokumentation.
Die Kontrollmessung arbeitet auf 1500 Pixel breiten Kopien der tatsächlichen
Vollauflösungsrender; Werte sind auf Vollauflösung zurückgerechnet. Sie ist
keine exakte Ground Truth. Alle 14 Fälle wählen jetzt Affine+yQuad. Die
abschließend ergänzte zusätzliche Prüfung gegen die Affine-Baseline wurde
für alle 14 ausgewählten direkten yQuad-Ketten mit ihren gespeicherten
Holdout-Daten erneut bestätigt; sie ändert diese Entscheidungen nicht.

| Bild | Verfahren | Kontrollpunkte | Mittel, px | P95, px |
| --- | --- | ---: | ---: | ---: |
| bild005 | AKAZE | 1759 | 0,436 | 1,130 |
| bild005 | SIFT | 1749 | 0,421 | 1,105 |
| bild023 | AKAZE | 536 | 0,400 | 1,138 |
| bild023 | SIFT | 548 | 0,300 | 0,734 |
| bild026 | AKAZE | 465 | 0,991 | 2,653 |
| bild026 | SIFT | 443 | 1,830 | 4,719 |
| bild087 | AKAZE | 1117 | 0,328 | 0,817 |
| bild087 | SIFT | 1105 | 0,353 | 0,854 |
| bild089 | AKAZE | 1560 | 0,298 | 0,898 |
| bild089 | SIFT | 1555 | 0,318 | 0,975 |
| bild090 | AKAZE | 1678 | 0,377 | 0,978 |
| bild090 | SIFT | 1702 | 0,367 | 0,927 |
| bild092 | AKAZE | 2510 | 0,260 | 0,563 |
| bild092 | SIFT | 2534 | 0,236 | 0,571 |

Die zuvor guten SIFT-Render von bild089 und bild092 sind links UND rechts in
voller Auflösung pixelidentisch erhalten (Farbe/Fenstermasken aus, automatische
Grundeinstellung). bild092 hat links 4040×2693, rechts 4041×2694 Pixel; es nutzt
wie bisher den gemeinsamen Bildbereich. Beide Eingaben sind S110-TIFFs mit
Orientation 1. Originaldateien und bestehende Sidecars wurden nicht verändert.

## Noch experimentell: erste Ausreißerfilterung

Beim Campingplatz bild026 verwirft der erste RANSAC-Schritt viele Punkte
gegenüber einem affinen Vertikalmodell. Eine zweite, versuchsweise Auswahl
anhand der Residuen nach yQuad gewinnt weitere zur Korrektur nutzbare Punkte.
Das Experiment verwendet die tatsächlich ermittelten Merkmalskorrespondenzen
erneut; geometrische Analyse und Render laufen mit diesen unveränderten
Koordinaten. Das Ergebnis wird unabhängig am gerenderten Bild geprüft.

| Verfahren | Inlier vorher | Nach erster Neuauswahl | Kontrollmittel vorher | Experiment Mittel | Experiment P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| AKAZE | 13048 | 18279 | 0,991 | 0,510 | 1,144 |
| SIFT | 10184 | 14661 | 1,830 | 0,515 | 1,125 |

Eine weitere Wiederholung verbessert das Mittel nicht (rund 0,541/0,533 px).
Im Experiment bleibt der automatische Fensterwert des ersten Ergebnisses
erhalten; es ist kein Test eines neuen Nahpunktalgorithmus. Die erneute
Punktauswahl ist noch nicht produktiv integriert: zusätzliche Absicherung gegen
Fehlmatches, unabhängige Prüfung und Tests an allen Vergleichspaaren fehlen.

## Verifikation und offene Freigabepunkte

109 automatische Tests bestehen, einschließlich neuer Gegenfälle für
regionale Verschlechterung, robuste Tail-Fehler, fehlende Unterstützung,
NaN/Inf, Rangmangel, kumulierte Toleranzen und zu geringe Verbesserungen.
Der alte Projektivtest prüft weiterhin, dass Trapez die Holdout-Prüfung besteht;
er fordert jetzt zusätzlich gute Resthöhe und lässt eine noch bessere direkte
yQuad-Kette zu. Die reine Affine-Referenz bleibt Affine.
Kompilierung und Hashes der Original-Assets ebenfalls geprüft.

Die Nahpunktberechnung ist noch unverändert und bleibt ein Freigabeblocker.
Beim Campingplatz ist weitere Qualitätsarbeit erforderlich. Die Laufzeit ist
separat zu profilieren: SIFT benötigte beim Wald in dieser Umgebung rund 75 s;
die neue Auswahl allein behebt das nicht. Ein direkter Vergleich mit StereoPhoto
Maker auf demselben Rechner und denselben Eingaben steht noch aus. Plattform-
Builds und reale Bedienprüfung der fertigen 1.1 sind ebenfalls noch ausstehend.
