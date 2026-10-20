# StereoFine 1.1: räumliche Auswahlprüfung für LightGlue

20.10.2026. Fortsetzung des [ersten Modellvergleichs](NEURAL_PILOT_1.1.md).
Forschungsprogramme, keine Produktintegration oder neue Freigabe. Modelle,
Gewichte und Geometrieverfahren entsprechen dem ersten Vergleich. Es wird
genau ein Kandidat untersucht: ALIKED + LightGlue, ohne zusätzliche lokale
LK-Nachmessung der Fit-Punkte, gegen die vorhandene RC3-SIFT-Korrektur.

## Vorab festgelegtes Prüfverfahren

Die Auswahl verwendet die vorhandenen strengen RC3-Schwellen. Diese wurden
nicht anhand der zusätzlichen neuronalen Bildvergleiche angepasst.

1. Auf den Quellbildern werden bei höchstens 1500 Pixel Breite je 5×5-Zelle
   bis zu 160 Shi–Tomasi-Merkmale gesucht. Pyramiden-LK ohne Startkorrektur,
   Vorwärts-/Rückwärtsfehler unter 0,35 Pixel, LK-Patchfehler unter 10 und
   NCC mindestens 0,90 bestätigen die Zuordnungen. Es gibt keinen Filter
   anhand des Restfehlers einer der verglichenen Justagen.
2. Ganze 64-Pixel-Blöcke werden deterministisch auf zwei Prüfgruppen verteilt.
   Beide Korrekturen werden jeweils an denselben Punktidentitäten geprüft.
   Die erste Gruppe wählt aus; die zweite kann den Kandidaten nur bestätigen
   oder verwerfen. Es werden keine Parameter damit nachgeschätzt und keine
   weiteren Kandidaten anhand dieser zweiten Gruppe nachgereicht.
3. Jede Gruppe muss die globale RC3-Gewinnprüfung sowie regionale Prüfungen
   auf **3×3 und 5×5** bestehen. Der robuste Mittelwert muss um mindestens
   0,05 Analysepixel oder fünf Prozent sinken. Median/P90/P95 dürfen nicht
   über die bestehende Präzisionstoleranz steigen. Regionale Mittelwerte/P90
   dürfen höchstens um 0,10 Analysepixel oder zehn Prozent steigen.
   Mindestens 24 Punkte und drei Zellen mit jeweils mindestens sechs Punkten
   sind erforderlich. Mittelwerte sind am P95 winsorisiert.
4. Vier äußere 20-Prozent-Ecken und zusätzlich die untere rechte 10-Prozent-Ecke
   werden getrennt kontrolliert. Ab sechs Punkten gilt derselbe regionale
   Verschlechterungsschutz. Schwächer belegte Ecken werden ausdrücklich als
   **ungeprüft** ausgegeben; sie sind auch bei einer Auswahl kein Gütenachweis.

Protokoll-Hash: `6c699e03c7fb0df45f505e0a3d3cab3fe1f6d988f601ced8eeddd5414af56009`.
Zwischengespeicherte Ergebnisse werden nur bei identischem Protokoll und
identischen SHA-256 der beiden Bilder, des Zustands und der Matchdateien
wiederverwendet. Private Pfade, Punkte und Korrekturzustände werden nicht
in die öffentliche Zusammenfassung übernommen.

## Wichtige Messgrenzen

Die beiden Gruppen sind räumlich getrennte Prüfungen des Selektors. Sie sind
**keine räumlich aus den Geometriefits ausgeschlossenen Trainingsblöcke**:
die vorhandenen Fits könnten Merkmale an ähnlichen Bildstellen verwendet
haben. Die zusätzliche LK/NCC-Messung ist vom neuralen Matcher getrennt,
aber keine manuell vermessene Ground Truth. Wiederholungsmuster, Verdeckungen
und Bewegung können auch diese Prüfung täuschen. Ein produktiver Selektor
benötigt zusätzlich eine Prüfung mit tatsächlich zurückgehaltenen Fit-Blöcken
und weiterem unabhängigen Bildmaterial.

