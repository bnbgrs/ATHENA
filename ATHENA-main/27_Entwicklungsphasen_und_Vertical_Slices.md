# ATHENA Beta Specification v0.1 – Kapitel 27

## Entwicklungsphasen und Vertical Slices

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Repository:** [Beta Kapitel 25](25_Repository_und_Code-Struktur.md)
**Tests:** [Beta Kapitel 26](26_Teststrategie.md)

---

## Teil I – Entwicklungsprinzip

### 1. Ziel

ATHENA wird nicht als monolithischer Big-Bang gebaut. Die Implementierung erfolgt in vertikalen Slices, die jeweils einen echten End-to-End-Nutzen liefern und durch Tests abgesichert werden.

---

### 2. Vertical Slice

Ein Slice durchquert:

```text
UI/API
→ Core
→ Domain
→ Storage
→ Tests
```

statt zuerst monatelang isolierte Infrastruktur ohne nutzbaren Pfad zu bauen.

---

### 3. Spec before Code

Alpha bleibt gefroren. Beta-Kapitel bilden technische Leitplanken. Implementierung kann Detailfeedback liefern, aber Abweichungen werden bewusst dokumentiert.

---

### 4. Small Commits

Jeder Slice wird in kleine testbare Commits zerlegt.

---

## Teil II – Phase 0 Repository

### 5. Ziel

Entwicklungsgrundlage ohne Produktlogik.

---

### 6. Deliverables

- `pyproject.toml`;
- src layout;
- test layout;
- CI;
- version module;
- basic CLI/launcher;
- logging skeleton.

---

### 7. Gate

Clean checkout kann installieren, Tests laufen, leeres Corepackage startet.

---

## Teil III – Slice 1 Chat Persistence

### 8. Goal

Erster echter ATHENA-Pfad:

```text
Core starten
→ lokalen Model Provider erkennen
→ Chat erstellen
→ Nachricht senden
→ Antwort streamen
→ Chat speichern
→ Core neu starten
→ Chat wieder laden
```

---

### 9. Storage

Minimal nötig:

- actors;
- chats;
- messages;
- revisions;
- commit records;
- provenance/audit basics.

---

### 10. UI

Einfache Desktop Chatansicht oder zunächst API-Testclient plus minimale UI.

---

### 11. No Knowledge Yet

Noch keine automatische Wissensextraktion.

---

### 12. Gate

Restart verliert keine bestätigte Nachricht; Cancel erzeugt keinen falschen completed state.

---

## Teil IV – Slice 2 Knowledge Extraction

### 13. Goal

```text
Chat
→ Extraction Job
→ Primary Model structured output
→ KnowledgeUnit/Claim
→ Provenance
→ spätere Suche
→ Antwort mit Knowledge
```

---

### 14. User Write

Parallel muss direkter Benutzerwrite ohne ModelSignature funktionieren.

---

### 15. Gate

Userkorrektur, ModelSignature, Source/Message Provenienz und Revision Conflict getestet.

---

## Teil V – Slice 3 File Import

### 16. Goal

```text
Datei auswählen
→ Blob Store
→ Source
→ Text Representation
→ Anchors/Chunks
→ Search
→ Knowledge Extraction
```

---

### 17. Formats

Beginnen mit:

- TXT/Markdown;
- PDF mit nativem Text.

Danach weitere Formate/OCR.

---

### 18. Gate

Parserfehler verliert Original nicht; großer Import streamt.

---

## Teil VI – Slice 4 Search

### 19. Goal

FTS5 → Embeddings → HNSW → Hybrid Retrieval → Context Builder.

---

### 20. Order

Zuerst lexical search, dann vector, dann hybrid.

---

### 21. Gate

Derived State komplett löschen → rebuild → gleiche canonical IDs.

---

## Teil VII – Slice 5 Context Builder

### 22. Goal

Conversation + Personal Memory + Knowledge + Source Evidence unter realem Tokenbudget.

---

### 23. Gate

Kein Context overflow, Current User Instruction überschreibt Memory, Prompt Injection bleibt Data.

---

## Teil VIII – Slice 6 Personal Memory

### 24. Goal

