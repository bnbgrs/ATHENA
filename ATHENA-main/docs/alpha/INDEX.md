# ATHENA Alpha – Dokumentindex

**Version:** ATHENA_ALPHA v2.0.1 FINAL
**Status:** Final – Konsistenzpatch v2.0.1; eingefrorener Alpha-Architekturstand

## Normative Hierarchie

1. **Kapitel 1–2:** oberste Prinzipien.
2. **Kapitel 3–27:** normative Detailarchitektur.
3. **Kapitel 28:** Scope, Entwicklungsgrenzen und Übergang zur Beta-Spezifikation.
4. **Kapitel 29:** nicht-normative Zusammenfassung.

Bei einem Konflikt gilt die spezifischere normative Regel aus Kapitel 3–28, sofern sie den obersten Prinzipien aus Kapitel 1–2 nicht widerspricht. Widersprüche werden ausdrücklich bereinigt und niemals stillschweigend durch Implementierungsentscheidungen aufgelöst.

## Dateinamen

Repository-Dateinamen verwenden bewusst ASCII-Transliteration (`ae`, `oe`, `ue`, `ss`). Die Inhalte bleiben UTF-8 mit normalen deutschen Zeichen. Dadurch bleiben Git-, ZIP-, Shell- und Uploadpfade portabel und `#U00...`-Escapes werden vermieden.

## Kapitel

- [Kapitel 1 – Vorwort, Vision und Identität](01_Vorwort_Vision_Identitaet.md)
- [Kapitel 2 – Philosophie und Leitprinzipien](02_Philosophie_und_Leitprinzipien.md)
- [Kapitel 3 – Systemarchitektur](03_Systemarchitektur.md)
- [Kapitel 4 – Das Wissenssystem](04_Wissenssystem.md)
- [Kapitel 5 – Roharchiv und Quellenmanagement](05_Roharchiv_und_Quellenmanagement.md)
- [Kapitel 6 – Wissensextraktion und Wissensgraph](06_Wissensextraktion_und_Wissensgraph.md)
- [Kapitel 7 – Primärmodell und Infrastrukturmodelle](07_Das_Primaermodell_und_die_Infrastrukturmodelle.md)
- [Kapitel 8 – Persönliches Gedächtnis](08_Persoenliches_Gedaechtnis.md)
- [Kapitel 9 – Suchsystem und Wissensabruf](09_Suchsystem_und_Wissensabruf.md)
- [Kapitel 10 – Internet, Anonymisierung und externe Informationsquellen](10_Internet_Tor_und_externe_Informationsquellen.md)
- [Kapitel 11 – Das Nachrichten- und Ereignissystem](11_Das_Nachrichten_und_Ereignissystem.md)
- [Kapitel 12 – Hintergrunddienste, Scheduler und Aufgabenverwaltung](12_Hintergrunddienste_Scheduler_und_Aufgabenverwaltung.md)
- [Kapitel 13 – Datenspeicherung, Synchronisation und Portabilität](13_Datenspeicherung_Synchronisation_und_Portabilitaet.md)
- [Kapitel 14 – Sicherheit, Datenschutz und Vertrauensmodell](14_Sicherheit_Datenschutz_und_Vertrauensmodell.md)
- [Kapitel 15 – Backup, Wiederherstellung und Katastrophenschutz](15_Backup_Wiederherstellung_und_Katastrophenschutz.md)
- [Kapitel 16 – Desktop-Anwendung und Benutzeroberfläche](16_Desktop_Anwendung_und_Benutzeroberflaeche.md)
- [Kapitel 17 – Update-, Versions- und Kompatibilitätsstrategie](17_Update-_Versions-_und_Kompatibilitaetsstrategie.md)
- [Kapitel 18 – Plugin- und Erweiterungssystem](18_Plugin-_und_Erweiterungssystem.md)
- [Kapitel 19 – Audit, Provenienz und Nachvollziehbarkeit](19_Audit_Provenienz_und_Nachvollziehbarkeit.md)
- [Kapitel 20 – Datenlebenszyklus, Aufbewahrung, Archivierung und Löschung](20_Datenlebenszyklus_Aufbewahrung_Archivierung_und_Loeschung.md)
- [Kapitel 21 – Modellfreiheit, Inhaltsneutralität und robuste Wissensverarbeitung](21_Modellfreiheit_Inhaltsneutralitaet_und_robuste_Wissensverarbeitung.md)
- [Kapitel 22 – Kontextmanagement, Gespräche und Kontinuität](22_Kontextmanagement,_Gespraeche_und_Kontinuitaet.md)
- [Kapitel 23 – Wissensqualität, Konsistenz und Selbstwartung](23_Wissensqualitaet,_Konsistenz_und_Selbstwartung.md)
- [Kapitel 24 – Performance, Skalierbarkeit und Ressourcenmanagement](24_Performance,_Skalierbarkeit_und_Ressourcenmanagement.md)
- [Kapitel 25 – Datenformate, Obsidian und langfristige Lesbarkeit](25_Datenformate,_Obsidian_und_langfristige_Lesbarkeit.md)
- [Kapitel 26 – Mobile Zukunft und Mehrgerätezugriff](26_Mobile_Zukunft_und_Mehrgeraetezugriff.md)
- [Kapitel 27 – Recovery Mode, Selbstdiagnose und Fehlerbehandlung](27_Recovery_Mode,_Selbstdiagnose_und_Fehlerbehandlung.md)
- [Kapitel 28 – Roadmap, Entwicklungsgrenzen und Übergang zur Beta-Spezifikation](28_Roadmap,_Entwicklungsgrenzen_und_Uebergang_zur_Beta-Spezifikation.md)
- [Abschluss – Unveränderliche Leitregeln von ATHENA](29_Abschluss_unveraenderliche_Leitregeln.md)

## Begleitdokument

- [Konsolidierungsänderungen v2.0](CHANGES_ALPHA_v2.0.md)
- [Konsistenzpatch v2.0.1](CHANGES_ALPHA_v2.0.1.md)

## Freeze-Regel

Diese Fassung ist der eingefrorene Alpha-Stand und wird als `alpha-v2.0.1-final` versioniert. Spätere Änderungen an Alpha erfolgen nur bewusst, versioniert und mit dokumentierter Begründung. Implementierungsdetails gehören in `docs/beta/`.