Die zusätzlichen neuronalen Vergleiche stammen aus demselben vorhandenen
Bestand von vier Gespannen. Sie ersetzen keinen Test an weiteren Kameras.
Ein abgelehnter Kandidat ist nicht notwendig überall schlechter; die Ablehnung
besagt, dass die vorab festgelegte Übernahmeprüfung nicht bestanden wurde.

## Kontrolle tatsächlich gerenderter Bilder

Für S95 bild038, NX1000 bild033 und S110 bild090 wurden auch die verworfenen
Kandidaten explizit als Gegenprobe gerendert. Für **beide** Varianten wurden
Nahpunkt und Beschnitt mit unverändertem RC3-Code neu berechnet. Die Rasterprobe
enthält jetzt zusätzlich alle 25 Zellen. Ihre Punktmengen können nach dem
Beschnitt voneinander abweichen; sie ist deshalb von der Prüfung identischer
Quellpunkte zu unterscheiden. Diese Gegenproben ändern keine Auswahlentscheidung.
Die Rasterdiagnostik allein ist keine Freigabe von Nahpunkt und Beschnitt.
Ein produktiver Übernahmepfad muss diese Größen und die nutzbare Bildfläche
zusätzlich absichern.

- **S95 bild038:** Globale Raster-P95 verbessert sich von 1,303 auf 0,906 Pixel.
  Eine obere mittlere 5×5-Zelle verschlechtert sich jedoch von 1,405 auf
  2,945 Pixel bei 22 bzw. 23 Prüfpunkten. Auch die getrennten Quellpunktgruppen
  zeigen regionale Verschlechterungen: im linken mittleren 3×3-Feld P90
  0,591→0,803 Pixel bzw. 0,331→0,694 Pixel. Der bessere Gesamtwert rechtfertigt
  deshalb keinen automatischen Austausch.
- **NX1000 bild033:** Globale Raster-P95 verbessert sich von 6,241 auf
  4,779 Pixel. In einer oberen mittleren Zelle steigt sie von 3,657 auf
  6,268 Pixel bei nur 12 bzw. 8 Punkten; die untere rechte 20-Prozent-Ecke
  steigt von 0,898 auf 1,151 Pixel bei 49 bzw. 43 Punkten. Der insgesamt
  bessere Wert verbirgt lokale Verschlechterungen.
- **S110 bild090:** Globale Raster-P95 verändert sich nur von 0,758 auf
  0,741 Pixel. Die äußerste untere rechte Ecke bleibt schwach belegt:
  mittlerer Rest 1,857→1,910 Pixel bei sechs bzw. fünf Punkten. Eine Lösung
  dieses Randproblems ist damit weiterhin nicht nachgewiesen.

## Reproduktion und Abgrenzung

Alle Originalbilder bleiben privat. Die Programme unter `experiments/` und
ihre zehn Tests bleiben außerhalb der Programm- und Quellpakete. Die
Produkt-Testmenge wird dadurch nicht um fehlende neuronale Abhängigkeiten
erweitert. Es bestehen 139 bisherige Tests und zehn neue experimentelle Tests
(149 insgesamt). Die Programme benötigen für die Auswahlprüfung kein Torch.
Nur die vorgelagerte Inferenz verwendet die ursprünglichen Modellgewichte.

```sh
# Inferenz wie im ersten Bericht, ohne --names/--limit für alle 29 SIFT-Fälle:
python experiments/neural_matches.py lightglue_aliked \
  --manifest /private/cases.json --output /private/neural \
  --lightglue-source /private/LightGlue --roma-source /private/RoMaV2 \
  --cache /private/model-cache
python experiments/select_neural_candidate.py /private/neural --output /private/selection
python experiments/render_neural_selection.py /private/neural --selection /private/selection
# Explizite Gegenproben, auch wenn diese Kandidaten verworfen wurden:
python experiments/render_neural_selection.py /private/neural --selection /private/selection \
  --names s95_bild038 nx1000_bild033 s110_bild090
python experiments/check_neural_guard_sensitivity.py /private/selection \
  --output /private/sensitivity.json
python experiments/summarize_neural_selection.py /private/selection \
  --manifest /private/cases.json --output /private/public-summary.json \
  --guard-sensitivity /private/sensitivity.json
python -m unittest discover -s tests
python -m unittest discover -s experiments/tests
```

