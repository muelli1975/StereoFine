# StereoFine 1.1 RC1/RC2: geprüfter Verarbeitungsstand

20.10.2026. Vorabversion zur praktischen Windows-Prüfung, keine allgemeine
Zusicherung für beliebige Kameragespanne. Die veröffentlichten 1.0-Pakete
bleiben unverändert. Alle verwendeten Originalaufnahmen bleiben außerhalb des
Repositories und der Programmarchive.

## Umgesetzte Verarbeitung

Die Modellwahl aus [MODEL_SELECTION_1.1.md](MODEL_SELECTION_1.1.md) bleibt
erhalten. Zusätzlich wird einmalig nach echten, zunächst verworfenen
Korrespondenzen gesucht. Neue Punkte benötigen Patchkorrelation ≥0,85 bei
ausreichendem Kontrast. Ganze 32-Analysepixel-Blöcke (20 %) trainieren die
Neuberechnung nicht; vier Pixel große Zellen dünnen doppelte Prüfpunkte aus.
Mindestens 30 und 5 % zusätzliche bestätigte Trainingspunkte sind erforderlich.

Die erneute Anpassung muss robust global besser sein und die regionalen
Schutzprüfungen bestehen. Bei dieser Wiederanpassung dürfen kleine regionale
Fehler innerhalb expliziter Qualitätsgrenzen handeln: Mittel ≤0,5 und P90 ≤1,5
Analysepixel. Größere regionale Fehler behalten die bisherigen relativen und
absoluten Verschlechterungsgrenzen. Die Prüfmittel werden bei P95 winsorisiert;
Median/P90/P95 bleiben separate Prüfgrößen. Diese technischen Auswahlgrenzen
sind keine kalibrierten Konfidenzintervalle. Unveränderte oder schlechtere
Neuanpassungen werden verworfen. Es gibt genau einen Wiederanpassungsschritt.

Die Nahpunktanalyse:

- füllt die bisher durch den gemeinsamen SGBM-Suchbereich ausgeschlossenen
  breiten Ränder für die Berechnung auf und prüft Korrespondenzen anschließend
  wieder in den echten unaufgefüllten Bildern;
- benutzt P99 als robuste Ausgangsschätzung und untersucht kleine nahe Regionen
  sowie zusätzliche Punkte in Messlücken/Randbereichen;
- verlangt eindeutige, gegenseitig bestätigte Patchvergleiche mit ausreichendem
  Kontrast und räumlicher Bestätigung durch benachbarte Punkte;
- sucht bei zunächst isolierten nahen Treffern gezielt nach Nachbarbestätigung;
- ergänzt bestätigte extremere Vordergründe um ein halbes Analysepixel
  Messreserve; die etablierte automatische Verschiebung um weitere 3‰ bleibt;
- markiert unbestätigte Extreme oder erreichte Suchgrenzen als unsicher.

Das ist keine Auswahl des ungeprüften Maximums. Kleine echte Vordergründe
dürfen jetzt sowohl Nahpunkt als auch gesamten Disparitätsumfang vergrößern.
Die Ampelgrenzen 33/40‰ und die Regler-/Tastaturbedienung sind unverändert.

sf-align-4 und sf-disparity-2 invalidieren alte automatische Berechnungen.
Explizite manuelle Werte, Favoriten und Eingabeeinstellungen bleiben erhalten.
Die TIFF-Ausrichtung und vier früheren Wartungskorrekturen sind enthalten.

## Zusätzliche Randkorrektur

Die gezielte Prüfung der äußersten unteren rechten 10 % bestätigt Restfehler,
die globale Mittelwerte verbergen. Nach der bisherigen Verbesserung blieben
zum Beispiel bei bild026/SIFT rund 2,25 px mittlerer Höhenversatz in dieser
kleinen Ecke. Die Aufnahmen dieses S110-Satzes haben alle 5,2 mm Brennweite;
sie sind bereits als DxO-verarbeitete TIFFs geliefert. Ein eindeutiger Nachweis
von Objektivverzeichnung gegenüber anderen Ursachen ist damit nicht möglich.

