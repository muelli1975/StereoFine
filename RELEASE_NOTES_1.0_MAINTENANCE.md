# StereoFine 1.0 – Wartungsstand vom 20. Oktober 2026

Qualitätsupdate der bestehenden Version 1.0. Versionsnummer, Programmname und
Archivnamen bleiben 1.0; die Downloads des Releases v1.0 werden nach erfolgreichen
Tests und Plattform-Builds aktualisiert. Die 1.1-RC3-Pakete bleiben unverändert.

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

101 automatisierte Tests prüfen den Wartungsstand. Die Veröffentlichung setzt
erfolgreiche Tests, deutsche und englische GUI-Smoke-Tests unter Linux sowie
Windows-, Linux- und beide macOS-Builds voraus. Quellstand und Originalgrafiken
werden in allen vier Paketen vor der Veröffentlichung bytegenau kontrolliert.
Die praktische Windows-Prüfung mit den Originalbildern bleibt gesondert
vorzunehmen; macOS/Linux sind auf echten Desktops weiterhin nicht validiert.

[Windows herunterladen](https://github.com/muelli1975/StereoFine/releases/download/v1.0/StereoFine_1.0_Windows_x64.zip).
Das vollständige Archiv entpacken, den Ordner `StereoFine` öffnen und
`StereoFine.exe` starten. Die enthaltene Datei `Source/SOURCE_COMMIT.txt`
kennzeichnet den genauen Quellstand dieses Builds.

Vorheriger Release-Quellstand: `83e7fb4526df841aaddfc952f27e5b178bd184a9`.
Eine allgemeine Zusicherung fehlerfreier Justage beliebiger Motive ist mit
diesem Qualitätsupdate nicht verbunden.
