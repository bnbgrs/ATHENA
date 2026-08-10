# ATHENA Repository – Konsolidierungs- und QA-Bericht 2026-08-10

**Geprüfter Ausgangsstand:** vom Benutzer hochgeladener Repository-ZIP `ATHENA-main (2).zip`
**Ausgangs-ZIP SHA-256:** `1006d77992fae43f3d4ee532e5fe22af0a0a80ea4867618b7516c471f9e2f808`
**Ergebnis dieser Korrekturrunde:** alle im vorherigen Voll-Audit gefundenen Punkte wurden normativ beziehungsweise technisch aufgelöst.
**Alpha-Stand:** `ATHENA_ALPHA v2.0.1 FINAL`
**Beta-Stand:** `Beta Specification v0.1`, konsolidierter technischer Entwurf, noch nicht eingefroren.

## Ziel der Korrekturrunde

Die Korrektur verändert ATHENAs Produktidee nicht. Sie beseitigt Widersprüche zwischen Alpha und Beta, präzisiert technische Sicherheits- und Persistenzregeln und bereinigt den Repository-Zustand so, dass die Spezifikation als konsistente Grundlage für die Implementierung dienen kann.

Alpha v2.0.1 ist deshalb ein **Konsistenzpatch** auf Alpha v2.0. Beta bleibt v0.1 und soll während der Implementierung weiterhin kontrolliert präzisiert werden.

## Aufgelöste Auditpunkte

