# ATHENA Beta Specification

## Status

**Version:** Beta Specification v0.1
**Status:** Vollständiger konsolidierter technischer Entwurf – Cross-System-Korrekturen eingearbeitet
**Basis:** ATHENA Alpha v2.0.1 Final

Die Beta-Spezifikation übersetzt die Alpha-Prinzipien in eine konkrete technische v1-Architektur.

Alpha definiert **was ATHENA sein soll**. Beta definiert **wie ATHENA technisch umgesetzt wird**.

Die vorliegende Fassung enthält den Konsistenzpatch nach dem vollständigen Repository-Cross-Review. Besonders präzisiert wurden Langzeitspeicher/Replikation, Derived SourceChunks, Protected Metadata/Keys/Operational State, Backup-GC-Pins, temporäre Chats, Lifecycle-Historie und die reale v1-Plugin-Vertrauensgrenze.

---

## Normative Hierarchie

1. **ATHENA Alpha v2.0.1** besitzt höchste Autorität.
2. **Beta Kapitel 01–03** bilden das technische Fundament: Gesamtarchitektur, logisches Datenmodell und physische Persistenz.
3. **Beta Kapitel 04–24** konkretisieren die einzelnen Domänen und Betriebsfunktionen.
4. **Beta Kapitel 25–27** definieren Codeorganisation, Tests und Entwicklungsreihenfolge.

Ein späteres Detailkapitel darf ein in einem früheren Kapitel ausdrücklich offengelassenes `TBD` konkretisieren. Es darf jedoch keine bereits festgelegte Alpha-Regel oder fundamentale Invariante aus Kapitel 01–03 stillschweigend brechen.

Bei einem erkannten Konflikt wird die Spezifikation ausdrücklich korrigiert; die Implementierung darf nicht selbst entscheiden, welche widersprüchliche Regel ignoriert wird.

---

## Dateinamen

Wie Alpha verwendet auch Beta für Repository-Dateinamen ASCII-Transliteration (`ae`, `oe`, `ue`, `ss`). Markdowninhalte bleiben normales UTF-8.

---

## Gesamtumfang

Die Beta-v0.1-Spezifikation besteht aus **27 Kapiteln**.

## Fundament

### 01 – Systemarchitektur und technische Basis

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Core, Module, Providergrenzen, Jobs, Retrieval-Grundprinzipien und v1-Referenzarchitektur.

[01_Systemarchitektur_und_Technische_Basis.md](01_Systemarchitektur_und_Technische_Basis.md)

### 02 – Persistentes Datenmodell und ID-System

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert UUIDv7, Entitäten, Revisionen, Provenienz, Durable Operational State und Derived State.

[02_Persistentes_Datenmodell_und_ID_System.md](02_Persistentes_Datenmodell_und_ID_System.md)

### 03 – Storage, Datenbanken und Migrationen

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Legt SQLite, Blob Store, FTS5, HNSW, Backupformat, Verschlüsselungsstorage und Migrationstechnik fest.

[03_Storage_Datenbanken_und_Migrationen.md](03_Storage_Datenbanken_und_Migrationen.md)

---

## Speicherung und Wissen

### 04 – Quellen, Roharchiv und Import-Pipeline

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Intake, Staging, Sources, Repräsentationen, OCR/STT, Chunking und Import-Resume.

[04_Quellen_Roharchiv_und_Import-Pipeline.md](04_Quellen_Roharchiv_und_Import-Pipeline.md)

### 05 – Wissenseinheiten, Claims und Wissensgraph

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert semantische Wissensbildung, Claims, Evidenz, Relations, Projekte und Concept Notes.

[05_Wissenseinheiten_Claims_und_Wissensgraph.md](05_Wissenseinheiten_Claims_und_Wissensgraph.md)

### 06 – Personal Memory

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Präferenzen, Scopes, sensibles Memory, Learning Modes und Context-Integration.

[06_Personal_Memory.md](06_Personal_Memory.md)

