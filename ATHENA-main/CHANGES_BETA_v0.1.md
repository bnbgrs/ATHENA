# ATHENA Beta v0.1 – Konsolidierungsstand

## Zweck

Dieses Dokument beschreibt den Stand der ersten vollständigen technischen Beta-Spezifikation.

## Umfang

- 27 technische Kapitel
- Kapitel 01–03: Architektur, logisches Datenmodell und physische Persistenz
- Kapitel 04–24: Domänen, Modelle, Suche, Jobs, Netzwerk, Sicherheit, UI und Betrieb
- Kapitel 25–27: Repository, Teststrategie und Entwicklungsplan

## Wichtigste durchgängige Invarianten

- Benutzer bleibt höchste semantische Autorität.
- Nur Benutzer und aktives Primärmodell veranlassen semantische Änderungen an kanonischem Wissen.
- Infrastructure Models treffen keine autonomen semantischen Wissensentscheidungen.
- Knowledge, Personal Memory, Raw Archive, Audit/Provenienz und Configuration bleiben getrennte autoritative Domänen.
- Durable Operational State ist geschützt und nicht mit rekonstruierbarem Derived State zu verwechseln.
- Originalquellen werden durch Analyse nicht verändert.
- Direkte Benutzeränderungen benötigen keine erfundene ModelSignature.
- Modellbasierte semantische Änderungen sind auf ModelSignature und ProcessingRun zurückführbar.
- Stabile UUIDv7-Identitäten sind unabhängig von Pfad, Dateiname und Speicherort.
- Revisionen ersetzen keine Historie durch in-place Überschreiben.
- SQLite ist v1-Hauptdatenbank, aber nicht auf Netzwerkfreigaben als Live-WAL-Datenbank.
- Große Originale liegen als immutable Blobs.
- FTS5, Embeddings und HNSW sind Derived State.
- Protected Klartext gelangt nicht in normale persistente Search-/Vector-Indizes.
- Langlaufende Arbeit ist persistent, checkpointbar und idempotent.
- Research besitzt Scope, Snapshot und messbare Coverage.
- Externer Zugriff läuft über den ExternalAccessGateway und Fail-Closed.
- Plugins besitzen Least-Privilege-Capabilities und keinen direkten DB-/Secretzugriff.
- Backup ist erst gültig nach Verifikation; Restore berücksichtigt Deletion Ledger.
- Recovery funktioniert ohne Modell, Plugins, Obsidian und Internet.
- Entwicklung erfolgt in Vertical Slices mit Crash-, Security-, Migration- und Restoretests.

## Status

Die Beta-Spezifikation ist damit **inhaltlich vollständig als erster Entwurf**, aber bewusst noch nicht als unveränderlich gefroren.

Anders als Alpha soll Beta während der tatsächlichen Implementierung kontrolliert präzisiert werden, wenn Tests oder reale technische Grenzen dies erfordern.

Änderungen müssen nachvollziehbar bleiben und dürfen Alpha nicht stillschweigend widersprechen.

## Cross-System-Konsistenzpatch 2026-08-10

Nach einem vollständigen Repository-Audit wurden folgende Punkte in Beta v0.1 korrigiert beziehungsweise präzisiert:

- lokale `athena.db` als sichere transaktionale Materialisierung; optionaler `long_term_root` als verifizierte versionierte Langzeitreplik, ohne SQLite live über SMB/NFS zu öffnen;
- expliziter Replication Watermark und Schutz noch nicht langzeitreplizierter Commits;
- `SourceChunk` eindeutig als Derived State; dauerhafte Evidenz über SourceRepresentation + SourceAnchor;
- Lifecycle-/Protection-Historie über commit-sequenzierte EntityStateHistory;
- `temporary` und `do_not_store` semantisch getrennt;
- `restore_blocking_until = NULL` als unbefristeter Block für endgültige Löschung;
- SQLite `application_id` konkret als Integer `1096042574` (`0x4154484E`, `ATHN`);
- SQLite-UNIQUE/NULL-Problem bei Configuration über Partial Unique Indexes korrigiert;
- Disk-Full-Schwellen von `min()` auf die beabsichtigte `max()`-Logik korrigiert;
- Protected Source-Metadaten und alle content-derived Hashes konsistent geschützt;
- vollständige persistente Keyhierarchie mit Key Slots, Root Key, versionierten Scope Keys und per-object DEKs festgelegt;
- Protected Durable Operational State für Jobs, Checkpoints, Pending Writes, ResearchScopes und CandidateSets definiert;
- resumierbarer Protect/Unprotect Transition Workflow ergänzt;
- Backup Snapshot Pins verhindern Race zwischen Snapshot und Blob-GC;
- v1-Pluginmodell präzisiert: Capability-/Prozessisolation schützt offizielle Schnittstellen und Corestabilität, ist ohne OS-Sandbox aber keine Garantie gegen absichtlich bösartigen lokalen Plugin-Code;
- visuelle Infrastrukturmodelle dürfen keine autonomen kanonischen semantischen Entscheidungen treffen.

Zusätzliche Konsolidierungen dieser Korrekturrunde:

- `derived://chunk/<chunk_id>` ersetzt den irreführenden Raw-Archive-URI für Derived SourceChunks; auch Beta 01 klassifiziert Chunks nun ausdrücklich als rekonstruierbaren Derived State;
- As-of-Retrieval verwendet zusätzlich `entity_state_history`, damit historischer Lifecycle- und Protection-Zustand korrekt rekonstruiert wird;
- Recovery startet ProtectionScopes immer runtime-locked; Lock/Unlock ist kein persistenter Scope-Lifecycle;
- v1-Key-Wrapping ist konkret auf AES-256-GCM mit eindeutigem 96-Bit-Nonce und AAD-Bindung festgelegt;
- Repository-Dateinamen wurden auf ASCII-Transliteration normalisiert und sämtliche internen Links entsprechend bereinigt;
- alte Paket-QA-/SHA-Artefakte und extensionless Duplikate wurden entfernt; der Repository-Validator liegt unter `scripts/validate_spec.py`.