Explizites:

```text
Merke dir ...
```

plus Memory View und Contextintegration.

---

### 25. Later

Automatische Memory Suggestions erst nach stabilem explizitem Memory.

---

### 26. Gate

Reset Memory verändert Knowledge/Archive nicht.

---

## Teil IX – Slice 7 Durable Jobs

### 27. Goal

Persistente Queue, Lease, Checkpoint, Retry, Cancel.

---

### 28. Use Case

Reindex-/Importjob als erste reale Jobs.

---

### 29. Gate

Hard kill + restart + idempotent resume.

---

## Teil X – Slice 8 Large Documents

### 30. Goal

Große Dokumente chunkweise verarbeiten, checkpointen und hierarchisch synthetisieren.

---

### 31. Gate

Dokument mehrfach größer als Kontext; kein Overflow; Resume nach Crash.

---

## Teil XI – Slice 9 Exhaustive Research

### 32. Goal

ResearchScope → CandidateSet → Work Units → Coverage → synthesis.

---

### 33. Gate

Snapshot consistency und ehrliche partial coverage.

---

## Teil XII – Slice 10 Resource Manager

### 34. Goal

Admission/Preemption für CPU/RAM/GPU/VRAM/Disk.

---

### 35. Gate

Background inference weicht interaktivem Chat; kein unsafe interruption.

---

## Teil XIII – Slice 11 Offline Archive

### 36. Goal

Archive Root auf NAS/external, lokaler spool, Outbox sync.

---

### 37. Gate

NAS disconnect während Import → kein Datenverlust → später verify sync.

---

## Teil XIV – Slice 12 News

### 38. Goal

External Gateway + Daily News Collector + Sources + Events + Digest.

---

### 39. Gate

Privacy Route fail closed; source comparison; backfill.

---

## Teil XV – Slice 13 Protected Content

### 40. Goal

ProtectionScope, unlock/lock, encrypted blobs/payloads, protected search runtime.

---

### 41. Gate

Protected Canary darf unprotected persistent state nicht erreichen.

---

## Teil XVI – Slice 14 Backup

### 42. Goal

Automatischer Snapshot, Blob dedup, verification, retention.

---

### 43. Gate

Restore Test auf separate Roots erfolgreich.

---

## Teil XVII – Slice 15 Deletion and Restore

### 44. Goal

DeletionMarker + Backup Deletion Ledger + Restore protection.

---

### 45. Gate

Alter Snapshot kann gelöschte Entity bei aktuellem Ledger nicht reaktivieren.

---

## Teil XVIII – Slice 16 Recovery

### 46. Goal

Read-only Safe Mode, integrity checks, derived rebuild, backup restore.

---

### 47. Gate

DB-/FTS-/Pluginfehler-Szenarien bestehen Recoverytests.

---

## Teil XIX – Slice 17 Obsidian

### 48. Goal

Projection Writer + stable IDs + editable roundtrip + conflicts.

---

### 49. Gate

Rename/move/external edit ohne Identitätsverlust.

---

## Teil XX – Slice 18 Plugins

### 50. Goal

Plugin manifest, out-of-process host, capabilities, restricted network.

---

### 51. Gate

Plugincrash/Core survives; no direct DB/secret/network bypass.

---

## Teil XXI – Slice 19 Desktop Completion

### 52. Goal

Knowledge, Memory, Jobs, Models, News, Backup, Security, Diagnostics in polierter Desktop UI + Tray.

---

### 53. Gate

Kernworkflows ohne CLI nutzbar.

---

## Teil XXII – Slice 20 Update System

### 54. Goal

Staged app updates, clone migration, rollback marker.

---

### 55. Gate

Crash during update/migration → recoverable old/new valid state.

---

## Teil XXIII – Beta Milestones

### 56. M0 Foundation

Repository, Core lifecycle, logging, CI.

---

### 57. M1 Persistent Chat

Slice 1 bestanden.

---

### 58. M2 Knowledge Core

Slices 2–6 bestanden.

---

### 59. M3 Durable Automation

Slices 7–11 bestanden.

---

### 60. M4 Connected ATHENA

News/External Access bestanden.

