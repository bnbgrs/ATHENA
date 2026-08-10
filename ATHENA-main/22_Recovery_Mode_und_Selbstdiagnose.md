# ATHENA Beta Specification v0.1 – Kapitel 22

## Recovery Mode und Selbstdiagnose

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Backup:** [Beta Kapitel 21](21_Backup_und_Restore.md)

---

## Teil I – Ziel

### 1. Ziel

Recovery Mode ist ein bewusst kleiner, robuster Betriebsmodus für Situationen, in denen der normale ATHENA-Stack nicht sicher startet oder schreibt.

---

### 2. Minimal Dependencies

Recovery darf nicht benötigen:

- Primärmodell;
- Embeddings/HNSW;
- Obsidian;
- Plugins;
- Internet;
- News;
- normales Backgroundsystem.

---

### 3. Data first

Recoverypriorität ist:

```text
keine weitere Beschädigung
→ Zustand feststellen
→ Daten sichern
→ verständliche Reparaturoption
```

---

### 4. No Guessing

Bei unklaren konkurrierenden Datenbank-/Migrationkandidaten entscheidet Recovery nicht allein anhand Dateidatum.

---

## Teil II – Startup Health

### 5. Startup Phases

```text
manifest
→ state root
→ DB open
→ application_id/schema
→ quick_check
→ migration state
→ storage roots
→ secrets provider
→ derived state
→ optional modules
```

---

### 6. Critical vs Optional

Fehlendes Primärmodell ist optionaler Komponentenfehler. Beschädigte `athena.db` ist kritisch.

---

### 7. Health States

Komponenten:

```text
ok
degraded
unavailable
error
recovery_required
```

---

### 8. Startup Report

Core erzeugt einen strukturierten Health Report für UI/CLI.

---

## Teil III – Recovery Entry

### 9. Automatic Offer

Mehrere fehlgeschlagene Starts oder kritischer DB-Check bieten Recovery Mode automatisch an.

---

### 10. Manual

Recovery kann explizit vom Benutzer gestartet werden.

---

### 11. Safe Flags

CLI/Launcher kann einen `--recovery`-ähnlichen Modus anbieten; genaue Kommandoform gehört Codeimplementierung.

---

### 12. No Plugin Load

Recovery lädt Drittplugins standardmäßig nicht.

---

## Teil IV – Read-only Safe Mode

### 13. When

Wenn Daten lesbar, aber sichere Writes nicht garantiert sind.

---

### 14. Allowed

- Knowledge lesen;
- Sources prüfen;
- Backupstände anzeigen;
- Diagnose exportieren.

---

### 15. Denied

- normale Edits;
- automatische Knowledge Extraction;
- Migrationswrites;
- unkritische Backgroundwrites.

---

### 16. UI

Deutlich sichtbarer Read-only-Banner mit Grund.

---

## Teil V – Database Recovery

### 17. Quick Check Failure

Writer bleibt geschlossen.

---

### 18. Diagnostic Copy

Soweit Speicher verfügbar wird vor Reparaturversuchen eine unveränderte Diagnosekopie erstellt.

---

### 19. Backup First

Bevor invasive Recovery versucht wird, werden gültige Backupstände gesucht.

---

### 20. SQLite Recovery

Ein dokumentiertes SQLite-Recovery-Verfahren darf als letzte Option verwendet werden. Resultat wird als neue Candidate DB behandelt und vollständig validiert, nie direkt über Original geschrieben.

---

### 21. Foreign Key Failure

Referenzfehler werden nicht automatisch durch Löschen von Rows „repariert“. Candidate Repair benötigt nachvollziehbare Strategie.

---

## Teil VI – Migration Recovery

### 22. Journal

`migration_state.json` zeigt Phase und Kandidaten.

---

### 23. Candidate Validation

Jede DB-Kandidatin:

- application_id;
- schema;
- quick/integrity check;
- foreign key check;
- expected migration metadata.

---

### 24. Rollback

Wenn alte Pre-Migration-DB intakt, kann sie reaktiviert werden.

---

### 25. Forward Complete

Ist Migrationskandidat vollständig validiert, kann Migration kontrolliert abgeschlossen werden.

---

### 26. Ambiguous

Bei zwei plausiblen Zuständen zeigt UI Zeit, Schema, Commitseq und Health für Benutzerentscheidung.

---

## Teil VII – Blob Recovery

### 27. Missing Blob

Prüfen:

- alternative BlobLocation;
- Spool;
- Backup Objects;
- Archive Root offline.

---

### 28. Hash Mismatch

Beschädigte Location quarantinieren; intakte Kopie suchen.

---

### 29. Rehydrate

Aus Backup wiederhergestellter Blob erhält neue verifizierte Location, gleiche `blob_id`, wenn Bytes/Integrität identisch.

---

### 30. No Fabrication

Fehlender Blob wird nicht durch leere Datei oder Modellrekonstruktion ersetzt.

---

## Teil VIII – Derived State Recovery

### 31. FTS

`search.db` kann gelöscht und neu aufgebaut werden.

---

### 32. HNSW

Beschädigter Vector Index wird aus EmbeddingRecords rebuild.

---

### 33. Embeddings

Beschädigte/inkompatible EmbeddingRecords können aus Sources/Knowledge neu berechnet werden.

---

### 34. Cache

Cache kann vollständig verworfen werden.

---

### 35. Priority

Derived Rebuild beginnt erst, wenn autoritative Integrität bestätigt ist.

---

## Teil IX – Job Recovery

### 36. Orphan Running

Running Jobs mit abgelaufener Lease werden nicht als completed angenommen.

---

### 37. Checkpoint

Letzten bestätigten Checkpoint bestimmen.