Eine zusätzliche kubische **vertikale** Restkorrektur ersetzt bei belegtem
Gewinn das quadratische Feld. Sie verändert keine horizontalen Koordinaten
und ist keine vollständige radiale Objektivkalibrierung. Es gibt einen Versuch,
keine iterative Suche nach immer komplexeren Modellen. Mindest-NCC ist 0,90,
Trainingsresiduen höchstens 3 Analysepixel, mindestens 120 Trainingspunkte und
48 ausgedünnte Prüfpunkte, Trainingsunterstützung in mindestens fünf Regionen.
Ganze 32-Pixel-Blöcke bleiben vom Fit ausgeschlossen. Die symmetrische
Feldanpassung berücksichtigt beide Augenpositionen und die inverse Rasterabbildung.
Die globalen/regionalen Schutzprüfungen bleiben erforderlich. Zusätzlich dürfen
genügend belegte äußere 20%-Ecken nicht über ihre bisherigen Fehler plus 0,1
Analysepixel bzw. die Qualitätsgrenzen Mittel 0,5/P90 1,5 hinaus schlechter werden.
Das Feld wird auf einem 33×33-Gitter im ganzen Bild auf Ausmaß und Gradienten
geprüft; der Rasterpfad begrenzt seine Auslenkung zusätzlich auf höchstens 24
Analysepixel bzw. 1,8 % der kleineren Bilddimension.

Fünf der 22 Läufe wählen die zusätzliche Stufe. Auf allen vier neuen IXUS-Paaren
wird sie mangels ausreichenden Gewinns verworfen. Auch die Grenzprüfungen
bleiben aktiv: Bei bild090/AKAZE verhindert die Feldgrenze eine unzureichend
abgesicherte Extrapolation. Ein gleichmäßig perfektes Ergebnis bis in jede
Ecke kann daher auch dieser RC nicht beanspruchen.

## Tatsächlich gerenderte elf Paare

Alle Paare mit AKAZE und SIFT, voller Eingabeauflösung, automatische
Grundeinstellung, Farbe und Fenstermasken aus. Kontrolle per unabhängiger
Vorwärts-/Rückwärts-LK-Messung auf 1500 Pixel breiten Kopien der tatsächlichen
Vollauflösungsrender, zurückgerechnet auf Vollauflösung. Die neuen IXUS-JPEGs
haben 4000×2248 Pixel, Brennweite 5,9 mm und EXIF-Orientation 1; ihre linken
Pixelbilder stehen dennoch auf dem Kopf. Nur dafür wird die bestehende
Eingabeoption links 180° gesetzt, rechts 0°. Originale bleiben unverändert.
Details der Methode
stehen in [REAL_IMAGE_BASELINE_1.1.md](REAL_IMAGE_BASELINE_1.1.md).

