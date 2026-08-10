# ATHENA Alpha v2.0.1 – Konsistenzpatch

Dieses Dokument protokolliert ausschließlich Korrekturen am bereits konsolidierten Alpha-v2.0-Architekturstand. Es führt keine neue Produktfunktion ein.

## Normative Korrekturen

- Das Raw Archive wurde präzise als **autoritative historische Quellenbasis** bezeichnet, nicht als alleinige historische Wahrheit aller ATHENA-Domänen.
- Aus Quellen abgeleitetes Wissen muss auf Originalquellen zurückführbar sein; direkt vom Benutzer erzeugtes Wissen wird dagegen auf die originierende Benutzeraktion zurückgeführt und benötigt keine künstliche Source.
- Der Ablauf `Originalquelle → Primärmodell → Knowledge` gilt ausdrücklich für **automatisierte Wissensextraktion aus Quellen**. Direkte Benutzererstellung und Benutzerkorrektur sind ein separater gleichwertiger semantischer Schreibpfad.
- Langzeitspeicher wurde mit der Beta-v1-Transaktionsarchitektur versöhnt: Die logische Autorität von ATHENA Persistent Data ist nicht an eine physische Datei gebunden. Eine lokale transaktionale Datenbank darf den aktiven Zustand materialisieren, während ein NAS/externer `long_term_root` verifizierte versionierte Langzeitreplikationen hält.
- Lokal bestätigte, aber noch nicht langzeitreplizierte Commits bleiben gültiger logischer ATHENA-Zustand und werden als nicht rekonstruierbarer Pending State geschützt.
- „Nicht speichern“ wurde gegenüber einem temporären Chat verschärft: kein persistenter vollständiger Chat-Payload; ausdrücklich daraus gespeichertes Knowledge/Memory bleibt über Benutzeraktions-Provenienz möglich.
- Plugin-Vertrauensgrenze wurde präzisiert: Least-Privilege-Capabilities und Prozessisolation sind nicht automatisch eine OS-Sandbox gegen absichtlich bösartigen lokalen Code. Eine solche Sicherheitsbehauptung benötigt technisch erzwungene Sandboxmechanismen.

## Formale Korrekturen

- Alpha-Status auf `ATHENA_ALPHA v2.0.1 FINAL` vereinheitlicht.
- Repository-Dateinamen verwenden ASCII-Transliteration für Umlaute, um `#U00...`-Escapes und kaputte Git-/ZIP-Links zu vermeiden.
- Interne Links und Index wurden entsprechend aktualisiert.

## Hierarchie

Die normative Hierarchie bleibt unverändert:

1. Kapitel 1–2: oberste Prinzipien.
2. Kapitel 3–27: normative Detailarchitektur.
3. Kapitel 28: normativer Scope und Übergang zur Beta-Spezifikation.
4. Kapitel 29: nicht-normative Zusammenfassung.

Alpha v2.0.1 ersetzt v2.0 als aktuellen finalen Alpha-Stand. `CHANGES_ALPHA_v2.0.md` bleibt als historisches Konsolidierungsprotokoll erhalten.
