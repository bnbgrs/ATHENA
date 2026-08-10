# ATHENA Beta Specification v0.1 – Kapitel 07

## Provenienz, Audit und Versionierung

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)
**Knowledge:** [Beta Kapitel 05](05_Wissenseinheiten_Claims_und_Wissensgraph.md)
**Personal Memory:** [Beta Kapitel 06](06_Personal_Memory.md)

---

## Teil I – Ziele und Begriffe

### 1. Ziel

Dieses Kapitel definiert die vollständige Nachvollziehbarkeit autoritativer und semantisch relevanter Änderungen.

ATHENA muss beantworten können:

```text
Was ist entstanden?
Wann?
Durch wen?
Aus welchen Inputs?
Mit welchem Modell/Prozess?
Welche Revision war vorher gültig?
Welche Revision ist jetzt gültig?
```

---

### 2. Provenienz versus Audit

**Provenienz** beschreibt die Herkunft eines konkreten Datenobjekts oder einer Änderung.

**Audit** beschreibt ein relevantes Systemereignis.

Beides ist verbunden, aber nicht identisch.

---

### 3. Versionierung

Versionierung erhält die Entwicklung desselben logischen Objekts über Revisionen.

Sie darf nicht mit Git-Versionierung des ATHENA-Quellcodes verwechselt werden.

---

### 4. Minimalprinzip

Audit und Provenienz speichern so viel wie für Nachvollziehbarkeit notwendig, aber keine unnötigen Schattenkopien sensibler oder gelöschter Inhalte.

---

## Teil II – ProvenanceRecord

### 5. Pflichtkette

Jede semantische Revision besitzt einen ProvenanceRecord.

---

### 6. Subject

`subject_ref` zeigt auf die Entität beziehungsweise Revision, deren Entstehung erklärt wird.

---

### 7. Actor

Der tatsächliche Akteur wird gespeichert:

```text
user
primary_model
system
plugin
importer
external_client
```

Keine erfundene Modellbeteiligung.

---

### 8. Sources

Eine Provenienz darf mehrere Inputs besitzen. Die Reihenfolge kann über `ordinal` erhalten werden, wenn sie für Verarbeitung relevant ist.

---

### 9. Parent Provenance

Mehrstufige Ableitungen bilden einen Provenienzgraph.

Beispiel:

```text
Source
→ OCR
→ Interpretation
→ Claim
→ Concept Note
```

---

### 10. Reason

Ein optionaler Reason beschreibt den menschlich verständlichen Anlass, beispielsweise:

```text
user correction
scheduled revalidation
document extraction
manual merge
```

---

## Teil III – Modellprovenienz

### 11. ModelSignature Pflicht

Wenn das Primärmodell eine semantische Entscheidung erzeugt, ist `model_signature_id` verpflichtend.

---

### 12. User Write

Bei direkter Benutzeränderung:

```text
model_signature_id = null
```

Dies ist ein gültiger vollständiger Provenienzzustand.

---

### 13. ProcessingRun

Modellprovenienz verweist zusätzlich auf den konkreten ProcessingRun, damit Inputscope, Pipelineversion und Prompttemplate nachvollziehbar bleiben.

---

### 14. Prompt Template

Langfristig wissensbildende Modellläufe speichern Template-ID und Template-Version, nicht zwingend eine komplette interne Systempromptkopie im Audit.

---

### 15. Parameter

Relevante Generationseinstellungen werden in ModelSignature beziehungsweise ProcessingRun gespeichert. Unbekannte Parameter bleiben unbekannt.

---

### 16. Model Drift

Eine geänderte ModelSignature mitten in einem gepinnten Job wird als Drift erkannt. Die Verarbeitung darf nicht stillschweigend gemischt werden.

---

## Teil IV – Audit

### 17. Audit Event Types

Kernereignisse:

```text
entity_created
entity_revised
entity_archived
entity_deleted
source_imported
job_started
job_failed
backup_completed
restore_started
migration_completed
security_denied
plugin_permission_changed
external_access
```

---

### 18. Sanitized Summary

`sanitized_summary` ist optional und darf keine geschützten Details in einen ungeschützten Logbereich kopieren.

---

### 19. Audit Target

Ein AuditEvent darf mehrere Targets referenzieren. Dadurch muss ein Multi-Entity-Commit nicht durch inhaltliche Duplikate in jedem Event erklärt werden.

---

### 20. Result

Mindestens:

```text
success
failure
partial
denied
cancelled
```