### 07 – Provenienz, Audit und Versionierung

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Herkunft, Modell- und Benutzerprovenienz, Revisionen, Commit-Historie und Auditgrenzen.

[07_Provenienz_Audit_und_Versionierung.md](07_Provenienz_Audit_und_Versionierung.md)

---

## Modelle und Kontext

### 08 – Primärmodell und Provider-System

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert PrimaryModelProvider, InfrastructureProvider, ModelSignature, Laden/Entladen und Refusal-Failsafe.

[08_Primaermodell_und_Provider-System.md](08_Primaermodell_und_Provider-System.md)

### 09 – Context Builder und Token-Budget

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert dynamisches Tokenbudget, Kontextquellen, Injection-Grenzen und hierarchische Verarbeitung.

[09_Context_Builder_und_Token-Budget.md](09_Context_Builder_und_Token-Budget.md)

### 10 – Retrieval und Suche

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert FTS5, Embeddings, HNSW, Hybrid Retrieval, RRF, Graph- und temporale Suche.

[10_Retrieval_und_Suche.md](10_Retrieval_und_Suche.md)

### 11 – Exhaustive Research

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert ResearchScope, Snapshots, CandidateSets, Coverage, Resume und hierarchische Synthese.

[11_Exhaustive_Research.md](11_Exhaustive_Research.md)

---

## Hintergrundsysteme

### 12 – Job-System, Queue und Scheduler

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert persistente Queue, Prioritäten, Leases, Fencing, Retry, Backpressure und Zeitpläne.

[12_Job-System_Queue_und_Scheduler.md](12_Job-System_Queue_und_Scheduler.md)

### 13 – Ressourcenmanagement

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert CPU/RAM/GPU/VRAM/Disk Admission, Preemption, Ressourcenmodi und Benutzerpriorität.

[13_Ressourcenmanagement.md](13_Ressourcenmanagement.md)

### 14 – Nachrichten- und Ereignissystem

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Daily News, Sourcevergleich, Eventbildung, Digests und historischen Backfill.

[14_Nachrichten_und_Ereignissystem.md](14_Nachrichten_und_Ereignissystem.md)

---

## Netzwerk und Sicherheit

### 15 – External Access Gateway und Netzwerkzugriff

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert externe Autorisierung, Privacy Route, Fail-Closed, SSRF-Grenzen und Netzwerk-Audit.

[15_External_Access_Gateway_und_Netzwerkzugriff.md](15_External_Access_Gateway_und_Netzwerkzugriff.md)

### 16 – Sicherheitsarchitektur und Protected Content

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert ProtectionScopes, Keyhierarchie, AES-GCM, Argon2id, Secrets, Lock/Unlock und Prompt-Injection-Schutz.

[16_Sicherheitsarchitektur_und_Protected_Content.md](16_Sicherheitsarchitektur_und_Protected_Content.md)

### 17 – Plugin-System und Berechtigungen

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert PluginHost, Manifest, Capabilities, Netzwerk-/Secretgrenzen und Crash-Isolation.

[17_Plugin-System_und_Berechtigungen.md](17_Plugin-System_und_Berechtigungen.md)

---

## Benutzeroberflächen

### 18 – Desktop-Anwendung und System Tray

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert PySide6-Desktopclient, Chat, Knowledge, Tray, Models, Jobs, Security und Diagnostics.

[18_Desktop-Anwendung_und_System_Tray.md](18_Desktop-Anwendung_und_System_Tray.md)

### 19 – Core API und zukünftige Clients

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert versionierte lokale API, Authentifizierung, Streaming, Commands und zukünftige Remote-Clients.

[19_Core_API_und_zukuenftige_Clients.md](19_Core_API_und_zukuenftige_Clients.md)

### 20 – Obsidian und externe Bearbeitung

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Markdownprojektion, Front Matter, externe Edits, Konflikte und Protected-Grenzen.

[20_Obsidian_und_externe_Bearbeitung.md](20_Obsidian_und_externe_Bearbeitung.md)

---

## Betrieb und Zuverlässigkeit

