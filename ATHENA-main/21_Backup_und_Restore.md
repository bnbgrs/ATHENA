# ATHENA Beta Specification v0.1 – Kapitel 21

## Backup und Restore

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Security:** [Beta Kapitel 16](16_Sicherheitsarchitektur_und_Protected_Content.md)

---

## Teil I – Ziele

### 1. Ziel

Dieses Kapitel konkretisiert Betrieb, Zeitplanung, Aufbewahrung, Verifikation und Benutzerworkflow des in Kapitel 03 definierten Backupformats.

---

### 2. Backup Definition

Ein Backup gilt nur als erfolgreich, wenn:

- Snapshot vollständig;
- Blob Objects vollständig;
- Manifest validiert;
- Integritätsprüfung bestanden;
- `complete.marker` vorhanden.

---

### 3. Separate Physical Copy

Mindestens eine gültige Sicherung soll auf einem anderen physischen Datenträger liegen.

---

### 4. No Git Backup

Git sichert Code/Spezifikationen, nicht den persönlichen ATHENA-Datenbestand.

---

## Teil II – Backup Scope

### 5. Must Backup

Mindestens:

- `athena.db`;
- alle referenzierten nicht rekonstruierbaren Blobs;
- geschützte Ciphertextblobs;
- notwendige Storage-/Schema-Metadaten;
- Deletion Ledger;
- exportierbare Secrets-Metadaten, nicht ungeschützte Secrets.

---

### 6. Optional Derived

FTS/HNSW/Caches müssen standardmäßig nicht gesichert werden.

---

### 7. Durable Operational

Jobs/Checkpoints sind Teil `athena.db` und somit im Snapshot enthalten.

---

### 8. Spool

Nicht synchronisierte Durable-Spool-Blobs müssen ebenfalls in ein Backup aufgenommen werden, wenn ein Backup während Archive-Offline-Zustand als vollständig gelten soll.

---

## Teil III – Zeitplanung

### 9. Default Retention

Default:

```text
7 täglich
4 wöchentlich
12 monatlich
5 jährlich
```

---

### 10. Daily

Ein automatisches Daily Backup läuft in einer konfigurierbaren ruhigen Zeit beziehungsweise bei nächster Gelegenheit.

---

### 11. Missed

Verpasst ATHENA einen Backuptermin, wird bei nächster Verfügbarkeit nachgeholt, sofern nicht bereits ein gleichwertig neuer Snapshot existiert.

---

### 12. Overlap

Es läuft nicht gleichzeitig mehrfach derselbe Backupjob auf dasselbe Ziel.

---

### 13. Manual

Manuelles Backup ist jederzeit möglich, soweit Storagezustand sicher.

---

## Teil IV – Backup Targets

### 14. Target

Jedes Ziel besitzt:

- ID;
- Root;
- Status;
- Retention Policy;
- letzte erfolgreiche Sicherung;
- letzte Verifikation;
- Deletion-Ledger-Watermark.

---

### 15. Offline Target

Offlineziel wird nicht als Fehler des Wissensbestands behandelt, aber anstehende Sicherung/Löschpropagation bleibt sichtbar.

---

### 16. Multiple Targets

Mehrere Backupziele können parallel konfiguriert werden.

---

### 17. Protected

Backupziel muss Ciphertext unverändert sichern; kein Unlock erforderlich.

---

## Teil V – Snapshot Ablauf

### 18. Preflight

Vor Backup:

- Ziel online;
- freier Speicher;
- Repository Manifest;
- laufende Migration;
- DB Health;
- Disk CRITICAL.

Unsicherer Zustand verhindert falsches Success.

---

### 19. DB Backup

SQLite Online Backup API erzeugt konsistenten Snapshot.

---

### 20. Commit Boundary

`snapshot_commit_seq` wird aus Snapshot-DB gelesen.

---

### 21. Blob Enumeration

Alle im Snapshot benötigten BlobIDs werden ermittelt.

---

### 22. Object Copy

Fehlende Objects werden verifiziert kopiert.

---

### 23. Manifest

Snapshotmanifest wird kanonisch erstellt.

---

### 24. Complete

Erst nach Final Verification wird complete marker geschrieben.

---

## Teil VI – Inkremenz/Deduplizierung

### 25. Blob Dedup

Immutable Blob Objects werden repositoryweit per SHA-256 dedupliziert.

---

### 26. DB Full Snapshot

