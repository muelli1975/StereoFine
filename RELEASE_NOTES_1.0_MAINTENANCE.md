# StereoFine 1.0 – Wartungsstand vom 20. Oktober 2026

Getrennter Wartungsbuild zur praktischen Prüfung. Der bisherige Release v1.0
und die 1.1-RC3-Pakete werden nicht überschrieben.

- „Original“ erhält bei Justage und Ausgabe das Seitenverhältnis der orientierten
  Eingabebilder statt des bereits verkleinerten gemeinsamen Ausschnitts.
- Gleichnamige Eingaben, die dieselbe Ergebnis-/Sidecar-Datei belegen würden,
  werden vor der Verarbeitung mit verständlicher Meldung erkannt.
- TIFF-Ausrichtung wird nicht doppelt angewendet. Alle EXIF-Ausrichtungen sind
  für 8/16 Bit und verschiedene Kanallayouts/Kompressionen geprüft. Veraltete
  automatische Analysen werden verworfen; explizite Bearbeitungswerte und
  Favoriten unveränderter Quellen bleiben erhalten.
- Integer-Farbtransfer und die Bestimmung des gemeinsamen gültigen Rechtecks
  sind beschleunigt, bei identischem Ergebnis.
- SIFT verwendet eine speicherbegrenzte exakte Distanzberechnung für die
  quantisierten OpenCV-Deskriptoren. Derselbe Ratio-Test, dieselben Matches;
  für andere Deskriptorformate bleibt der bisherige Matcher erhalten.
- Windows-Dokumentation verwendet den tatsächlichen Archivnamen
  `StereoFine_1.0_Windows_x64.zip`; Programmordner `StereoFine` und
  Programmdatei `StereoFine.exe` sind ohne Versions-/Architekturzusatz.
- Plattformpakete enthalten einen vor dem Build gesicherten, gegen rohe
  Git-Blobs geprüften Quellstand, auch bei Windows-Zeilenenden.

Die Justagemodelle, ihre Auswahl und die Nahpunktberechnung entsprechen
weiterhin 1.0. Die weitergehenden Justage-/Nahpunktänderungen der 1.1-Vorabversion
sowie experimentelle Subpixel-, LightGlue- und RoMa-Verfahren sind nicht enthalten.
Bekannte Grenzen bei schwierigen Randbereichen und der Nahpunktbestimmung
sind damit nicht pauschal beseitigt. Bedienung, Regler, Originalgrafiken und
CPU-Betrieb bleiben erhalten; zusätzliche Modelle oder GPU werden nicht benötigt.

Dieser Build wird zunächst als Actions-Artefakt zur Prüfung angeboten. Eine
allgemeine Zusicherung fehlerfreier Justage beliebiger Motive ist damit nicht
verbunden; die praktische Windows-Prüfung ist gesondert vorzunehmen.