Das Manifest entspricht dem ersten Bericht. Die Zusammenfassung verlangt einen
vollständigen Vergleich mit dem Manifest; fehlende Fälle werden nicht als
Ablehnungen gezählt. Die dokumentierten ursprünglichen acht Fits wurden erneut
berechnet und stimmen nach Entfernung der Zeitdiagnostik exakt überein.
Die bisherigen beiden Inferenz-/Auswertetreiber berücksichtigen jetzt auch
`swap_eyes`. Bei sämtlichen 29 untersuchten Fällen ist dieser Wert falsch;
die Korrektur ändert die bisherigen Messergebnisse nicht.

Die CPU-Läufe erfolgen teils parallel mit Auswertungen und sind kein isolierter
Geschwindigkeitsbenchmark. Eine GPU wurde weiterhin nicht getestet. Die
1.0-Wartungsfassung, die veröffentlichten Versionen und sämtliche produktiven
Bildverarbeitungsfunktionen bleiben auf dem zuvor dokumentierten Stand.

## Vollständiger Vergleich

Alle **29** verfügbaren Paare wurden mit ALIKED + LightGlue untersucht, darunter **21 zusätzliche** neuronale Vergleiche gegenüber dem ersten Pilot. Der unveränderte strenge Selektor übernimmt **0 von 29** Kandidaten. Das ist keine Aussage, dass sämtliche Kandidaten überall schlechter wären; ein ausreichend abgesicherter automatischer Austausch wurde mit dieser Politik nicht erreicht.

[Öffentliche Ergebnisdaten](NEURAL_SELECTION_1.1_RESULTS.json). P95 an identischen räumlich verteilten Quellpunkten, in Vollauflösungspixeln. Raster-P95 ist eine andere Messung.

| Paar | Punkte | RC3-SIFT P95 | ALIKED/LightGlue P95 | Strenge Übernahme |
|---|---:|---:|---:|---|
| ixus_bild008 | 949 | 1.241 | 1.236 | nein |
| ixus_bild015 | 866 | 0.623 | 0.557 | nein |
| ixus_bild027 | 941 | 1.328 | 1.328 | nein |
| ixus_bild050 | 144 | 1.384 | 1.375 | nein |
| nx1000_bild001 | 667 | 1.170 | 1.422 | nein |
| nx1000_bild004 | 1095 | 2.483 | 2.304 | nein |
| nx1000_bild008 | 1146 | 0.582 | 1.227 | nein |
| nx1000_bild012 | 1765 | 2.279 | 2.354 | nein |
| nx1000_bild023 | 624 | 0.428 | 1.183 | nein |
| nx1000_bild029 | 1050 | 3.228 | 4.056 | nein |
| nx1000_bild033 | 1375 | 8.793 | 6.611 | nein |
| nx1000_bild041 | 67 | 0.720 | 0.681 | nein |
| nx1000_bild043 | 421 | 1.226 | 1.424 | nein |
| nx1000_bild045 | 1067 | 4.531 | 5.625 | nein |
| s110_bild005 | 1498 | 0.969 | 1.009 | nein |
| s110_bild023 | 1472 | 0.687 | 0.556 | nein |
| s110_bild026 | 985 | 1.086 | 1.132 | nein |
| s110_bild087 | 1016 | 1.899 | 1.081 | nein |
| s110_bild089 | 1179 | 0.771 | 0.823 | nein |
| s110_bild090 | 1227 | 0.868 | 0.889 | nein |
| s110_bild092 | 2254 | 0.772 | 0.821 | nein |
| s95_bild010 | 280 | 1.500 | 1.007 | nein |
| s95_bild012 | 521 | 0.498 | 0.594 | nein |
| s95_bild032 | 1067 | 0.653 | 0.677 | nein |
| s95_bild038 | 1061 | 1.388 | 0.915 | nein |
| s95_bild054 | 1341 | 0.548 | 0.603 | nein |
| s95_bild057 | 445 | 0.415 | 0.422 | nein |
| s95_bild059 | 682 | 0.754 | 0.519 | nein |
| s95_bild067 | 413 | 0.385 | 0.534 | nein |