v1 speichert pro Backup einen vollständigen SQLite-Snapshot für einfache robuste Restores.

---

### 27. Future Incremental

Spätere DB-Inkrementalverfahren dürfen ergänzt werden, wenn Restore nicht von proprietärer und fragiler Kette abhängig wird.

---

### 28. GC

Nach Auswahl des DB-Snapshots werden alle noch aus dem Produktivstorage benötigten BlobIDs **dauerhaft für diesen Backupjob gepinnt**, bevor paralleler Blob-GC sie entfernen kann.

Retention/Backup-Object-GC löscht nur Backup Objects, die von keinem surviving Snapshot referenziert werden.

Produktions-Blob-GC respektiert zusätzlich alle aktiven `backup_snapshot_pin`-Einträge. Pins werden erst nach `complete.marker` beziehungsweise kontrolliertem Abbruch-Cleanup entfernt.

## Teil VII – Retention

### 29. Selection

Daily/Weekly/Monthly/Yearly Slots werden deterministisch aus Snapshotzeiten gewählt.

---

### 30. Never Delete Only Good Copy

Wenn Retention technisch dazu führen würde, dass kein verifizierter Snapshot mehr bleibt, wird nicht automatisch gelöscht.

---

### 31. Failed Snapshot

Unvollständige Backups zählen nicht als Retention Restore Points.

---

### 32. Storage Full

Backupziel voll: Policy darf erlaubte alte Backups rotieren; wenn dies nicht sicher reicht, Benutzer informieren.

---

## Teil VIII – Verification

### 33. Light Verify

Nach jedem Backup:

- Manifest;
- DB quick/integrity profile;
- erforderliche Objectexistenz;
- Hashes der neu kopierten Objects.

---

### 34. Deep Verify

Periodisch:

- vollständiger DB integrity check;
- alle Objecthashes oder rotierende Vollprüfung;
- Restore Smoke Test.

---

### 35. Verified State

Snapshotstatus:

```text
unverified
verified_light
verified_deep
failed
```

---

### 36. No Trust by Presence

Eine Datei im Backupordner gilt nicht automatisch als gültiges Backup.

---

## Teil IX – Restore Tests

### 37. Scheduled Test

Regelmäßiger Restore Test in separatem Staging.

---

### 38. No Production Overwrite

Testrestore berührt produktive Roots nicht.

---

### 39. Checks

Mindestens:

- DB opens;
- schema;
- entity counts;
- random blobs;
- protected ciphertext presence;
- Deletion Ledger;
- derived rebuild readiness.

---

### 40. Audit

Restoretest-Ergebnis wird auditiert.

---

## Teil X – Deletion Ledger

### 41. Purpose

Verhindert, dass später gelöschte IDs aus alten Snapshots still zurückkehren.

---

### 42. Propagation

Jedes erreichbare Backupziel erhält aktuelle Ledgerrecords.

---

### 43. Offline

Offline Backupziele bleiben als `deletion_sync_pending` sichtbar.

---

### 44. Restore Warning

Restore von Medium ohne aktuellen Ledger zeigt klare Einschränkung.

---

### 45. No Payload

Ledger enthält keine gelöschten Inhalte.

---

## Teil XI – Restore UI

### 46. Selection

UI zeigt:

- Zeitpunkt;
- Target;
- Verification Status;
- Schema;
- Größe;
- Snapshot Commit;
- Deletion-Ledger-Stand.

---

### 47. Pre-Restore Backup

Wenn aktueller Zustand lesbar, wird vor Restore automatisch ein Rettungssnapshot vorgeschlagen/erstellt.

---

### 48. Destination

Restore darf in neuen State-/Archive Root erfolgen.

---

### 49. Confirmation

UI erklärt, welche Daten zeitlich zurückgesetzt werden und welche späteren Löschmarker angewendet werden.

---

## Teil XII – Restore Ablauf

### 50. Staging

Restore immer in separates Recovery Staging.

---

### 51. DB Verify

Snapshot-DB vor Aktivierung vollständig prüfen.

---

### 52. Objects

Erforderliche Objects kopieren/verifizieren.

---

### 53. Ledger Apply

Aktuell verfügbaren Deletion Ledger anwenden.

---

### 54. Activate

Erst nach Health Checks werden neue Roots aktiviert.

---

### 55. Derived Rebuild

Search/Embeddings/HNSW neu aufbauen.