---

### 21. Reason Code

Maschinenlesbare Codes ermöglichen Diagnose ohne sensitive Freitexte.

---

### 22. Append-only Semantik

AuditEvents werden nicht umgeschrieben. Fehlerhafte Auditmetadaten werden durch ein neues Korrekturevent dokumentiert.

---

## Teil V – Commit-Historie

### 23. CommitRecord

Jeder autoritative Write besitzt `commit_id` und monotones `commit_seq`.

---

### 24. Commit versus Revision

Ein Commit kann mehrere Revisionen enthalten. Eine Revision gehört genau zu dem Commit, in dem sie bestätigt wurde.

---

### 25. Change Feed

`commit_changes` ist der maschinenlesbare Änderungsstrom für Derived State und Projektionen.

---

### 26. Commit Reason

Der Commit kann einen allgemeinen Anlass besitzen, während einzelne ProvenanceRecords detailliertere Herkunft enthalten.

---

### 27. Transaction Visibility

Uncommitted Änderungen werden weder im Audit als erfolgreich noch im Change Feed als gültig dargestellt.

---

## Teil VI – Revisionshistorie

### 28. Immutable Revision

Eine bestätigte Revision ist unveränderlich.

---

### 29. Parent Chain

`parent_revision_id` bildet die direkte Vorgängerkette. Bei Merge können zusätzliche Provenance Inputs mehrere Ursprungsversionen referenzieren.

---

### 30. Current Head

`entity_heads` zeigt auf die aktuelle Revision; historische Referenzen bleiben auf alten Revision IDs stabil.

---

### 31. History View

Die UI kann pro Entität zeigen:

- Zeit;
- Akteur;
- Change Kind;
- Reason;
- ModelSignature falls vorhanden;
- Diff zur Vorgängerrevision.

---

### 32. Diff ist Derived

Text-/JSON-Diffs können on-demand berechnet und gecacht werden. Sie sind nicht zwingend autoritative Daten.

---

## Teil VII – Benutzerkorrektur

### 33. User Correction

Eine Benutzerkorrektur erzeugt eine neue Revision mit `created_by_actor=user`.

---

### 34. Vorrang

Spätere automatische Läufe behandeln explizite Benutzerkorrekturen als starke bestehende Evidenz über ATHENAs gewünschten kanonischen Zustand.

---

### 35. Keine ewige Sperre

Benutzerkorrektur bedeutet nicht, dass das Wissen niemals wieder verändert werden darf. Neue Evidenz oder erneute Benutzerentscheidung kann eine neue Revision erzeugen.

---

### 36. Visible Source Conflict

Wenn externe Quellen weiterhin der Benutzerkorrektur widersprechen, darf ATHENA diesen Konflikt sichtbar halten, statt Quellen zu löschen.

---

## Teil VIII – Ableitungsketten

### 37. Lineage Granularity

Nicht jeder technische CPU-Schritt benötigt einen ProvenanceRecord. Persistiert werden semantisch oder reproduzierbarkeitsrelevante Stages.

---

### 38. OCR Lineage

Beispiel:

```text
Source Blob
→ OCR ProcessingRun
→ SourceRepresentation
→ SourceAnchor
→ Claim Extraction
→ Claim
```

---

### 39. Research Lineage

Exhaustive Research speichert:

- ResearchScope;
- Snapshot;
- CandidateSet;
- verarbeitete Revisionen;
- Partial Syntheses;
- finale Synthese.

Damit ist der Ergebnisweg rekonstruierbar, ohne verborgenes Chain-of-Thought speichern zu müssen.

---

### 40. Keine Chain-of-Thought-Pflicht

ATHENA archiviert keine geheimen Modellreasoning-Tokens als Provenienzanforderung. Nachvollziehbarkeit basiert auf Inputs, Outputs, Modellsignatur, Pipeline und expliziten strukturierten Begründungen.

---

## Teil IX – Protected Audit

### 41. Protection Scope

Provenance/Audit, deren Metadaten selbst vertraulich sind, erhalten einen passenden Protection Scope.

---

### 42. Locked View

Im gesperrten Zustand darf maximal neutral sichtbar sein:

```text
geschützte Aktion vorhanden
```

wenn dies strukturell nötig ist.

---

### 43. No Secret in Error

Fehlermeldungen und Audit Reason Strings dürfen keine entschlüsselten Inhalte in ungeschützte Logs kopieren.

---

## Teil X – Löschung

### 44. Audit nach Delete