---

### 38. Side Effect

External/Outbox Jobs werden auf mögliche bereits erfolgte Side Effects reconciled.

---

### 39. Migration Job

Migrationjobs besitzen strengere Recoverypolicy und dürfen nicht automatisch neben unklarer DB weitermachen.

---

## Teil X – Configuration Recovery

### 40. Invalid Config

Fehlerhafte ConfigurationEntry kann über letzte gültige Revision beziehungsweise Safe Defaults umgangen werden.

---

### 41. Keep Bad Revision

Fehlerhafte Config bleibt für Diagnose historisch sichtbar, statt still gelöscht zu werden.

---

### 42. Storage Root

Nicht erreichbarer Archive Root kann neu gebunden werden; Object IDs ändern sich nicht.

---

### 43. Secrets

Nicht erreichbarer Secrets Provider degradiert Connectorfunktionen; Corewissen bleibt lesbar.

---

## Teil XI – Protected Recovery

### 44. Locked by Default

Recovery startet alle Protected Scopes **runtime-locked**, unabhängig davon, in welchem persistenten Lifecycle-Zustand sich ein `ProtectionScope` befindet.

`locked` beziehungsweise `unlocked_for_session` ist ausschließlich Zustand des aktuellen `SecurityContext` und wird nicht als persistenter Scope-Lifecycle gespeichert. Ein Crash oder Restore kann daher keinen alten `unlocked`-Zustand wiederherstellen.

---

### 45. Ciphertext Integrity

Protected Blob kann ohne Passwort auf Ciphertexthash geprüft werden.

---

### 46. Unlock Optional

Entschlüsselungsprüfung erfolgt nur nach bewusster Authentifizierung.

---

### 47. Key Failure

Fehlendes/defektes Keymaterial führt nicht zu Überschreiben des Ciphertexts.

---

### 48. Recovery Key

Optionaler Recoverykey kann im Core-kontrollierten Flow verwendet werden.

---

## Teil XII – Backup Recovery

### 49. Repository Scan

Recovery kann Backup Repositories ohne normalen Corebetrieb lokalisieren und Manifeste lesen.

---

### 50. Verification

Restorepointstatus wird neu geprüft, nicht blind aus altem UIcache übernommen.

---

### 51. Deletion Ledger

Restore UI zeigt Ledgerstand und offene Löschpropagation.

---

### 52. Emergency Restore

Restore in neues Staging, nicht in-place.

---

## Teil XIII – Self-Diagnostics

### 53. Diagnostic Rules

Bekannte Fehlerbilder werden regelbasiert diagnostiziert.

---

### 54. Examples

- DB locked;
- Archive offline;
- FTS corrupt;
- Model backend unavailable;
- Privacy route unavailable;
- Backup target full;
- Plugin incompatible;
- Disk Critical.

---

### 55. Explain

Diagnose enthält:

- Ursache soweit bekannt;
- betroffene Funktion;
- Datenrisiko;
- automatische sichere Schritte;
- Benutzeroptionen.

---

### 56. No False Certainty

Wenn Ursache unbekannt, sagt ATHENA dies.

---

## Teil XIV – Diagnostics Export

### 57. Bundle

Export kann enthalten:

- versions;
- component health;
- sanitized logs;
- schema info;
- job states;
- storage status;
- recent error codes.

---

### 58. Redaction

Keine Secrets, Protected Klartexte oder unnötige persönliche Chats.

---

### 59. User Review

Vor Export kann UI Kategorien anzeigen.

---

## Teil XV – Recovery UI

### 60. Simple

Hauptaktionen:

```text
Read-only öffnen
Integrität prüfen
Backup wiederherstellen
Index neu aufbauen
Storage neu verbinden
Diagnose exportieren
```

---

### 61. No Technical Wall

SQL PRAGMAs/Stacktraces sind nur Advanced Detail.

---

### 62. Risk Labels

Invasive Aktionen werden klar als solche markiert und möglichst erst auf Kopien ausgeführt.

---

## Teil XVI – Tests

### 63. DB Corrupt Test

DB-Page beschädigen. Startup muss Writebetrieb verweigern und Recovery anbieten.

---

### 64. FTS Corrupt Test

Nur search.db beschädigen. Normaler Core darf mit Search degraded starten.

---

### 65. Migration Crash Test

Crash mitten in Clone Migration. Recovery erkennt alte und candidate DB.

---

### 66. Archive Offline Test

NAS offline. Core mit lokalem Knowledge/Spool nutzbar; kein falscher Corruptionstatus.

---

### 67. Missing Blob Test

Eine BlobLocation fehlt, Backupkopie vorhanden. Recovery rehydriert.

---

### 68. Protected Key Failure Test

Key unwrap fehlschlägt. Ciphertext bleibt unverändert.

---

### 69. Plugin Crash Loop Test

Defektes Plugin verhindert Normalstart. Recovery startet ohne Plugin und kann es deaktivieren.

---

### 70. No Internet Test

Recovery vollständig ohne Internet nutzbar.

---

### 71. New Hardware Test

Nur Backup Repository vorhanden. Recovery/Restore auf neue Roots erfolgreich.

---

### 72. Diagnostic Redaction Test

Diagnosebundle automatisiert auf Secrets/Protected Teststrings prüfen.

---

### 73. Abschluss

Recovery ist bestanden, wenn ATHENA bei echten Fehlern bevorzugt sicher und verständlich degradiert statt weiterzuschreiben, und wenn der Benutzer selbst ohne Modell/Plugins/Internet seine Daten prüfen und wiederherstellen kann.

---

## Nächster Schritt

**Beta Kapitel 23 – Updates, Migrationen und Kompatibilität**.
