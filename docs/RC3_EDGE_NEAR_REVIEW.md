# RC3: Randkorrektur, Nahpunkt und weitere Präzisionsansätze

Untersuchung vom 20.10.2026. Verarbeitungsstand:
`081275da0aa394d181f3debf9a8c2e361bdb37e5` (Tag `v1.1-rc3`).
Dieser Untersuchungszweig enthält ausschließlich Diagnoseprogramme, Tests und
Befunde. Anwendungscode, RC3-Archive, Entwicklungszweig und stabile 1.0 bleiben
unverändert. Die Kandidaten sind keine freigegebenen Programmfunktionen.
Die privaten Originalbilder, Match-Caches und vollständigen Zustandsdateien
werden nicht veröffentlicht.

## Was tatsächlich geprüft wurde

- Die 133 bestehenden Tests bestehen am unveränderten RC3-Code.
- Sechs zusätzliche Tests reproduzieren die Nahpunkt-Stichprobenlücke mit echten
  Bildpatches und prüfen Mehrdeutigkeit, strukturlose Flächen, überhöhtes P99,
  begrenzte Prüfkosten und unveränderte bereits bestätigte Ergebnisse.
  Insgesamt bestehen lokal 139 Tests; keine neue Plattform-Build-Freigabe.
- 29 Originalpaare: sieben S110, vier IXUS, acht S95, zehn NX1000, jeweils
  AKAZE und SIFT. In allen 58 Läufen wurden Nahpunktwert, vollständige
  Bestätigungsdiagnostik und Unsicherheitsgründe gegen gespeicherte RC3-Befunde
  reproduziert. Die jeweiligen Justagezustände wurden für diesen Vergleich
  geladen; die Merkmalsdetektion wurde dabei nicht erneut ausgeführt.
- Der kubische Fit von bild090 wurde für beide Verfahren aus gespeicherten
  Rohmatches mit der unveränderten Produktionspipeline nachgerechnet. Die
  renderrelevanten Korrekturparameter stimmen exakt mit RC3 überein.
- Die Original-Asset-Prüfsummen stimmen. Keine GUI-/Bedienänderungen, neuen
  Laufzeitabhängigkeiten oder Änderungen an Cacheversionen.

Maschinenlesbare, auf Messwerte beschränkte Zusammenfassung:
[RC3_REVIEW_SUMMARY.json](RC3_REVIEW_SUMMARY.json).

## bild090: eine knappe Feldgrenze und begrenzte lokale Evidenz

Bei AKAZE wird der kubische Kandidat vor der Qualitätsauswertung mit
`field_limit` verworfen. Seine maximale Auslenkung beträgt **24,068682**
Analysepixel gegenüber **24** erlaubten Pixeln. Das Maximum liegt bei (0,0),
also oben links. In der äußeren oberen linken 20%-Ecke gibt es keine Rohmatches.
Die gesamte Feldprüfung ist deshalb eine Schutzbedingung gegen ungemessene
Extrapolation, keine Aussage über einen nachgewiesenen Fehler an dieser Stelle.

Die äußerste untere rechte 10%-Ecke ist nicht völlig ohne Korrespondenzen:

| Verfahren | Rohmatches | NCC ≥0,90 | zusätzlich Residuum ≤6 Analysepixel | Training | blockweise zurückgehaltene, ausgedünnte Prüfung |
|---|---:|---:|---:|---:|---:|
| AKAZE | 34 | 29 | 25 | 19 | 5 |
| SIFT | 48 | 30 | 28 | 19 | 8 |

Das sind lokale Daten, keine Garantie für fehlerfreie Matches. Insbesondere
ist die äußerste Ecke für eine eigenständige komplexere Modellanpassung sehr
schwach belegt. Die ursprünglich sechs unabhängigen Raster-Kontrollpunkte sind
nicht die Gesamtzahl der zum Fit verfügbaren Matches.

SIFT verwendet den kubischen Kandidaten bereits. Seine maximale Auslenkung
beträgt 23,520404 Analysepixel. Ein Lockern der Feldgrenze würde daher den
verbleibenden SIFT-Randfehler nicht beseitigen.

### Kontrollierter Gegenversuch innerhalb derselben Grenze

Zusätzlich zum unbeschränkten Gegenversuch wurden die AKAZE-Koeffizienten
mit **0,997146396** multipliziert. Damit bleibt dasselbe Feldmodell auf dem
bestehenden 33×33-Prüfgitter innerhalb der ursprünglichen Grenze von 24 Pixeln.
Es werden weder Freiheitsgrade ergänzt noch Qualitätsgrenzen erhöht. Das ist
hier eine experimentelle Amplitudendämpfung, keine neue kalibrierte Optikkorrektur
und kein nachgewiesenes global optimales beschränktes Least-Squares-Verfahren.

Der begrenzte Kandidat besteht den bisherigen globalen und regionalen Holdout-
Vergleich sowie die ausreichend belegten äußeren 20%-Ecken. Im tatsächlichen
Vollauflösungsrender wird zusätzlich auf einem 5×5-Raster nach unabhängigen
Shi–Tomasi-/LK-Korrespondenzen gesucht (NCC ≥0,90, Vorwärts-/Rückwärtskontrolle).
Bei unveränderter gespeicherter Scheinfensterverschiebung ergibt diese neue Probe:

| AKAZE-Kontrolle | RC3 | begrenzter Kandidat |
|---|---:|---:|
| globaler mittlerer Höhenfehler | 0,470 px, 1593 Punkte | 0,284 px, 1654 Punkte |
| äußerste untere rechte 10%: Mittel | 2,008 px, 5 Punkte | 1,569 px, 5 Punkte |
| äußerste untere rechte 10%: P95 | 3,106 px | 2,644 px |

Diese neu gezogenen Rasterproben sind nicht identisch mit den historischen
sechs Punkten (1,828/1,613 px Mittel im früheren AKAZE-/SIFT-Protokoll). Der
Beschnitt unterscheidet sich zudem um eine Zeile. Zahlen aus verschiedenen
Proben dürfen nicht als Messung derselben Punktidentitäten verrechnet werden.
Die für die Modellentscheidung verwendeten Holdout-Identitäten bleiben hingegen
vor/nach der Korrektur identisch. SIFT rendert im Gegenversuch unverändert.

**Bewertung:** Es besteht eine begründete Verbesserungschance ohne Lockerung
von Grenzen. Der Rand wird damit aber nicht vollständig korrekt. Eine
Übernahme benötigt Vergleich aller durch die Feldgrenze abgelehnten Fälle,
zusätzliche Randkontrollen und echte Windows-Prüfung. Die bestehende
Extrapolationsprüfung sollte erhalten bleiben. Eine allgemeine Erhöhung auf
25 oder 48 Pixel ist durch diesen Einzelfall nicht begründet.

## bild008: die Messstellenauswahl übersieht verwertbare Nahstellen

Die linke IXUS-Aufnahme wird wie im bisherigen Protokoll explizit um 180°
gedreht. Analysebreite 1500 Pixel. RC3 findet 45/42 bestätigte Patches, aber
deren räumlich gestützte maximale Disparität liegt nur bei 8,265/8,309
Analysepixeln. Die P99-Ausgangswerte sind 18,500/18,438 Pixel, entsprechend
12,333/12,292‰. Die Unsicherheit ist für diese Messgrundlage korrekt.

Der Komponentenpfad nimmt höchstens acht nach Disparität sortierte Startpunkte
je naher Komponente. Deren Spitzen liegen hier vielfach an ungeeigneten
kontrastarmen oder gemischten Stellen. Auch die begrenzte zusätzliche
Merkmalsauswahl erreicht die verwertbaren nahen Zaunstellen nicht. Die Aussage
"es gibt keine zuverlässig messbaren Nahstellen" wäre deshalb falsch.

Ein begrenzter Gegenversuch verteilt höchstens 128 weitere Prüfstellen über
16-Pixel-Zellen im vertrauenswürdigen P98-Bereich. Er verwendet exakt RC3s
`verify_patch` und `supported_near_edge`: Kontrast ≥6, NCC ≥0,85,
Eindeutigkeitsabstand ≥0,05, globale horizontale Suche, gegenseitige Prüfung
und räumliche Nachbarstützung. Die Schwellen werden nicht gelockert.

| bild008 | zusätzliche bestätigte Stellen | gestütztes Maximum | Kandidat inklusive bestehender Reserve |
|---|---:|---:|---:|
| AKAZE | 16 | 19,084 Analysepixel | 13,056‰ |
| SIFT | 19 | 19,056 Analysepixel | 13,037‰ |

Eine gesonderte Prüfung in voller Auflösung verwendet 41×41-Patches,
globale horizontale Streifensuche, ±6 Pixel Höhenbereich, Kontrast-,
Eindeutigkeits- und Rückprüfung. Sie bestätigt 18/17 der geprüften Stellen,
mit maximal 12,833/12,582‰. Diese Methode verwendet größere native Patches
und keine durch SGBM eingeschränkte horizontale Suche; sie bleibt mit dem
Analyse-Patchvergleich methodisch verwandt und ist keine Tiefen-Ground-Truth.

**Bewertung:** Nachgewiesen ist eine Lücke der Vorauswahl, kein Grund zum
Entfernen der Unsicherheitsprüfung. Für bild008 genügt bereits bessere Auswahl
innerhalb der bestehenden Messmethode. Eine zweite Messskala kann zusätzliche
Absicherung liefern; ein neues Tiefennetz ist dafür nicht erforderlich.

## Gegenkontrollen: Unsicherheit darf nicht pauschal verschwinden

Von 58 Läufen bleiben 50 Nahpunkt-Bestätigungsobjekte unverändert, weil der
experimentelle Zweig bei bereits bestätigtem P99 nicht läuft. Das umfasst auch
Fälle mit einem separat ungestützten Extrempunkt: `confirmed` allein ist kein
Freigabesignal; `unsupported_extreme` und die übrigen Unsicherheitsgründe zählen
weiterhin.