| Gespann/Bild | Verfahren | Punkterholung | Kubisches Feld | Mittlerer Höhenfehler, px | P95, px | Roh-Nahpunkt, ‰ |
| --- | --- | --- | --- | ---: | ---: | ---: |
| S110/bild005 | AKAZE | nein | nein | 0,433 | 1,086 | 38,633 |
| S110/bild005 | SIFT | nein | nein | 0,411 | 1,046 | 38,343 |
| S110/bild023 | AKAZE | ja | ja | 0,222 | 0,602 | 36,345 |
| S110/bild023 | SIFT | nein | nein | 0,291 | 0,708 | 37,043 |
| S110/bild026 | AKAZE | ja | ja | 0,343 | 0,855 | 34,036 |
| S110/bild026 | SIFT | ja | ja | 0,373 | 0,936 | 34,453 |
| S110/bild087 | AKAZE | nein | nein | 0,317 | 0,817 | 35,009 |
| S110/bild087 | SIFT | nein | nein | 0,353 | 0,873 | 34,800 |
| S110/bild089 | AKAZE | nein | nein | 0,294 | 0,869 | 36,229 |
| S110/bild089 | SIFT | nein | ja | 0,231 | 0,546 | 35,465 |
| S110/bild090 | AKAZE | nein | nein | 0,378 | 0,974 | 35,058 |
| S110/bild090 | SIFT | nein | ja | 0,223 | 0,627 | 34,814 |
| S110/bild092 | AKAZE | nein | nein | 0,258 | 0,563 | 22,375 |
| S110/bild092 | SIFT | nein | nein | 0,234 | 0,556 | 22,264 |
| IXUS/bild008 | AKAZE | nein | nein | 0,269 | 0,761 | 12,333 |
| IXUS/bild008 | SIFT | nein | nein | 0,272 | 0,783 | 12,292 |
| IXUS/bild015 | AKAZE | nein | nein | 0,216 | 0,568 | 5,303 |
| IXUS/bild015 | SIFT | nein | nein | 0,183 | 0,574 | 4,980 |
| IXUS/bild027 | AKAZE | nein | nein | 0,506 | 1,532 | 9,209 |
| IXUS/bild027 | SIFT | nein | nein | 0,494 | 1,542 | 9,776 |
| IXUS/bild050 | AKAZE | nein | nein | 0,405 | 1,117 | 1,555 |
| IXUS/bild050 | SIFT | nein | nein | 0,398 | 1,195 | 1,269 |

In keinem der 22 Läufe liegen akzeptierte LK-Kontrollpunkte vor dem Fenster.
Die bereits gute SIFT-Geometrie von bild092 bleibt unverändert. Bei bild089/SIFT
wird die weitere Verbesserung durch die kubische Stufe unabhängig bestätigt.
Bei IXUS/bild008 bleibt der Nahpunkt in beiden Verfahren als unbestätigt/unsicher
markiert. Keine Umdeutung dieses Warnfalls als bestandene Nahpunktfreigabe.

Weitere unabhängige Nahpunktkontrolle mit anderen Patchgrößen, breiterer
Vertikalsuche und reziproker Prüfung auf den ausgegebenen Bildern: Bei allen
20 nicht als unsicher markierten Läufen wurde mindestens ein naher Prüftreffer
separat bestätigt. Die jeweils vordersten bestätigten Treffer liegen mindestens
rund 3,33‰ hinter dem Fenster. Für bild005/beide Verfahren, bild026/AKAZE,
bild092/AKAZE und IXUS bild015/SIFT sowie bild027/SIFT wurden wegen Randnähe oder
Patchgröße direkt die Vollauflösungsrender geprüft (25-/41-Pixel-Patches);
die übrigen Kontrollen nutzen die 1500-Pixel-Kopien. IXUS bild008 bleibt trotz
einzelner bestätigter Punkte insgesamt ein unbestätigter Nahpunkt. Das ist lokale
bildliche Evidenz, keine lückenlose Ground Truth oder Garantie für strukturlose
oder verdeckt liegende Bildstellen.

Gezielte zusätzliche Eckenkontrolle: LK-Punkte werden pro 5×5-Zelle gesucht,
vorwärts/rückwärts geprüft und verlangen zusätzlich NCC ≥0,90 mit ausreichendem
Kontrast. In der äußersten unteren rechten 10%-Ecke ergibt sich nach Korrektur:

| Bild/Verfahren | Prüfpunkte | Mittlerer Höhenfehler, px | P95, px |
| --- | ---: | ---: | ---: |
| bild023/AKAZE | 10 | 0,583 | 0,875 |
| bild023/SIFT | 10 | 1,657 | 2,099 |
| bild026/AKAZE | 10 | 0,386 | 0,715 |
| bild026/SIFT | 8 | 0,600 | 0,869 |
| bild090/AKAZE | 6 | 1,828 | 2,815 |
| bild090/SIFT | 6 | 1,613 | 2,583 |

Die kleinen Punktzahlen sind ausdrücklich eine lokale Stichprobe. Insbesondere
bild090 zeigt weiterhin Randreste; Bildmittelwerte allein wären irreführend.

