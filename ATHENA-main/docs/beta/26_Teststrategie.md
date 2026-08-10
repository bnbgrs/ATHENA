# ATHENA Beta Specification v0.1 – Kapitel 26

## Teststrategie

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Recovery:** [Beta Kapitel 22](22_Recovery_Mode_und_Selbstdiagnose.md)

---

## Teil I – Testphilosophie

### 1. Ziel

Tests beweisen nicht nur einzelne Funktionen, sondern insbesondere ATHENAs Kerninvarianten: kein Datenverlust, keine stillen Überschreibungen, reproduzierbare Herkunft, sichere Degradation und Wiederherstellbarkeit.

---

### 2. Pyramid

v1 kombiniert:

```text
unit
contract
integration
end-to-end
recovery/chaos
migration
security
performance
```

---

### 3. Real Storage Where Needed

Kritische SQLite-/Filesystem-/Backup-Tests verwenden echte temporäre Dateien und keine ausschließlich gemockte Persistenz.

---

### 4. Deterministic Core

Zeit, UUIDgenerator, Provider und Resource Probes werden testbar injizierbar gemacht.

---

## Teil II – Unit Tests

### 5. Domain

Testen:

- Entity validation;
- revision rules;
- memory scope;
- claim status;
- relation types;
- lifecycle transitions.

---

### 6. Pure Services

Rankinghelpers, Contextbudgeting, Retentionauswahl und State Machines sollen als reine Funktionen testbar sein, wo sinnvoll.

---

### 7. No DB for Pure Rules

Semantische Regeln benötigen nicht für jeden Unit Test SQLite.

---

## Teil III – Repository Integration

### 8. SQLite Real

Repositories werden gegen echte temporäre SQLite DB getestet.

---

### 9. PRAGMAs

Tests verifizieren Pflicht-PRAGMAs.

---

### 10. Atomicity

Fehler zwischen einzelnen Write-Schritten → vollständiger Rollback.

---

### 11. Foreign Keys

Ungültige References werden tatsächlich von DB/Core abgewiesen.

---

### 12. WAL Crash

Harte Prozessabbrüche in separaten Testprozessen prüfen Crash Recovery.

---

## Teil IV – Blob Tests

### 13. Roundtrip

Random bytes → BlobStore → read → hash identical.

---

### 14. Dedup

Identische unprotected bytes → eine physische Blobkopie.

---

### 15. Crash Window

Finaler Blob ohne DBcommit → Orphan GC.

---

### 16. Network Simulation

Archive Root disconnect/reconnect mit Durable Spool.

---

### 17. Protected

Encrypted Blob tamper → authentication failure.

---

## Teil V – Contract Tests

### 18. PrimaryModelProvider

Jeder Provider muss denselben Contracttest bestehen.

---

### 19. EmbeddingProvider

Dimension, batch, errors, signature.

---

### 20. OCR/STT

Anchors und Failure States.

---

### 21. StorageProvider

Root health, write, verify, move, offline behavior.

---

### 22. VectorIndexProvider

Build, add, query, delete/rebuild, manifest.

---

### 23. ExternalAccessGateway

Authorization, redirects, fail-closed, size/timeouts.

---

## Teil VI – API Tests

### 24. Schema

Requests/Responses gegen API-Schemas.

---

### 25. Auth

Missing/invalid session → denied.

---

### 26. Concurrency

expected_revision conflict.

---

### 27. Idempotency

Repeated create/action.

---

### 28. Streaming

Order, cancel, reconnect.

---

### 29. Pagination

Stable cursor semantics.

---

## Teil VII – Model Tests

### 30. Fake Provider

CI verwendet deterministischen FakePrimaryModelProvider für die Mehrheit der Tests.

---

### 31. Structured Invalid

Fake liefert invalid JSON/IDs → validation/repair.

---

### 32. Refusal

Fake refusal → Source/Job state correct.

---

### 33. Real Backend Smoke

