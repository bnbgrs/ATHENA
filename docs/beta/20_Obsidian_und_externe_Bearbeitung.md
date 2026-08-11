# ATHENA Beta Specification v0.1 – Kapitel 20

## Obsidian und externe Bearbeitung

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)
**Core API:** [Beta Kapitel 19](19_Core_API_und_zukuenftige_Clients.md)

---

## Teil I – Rolle von Obsidian

### 1. Ziel

Obsidian ist in ATHENA v1 eine optionale menschenlesbare Knowledge-Projektion und Bearbeitungsoberfläche.

Es ist **nicht** die alleinige Source of Truth und nicht erforderlich, damit ATHENA funktioniert.

---

### 2. Optionalität

Ist Obsidian nicht installiert, funktionieren:

- Chat;
- Knowledge;
- Search;
- Memory;
- Jobs;
- Backup;
- Recovery

weiter.

---

### 3. Projection, nicht Mirror DB

Markdown-Dateien repräsentieren ausgewählte Knowledge-/Concept-Note-Daten. Sie müssen nicht jede interne technische Entität spiegeln.

---

### 4. Stable ID

Front Matter enthält `athena_id`. Dateiname und Ordner sind Darstellung.

---

## Teil II – Projection Root

### 5. Root

Obsidian-Projektionen liegen unter konfiguriertem `projection_root`.

---

### 6. Vault

Der Benutzer kann einen bestehenden oder separaten Vault wählen. ATHENA schreibt nur in ausdrücklich konfigurierte Bereiche.

---

### 7. Managed Area

Default:

```text
ATHENA/
```

als klar markierter verwalteter Bereich innerhalb eines Vaults.

---

### 8. Editable Areas

Dateien werden als:

```text
managed_readonly
managed_editable
user_owned
```

klassifiziert.

---

## Teil III – Markdownformat

### 9. UTF-8

Projektionen verwenden UTF-8 und normalisierte Line Endings.

---

### 10. Front Matter

Mindestens:

```yaml
athena_id: "..."
entity_type: knowledge_unit
revision_id: "..."
revision_no: 4
projection_version: 1
```

---

### 11. Human Fields

Weitere menschenlesbare Felder können enthalten:

```yaml
title:
project:
status:
created:
updated:
```

Sie sind Projektion und müssen gegen Core-Schema gemappt werden.

---

### 12. Body

Der Body ist lesbar, auch wenn ATHENA nicht verfügbar ist.

---

### 13. Internal IDs

IDs werden nicht unnötig im Fließtext sichtbar gemacht, solange Front Matter und Links ausreichen.

---

## Teil IV – Dateinamen

### 14. Slug

Dateiname wird aus Titel/Typ menschenlesbar erzeugt.

---

### 15. Collision

Namenskollision wird mit kurzer neutraler ID-Suffixlösung behandelt.

---

### 16. Rename

Manuelles Umbenennen ändert nicht die ATHENA-ID.

---

### 17. Illegal Characters

OS-inkompatible Zeichen werden nur im Dateinamen normalisiert, nicht im kanonischen Titel.

---

## Teil V – Links

### 18. ATHENA Links

Beziehungen können als Obsidian-Wikilinks projiziert werden.

---

### 19. Resolution

Linkauflösung basiert intern auf `athena_id`, nicht allein auf Dateiname.

---

### 20. Broken File Link

Wenn Benutzer Datei verschiebt/umbenennt, Projection Reconciler kann sie über Front Matter wiederfinden.

---

### 21. External Note Link

Links zu user-owned Notizen dürfen gespeichert werden, werden aber nicht automatisch als kanonische Knowledge-Entity interpretiert.

---

## Teil VI – Projection Writer

### 22. Change Feed

Projection Writer konsumiert `commit_changes`.

---

### 23. Atomic Write

Dateiupdate:

```text
temp file
↓
flush
↓
atomic replace
```

soweit Dateisystem dies unterstützt.

---

### 24. Write Stamp

Projection Writer hält eine technische Write Stamp/Hash, damit eigene Änderungen nicht als externe User Edits zurückimportiert werden.

---

### 25. Batching

Viele Änderungen werden gebatcht und mit Backpressure auf langsamen Vaults geschrieben.

---

### 26. Failure

Projection Failure verändert kein kanonisches Knowledge. Job bleibt retrybar.

---

## Teil VII – Externe Bearbeitung

### 27. Watch

Editable Managed Files werden auf externe Änderungen überwacht.

---

### 28. Debounce

Editoren erzeugen häufig mehrere Saveevents. Reconciler wartet ein Stabilitätsfenster.

---

### 29. Parse

Vor Import werden Front Matter, `athena_id`, Revision und Markdownstruktur validiert.

---

### 30. Expected Revision

Enthält Datei Revision 5, Core ist inzwischen Revision 6:

```text
conflict
```

kein blindes Overwrite.

---

### 31. User Actor

Eine vom Benutzer in Obsidian vorgenommene semantische Änderung wird als Benutzeränderung gespeichert. Provenienz kann `client=obsidian_projection` nennen.

---

## Teil VIII – Conflict Workflow

### 32. Three-way Merge