Acht Läufe erhalten zusätzliche Proben. Darunter gibt es zwei wesentliche
Grenzfälle:

- S95 bild012/SIFT behält ein ungestütztes Extrem. Die Unsicherheit muss bleiben.
- NX1000 bild004/SIFT erhält analytisch einen gestützten Kandidaten von
  5,164‰, der sich mit der nativen Gegenmessung nicht ausreichend bestätigen
  lässt. Dort werden nur deutlich fernere Stellen bis 0,919‰ gesichert.
  Das widerlegt nicht schon den nahen Kandidaten; es reicht aber ausdrücklich
  nicht zum Aufheben der Unsicherheit. Eine reine zusätzliche Probenrunde
  wäre daher noch keine allgemein ausreichend validierte Produktkorrektur.

Die synthetischen Gegenfälle behalten strukturlose und wiederholte Muster
unsicher. Eine überhöhte P99-Schätzung wird weder abgesenkt noch durch fernere
bestätigte Punkte als sicher erklärt.

## Weitere Präzisionsansätze für 1.1

AKAZE/SIFT liefern die anfänglichen Merkmale und Zuordnungen. Genauigkeit hängt
zusätzlich von Punktlokalisierung, Verteilung, Ausreißern, Geometriemodell und
tatsächlicher Rasterabbildung ab. Ein anderer Detektor ersetzt diese Prüfungen
nicht. SIFT-Koordinaten sind bereits subpixelgenau repräsentiert; eine zusätzliche
Nachmessung optimiert die Zuordnung anhand tatsächlicher Bildintensitäten.

1. **Lokale Subpixel-Nachmessung**, z.B. pyramidal Lucas–Kanade mit Startmatches,
   Rückprüfung, Photometrieprüfung und blockweise unabhängiger Modellbewertung.
   Dafür sind keine neuen Laufzeitabhängigkeiten nötig. Frühere experimentelle
   Renderprüfungen an S95 bild038 verbesserten P95 von 1,930 auf 0,925 px
   (AKAZE) bzw. 1,287 auf 0,860 px (SIFT). Bei bild090 sank der globale Fehler,
   während eine kleine Randprobe nicht besser wurde. Diese Versuche sind keine
   Freigabe der Nachmessung und kein vollständiger Vergleich aller 29 Paare.
2. **ALIKED + LightGlue**, alternativ zuerst SIFT + LightGlue, als separat
   vermessener zusätzlicher Matcher. LightGlue ist ein Zuordnungsverfahren für
   Merkmale, kein Objektivkorrekturmodell. Benchmarkerfolge anderer Datensätze
   belegen keinen Präzisionsgewinn an diesen StereoFine-Bildern.
3. **Dichteres Matching wie RoMa v2** als weiterer Vergleichskandidat, wenn lokale
   Merkmale wichtige Bildbereiche nicht abdecken. Laufzeit, Speicher,
   Plattformpaketierung und Lizenzen sämtlicher Modelle/Gewichte müssten vor
   einer Integration gesondert geprüft werden. Hier wurde es nicht ausgeführt.

Primärquellen, am 20.10.2026 gelesen:
[OpenCV LK/ECC](https://docs.opencv.org/4.13.0/dc/d6b/group__video__track.html),
[LightGlue](https://github.com/cvg/LightGlue),
[RoMa v2](https://github.com/Parskatt/RoMaV2),
[Subpixel-Lokalisierung als separates Problem](https://arxiv.org/abs/2407.11668).
Alle Verfahren haben Voraussetzungen. Maßgeblich bleiben unabhängige
Kontrollmessungen am endgültigen Bild, einschließlich schwach belegter Ränder.

## Reproduktion

Voraussetzung sind der RC3-Quellstand plus diese Diagnoseprogramme und dieselben
privaten Originale/Zustandsdateien. Lokale Umgebung: Python 3.12, OpenCV 4.13,
NumPy 2.4, vier OpenCV-Threads. Der private Manifestaufbau ist in den jeweiligen
Skript-Docstrings beschrieben. Quellen müssen in maximaler Ausgabegeometrie
(kein Zoom/Pan) analysiert worden sein; diese Voraussetzung gilt für den Testsatz.

```sh
python -m unittest discover -s tests -p 'test_*.py'
python scripts/diagnose_rc3.py /private/manifest.json --output /private/near-results.json
python scripts/diagnose_rc3_field.py /private/corner-manifest.json --output /private/field-results.json --render
```

Die Programme schreiben nur die angegebenen Diagnose-JSON-Dateien. SHA-256 der
privaten Eingaben erlauben die Wiedererkennung desselben Materials. Der Feldtest
setzt die gespeicherten Rohmatches und anfängliche Inlier-Maske voraus und prüft
zuerst exakte Reproduktion der renderrelevanten RC3-Korrektur. Der Nahpunkttest
prüft die komplette gespeicherte Bestätigungsdiagnostik und Unsicherheitsgründe.
Die experimentellen Werte werden nicht in `.sfin` oder Programmeinstellungen
übernommen. Windows-Anwendungstest und eine stabile 1.1-Freigabe stehen aus.
