# StereoFine: interner neuronaler Modellvergleich

20.10.2026. Eigenständiger Forschungsversuch, keine Produktintegration und
keine Änderung der veröffentlichten RC3-/1.0-Pakete. Basis der Auswertung ist
RC3 `081275da0aa394d181f3debf9a8c2e361bdb37e5`.

## Tatsächlich ausgeführt

- SIFT + LightGlue und ALIKED + LightGlue: je acht Originalpaare, vier Gespanne.
- RoMa v2, offizieller Modus `fast`: sechs dieser Paare. Zwei zusätzliche Paare
  wurden aus Laufzeitgründen im ersten Pilot zurückgestellt. Fehlende Werte
  sind keine Qualitätsbewertung.
- Je erfolgreichem Matcher-Lauf wurden Rohzuordnungen und zusätzlich lokal mit
  Lucas–Kanade nachgemessene Zuordnungen mit derselben RC3-Geometrie verarbeitet.
  Insgesamt 22 Matcher-Läufe und 44 tatsächlich gerenderte Kandidaten.
- RoMa v2 im offiziellen Standardmodus `precise` wurde zusätzlich für bild090
  versucht. Das Betriebssystem beendete diesen Lauf beim 8-GiB-Speicherlimit
  (Exit 137, OOM-Kill). Es gibt dafür kein Messergebnis. Insbesondere folgt aus
  dem schnellen Modus kein Urteil über die erreichbare Qualität von `precise`.

Originalbilder, komplette Zustände, Punktdateien und Modellgewichte bleiben
außerhalb des Repositories. [Ergebnisdaten](NEURAL_PILOT_1.1_RESULTS.json)
enthalten nur freigegebene Namen, Konfiguration und Messwerte.

## Originalmodelle und Umgebung

Die Originalgewichte wurden geladen; keine Neugewichtung, kein Training und
keine Änderung der Netzarchitektur. Die offizielle CPU-RoMa-Implementierung
wird ohne CUDA-Erweiterung mit ihrem Torch-Fallback verwendet. Der gedrehte
IXUS-Eingang benötigt eine zusammenhängende Arraykopie für `torch.from_numpy`;
das ändert keine Pixel. Der erste Versuch ohne diese Kopie wurde korrigiert
und für IXUS erfolgreich wiederholt.

- Linux x86-64, Python 3.12.14, PyTorch 2.9.1+cpu, torchvision 0.24.1+cpu,
  OpenCV 4.13.0, NumPy 2.4.6, Pillow 12.2.0, Kornia 0.8.2, einops 0.8.1.
- Vier Torch-/OpenCV-Threads, acht CPU-Kerne als Containerquote, insgesamt
  acht GiB Speicherlimit. Keine CUDA-/MPS-GPU verfügbar.
- LightGlue: `eb42fee2d71449efb0aa5c10549752b5d75384d8`.
- RoMa v2: `95c9968145c8906b7b59383258e9f73b02853d89`, Gewichte v2.0.1.
- DINOv3-Code: `adc254450203739c8149213a7a69d8d905b4fcfa`.
- ALIKED-Gewichte `aliked-n16`, Originalrepository
  `683d7c65197395c0b3f01ebe76e1084a27e73a65`.
- Größen und SHA-256 aller Gewichte stehen in der Ergebnisdatei. RoMas
  Checkpoint umfasst rund 1,10 GB; LightGlue-Matcher je rund 47,6 MB, ALIKED
  zusätzlich rund 2,74 MB. Das sind keine kompletten Installationsgrößen.

LightGlue verwendet bis zu 4096 Merkmale und 1536 Pixel lange Eingabeseite.
Die Autoren-SIFT-Extraktion enthält RootSIFT und andere Detektoreinstellungen
als StereoFines bisheriger SIFT-Pfad. Dieser Pilot vergleicht daher komplette
Kombinationen, nicht ausschließlich zwei Matcher an identischen Deskriptoren.
RoMa `fast` verwendet 512×512, eine Richtung und 5000 räumlich ausgewogene
Stichproben. `precise` verwendet 800×800 und zusätzlich 1280×1280 mit beiden
Richtungen. Die Modi haben bewusst unterschiedliche Ressourcenprofile.

## Bewertung ohne Vertrauen auf Netz-Konfidenz allein

Die neuralen Punkte werden in das unveränderte 3000-Pixel-Analysesystem
überführt. Vertikales RANSAC, vorhandene Modellwahl, Punkterholung und begrenzte
kubische Prüfung bleiben aktiv. Horizontale Szenentiefe ist kein Fit-Ziel.