Optionaler lokaler Integrationstest gegen echtes Model Backend, nicht Voraussetzung für jede CI-Ausführung.

---

### 34. No Semantic Golden Fragility

Tests vermeiden übermäßig exakte Wortlaut-Goldens für generative Antworten. Sie prüfen strukturierte Invarianten und Evidenzrefs.

---

## Teil VIII – Retrieval Tests

### 35. Corpus

Synthetischer Testkorpus mit:

- exact match;
- paraphrases;
- conflicting sources;
- dates;
- projects;
- duplicates.

---

### 36. Metrics

Retrievalqualität kann mit Recall@K/MRR/NDCG auf fixem Korpus überwacht werden.

---

### 37. Hybrid

FTS, vector, graph und RRF getrennt sowie gemeinsam testen.

---

### 38. Protected

Locked content darf Recalltests unprotected nicht leaken.

---

### 39. Watermark

Fresh writes bei stale index.

---

## Teil IX – Context Tests

### 40. Budget

Zufällige Kandidatenmengen → niemals Context Limit überschreiten.

---

### 41. Property Test

Für beliebige positive Budgetkomponenten muss:

```text
used + output_reserve + safety_margin <= capacity
```

gelten.

---

### 42. Injection

Sourceinstruction bleibt Data.

---

### 43. Revision Snapshot

Included refs bleiben stabil.

---

## Teil X – Research Tests

### 44. Large Corpus

Viele tausend synthetic Work Units.

---

### 45. Resume

Random crash points + idempotent resume.

---

### 46. Coverage

Failures/unavailable korrekt gezählt.

---

### 47. Delta

Neue commits nach snapshot.

---

### 48. Contradictions

Final result retains conflicting evidence.

---

## Teil XI – Job/Queue Tests

### 49. State Machine

Alle erlaubten/verbotenen Transitions.

---

### 50. Lease

Expiry, renew, zombie fencing.

---

### 51. Retry

Transient/permanent.

---

### 52. Backpressure

Producer throttle.

---

### 53. Priority

Interactive/P0 behavior.

---

### 54. Schedule

DST, missed runs, backfill.

---

## Teil XII – Security Tests

### 55. Secret Redaction

Automatisierte Suche nach Canary-Secrets in Logs/Diagnostics.

---

### 56. Protected Canary

Protected Klartext-Canary darf nicht in unprotected DB/search/cache auftauchen.

---

### 57. Crypto Tamper

Ciphertext/AAD/nonce modifications fail.

---

### 58. Unlock

Wrong/correct password, lock cleanup.

---

### 59. Prompt Injection

Testdocuments mit adversarial instructions.

---

### 60. SSRF

Redirects zu localhost/private IP.

---

### 61. Plugin Permissions

Capability matrix.

---

## Teil XIII – Backup/Restore

### 62. Snapshot Consistency

Concurrent writes während Online Backup.

---

### 63. Manifest

Missing/corrupt objects.

---

### 64. Retention

Mehrjährige simulierte Timeline.

---

### 65. Deletion Ledger

Old restore + newer delete.

---

### 66. New Hardware

Different roots.

---

### 67. Protected

Ciphertext-only backup.

---

## Teil XIV – Migration Tests

### 68. Every Supported Source Version

CI hält Fixtures älterer Schemaversionen.

---

### 69. Forward

Jede supported old DB → current.

---

### 70. Crash

Kill at migration phases.

---

### 71. Disk Full

Preflight und mid-operation.

---

### 72. Rollback

Pre-migration candidate.

---

### 73. No Semantic Change

Hashes/semantic payloads unchanged bei rein technischer migration.

---

## Teil XV – Recovery Tests

### 74. DB Corruption

Controlled corruption scenarios.

---

### 75. FTS/HNSW Corruption

Derived only.

---

### 76. Missing Blob

Alternative location/backup.

---

### 77. Broken Config

Safe defaults/last valid.

---

### 78. Plugin Crash Loop