Wenn möglich verwendet ATHENA:

```text
exported base revision
current canonical revision
edited file
```

für einen Three-way Diff.

---

### 33. Non-conflicting

Nicht überlappende einfache Änderungen dürfen automatisch zusammengeführt werden, wenn eindeutig.

---

### 34. Semantic Conflict

Inhaltlich kollidierende Änderungen werden dem Benutzer gezeigt.

---

### 35. Conflict File

ATHENA schreibt keine kryptischen Git-Conflictmarker in die kanonische Note. Optional kann eine separate lokale Conflict-Copy erzeugt werden.

---

### 36. Resolution

Nach Benutzerentscheidung entsteht eine neue canonical Revision und Projektion wird aktualisiert.

---

## Teil IX – Neue manuelle Dateien

### 37. No ID

Neue Datei ohne `athena_id` wird als Importkandidat behandelt.

---

### 38. Import UI

Benutzer kann wählen:

- neue KnowledgeUnit;
- Concept Note;
- Source;
- nicht importieren.

---

### 39. No Filename Merge

Ähnlicher Dateiname führt nicht automatisch zum Merge mit bestehender Entity.

---

### 40. Assigned ID

Nach erfolgreichem Import schreibt ATHENA die neue stabile ID in Front Matter.

---

## Teil X – Löschung

### 41. File Delete

Löscht Benutzer eine Managed-Datei, wird **nicht sofort** die canonical Entity gelöscht.

---

### 42. Delete Intent

Reconciler zeigt:

```text
Datei wurde entfernt.
Auch aus ATHENA löschen?
Projektion neu erzeugen?
```

---

### 43. Canonical Delete

Erst explizite Bestätigung beziehungsweise definierte Editable-Delete-Policy startet den normalen Löschworkflow.

---

### 44. ATHENA Delete

Wird Entity in ATHENA gelöscht, entfernt Projection Writer die zugehörige Datei beziehungsweise markiert sie entsprechend.

---

## Teil XI – Protected Content

### 45. Default

Protected Content wird standardmäßig **nicht** als unverschlüsseltes Markdown in einem normalen Obsidian Vault projiziert.

---

### 46. Explicit Plaintext Export

Nur ausdrücklich bestätigte Klartextprojektion kann erlaubt werden und wird als Sicherheitsrisiko gekennzeichnet.

---

### 47. No Locked Metadata

Normale Vaultdateien dürfen protected Titel/Inhalte nicht leaken.

---

## Teil XII – Sources und Attachments

### 48. Source Projection

Originalquellen müssen nicht in den Vault dupliziert werden.

---

### 49. References

Concept Notes können menschenlesbare Links/Source-Citations enthalten.

---

### 50. Attachment Copy

Optionales Kopieren von Attachments in den Vault ist eine Projektion und keine neue Source of Truth.

---

### 51. Move

Vaultattachment-Move ändert nicht den Raw-Archive-Blob.

---

## Teil XIII – Obsidian Plugins

### 52. No Dependency

ATHENA setzt kein spezielles Obsidian-Plugin voraus, um sein Kernwissen zu lesen.

---

### 53. Optional Plugin

Ein späteres ATHENA-Obsidian-Plugin kann Komfortfunktionen wie Entity-Picker oder Statusanzeige ergänzen.

---

### 54. No Direct DB

Auch ein Obsidian-Plugin greift über Core API zu, nicht auf SQLite.

---

## Teil XIV – Portabilität

### 55. Readable Alone

Ein exportierter Knowledge-Projektionsordner bleibt ohne ATHENA weitgehend verständlich.

---

### 56. Front Matter Docs

Das Projection-Front-Matter-Schema wird dokumentiert.

---

### 57. Future Editor

Andere Markdowneditoren können dieselbe Projektion verwenden.

---

## Teil XV – Tests

### 58. Rename Test

Managed File umbenennen. `athena_id` bleibt; keine neue KnowledgeUnit.

---

### 59. Move Test

Datei in Unterordner verschieben. Reconciler findet sie per ID.

---

### 60. Concurrent Edit Test

ATHENA Revision 6, externe Datei basiert auf 5. Conflict statt overwrite.

---

### 61. Own Write Loop Test

Projection Writer speichert; Watcher darf denselben Write nicht als neue Userrevision importieren.

---

### 62. New File Test

Datei ohne ID wird Importkandidat, nicht Auto-Merge.

---

### 63. Delete File Test

Datei löschen → keine sofortige canonical Löschung.

---

### 64. Protected Test

Protected Entity darf nicht automatisch als plaintext Markdown auftauchen.

---

### 65. Obsidian Missing Test

Vault offline/nicht vorhanden. Core läuft; ProjectionJob wartet.

---

### 66. Roundtrip Test

KnowledgeUnit exportieren, Body extern editieren, importieren. Neue Revision + User Provenance.

---

### 67. Abschluss

Die Obsidian-Integration ist bestanden, wenn Markdown langfristig nützlich und editierbar bleibt, ohne dass Dateinamen, Watcherevents oder externe Editoren ATHENAs canonical Versionierung umgehen können.

---

## Nächster Schritt

**Beta Kapitel 21 – Backup und Restore**.