Daneben werden Merkmale auf den ursprünglichen Graubildern gesucht und mit
pyramidalem LK vorwärts/rückwärts verfolgt, mit NCC ≥0,90 geprüft. Diese Punkte
sind keine Fit-Eingabe für den Kandidaten. Für denselben Bildfall werden die
**identischen** Kontrollidentitäten mit RC3-SIFT und jedem Kandidaten bewertet.
Es sind separate Bildmessungen, keine manuell vermessene Ground Truth; ähnliche
Bildstrukturen, Verdeckungen oder Bewegung können auch diese Prüfung täuschen.

Zusätzlich werden sämtliche Kandidaten in voller Auflösung gerendert,
Nahpunkt und automatischer Beschnitt neu berechnet und räumlich verteilte
5×5-Rasterkontrollen vorgenommen. Alle acht RC3-SIFT-Referenzrender werden
mit derselben Rasterprobe kontrolliert. Diese nach dem Render neu ermittelten
Punktmengen können sich unterscheiden und sind von der Prüfung identischer
Quellpunkte getrennt zu betrachten. Leere/schwach belegte Ecken bestehen keinen
Genauigkeitsnachweis. P95 verschiedener Kontrollverfahren ist nicht austauschbar.

## Höhenfehler an identischen Quell-Kontrollpunkten

P95 in Vollauflösungspixeln; kleiner ist besser. Hier zunächst die Rohmatches
vor zusätzlicher lokaler LK-Nachmessung. Vollständige Varianten und tatsächliche
Rasterproben stehen in der maschinenlesbaren Ergebnisdatei.

| Paar | SIFT RC3 | ALIKED + LightGlue | SIFT + LightGlue | RoMa fast |
|---|---:|---:|---:|---:|
| S110 bild005 | 1,055 | 1,101 | 1,072 | nicht gemessen |
| S110 bild026 | 0,989 | 1,143 | 1,881 | 1,024 |
| S110 bild090 | 0,768 | 0,722 | 1,057 | 0,996 |
| IXUS bild008 | 0,682 | 0,686 | 0,686 | 0,906 |
| S95 bild038 | 1,354 | 0,904 | 1,539 | 0,969 |
| S95 bild067 | 0,278 | 0,317 | 0,284 | 0,371 |
| NX1000 bild033 | 2,281 | 1,682 | 1,617 | 5,277 |
| NX1000 bild045 | 0,919 | 0,890 | 0,917 | nicht gemessen |

Belegte Aussagen aus diesem kleinen Pilot:

- ALIKED + LightGlue verbessert die schwierige S95-Dämmerungsaufnahme bild038
  deutlich. Die neue Rasterprobe bestätigt den Gewinn ebenfalls. Das ist ein
  konkreter Nutzen, aber kein allgemeiner Sieg über SIFT.
- Bei bild026 ist der SIFT-LightGlue-Rohkandidat deutlich schlechter. Bei bild005
  besteht kein belegter Gewinn. Gute bisherige Ergebnisse müssen deshalb
  erhalten bleiben; Netz-Konfidenz allein ist keine Übernahmeentscheidung.
- Zusätzliche lokale LK-Nachmessung ist ebenfalls kein universeller Gewinn:
  SIFT + LightGlue/NX1000 bild045 erreicht P95 0,504 statt 0,919 px der Referenz;
  bei NX1000 bild033 verschlechtert dieselbe Kombination P95 auf 2,540 px.
- RoMa fast/NX1000 bild033 verbessert sich durch Patch-/Rückprüfung und lokale
  Nachmessung von 5,277 auf 1,935 px, bei unveränderter Referenz 2,281 px.
  Seine Rohzuordnungen allein wären hier eine klare Verschlechterung.
- Der äußerste untere rechte bild090-Rand bleibt schwach belegt und fehlerhaft.
  ALIKED-LightGlue/Rohkandidat: 1,910 px mittlerer Rest bei fünf Rasterpunkten;
  RC3-SIFT: 1,857 px bei sechs Punkten. SIFT-LightGlue verbessert diese kleine
  Probe, verschlechtert dabei aber globale Größen. Der Pilot belegt keine
  durchgängige Behebung dieses Randproblems.
- Die Rasterprobe findet bei NX1000 bild033 große obere Abweichungen; der
  herkömmliche globale Kontrollpunktesatz erfasst diese schwächer. Deshalb
  werden räumliche Rasterwerte und Quell-Kontrollwerte getrennt ausgegeben.
  Ohne Ground Truth ist aus diesen Proben keine sichere Ursachenentscheidung
  zwischen Justagefehler, problematischer Korrespondenz und Bewegung möglich.

Eine Überlegenheit gegenüber Cosima oder StereoPhoto Maker wurde nicht
vermessen. Weder deren interne Verfahren noch deren Ergebnisse auf diesem
Satz wurden hier geprüft. Der nachgewiesene Vorteil ist motivabhängig.

## CPU/GPU und Laufzeitgrenzen