| ID | Ursprüngliches Problem | Korrektur | Status |
|---|---|---|---|
| A1 | `#U00...`-Escapes in 16 Dateinamen und gebrochene Links | Alle Repository-Dateinamen auf ASCII-Transliteration (`ae`, `oe`, `ue`, `ss`) normalisiert; sämtliche internen Links angepasst | BEHOBEN |
| A2 | Extensionless Duplikate von Beta 01 und 03 | Duplikate entfernt | BEHOBEN |
| A3 | Paketbezogenes `docs/SHA256SUMS.txt` passte nicht zum Repository | Stales Package-Manifest entfernt | BEHOBEN |
| A4 | Alter 49/49-Package-QA beschrieb nicht den Repository-Zustand | Alten Bericht entfernt; dieser Repository-QA und `scripts/validate_spec.py` ersetzen ihn | BEHOBEN |
| A5 | Alpha gleichzeitig `FINAL`, Freeze-Kandidat und bereit zum Freeze | Aktueller Alpha-Stand einheitlich als `ATHENA_ALPHA v2.0.1 FINAL`; historischer v2.0-Report bleibt ausdrücklich historisch | BEHOBEN |
| A6 | `.gitignore` fehlte | Root-`.gitignore` für DB, Archive, Backups, Secrets, Logs, Caches, Build- und Pythonartefakte ergänzt | BEHOBEN |
| B1 | Alpha/Beta01 erlaubten NAS-Langzeitspeicher, Beta03 band strukturierten Zustand faktisch nur an lokale SQLite | Lokale `athena.db` ist transaktionale aktive Materialisierung; optionaler `long_term_root` hält verifizierte versionierte strukturierte Replikationen; kein Live-SQLite über SMB/NFS; Replication Watermark und Recovery definiert | BEHOBEN |
| B2 | Beta04 erlaubte semantische visuelle Interpretation durch Infrastrukturprozesse | Infrastruktur darf nur technische Repräsentationen erzeugen; kanonische semantische Bedeutung ausschließlich Benutzer oder aktives Primärmodell | BEHOBEN |
| B3 | Alpha05 verlangte Originalquelle für jede Wissenseinheit | Quellenbasierte Ableitungen müssen auf Sources zurückgehen; direktes Benutzerwissen auf originierende Benutzeraktion | BEHOBEN |
| B4 | Alpha06 stellte Source→Primärmodell als universellen Wissenspfad dar | Automatische Quellenextraktion und direkter Benutzer-Schreibpfad ausdrücklich getrennt | BEHOBEN |
| B5 | `SourceChunk` zugleich Raw-Archive-Entität und Derived State | `SourceChunk` eindeutig Derived State; `derived://chunk/...`; langlebige Evidenz verwendet Source/retained SourceRepresentation/SourceAnchor | BEHOBEN |
| C1 | Protected Source-Metadaten konnten im Klartext liegen | `protection_scope_id` und `protected_metadata_payload_id`; sensitive Dateinamen, URIs und Zeitmetadaten verschlüsselt beziehungsweise neutralisiert | BEHOBEN |
| C2 | Protected Hashsemantik nicht für alle content-derived Hashes festgelegt | Globale Regel für Revision-, Representation-, Anchor-, Chunk-, Search- und Embedding-Hashes; kein deterministischer Protected-Klartexthash außerhalb Schutzkontext | BEHOBEN |
| C3 | Physische Keyhierarchie unvollständig | `key_slots`, Root Key, `protection_scope_keys`, `protected_blob_envelopes`, per-object DEKs; v1-Wrapping konkret AES-256-GCM mit 96-Bit-Nonce und AAD | BEHOBEN |
| C4 | Jobs/Checkpoints/Research konnten Protected Klartext leaken | Protection Scope + verschlüsselte Payloads für Jobs, Checkpoints, Pending Writes, Outbox, ResearchScopes und CandidateSets; unprotected Rows nur neutrale Ablaufdaten | BEHOBEN |
| C5 | Nachträgliches Protect/Unprotect nicht vollständig definiert | Resumierbarer `ProtectionTransitionJob` mit Write Guard, Historien-/Metadatenmigration, Derived-State-Purge, Projection-Cleanup, Verifikation und Audit | BEHOBEN |
| C6 | Plugin-Threat-Model behauptete Schutz gegen bösartige Plugins ohne echte Sandbox | v1-Vertrauensmodell ehrlich definiert: Drittplugins sind explizit vertrauter lokaler Code; Prozess-/Capability-Isolation schützt Core/API, nicht vor absichtlich bösartigem OS-Code; hostile-code guarantee erst mit OS-Sandbox | BEHOBEN |
| D1 | Race zwischen Backup-Snapshot und Blob-GC | Persistente `backup_snapshot_pin`-Pins; GC respektiert Pins bis verifiziertem Backup beziehungsweise kontrolliertem Abbruch; expliziter Race-Test ergänzt | BEHOBEN |
| D2 | Lifecycle-/Protection-Zustand nicht historisch rekonstruierbar | `entity_state_history` mit Commitsequenzen; As-of-Retrieval verwendet diese Historie | BEHOBEN |
| E1 | SQLite `application_id` als Text `ATHN` beschrieben | Konkreter 32-Bit-Wert `1096042574` / `0x4154484E`; `ATHN` bleibt menschenlesbare Magic-Bezeichnung | BEHOBEN |
| E2 | `UNIQUE(..., NULL, ...)` bei globaler Configuration nicht eindeutig | Zwei Partial Unique Indexes für globalen und scoped Fall | BEHOBEN |
| E3 | Disk-Full-Schwellen verwendeten `min()` statt beabsichtigter Sicherheitslogik | `max()`-Logik für absolute/relative Mindestreserve | BEHOBEN |
| F1 | `temporary` und `do_not_store` praktisch gleich | `temporary`: begrenzte technische Persistenz mit TTL zulässig; `do_not_store`: kein persistenter vollständiger Chat-Payload, soweit technisch möglich RAM-only | BEHOBEN |
| F2 | `restore_blocking_until` für endgültige Löschung unklar | `NULL` bedeutet unbefristeter Restore-Block; non-null nur für bewusst zeitlich begrenzte Tombstones | BEHOBEN |
| F3 | Persistenter ProtectionScope und Runtime Lockstate vermischt | Persistenter Scope kennt nur Lifecycle wie `active`, `retired`, `pending_delete`; `locked/unlocked_for_session` ausschließlich Runtime-SecurityContext; Recovery startet runtime-locked | BEHOBEN |
| G1 | 112 doppelte Markdown-Trenner in Beta01 | Doppelte `---`-Folgen entfernt; globaler Markdown-Check ergänzt | BEHOBEN |