### Zusätzliche Sensitivitätskontrolle

Um eine unnötig strenge Ablehnung zu prüfen, wurde anschließend separat der Einsatz der beiden bereits in RC3 verwendeten regionalen Qualitätsschwellen von 0,5/1,5 Analysepixeln untersucht; die übrigen Prüfungen bleiben unverändert. Das ist kein Nachbau der gesamten RC3-Verfeinerungslogik. Es wurden keine neuen Schwellen optimiert. Diese **nachträgliche Sensitivitätskontrolle ist keine vorab festgelegte Validierung** und verändert den strengen Selektor nicht.

Damit würden drei Fälle übernommen: S110 bild023, S110 bild087 und S95 bild038. Die ersten beiden haben in diesem Durchlauf keine zusätzliche native Rasterkontrolle erhalten. Beim dritten belegt die Rasterkontrolle trotz globalem Gewinn die oben dokumentierte lokale Verschlechterung. Lockere Prüfungen sind daher ebenso wenig automatisch richtig wie ein ausnahmsloser Verschlechterungsschutz. Die Schwellen müssen zusammen mit Messunsicherheit und akzeptabler Ausgabequalität begründet werden.

Die Sensitivitätsauswertung reproduziert zuvor alle 29 strengen Entscheidungen und deren vollständige Prüfprotokolle exakt. Die Ergebnisse rechtfertigen eine verbesserte Geometrieprüfung, keine ungeprüfte Lockerung der Schutzbedingungen.


## Folgerung für die Geometrieentwicklung

Der aktuelle Programmcode kombiniert Affine-LMS, ein begrenztes Trapezmodell
und quadratische bzw. kubische vertikale Felder. Das ist keine vollständige
Kamerakalibrierung. Der frühe RANSAC-Filter verwendet ein ebenes Modell des
Höhenfehlers. Als überprüfbare Hypothese ist zu untersuchen, ob dieses Modell
bei deutlicher Verzeichnung echte Korrespondenzen zu früh entfernt.

Der nächste Vergleich sollte deshalb zuerst bei **identischen Matches** die
Geometrie austauschen: bisherige Korrektur gegen robuste Fundamentalgeometrie
und projektive Rektifizierung nach Hartley bzw. eine Variante mit geringerer
Bildverformung. Danach werden bei identischer Geometrie unterschiedliche
Matcher und abgesicherte Subpixel-Nachmessung verglichen. Diese Versuche sind
noch nicht ausgeführt und ihre Überlegenheit wird hier nicht behauptet.

Etablierte Referenzen:

- [OpenCV: Kameramodell, Verzeichnung, Stereo-Kalibrierung und Rektifizierung](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html).
  Stärkere Objektivverzeichnung ist vor einer rein projektiven Rektifizierung
  zu berücksichtigen. Ein Rohkamera-Profil darf auf bereits von DxO entzerrte
  TIFFs nicht ungeprüft erneut angewendet werden; maßgeblich ist die Geometrie
  der tatsächlich entwickelten Bilder und deren Brennweiten-/Beschnittzustand.