Beide LightGlue-Kombinationen sowie RoMa fast haben auf CPU erfolgreich
Originalbilder verarbeitet. Für StereoFine ist deshalb kein allgemeiner
GPU-Zwang erforderlich. Ein optionaler neuronaler Pfad könnte GPU nutzen und
den bisherigen klassischen CPU-Pfad erhalten.

Die ersten Inferenzzeiten liegen bei LightGlue ungefähr bei 17–83 Sekunden
und RoMa fast bei 31–164 Sekunden je Paar. Diese Werte sind **keine saubere
Geschwindigkeitsrangliste**: Modelle und Auswertungen liefen zeitweise
parallel. Sie schließen das initiale Laden/Herunterladen nicht ein. Es gibt
keinen gemessenen GPU-Faktor und keine Hochrechnung auf Christophs RTX 3060.

Der `precise`-OOM-Versuch belegt eine Grenze dieser 8-GiB-Umgebung unter der
gewählten Ausführung. Er bestimmt keine allgemeine minimale RAM-/VRAM-Anforderung.
Für einen produktiven RoMa-Präzisionsmodus sind GPU- und Speicherprüfung nötig.
Verschiedene Backends können andere Laufzeit-, Speicher- und Rundungseigenschaften
haben. Ein CPU-Fallback benötigt eine passende, separat geprüfte Konfiguration.

## Konsequenz für die Entwicklung

ALIKED + LightGlue ist als zusätzlicher 1.1-Kandidat interessant; ein automatischer
Ersatz des bisherigen Matchings ist nicht gerechtfertigt. Eine Produktintegration
braucht gemeinsame räumlich zurückgehaltene Prüfpunkte gegen den bisherigen
Stand, Randkontrollen, sichere Rückfälle und einen breiteren Bildbestand.
RoMa fast bleibt eine Gegenprobe; der präzise Modus ist hier nicht freigeprüft.
Die vorhandene Geometriemodellierung wird durch mehr Matches nicht automatisch
zu einer vollständigen Objektivkalibrierung. Lizenzen sämtlicher verwendeter
Modelle/Gewichte und Offline-Paketierung sind vor einer Integration zu prüfen.

Die **1.0-Wartungsfassung bleibt davon getrennt**. Ihr Build-Commit ist
`ee9c9007978b53f43881a21fcde229fcf3896056`; 101 Tests, DE/EN-GUI-Prüfung und alle
vier Plattformjobs sind erfolgreich. Alle vier heruntergeladenen Archive wurden
zusätzlich auf kanonische Quellbytes, Original-Assets, Binärformat/Architektur
und ExifTool 13.59 geprüft. [Paketprüfdaten](MAINTENANCE_1.0_BUILD_CHECKS.json).
[Buildlauf und Downloads](https://github.com/muelli1975/StereoFine/actions/runs/39429618817).
Die bisherige 1.0-Veröffentlichung wurde nicht überschrieben. Der Wartungsbuild
enthält die belegten Datei-/TIFF-/Seitenverhältnis-Korrekturen und exakten
Beschleunigungen; die weitergehende Geometrie-/Nahpunktüberarbeitung bleibt
im 1.1-Zweig. Die praktische Windows-Prüfung des Wartungsbuilds steht aus.

## Reproduktion

Die eigenständigen Forschungsprogramme liegen unter `experiments/` und werden
von StereoFine nicht importiert. Die Gewichte und fremden Source-Checkouts
werden nicht in Programmarchive aufgenommen. Das Testprogramm kann öffentliche
Originalgewichte nachladen; die produktive Anwendung bleibt vollständig offline.

```sh
python experiments/neural_matches.py lightglue_aliked \
  --manifest /private/cases.json --output /private/results \
  --lightglue-source /private/LightGlue --roma-source /private/RoMaV2 \
  --cache /private/model-cache \
  --names s110_bild090_SIFT s95_bild038_SIFT ixus_bild008_SIFT \
  nx1000_bild033_SIFT s110_bild026_SIFT s95_bild067_SIFT \
  nx1000_bild045_SIFT s110_bild005_SIFT
python experiments/evaluate_neural_matches.py /private/results
```

Dasselbe für `lightglue_sift`, `roma_fast` bzw. `roma_precise`. Für gleiche Fälle
`--names` ausdrücklich setzen; unterschiedliche voreingestellte Fallbudgets
sind kein gepaarter Vollvergleich. Manifest: die privaten Fälle aus dem
RC3-Diagnosetreiber mit `name`, `left`, `right`, `state`, wobei `name` auf `_SIFT`
endet und `state` einen vollständigen gespeicherten PairState-Diagnosezustand
enthält. Bestehende Ergebnisse werden übersprungen. Das entspricht einem
Pilot-Treiber, keinem neuen öffentlichen StereoFine-Eingabeformat.