## Zusätzliche Repository-Bereinigung

- `.gitattributes` ergänzt, damit Markdown/Python/JSON/YAML/TOML/Shell in Git konsistente LF-Zeilenenden verwenden; Windows-Batchdateien dürfen CRLF verwenden.
- `.gitignore` verwendet für Runtime-Verzeichnisse Root-Anker, damit spätere Quellcodemodule wie `src/athena/archive/` und `src/athena/recovery/` nicht versehentlich ignoriert werden; synthetische Migrationstest-DBs können ausdrücklich versioniert werden.
- Root-README verlinkt jetzt sowohl Alpha- als auch Beta-Index und nennt die aktuellen Versionsstände.
- Beta-INDEX und Kapitelstatus sind auf den konsolidierten, noch nicht eingefrorenen v0.1-Zustand vereinheitlicht.
- `CHANGES_ALPHA_v2.0.1.md` dokumentiert den Alpha-Konsistenzpatch.
- `CHANGES_BETA_v0.1.md` dokumentiert den Cross-System-Konsistenzpatch.
- Historisches `CHANGES_ALPHA_v2.0.md` bleibt als ausdrücklich historisches Protokoll erhalten.
- Keine `.gitkeep`-, extensionless Beta-Duplikat- oder stalen Package-QA-Dateien verbleiben.

## Automatisierter Repository-Validator

Der Validator liegt unter:

```text
scripts/validate_spec.py
```

Aufruf aus dem Repository-Root:

```bash
python scripts/validate_spec.py
```

Der aktuelle Lauf prüft unter anderem:

- Dateinamen und Upload-Artefakte;
- Kapitelanzahl und Nummerierung;
- Markdown-H1 und Code-Fences;
- doppelte Trenner und Whitespace;
- alle relativen Markdown-Links;
- Alpha-/Beta-Indexvollständigkeit;
- Versions-/Statuskonsistenz;
- Alpha-Provenienz- und User-Write-Regeln;
- Langzeitreplikation und Network-SQLite-Grenze;
- Derived SourceChunk-Semantik einschließlich URI;
- Protected Metadata, Hashes, Keyhierarchie und Operational State;
- Protection Transition;
- Plugin-Vertrauensmodell;
- Backup-GC-Pins;
- EntityStateHistory und As-of-Abfragen;
- SQLite `application_id`;
- Configuration-UNIQUE/NULL;
- Disk-Full-Schwellen;
- temporäre und nicht gespeicherte Chats;
- Deletion Restore-Block;
- Runtime-Lockstate;
- bekannte alte widersprüchliche Formulierungen.

**Ergebnis des erweiterten Validators: 63/63 PASS.**

Der Validator wurde nach Aufnahme dieses QA-Dokuments erneut gegen das gesamte Repository ausgeführt und blieb bei **63/63 PASS**.

## Status nach dieser Korrekturrunde

**Alpha:** Die normative Architektur ist als `v2.0.1 FINAL` konsistent gepatcht. Weitere Alpha-Änderungen sollen nur als bewusst versionierte Architekturanpassung erfolgen.

**Beta:** v0.1 ist nun ein konsolidierter vollständiger technischer Entwurf. Beta bleibt bewusst änderbar, weil die konkrete Implementierung und die Recovery-/Security-/Performance-Tests noch reales Feedback liefern werden.

**Nächster Entwicklungsschritt:** Phase 0 und anschließend Vertical Slice 1 aus Beta Kapitel 27 können auf dieser Spezifikationsbasis beginnen.