## Exaktes SIFT-Matching und Zeitmessung

OpenCV-SIFT liefert hier quantisierte float32-Deskriptoren mit 128 ganzzahligen
Werten zwischen 0 und 255. Ihre vollständigen quadratischen L2-Distanzen lassen
sich exakt in float32 berechnen (auch doppelte Skalarprodukte <2^24). Die
blockweise Matrixberechnung begrenzt die Distanzmatrix auf ungefähr 64 MiB.
Sie behält die ursprüngliche Float-Distanz-Quotientenprüfung und die erste
kleinste Indexwahl bei. Andere Deskriptorformate nutzen unverändert BFMatcher.

Bei allen sieben realen S110-SIFT-Paaren stimmen Anzahl, Reihenfolge und
Koordinaten aller akzeptierten Punktpaare exakt mit BFMatcher überein.
Der Abgleich fand vor der zusätzlichen kubischen Randkorrektur statt;
die Zuordnungsfunktion ist seither unverändert.

Lokales Linux, Python 3.12, OpenCV 4.13, NumPy 2.4.6; OpenCV vier Threads,
NumPy/OpenBLAS natürliche Voreinstellung (hier neun Threads). Beispiel Wald:
80.633 linke und 76.504 rechte Deskriptoren. Matching bisher rund 64 s,
neues Matching rund 16,5–20,3 s. Diese Zeit betrifft nur das Matching.
Das ist kein Vergleich mit
StereoPhoto Maker auf Christophs Rechner und keine universelle Zeitgarantie.

## Automatische und manuelle Freigabe

132 automatische Tests bestehen lokal. Hinzu kommen Kompilierung, Modulimporte,
Original-Asset-Hashes und die obigen echten Bildprüfungen. Neue Regressionen
prüfen unter anderem ein echtes nahes Objekt mit nur rund 0,32 % Bildfläche im
ehemaligen Messrand, mehrdeutige Muster, isolierte falsche Extreme, überschrittene
Suchgrenzen, gesperrte Prüfblöcke, exaktes Matching, kubische Restfelder,
tatsächliches Raster und .sfin-Cache-Rundläufe.
Die saubere 20‰-Referenz prüft jetzt die tatsächliche Sollgeometrie mit ±0,5‰
Messtoleranz, statt den alten ROI-abhängigen Perzentilwert 19,833‰ festzuschreiben.

Vor Bereitstellung laufen in GitHub Actions zusätzlich dieselben Tests,
DE/EN-GUI-Smokes unter Xvfb und Windows/Linux/macOS-Builds. Der RC wird nur
nach erfolgreichem Abschluss aller Buildjobs als eigene Vorabversion angelegt.
Alle Archive enthalten den genauen Quellstand samt Commit unter `Source/`.

Ausstehend bleibt die praktische Prüfung der portablen Windows-Version durch
Christoph, insbesondere mit den problematischen TIFF-Paaren, vorhandenen
Einstellungen und weiteren Gespannen. Erst danach ist eine stabile 1.1 sinnvoll.

## RC2-Paketkorrektur

Die externe Archivkontrolle von RC1 fand unter Linux/macOS eine Abweichung in
`Source/StereoFine.spec`: PyInstaller erzeugt bei seinem CLI-Build diese Datei
neu, bevor der ursprüngliche Ablauf die Quellkopie anlegte. RC2 legt die
Quellkopie vor dem Buildwerkzeug an und verlangt einen sauberen Checkout.
Die Quelldateien werden in kanonischer Git-Schreibweise kopiert und nach dem
Build nochmals Datei für Datei geprüft; Windows-Zeilenenden verändern die
Quellkopie nicht. Die Bildverarbeitung ist unverändert. RC1 wird als durch RC2 ersetzt markiert;
1.0 bleibt unverändert. Die ausgelieferten Archive werden erneut mit den
getrackten Quelldateien und dem angegebenen Commit verglichen.