- [Loop/Zhang: Computing Rectifying Homographies for Stereo Vision](https://www.microsoft.com/en-us/research/publication/computing-rectifying-homographies-for-stereo-vision/).
  Eine passende Zeilenlage muss mit geringer Bildverformung vereinbart werden.
- [Monasse: Quasi-Euclidean Epipolar Rectification, IPOL](https://www.ipol.im/pub/art/2011/m_qer/).
  Eine ausführlich beschriebene Referenz mit Quellcode. Die konkrete Variante
  nimmt gleiche Kameraintrinsik, quadratische Pixel und mittigen Hauptpunkt an;
  diese Annahmen dürfen bei unseren Eingabeketten nicht ungeprüft gelten.
- [OpenCV: USAC](https://docs.opencv.org/4.13.0/de/d3e/tutorial_usac.html).
  Robuste Schätzer einschließlich MAGSAC sind eine Gegenprobe zum bisherigen
  frühen Höhenfehlerfilter; sie ersetzen keine Verzeichnungskorrektur.
- [Triggs et al.: Bundle Adjustment — A Modern Synthesis](https://lear.inrialpes.fr/people/triggs/pubs/Triggs-va99.pdf).
  Gemeinsame robuste Optimierung von Kamera- und gegebenenfalls Szenenparametern
  ist etabliert. Alle unbekannten Parameter aus einem beliebigen einzelnen
  Stereopaar zu schätzen, ist damit nicht automatisch zuverlässig möglich.

Als Zielgrößen sind vertikale Fehler auf tatsächlich zurückgehaltenen,
räumlich verteilten Prüfungen, geringe lokale Bildverformung und ausreichende
nutzbare Fläche gemeinsam zu betrachten. Nahpunkt und Fenster werden erst
danach separat geprüft. Horizontale Szenentiefe darf nicht als Fehler auf null
optimiert werden. Freie lokale Bildverformung oder immer höhere Polynome sind
kein abgesicherter Ersatz für fehlende Geometrieinformation.

## Verbindliche Anforderung an die .sfin-Speicherung

Die weitere Entwicklung soll etablierte Implementierungen wie OpenCV nutzen.
Eine neue produktive Geometrie und die zugehörige Speicherung sind als eine
zusammenhängende Änderung zu behandeln. Die folgenden Punkte sind Anforderungen,
noch keine implementierte Formatänderung:

- Die vorhandene Trennung zwischen Schema- und Pipelineversion weiterverwenden.
  Ein neuer Transformationsvertrag benötigt eine passende Formatversion und
  eine Aktualisierung der betroffenen Berechnungsversionen.
- Den angewendeten Modelltyp und alle zur Wiedergabe benötigten Transformationen
  beider Augen speichern. Bei projektiver Rektifizierung gehören die tatsächlich
  angewendeten Matrizen, ihre Koordinatenbasis, Bildabmessungen, Normalisierung
  und die Reihenfolge relativ zu Orientierung, Restkorrektur und Beschnitt dazu.
  Eine Fundamentalmatrix oder der Name des Matchers allein reproduziert den
  gewählten Bildausschnitt und die konkrete Rektifizierung nicht.
- `reproducible_alignment_correction()` ist derzeit eine ausdrückliche Positivliste
  der bestehenden Korrekturtypen. Neue Matrizen würden ohne Erweiterung beim
  Speichern entfallen. Zustand, Serializer, Lader, Renderer und Cachebasis
  müssen daher gemeinsam angepasst und getestet werden.
- Bestehende .sfin-Dateien weiterhin lesen. Favoriten und unabhängig gültige
  Nutzereinstellungen erhalten. Koordinatenabhängige manuelle Korrekturen und
  Ausschnitte benötigen eine geprüfte Übernahme; dieselben Zahlen auf einer
  neuen geometrischen Basis bedeuten nicht automatisch dieselbe Bearbeitung.
  Ein reiner Ladevorgang darf keine neue automatische Justage erzwingen.
- Alte Analysen nicht als Ergebnisse einer neuen Geometrie wiederverwenden.
  Abhängige Nahpunkt-/Fenster- und Farbparameter gezielt invalidieren. Unbekannte
  Transformationsmodelle eindeutig ablehnen, nicht als alte Geometrie ausgeben.
- Vor einer Migration Sicherung und Koexistenz mit älteren Programmversionen
  klären. Ein neuer Leser kann alte Dateien unterstützen; bereits veröffentlichte
  alte Programme können dadurch keine neuen Formate verstehen. Ein Schemawechsel
  allein schützt insbesondere nicht vor dem späteren Überschreiben durch ein
  altes Programm.
- Freigabetest: analysieren, rendern, speichern, Programmzustand neu laden und
  ohne erneute Merkmalsanalyse wieder rendern. Geometrie, Nahpunkt und Beschnitt
  müssen unter derselben unterstützten Umgebung identisch reproduziert werden.
  Zusätzlich Migration, beschädigte/neuere Formate und Vorschau/Export prüfen.

Das öffentliche Format wird erst mit einer tatsächlich geprüften und integrierten
Geometrie erweitert. Forschungsversuche ändern weder bestehende .sfin-Dateien
noch die veröffentlichte Version 1.0.