---

### 61. M5 Secure ATHENA

Protected Content + permissions bestanden.

---

### 62. M6 Recoverable ATHENA

Backup/Delete/Recovery bestanden.

---

### 63. M7 Extensible UX

Obsidian, Plugins, vollständige Desktop UI.

---

### 64. M8 Beta Candidate

Update, migrations, full test matrix, installer.

---

## Teil XXIV – Definition of Done pro Slice

### 65. Code

Produktionscode reviewbar und modular.

---

### 66. Tests

Unit + relevante Integration/Recoverytests grün.

---

### 67. Spec

Abweichungen von Beta dokumentiert.

---

### 68. Migration

Wenn Schema betroffen: Migration vorhanden und getestet.

---

### 69. Observability

Fehler-/Healthpfade sichtbar.

---

### 70. Security

Threat-relevante Tests bestanden.

---

### 71. Docs

User-/developer-relevante Dokumentation aktualisiert.

---

## Teil XXV – Branch/Commit Workflow

### 72. Feature Branch

Ein Slice kann aus mehreren Featurebranches bestehen.

---

### 73. Merge

Nur grüne Tests und nachvollziehbare Migrationen nach main.

---

### 74. Tagging

Meilensteine werden getaggt, sobald Gate bestanden.

---

### 75. No Giant AI Commit

AI-generierter Code wird in überprüfbare Module/Commits zerlegt; kein ungeprüfter 50.000-Zeilen-One-Shot.

---

## Teil XXVI – AI-gestützte Entwicklung

### 76. Task Packet

Für einen Codingtask werden geladen:

- relevante Beta-Kapitel;
- betroffene Codefiles;
- Interfaces;
- Tests;
- aktuelle Fehlerlogs.

Nicht das gesamte Repository.

---

### 77. Spec Retrieval

Repoindex verknüpft Module mit Beta-Kapiteln und Tests.

---

### 78. AI Output

AI darf Code vorschlagen/erzeugen; Tests und Git bleiben Nachweis, nicht bloße Modellbehauptung.

---

### 79. User Role

Benutzer muss nicht jede Zeile programmieren können, aber Entscheidungen, Tests und sichtbare Funktionsresultate kontrollieren können.

---

## Teil XXVII – Release Candidate Gate

### 80. Data Safety

Keine offenen bekannten Datenverlust-/Lost-Update-Bugs.

---

### 81. Recovery

Backuprestore, migration rollback, disk full, crash tests bestanden.

---

### 82. Security

Protected leak suite und permission tests bestanden.

---

### 83. Performance

Interaktive Kernpfade innerhalb definierter Zielwerte auf Referenzhardware.

---

### 84. Usability

Chat, Import, Search, Memory, Backup und Recovery über Desktop UI erreichbar.

---

### 85. Docs

Install, Storage, Backup, Protected Content und Recovery dokumentiert.

---

## Teil XXVIII – Was bewusst später kommt

### 86. Mobile Remote Client

Nach stabilem Core/API/Security.

---

### 87. Multi-device Shared Write

Kein v1 Distributed-CRDT-System.

---

### 88. Cloud Sync

Nur bei späterer expliziter Architekturentscheidung.

---

### 89. Alternative DB

Erst bei nachgewiesenem Bedarf.

---

### 90. Advanced Graph Database

Relationale Graphstruktur reicht für v1.

---

### 91. Persistenter encrypted protected vector index

Erst wenn In-Memory-Lösung für reale Protected-Datenmengen nicht ausreicht.

---

## Teil XXIX – Abschluss

### 92. Leitregel

> **ATHENA wird von einem kleinen sicheren End-to-End-Kern nach außen aufgebaut. Jede neue Fähigkeit muss auf dem bereits getesteten Persistenz-, Provenienz-, Security- und Recoveryfundament aufsetzen.**

---

### 93. Beta-Endpunkt

Wenn alle Meilensteine M0–M8 und die Release-Candidate-Gates erfüllt sind, ist die Beta-Spezifikation technisch ausreichend umgesetzt, um einen ersten echten ATHENA-v1-Betakandidaten zu veröffentlichen.

---
