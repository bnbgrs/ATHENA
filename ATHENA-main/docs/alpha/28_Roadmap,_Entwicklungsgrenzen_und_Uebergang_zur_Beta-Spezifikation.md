# Kapitel 28 – Roadmap, Entwicklungsgrenzen und Übergang zur Beta-Spezifikation

---

## Einleitung

ATHENA_ALPHA definiert die langfristigen Architekturprinzipien des Projekts. Sie beantwortet, was ATHENA sein soll und welche Systemgrenzen zukünftige Implementierungen respektieren müssen.

Die konkrete technische Umsetzung gehört in die Beta-Spezifikation.

## Grundprinzip

> **Alpha definiert Vision, Systemgrenzen und unveränderliche Prinzipien. Beta definiert die konkrete Umsetzung.**

Technische Einzelentscheidungen dürfen die langfristige Architektur nicht rückwirkend bestimmen.

## Status der Alpha-Phase

Mit Abschluss der Alpha gelten insbesondere folgende Bereiche konzeptionell definiert:

- Identität und Benutzerhoheit
- Systemarchitektur und Core-Prinzip
- Wissenssystem und Roharchiv
- Wissensextraktion und Provenienz
- Primärmodell und Infrastrukturmodelle
- persönliches Gedächtnis
- Suche und Kontextmanagement
- externe Informationsquellen und Privacy-Prinzipien
- Nachrichten- und Ereignissystem
- Hintergrunddienste und Aufgabenverwaltung
- persistente Speicherung, Synchronisation und Portabilität
- Sicherheit, Backup und Recovery
- Benutzeroberflächen und Mehrgerätezugriff
- Update-, Plugin- und Kompatibilitätsprinzipien
- Audit, Datenlebenszyklus und Wissensqualität
- Performance- und Ressourcenprinzipien
- langfristig lesbare Datenformate

## Was Alpha bewusst nicht festlegt

Alpha legt insbesondere nicht dauerhaft fest:

- konkrete Programmiersprachen
- konkrete Frameworks
- konkrete Datenbankprodukte
- konkrete Modellnamen oder Modellversionen
- Quantisierungen oder Samplingparameter
- konkrete GPU-, CPU-, RAM- oder VRAM-Anforderungen
- konkrete Modellserver oder Anbieter
- konkrete Installationspfade
- konkrete API-Endpunkte
- konkrete Tabellen-, Klassen- oder Dateischemata
- konkrete UI-Technologien

Diese Entscheidungen gehören in Beta und dürfen sich verändern, solange sie Alpha einhalten.

Alpha darf zur Erläuterung eines Prinzips **nicht-normative Beispiele oder geplante Referenzoptionen** nennen. Eine solche Nennung begründet keine technische Abhängigkeit; die verbindliche Auswahl und konkrete Integration erfolgt in Beta.

## Referenzimplementierung

Beta darf eine konkrete Referenzplattform, Referenzhardware und konkrete Modelle definieren. Diese sind Implementierungsprofile und keine unveränderlichen Bestandteile von ATHENA_ALPHA.

Ein späterer Wechsel von Hardware, Modell, Modellserver, Datenbank oder Framework verletzt Alpha daher nicht, sofern die normativen Systemgrenzen erhalten bleiben.

## Grenzen der ersten implementierten Version

Die erste implementierte Version soll die Alpha-Kernprinzipien in einem möglichst kleinen, überprüfbaren System realisieren. Funktionen dürfen schrittweise ergänzt werden.

Nicht jede langfristig vorgesehene Fähigkeit muss bereits in der ersten lauffähigen Version vorhanden sein. Entscheidend ist, dass frühe technische Entscheidungen spätere Alpha-konforme Erweiterungen nicht unnötig blockieren.

## Entwicklungslogik

Die weitere Entwicklung folgt grundsätzlich:

```text
ATHENA_ALPHA
      │
      ▼
Beta-Spezifikation
      │
      ▼
Implementierung
      │
      ▼
Tests gegen Alpha und Beta
      │
      ▼
Versionierte Releases
```

Implementierungserfahrungen dürfen zu Änderungen der Beta-Spezifikation führen. Änderungen an Alpha erfolgen dagegen nur bewusst und als neue Alpha-Version, nicht stillschweigend durch Code.

## Übergang zur Beta

Die Beta-Spezifikation konkretisiert insbesondere:

- Datenmodell und Persistenz
- Schnittstellen zwischen Modulen
- Job- und Queue-System
- Retrieval und Indexierung
- Modelladapter und Modellprofile
- Sicherheitsmechanismen
- Verschlüsselung und Schlüsselverwaltung
- Backup- und Restore-Verfahren
- Netzwerk- und Privacy-Implementierung
- Desktop- und spätere Client-Architektur
- Ressourcenmanagement
- Tests, Migrationen und Release-Prozess

Jede Beta-Entscheidung muss auf ihre Vereinbarkeit mit Alpha geprüft werden.

## Änderungsregel

Eine technische Schwierigkeit ist kein ausreichender Grund, ein Alpha-Prinzip stillschweigend zu umgehen.

Falls eine Alpha-Regel tatsächlich geändert werden soll, muss dies als bewusste Änderung der Alpha-Spezifikation versioniert und dokumentiert werden.

## Leitregel

> **Alpha ist der Architekturvertrag. Beta ist der technische Bauplan. Die Implementierung folgt beiden und ersetzt keinen von ihnen.**