Nach endgültiger Löschung bleibt nur minimaler Nachweis:

- ID;
- Entitätstyp;
- Löschzeit;
- Autorität/Regel;
- technische Ergebniskennung.

Kein Payload.

---

### 45. Provenance Purge

Provenienz, die ausschließlich den gelöschten Inhalt reproduzieren würde, wird ebenfalls minimiert beziehungsweise gelöscht.

---

### 46. DeletionMarker

Restore-Schutz wird über DeletionMarker/Backup Ledger gewährleistet, nicht durch Aufbewahrung einer Inhaltskopie.

---

### 47. Shared Provenance

Wenn ein ProvenanceRecord mehrere überlebende Entitäten betrifft, wird er nicht blind gelöscht. Sensitive gelöschte Teile werden minimiert und surviving refs erhalten.

---

## Teil XI – Aufbewahrung

### 48. Default

Audit/Provenienz werden grundsätzlich langfristig erhalten, weil sie Teil der Vertrauenswürdigkeit von ATHENA sind.

---

### 49. Technical Logs

Nicht mit Audit verwechseln: Debug-/Performance-Logs dürfen deutlich kürzere Rotation besitzen.

---

### 50. Retention Rule

Benutzerkonfigurierte Löschregeln können auch Auditbereiche betreffen, solange notwendige Integritäts- und Restore-Invarianten gewahrt bleiben und der Effekt verständlich angezeigt wird.

---

## Teil XII – Export und Portabilität

### 51. Export

Vollständiger Export enthält ProvenanceRecords, AuditEvents und Revisionsketten in dokumentierter strukturierter Form.

---

### 52. Stable References

Exportreferenzen verwenden UUIDs und Revision IDs, keine internen SQLite rowids.

---

### 53. Model Signature Export

ModelSignatures werden mit exportiert, auch wenn das zugehörige Modell auf dem Zielsystem nicht mehr installiert ist.

---

### 54. Audit Integrity

Exports dürfen optional eine Hashkette beziehungsweise Manifestprüfung besitzen, damit unbeabsichtigte Beschädigung erkennbar wird.

---

## Teil XIII – UI und Erklärung

### 55. Why do you know this

ATHENA kann aus Provenienz eine verständliche Antwort erzeugen:

```text
Diese Information stammt aus Dokument X, Seite 4,
wurde am ... extrahiert und später von dir korrigiert.
```

---

### 56. Why did this change

Revision History zeigt, warum die aktuelle Fassung von der vorherigen abweicht.

---

### 57. Model Disclosure

Bei modellgenerierter Wissensänderung kann die UI Modell/Version anzeigen. Bei Benutzeränderung wird kein Modell vorgetäuscht.

---

## Teil XIV – Tests

### 58. User Provenance Test

Benutzerrevision ohne ModelSignature muss validieren und vollständig nachvollziehbar sein.

---

### 59. Model Provenance Test

Primärmodellrevision ohne ModelSignature oder ProcessingRun wird abgewiesen.

---

### 60. Rollback Test

Fehler in einer Multi-Entity-Transaktion darf weder AuditSuccess noch CommitChanges hinterlassen.

---

### 61. Historical Reference Test

Eine Source/Knowledge-Revision wird später aktualisiert. Historische Provenienz muss weiterhin exakt auf die alte Revision zeigen.

---

### 62. Delete Shadow Copy Test

Gelöschten Text nach Purge in Audit/Provenance/Logs suchen. Kein Inhaltsfragment darf als versteckte Kopie verbleiben.

---

### 63. Protected Audit Test

Protected Event bei gesperrtem Scope: UI und unprotected Logs dürfen keine vertraulichen Titel zeigen.

---

### 64. Export Test

Export → neue Installation. Provenienzgraph und Revisionen müssen dieselben IDs referenzieren.

---

### 65. Processing Drift Test

Langer Job wird mit anderer ModelSignature fortgesetzt. Drift muss sichtbar/gestoppt werden.

---

### 66. Audit Failure Test

Ein fehlgeschlagener Backup- oder Migrationsjob darf nicht als success erscheinen.

---

### 67. Abschluss

Das Kapitel ist bestanden, wenn ATHENA seine Wissensgeschichte erklären kann, ohne den Benutzer hinter einer Black Box zu verstecken und ohne Audit zum heimlichen zweiten Datenarchiv zu machen.

---

## Nächster Schritt

**Beta Kapitel 08 – Primärmodell und Provider-System**.