---

## Teil XIII – Disaster Recovery

### 56. Lost Main Disk

Minimalpfad:

```text
neue Hardware
→ ATHENA installieren
→ Backup Repository auswählen
→ Snapshot verifizieren
→ Restore
→ Storage Roots wählen
→ Derived State rebuild
→ Primary Model konfigurieren
```

---

### 57. No Original Model Required

Restore benötigt nicht dasselbe historische Primärmodell, um Knowledge zu lesen.

---

### 58. No Obsidian Required

Obsidian ist für Restore nicht notwendig.

---

### 59. No Internet Required

Lokaler Backuprestore funktioniert ohne Internet.

---

## Teil XIV – Encryption and Recovery Keys

### 60. Ciphertext Backup

Protected Blobs bleiben verschlüsselt.

---

### 61. Key Material

Notwendiges wrapped Keymaterial wird gesichert, ohne Passwort/Klartextschlüssel offenzulegen.

---

### 62. Recovery Key Separation

Optionaler Recovery Key wird nicht zusammen mit dem Repository im Klartext gespeichert.

---

### 63. Test Unlock

Restoretest kann Protected Ciphertext strukturell prüfen, ohne zwingend jedes Mal zu entschlüsseln. Periodischer bewusster Protected Restore Test kann separat erfolgen.

---

## Teil XV – Failure

### 64. Backup Failure

Job wird failed/partial, nie success.

---

### 65. Target Disconnect

Copy stoppt; immutable bereits verifizierte Objects können bei Retry wiederverwendet werden.

---

### 66. DB Changes During Backup

Online Backup Snapshot bleibt konsistent; spätere Commits gehören in nächsten Snapshot.

---

### 67. Corrupt Object

Falscher Hash → Objekt nicht vertrauen; von Produktivstorage oder anderem Backup neu kopieren.

---

## Teil XVI – Portabilität

### 68. Documented Format

Repositorystruktur und Manifestformat werden dokumentiert.

---

### 69. No Proprietary-only

Langfristige Knowledge-/Originaldaten dürfen zusätzlich über vollständigen Export zugänglich bleiben.

---

### 70. Different OS

Pfade im Manifest sind relativ; Restore ist nicht an ursprünglichen Laufwerksbuchstaben gebunden.

---

## Teil XVII – Tests

### 71. Daily Rotation Test

Simulierte 2 Jahre Snapshots → Retention hält korrekte Daily/Weekly/Monthly/Yearly Slots.

---

### 72. Target Offline Test

Backupziel offline. Job wartet/fails sichtbar; aktuelles Knowledge bleibt sicher.

---

### 73. Dedup Test

100 identische große Blobs über viele Snapshots → nur ein Backup Object.

---

### 74. Incomplete Test

Crash vor complete marker. Snapshot darf nicht als Restore Point gelten.

---

### 75. Deletion Restore Test

Alten Snapshot restoren + aktuelles Ledger → gelöschte Entity bleibt gelöscht.

---

### 76. Corruption Test

Backup DB Byte beschädigen → Verification failed.

---

### 77. Missing Object Test

Manifest referenziert fehlenden Blob → Snapshot invalid.

---

### 78. New Hardware Test

Restore auf vollständig andere Roots → IDs/Relations unverändert.

---

### 79. Protected Test

Backupmedium durchsuchen → keine Protected Klartextpayloads.

---

### 80. Restore Test Automation

Testrestore darf produktive DB/Roots nicht verändern.

---

### 81. Backup-GC-Race-Test

1. DB-Snapshot erzeugen, der Blob X referenziert.
2. Backup Snapshot Pins erzeugen.
3. Source X in der Live-DB löschen und Produktions-GC starten.
4. Backup fortsetzen.

Erwartung:

- Blob X bleibt bis zur verifizierten Aufnahme in den Backup Object Store verfügbar;
- Produktions-GC überspringt den Pin;
- Snapshot kann `complete` werden;
- Pin wird erst danach entfernt.

---

### 82. Abschluss

Backup/Restore ist bestanden, wenn ATHENA nach realistischem Hauptdatenträgerverlust auf neuer Hardware vollständig rekonstruiert werden kann und ein „Backup vorhanden“-Status nur nach tatsächlicher Integritätsprüfung vergeben wird.

---

## Nächster Schritt

**Beta Kapitel 22 – Recovery Mode und Selbstdiagnose**.
