# StereoFine 1.1 – Testbuild RC3

Dieser Build ist eine Vorabversion zum Prüfen der überarbeiteten Justage.
Die reguläre 1.0 bleibt separat verfügbar.

- Verbesserte automatische Modellwahl mit robusten und räumlich verteilten
  Prüfungen; vollständige Korrekturketten werden miteinander verglichen.
- Erneute Auswahl bildlich bestätigter Punktpaare bei Restverzeichnung.
  Ganze Bildblöcke prüfen die Neuberechnung, ohne sie selbst zu trainieren.
- Zusätzliche begrenzte kubische Höhenkorrektur für glatte Restfehler an den
  Bildrändern. Sie benötigt bildlich bestätigte Punkte und Verbesserungen an
  zurückgehaltenen Bildblöcken; die äußeren Ecken werden gesondert geschützt.
  Dies ist keine vollständige Objektivkalibrierung.
- Nahpunktprüfung berücksichtigt kleine echte Vordergrundflächen und die
  bisherigen breiten Messlücken an den Bildrändern. Extreme Kandidaten werden
  durch eindeutige gegenseitige Bildvergleiche und benachbarte Punkte geprüft.
- Schnellere exakte SIFT-Zuordnung; Vergleich mit dem bisherigen Verfahren
  verwendet dieselben Punktpaare, ohne Näherungssuche.
- TIFF-Ausrichtung bei 8/16 Bit korrigiert. Alte automatische Berechnungen
  werden erneuert; manuelle Werte und Favoriten bleiben erhalten.
- Frühere Korrekturen zu Original-Seitenverhältnis und Namenskollisionen sowie
  ergebnisgleiche Beschleunigungen bei Farbe und gültigem Beschnitt enthalten.

Die Bedienung und die Ampelgrenzen bleiben erhalten. Durch die vollständigere
Erkennung naher Flächen können Nahpunkt und gesamter Disparitätsumfang andere,
größere Werte als in 1.0 ergeben. Unsichere Messungen bleiben als solche markiert.

Geprüft an elf echten Paaren (sieben Canon S110, vier Canon IXUS 100 IS) mit
AKAZE und SIFT, zusätzlich automatische Regressionen und Plattform-Builds.
Bei den vier gelieferten IXUS-Paaren ist die Eingabedrehung links auf 180° zu
stellen: Die Pixel sind kopfstehend gespeichert, EXIF meldet dennoch normal.
Die Nahpunktmessung von IXUS/bild008 bleibt in beiden Verfahren unsicher.
Lokale Restfehler sind weiterhin möglich; der RC ersetzt noch nicht die
praktische Prüfung auf Christophs Windows-Rechner.

Die Archive enthalten den genauen Quellstand unter `Source/`. Programme lokal
aus einem entpackten Ordner starten; vorhandene 1.0-Installation separat halten.

RC3 korrigiert gegenüber RC1/RC2 ausschließlich Versionierung und Paketierung:
Die Quellkopie wird vor PyInstaller gesichert und stammt aus einem sauberen
Checkout. Die Dateien werden direkt aus den gespeicherten Git-Blobs gelesen;
dadurch bleiben auch unter Windows die kanonischen Dateibytes erhalten.
Alle Plattformen prüfen die vollständige Quellkopie vor der Archivierung.
Die Bildverarbeitung entspricht dem an elf Paaren geprüften RC1-Stand.

Das [Bildprüfprotokoll](https://github.com/muelli1975/StereoFine/blob/development/1.1/docs/VALIDATION_1.1_RC1.md)
gilt weiterhin für diesen unveränderten Verarbeitungsstand.