### 21 – Backup und Restore

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Backupplanung, Retention, Verification, Deletion Ledger und Restore auf neuer Hardware.

[21_Backup_und_Restore.md](21_Backup_und_Restore.md)

### 22 – Recovery Mode und Selbstdiagnose

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Read-only Safe Mode, DB-/Blob-/Migration-Recovery und Diagnoseexport.

[22_Recovery_Mode_und_Selbstdiagnose.md](22_Recovery_Mode_und_Selbstdiagnose.md)

### 23 – Updates, Migrationen und Kompatibilität

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert App-/Schema-/Plugin-/API-Versionierung, staged Updates und Rollback.

[23_Updates_Migrationen_und_Kompatibilitaet.md](23_Updates_Migrationen_und_Kompatibilitaet.md)

### 24 – Logging, Monitoring und Observability

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert strukturierte Logs, Redaction, Metrics, Health, Alerts und Diagnose ohne Schattenarchiv.

[24_Logging_Monitoring_und_Observability.md](24_Logging_Monitoring_und_Observability.md)

---

## Implementierung

### 25 – Repository- und Code-Struktur

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Monorepo, Pythonmodule, UI-, Test-, Schema- und Git-Struktur.

[25_Repository_und_Code-Struktur.md](25_Repository_und_Code-Struktur.md)

### 26 – Teststrategie

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert Unit-, Contract-, Integration-, Security-, Recovery-, Chaos- und Migrationstests.

[26_Teststrategie.md](26_Teststrategie.md)

### 27 – Entwicklungsphasen und Vertical Slices

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren

Definiert die konkrete Entwicklungsreihenfolge von Foundation bis Beta Candidate.

[27_Entwicklungsphasen_und_Vertical_Slices.md](27_Entwicklungsphasen_und_Vertical_Slices.md)

---

## Zentrale v1-Entscheidungen

- modularer lokaler Monolith mit getrenntem Core und Desktop-Client;
- genau ein aktives Primärmodell für automatisierte semantische Wissensentscheidungen;
- Benutzer als höchste semantische Autorität;
- UUIDv7 und immutable Revisionen;
- lokale SQLite-Hauptdatenbank für strukturierten autoritativen Zustand;
- immutable Blob Stores für Originale;
- FTS5 + Embeddings + HNSW als rekonstruierbarer Suchzustand;
- persistente Queue, Checkpoints, Leases, Fencing und Backpressure;
- expliziter Context Builder statt Archivdump;
- Normal Retrieval und Exhaustive Research;
- ExternalAccessGateway mit Privacy Route und Fail-Closed;
- Protected Content mit Argon2id und AES-256-GCM;
- PySide6/Qt 6 als v1-Desktop-UI;
- Obsidian als optionale Projektion, nicht Source of Truth;
- manifestbasierte Backups mit Deletion Ledger;
- Recovery Mode ohne Primärmodell, Plugins, Obsidian oder Internet;
- Vertical-Slice-Entwicklung mit Recovery-/Securitytests als Release-Gates.

---

## Statuswerte

- **Geplant** – vorgesehen, noch nicht ausgearbeitet.
- **In Entwicklung** – wird aktiv bearbeitet.
- **Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren** – alle vorgesehenen Kernpunkte sind spezifiziert und der Cross-System-Review ist eingearbeitet; Implementierungsfeedback kann weiterhin kontrollierte Änderungen erzeugen.
- **Stabil** – für die aktuelle Beta verbindlich und gegen Implementierung validiert.
- **Ersetzt** – durch eine neuere Spezifikation abgelöst.

---

## Nächster Projektschritt

Der nächste sinnvolle Schritt nach diesem vollständigen Beta-v0.1-Entwurf ist **nicht noch mehr Spezifikation ins Blaue hinein**, sondern ein vollständiger Cross-Review und anschließend die Implementierung von **Vertical Slice 0 und 1** aus Kapitel 27.

Nach jedem implementierten Slice werden die betroffenen Beta-Kapitel gegen reale Tests und technische Erkenntnisse nachgeschärft.