Recovery without plugins.

---

### 79. No Model/Internet

Recovery still works.

---

## Teil XVI – UI Tests

### 80. ViewModel

Core API responses → deterministic UI state.

---

### 81. Accessibility

Keyboard navigation and labels.

---

### 82. Long List

Virtual/paginated models.

---

### 83. Core Disconnect

Reconnect state.

---

### 84. Tray

Open/load/unload/pause/quit.

---

### 85. Protected

No locked previews/notifications.

---

## Teil XVII – Property/Fuzz Tests

### 86. Parsers

Fuzz filenames, paths, malformed metadata, archives.

---

### 87. API

Malformed JSON/UUIDs/enums.

---

### 88. Canonical JSON

Equivalent structures → identical JCS hash.

---

### 89. Revision

Random valid edits preserve stable entity ID and monotonic revision numbers.

---

### 90. Graph

Random edge operations never leave forbidden orphan references.

---

## Teil XVIII – Performance Tests

### 91. Baselines

Measure:

- startup;
- simple search;
- hybrid search;
- DB commit;
- 1GB import streaming;
- FTS rebuild;
- vector rebuild;
- backup.

---

### 92. Scale Corpus

Synthetic scale targets include at least millions of lightweight entities/chunks for query-path testing.

---

### 93. No Hard Architecture Limit

Benchmarks are targets, not fixed archive-size limits.

---

### 94. Regression

Large regressions fail benchmark gate or require documented acceptance.

---

## Teil XIX – Chaos Tests

### 95. Kill Points

Random process kills during:

- import;
- blob sync;
- checkpoint;
- backup;
- migration clone;
- derived rebuild.

---

### 96. Storage Disconnect

Mount/network disappears mid-job.

---

### 97. Resource Pressure

Disk/RAM pressure simulation.

---

### 98. Backend Failure

Model provider restarts mid-call.

---

## Teil XX – Test Data

### 99. Synthetic

No real private user data in CI.

---

### 100. Deterministic Seeds

Randomized tests log seed for reproduction.

---

### 101. Sensitive Canaries

Known synthetic strings make leaks mechanically detectable.

---

## Teil XXI – CI Gates

### 102. Per Commit

Fast unit, contract, lint/type, core integration.

---

### 103. Per PR

Broader DB/API/security tests.

---

### 104. Nightly

Long scale, chaos, restore, full migration matrix.

---

### 105. Release

Full recovery/backup/migration/security suite plus clean-install smoke.

---

## Teil XXII – Coverage

### 106. Code Coverage

Coverage is a signal, not sole quality metric.

---

### 107. Critical Paths

Canonical writes, deletion, crypto, backup, migration and recovery require particularly strong branch/path coverage.

---

### 108. Spec Traceability

Critical Beta invariants map to one or more named tests.

---

## Teil XXIII – Acceptance

### 109. No Data Loss

Release cannot pass if known crash path can lose a committed Source/Knowledge object.

---

### 110. No Silent Overwrite

Concurrent writes must conflict.

---

### 111. Restore Proven

Release requires successful automated restore test from current backup format.

---

### 112. Protected Leak

Any confirmed protected-canary leak into unprotected persistent state is release blocker.

---

### 113. Migration

Every supported schema path must migrate in test.

---

## Teil XXIV – Abschluss

### 114. Leitregel

> **ATHENA wird nicht als zuverlässig betrachtet, weil der normale Pfad funktioniert. Sie gilt erst dann als zuverlässig, wenn Crash, Disk Full, Providerfehler, Netzwerkverlust, falsche Eingaben, konkurrierende Edits und Restore systematisch getestet wurden.**

---

### 115. Nächster Fokus

Kapitel 27 definiert die Entwicklungsreihenfolge, in der diese Tests zusammen mit vertikalen Funktionsslices entstehen.

---

## Nächster Schritt

**Beta Kapitel 27 – Entwicklungsphasen und Vertical Slices**.
