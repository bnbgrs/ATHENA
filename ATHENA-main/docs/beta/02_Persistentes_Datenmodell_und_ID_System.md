# ATHENA Beta Specification v0.1 – Kapitel 02

## Persistentes Datenmodell und ID-System

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Technische Basis:** [Beta Kapitel 01 – Systemarchitektur und technische Basis](01_Systemarchitektur_und_Technische_Basis.md)
**Zweck:** Verbindliche Definition der persistenten Entitäten, Identitäten, Revisionen, Referenzen, Provenienzketten und langlebigen Betriebszustände von ATHENA

---

## 1. Ziel dieses Kapitels

Dieses Kapitel definiert das **logische persistente Datenmodell** von ATHENA v1.

Es legt fest:

- welche langlebigen Entitäten existieren;
- welche IDs sie besitzen;
- wie Identitäten über Jahre stabil bleiben;
- wie Änderungen versioniert werden;
- wie Benutzeränderungen und Modelländerungen unterschieden werden;
- wie Originalquellen, Chunks und Evidenz adressiert werden;
- wie Wissen, Personal Memory und Raw Archive getrennt bleiben;
- wie Provenienz und Audit modelliert werden;
- wie Jobs, Checkpoints und Research-Snapshots persistent fortgesetzt werden;
- wie Löschung verhindert, dass Daten über Cache, Index oder Restore zurückkehren;
- wie Daten später exportiert, migriert und auf neue Speicherorte verschoben werden können.

Die physische Umsetzung in konkrete SQLite-Tabellen, Indizes, Dateilayouts und Migrationen wird in **Beta Kapitel 03 – Storage, Datenbanken und Migrationen** festgelegt.

> **Kapitel 02 definiert die Semantik und die Invarianten des Datenmodells. Kapitel 03 darf diese Semantik technisch abbilden, aber nicht verändern.**

---

## 2. Normative Hierarchie

Für dieses Kapitel gilt:

1. ATHENA Alpha v2.0.1 besitzt Vorrang.
2. Beta Kapitel 01 definiert die technische Gesamtarchitektur.
3. Dieses Kapitel konkretisiert Persistenz, Identität, Versionierung und Datenbeziehungen.
4. Spätere Beta-Kapitel dürfen zusätzliche Felder oder spezialisierte Entitäten ergänzen, solange sie die hier definierten Invarianten nicht stillschweigend brechen.

Ein späteres Implementierungsdetail darf insbesondere nicht:

- Benutzerautorität umgehen;
- Personal Memory mit Knowledge verschmelzen;
- Raw Archive als bloße Knowledge-Stufe behandeln;
- Originalquellen durch Interpretationen ersetzen;
- Modellsignaturen für Benutzeränderungen erfinden;
- stabile IDs durch Dateipfade ersetzen;
- Audit als Schattenkopie gelöschter Inhalte missbrauchen;
- Durable Operational State als beliebig löschbaren Cache behandeln.

---

## 3. Geltungsbereich

Das Kapitel umfasst drei persistente Zustandsklassen:

```text
ATHENA Persistent Data
+
Durable Operational State
+
Derived State
```

Diese Klassen besitzen unterschiedliche Schutz- und Wiederherstellungsregeln.

---

## 4. ATHENA Persistent Data

**ATHENA Persistent Data** ist der autoritative langlebige Systemzustand.

Er besteht aus fünf logisch getrennten Domänen:

```text
ATHENA Persistent Data
│
├── Knowledge
├── Personal Memory
├── Raw Archive
├── Audit & Provenance
└── Configuration
```

Keine dieser Domänen ist lediglich ein Cache der anderen.

---

## 5. Autorität der fünf persistenten Domänen

Die fünf Domänen besitzen unterschiedliche Autorität:

- **Knowledge** ist die autoritative Quelle für kanonisches semantisches Wissen.
- **Personal Memory** ist die autoritative Quelle für langfristige Zusammenarbeitseinstellungen und Präferenzen.
- **Raw Archive** ist die autoritative Quelle für gemäß Aufbewahrungsregeln erhaltene Originalquellen.
- **Audit & Provenance** ist die autoritative Quelle für Herkunft, Verarbeitung und relevante Änderungshistorie.
- **Configuration** ist die autoritative Quelle für persistente Benutzer- und Systemkonfiguration.

Sie dürfen einander referenzieren, aber nicht miteinander verschmelzen.

---

## 6. Durable Operational State

**Durable Operational State** enthält Zustände, die technisch-operativ sind, aber bis zu ihrer erfolgreichen Verarbeitung **nicht rekonstruierbar** sein können.

Beispiele:

- persistente Jobs;
- Checkpoints;
- noch nicht bestätigte Imports;
- Pending Writes;
- lokale Offline-Puffer;
- Sync-Outbox-Einträge;
- Research Scope;
- Candidate Sets während langlaufender Forschung;
- Resume-Metadaten;
- Commit- und Idempotency-Zustände.

Diese Daten dürfen nicht wie Cache behandelt werden.

---

## 7. Derived State

**Derived State** enthält vollständig rekonstruierbare technische Daten.

Beispiele:

- Embeddings;
- Volltextindizes;
- Vektorindizes;
- Ranking-Caches;
- Vorschaudaten;
- temporäre Retrieval-Caches;
- rekonstruierbare Suchstatistiken.

Derived State darf gelöscht und neu aufgebaut werden, sofern keine nicht rekonstruierbare Information ausschließlich dort vorhanden ist.

---

## 8. Grundsatz: Identität ist nicht Speicherort

Kein ATHENA-Objekt wird über einen Dateipfad, Laufwerksbuchstaben oder Tabellen-Row-ID dauerhaft identifiziert.

Nicht zulässig:

```text
D:\ATHENA\wissen\projekt-a.md
```

als Identität einer Wissenseinheit.

Zulässig:

```text
knowledge://unit/<stable-id>
```

Der physische Speicherort darf sich ändern, ohne dass die Objektidentität oder Beziehungen brechen.

---

## 9. Grundsatz: Identität ist nicht Inhalt

Eine Entitäts-ID wird nicht aus Titel, Dateiname oder aktuellem Inhalt abgeleitet.

Eine Wissenseinheit bleibt dieselbe Entität, wenn:

- ihr Titel korrigiert wird;
- ihr Text geändert wird;
- sie archiviert wird;
- ihre Beziehungen erweitert werden;
- ihr physischer Speicherort wechselt.

Inhaltliche Änderungen erzeugen **Revisionen**, nicht neue Identitäten.

---

## 10. Grundsatz: Original und Interpretation bleiben getrennt

Eine Originalquelle ist nicht ihre Zusammenfassung.

Ein Claim ist nicht seine Evidenz.

Eine Interpretation ist nicht das Original.

Eine Concept Note ist nicht automatisch eine Originalquelle.

Diese Ebenen erhalten getrennte IDs und getrennte Provenienz.

---

## 11. Grundsatz: Semantische und technische Daten werden getrennt

Ein Embedding darf nicht die einzige Darstellung einer Wissenseinheit sein.

Ein Suchindex darf nicht die einzige Kopie eines Chunks sein.

Ein Cache darf nicht die einzige Kopie eines Pending Imports sein.

Semantische und nicht rekonstruierbare Daten müssen unabhängig von Derived State erhalten bleiben.

---

## 12. Namenskonventionen

Logische Feldnamen verwenden:

```text
snake_case
```

Entitätsnamen verwenden:

```text
PascalCase
```

Beispiele:

```text
KnowledgeUnit
knowledge_id

PersonalMemoryEntry
memory_id

ProvenanceRecord
provenance_id
```

Enum-Werte verwenden:

```text
lower_snake_case
```

---

## 13. Globale ID-Entscheidung

Alle dauerhaft adressierbaren ATHENA-Entitäten erhalten eine **UUIDv7** als stabile technische Identität.

Beispiel:

```text
0198a7b2-8f8e-7b31-9cf5-1f22a4d6b771
```

UUIDv7 wird gewählt, weil es:

- ohne zentrale Koordinationsinstanz erzeugt werden kann;
- praktisch kollisionsfrei ist;
- zeitlich grob sortierbar ist;
- keine Dateipfade oder Benutzerdaten codiert;
- zukünftige Mehrgeräte-Szenarien unterstützt;
- bei Export und Migration stabil bleibt.

---

## 14. Externe Darstellung von IDs

Die kanonische Textdarstellung einer ID ist:

```text
lowercase UUID mit Bindestrichen
```

Beispiel:

```text
0198a7b2-8f8e-7b31-9cf5-1f22a4d6b771
```

Implementierungen dürfen UUIDs intern binär speichern, solange die kanonische Darstellung verlustfrei wiederhergestellt werden kann.

---

## 15. Keine semantische Bedeutung in UUIDs

Eine UUID darf nicht so interpretiert werden, als enthielte sie:

- Benutzeridentität;
- Projektname;
- Sicherheitsstufe;
- Dateityp;
- Wissenskategorie;
- Modellname.

Die Entitätsart wird separat gespeichert beziehungsweise durch die logische URI bestimmt.

---

## 16. Zeitkomponente von UUIDv7

Die Zeitkomponente von UUIDv7 dient lediglich:

- effizienter Sortierung;
- Indexlokalität;
- grober Erstellungsreihenfolge.

Sie ersetzt **keinen expliziten Zeitstempel**.

Jede relevante Entität besitzt weiterhin `created_at`.

---

## 17. ID-Erzeugung

IDs werden vom ATHENA Core beziehungsweise einer dafür vorgesehenen Core-Komponente erzeugt.

Nicht autorisierte Plugins, Modelle oder externe Quellen dürfen keine kanonischen IDs eigenmächtig festlegen.

Bei Import externer Daten kann eine externe ID zusätzlich gespeichert werden:

```text
external_id
external_namespace
```

Sie ersetzt niemals die ATHENA-ID.

---

## 18. IDs werden niemals wiederverwendet

Wird ein Objekt endgültig gelöscht, darf seine ID nicht später für ein anderes Objekt verwendet werden.

Dies gilt auch dann, wenn:

- derselbe Titel erneut auftaucht;
- dieselbe Datei erneut importiert wird;
- derselbe Text erneut erzeugt wird.

---

## 19. Primäre ID-Felder

Mindestens folgende IDs sind Teil des v1-Datenmodells:

```text
knowledge_id
claim_id
interpretation_id
source_id
blob_id
chunk_id
anchor_id
chat_id
message_id
memory_id
relation_id
project_id
concept_note_id
revision_id
provenance_id
audit_event_id
model_signature_id
processing_run_id
processing_stage_id
commit_id
job_id
checkpoint_id
candidate_set_id
research_scope_id
configuration_id
retention_rule_id
deletion_marker_id
protection_scope_id
outbox_item_id
```

Weitere IDs können später ergänzt werden.

---

## 20. Interne Datenbank-IDs

Eine physische Datenbank darf zusätzliche interne technische Schlüssel verwenden, beispielsweise:

```text
row_id
```

Solche Schlüssel:

- sind niemals API-Identität;
- werden nicht exportiert;
- dürfen nicht in Markdown-Projektionen als Referenz verwendet werden;
- dürfen sich bei Migration ändern.

Nur die stabilen ATHENA-IDs sind systemübergreifend verbindlich.

---

## 21. Logische URIs

ATHENA verwendet logische URIs für lesbare, domänenbezogene Referenzen.

Beispiele:

```text
knowledge://unit/<knowledge_id>
knowledge://claim/<claim_id>
knowledge://interpretation/<interpretation_id>

memory://entry/<memory_id>

archive://source/<source_id>
derived://chunk/<chunk_id>
archive://chat/<chat_id>
archive://message/<message_id>

audit://provenance/<provenance_id>
audit://event/<audit_event_id>

config://entry/<configuration_id>

operational://job/<job_id>

Derived URIs wie `derived://chunk/<chunk_id>` sind ausschließlich technische Laufzeit-/Buildreferenzen. Sie dürfen nicht als langlebige kanonische Evidenzreferenz persistiert werden.
operational://checkpoint/<checkpoint_id>
operational://research-scope/<research_scope_id>
```

Diese URIs sind logische Referenzen und keine Netzwerkadressen.

---

## 22. EntityRef

Interne Core-Schnittstellen verwenden ein einheitliches Referenzkonzept:

```text
EntityRef
```

Logisch enthält es mindestens:

```text
entity_type
entity_id
```

Optional kann eine konkrete Revision adressiert werden:

```text
revision_id
```

Beispiel:

```json
{
  "entity_type": "knowledge_unit",
  "entity_id": "0198a7b2-8f8e-7b31-9cf5-1f22a4d6b771",
  "revision_id": "0198a7c0-1da1-7c90-a271-1fc1203a4974"
}
```

---

## 23. Current Reference versus Revision Reference

Eine Referenz ohne `revision_id` bedeutet:

> aktuelle gültige Revision dieser Entität

Eine Referenz mit `revision_id` bedeutet:

> exakt diese historische Revision

Für Provenienz und reproduzierbare Verarbeitung werden möglichst konkrete Revisionen referenziert.

---

## 24. Keine stillen Referenzverschiebungen

Wenn ein Job oder eine Research-Auswertung auf einer bestimmten Revision basiert, darf ein späteres Update des Objekts die historische Referenz nicht unsichtbar auf die neue Revision verschieben.

Deshalb speichern reproduzierbare Prozesse:

```text
entity_id
+
revision_id
```

---

## 25. Common Entity Metadata

Langlebige Entitäten besitzen soweit passend gemeinsame Metadaten:

| Feld | Bedeutung |
|---|---|
| `id` | stabile Entitäts-ID |
| `created_at` | Erzeugungszeitpunkt |
| `created_by_actor_id` | auslösender Akteur |
| `lifecycle_state` | aktueller Lebenszykluszustand |
| `current_revision_id` | aktuelle Revision, falls revisioniert |
| `protection_scope_id` | optionaler Schutzbereich |
| `schema_version` | Version des logischen Entitätsschemas |

Nicht jede Entität benötigt jedes Feld physisch in derselben Tabelle. Die Semantik muss jedoch erhalten bleiben.

`lifecycle_state` und `protection_scope_id` in dieser Übersicht bezeichnen den **aktuellen materialisierten Zustand**. Änderungen dieser Felder, die für historische `as-of`-Abfragen, Restore, Audit oder Security relevant sind, müssen selbst historisierbar sein. Die physische v1-Umsetzung verwendet dafür eine commit-sequenzierte `EntityStateHistory`; ein heutiger Registrywert darf den historischen Zustand einer alten Revision nicht rückwirkend verändern.

---

## 26. Zeitformat

Zeitstempel werden logisch in UTC gespeichert.

Kanonische externe Darstellung:

```text
RFC 3339 / ISO 8601 UTC
```

Beispiel:

```text
2026-08-10T12:34:56.123456Z
```

Die physische Datenbankdarstellung wird in Kapitel 03 entschieden.

---

## 27. Originale Zeitzonen

Wenn eine Quelle einen lokalen Zeitpunkt mit Zeitzone enthält, darf ATHENA diese Information nicht verlieren.

Zusätzlich zum normalisierten UTC-Zeitpunkt können gespeichert werden:

```text
original_time_text
original_timezone
time_precision
```

---

## 28. Zeitpräzision

ATHENA darf keine höhere zeitliche Präzision vortäuschen, als die Quelle tatsächlich besitzt.

Beispiele für `time_precision`:

```text
exact
second
minute
hour
day
month
year
approximate
unknown
```

---

## 29. Systemzeit und Gültigkeitszeit

ATHENA unterscheidet mindestens:

```text
system_time
```

Wann ATHENA die Information gespeichert oder geändert hat.

und:

```text
valid_time
```

Für welchen realen Zeitraum die Information gilt.

---

## 30. Temporale Gültigkeit

Zeitabhängige Wissensobjekte können speichern:

```text
valid_from
valid_to
```

Beide Werte sind optional.

Beispiel:

```text
Person A arbeitet bei Unternehmen X.
valid_from = 2023-04-01
valid_to   = 2026-06-30
```

Eine spätere Änderung darf die historische Gültigkeit nicht automatisch zerstören.

---

## 31. Revisionen

Änderbare autoritative Entitäten werden versioniert.

Eine Änderung überschreibt nicht einfach den bisherigen Inhalt.

Logisch entsteht:

```text
Stable Entity
│
├── Revision 1
├── Revision 2
├── Revision 3
└── ...
```

Die stabile Entitäts-ID bleibt gleich.

---

## 32. Revision-ID

Jede persistierte Revision erhält eine eigene:

```text
revision_id
```

als UUIDv7.

Zusätzlich besitzt sie:

```text
revision_no
```

beginnend bei `1`.

`revision_no` ist nur innerhalb einer Entität eindeutig.

---

## 33. Mindestfelder einer Revision

Eine Revision enthält mindestens:

| Feld | Bedeutung |
|---|---|
| `revision_id` | stabile ID dieser Revision |
| `entity_id` | stabile ID der Entität |
| `revision_no` | fortlaufende Revisionsnummer |
| `parent_revision_id` | direkte Vorgängerrevision, falls vorhanden |
| `created_at` | Zeitpunkt der Revision |
| `created_by_actor_id` | auslösender Akteur |
| `provenance_id` | Herkunft dieser Änderung |
| `schema_version` | Schema dieser Revision |
| `payload_hash` | Hash des kanonisch serialisierten Inhalts |
| `change_kind` | Art der Änderung |

---

## 34. Change Kind

Beispiele für `change_kind`:

```text
create
edit
correct
merge
split
reclassify
archive
restore
supersede
metadata_update
```

Eine endgültige Löschung ist kein normaler Edit und wird separat behandelt.

---

## 35. Revisionen sind unveränderlich

Eine einmal bestätigte Revision wird nicht nachträglich inhaltlich verändert.

Fehler werden durch eine neue Revision korrigiert.

Ausnahme sind ausschließlich technische Reparaturen, die nachweislich keine Semantik oder sichtbare Historie verändern. Solche Reparaturen müssen auditierbar bleiben.

---

## 36. Current Revision

Die stabile Entität verweist auf genau eine aktuelle Revision:

```text
current_revision_id
```

Dieser Zeiger darf nur innerhalb eines validierten atomaren Commits geändert werden.

---

## 37. Optimistic Concurrency

Schreiboperationen auf revisionierte Entitäten verwenden:

```text
expected_revision_id
```

oder äquivalent:

```text
expected_revision_no
```

Wenn sich die Entität zwischen Lesen und Schreiben geändert hat:

```text
write rejected
+
conflict detected
```

ATHENA verwendet kein stilles Last-Write-Wins für kanonische semantische Daten.

---

## 38. Konfliktbehandlung

Bei konkurrierenden Änderungen kann ATHENA:

- den Benutzer zur Entscheidung auffordern;
- Änderungen automatisch zusammenführen, wenn sie nachweislich nicht kollidieren;
- beide Varianten als Konfliktzustand erhalten;
- einen neuen semantischen Merge durch Benutzer oder Primärmodell durchführen lassen.

Keine Variante darf unbemerkt verloren gehen.

---

## 39. CommitRecord

Jede atomare autoritative Schreibtransaktion erhält einen:

```text
CommitRecord
```

mit:

```text
commit_id
commit_seq
committed_at
actor_id
operation_type
reason
```

`commit_id` ist eine UUIDv7.

`commit_seq` ist eine lokal monotone Sequenz für den v1-Core.

---

## 40. Bedeutung von commit_seq

`commit_seq` dient:

- Snapshot-Grenzen;
- inkrementeller Indexierung;
- Change Feeds;
- Recovery;
- Testbarkeit;
- Erkennung veralteter Derived-State-Daten.

`commit_seq` ist **keine globale Objektidentität** und darf nicht anstelle von UUIDs verwendet werden.

---

## 41. Atomare Commit-Grenze

Ein semantischer Write kann mehrere Domänen betreffen.

Beispiel:

```text
neue KnowledgeUnit
+
neue Revision
+
ProvenanceRecord
+
AuditEvent
+
Relationship
```

Diese Änderungen werden als eine logische Transaktion bestätigt.

Entweder:

```text
alles committed
```

oder:

```text
nichts committed
```

---

## 42. Akteursmodell

Jede relevante Änderung besitzt einen auslösenden Akteur.

ATHENA unterscheidet mindestens:

```text
user
primary_model
system
plugin
importer
external_client
```

Die konkrete Implementierung kann weitere Akteurstypen ergänzen.

---

## 43. Actor Identity

Ein Akteur besitzt eine stabile `actor_id`.

Für den lokalen Hauptbenutzer kann ATHENA einen festen internen Benutzerakteur erzeugen.

Die `actor_id` ist nicht zwingend eine reale personenbezogene Kennung.

Sie dient der internen Nachvollziehbarkeit.

---

## 44. Benutzer als Akteur

Direkte Benutzeränderungen werden eindeutig als:

```text
actor_type = user
```

protokolliert.

Sie benötigen **keine Modellsignatur**.

ATHENA darf niemals eine Modellsignatur hinzufügen, wenn kein Modell an der semantischen Entscheidung beteiligt war.

---

## 45. Primärmodell als Akteur

Wird eine semantische Änderung durch das aktive Primärmodell erzeugt, gilt:

```text
actor_type = primary_model
```

und die Provenienz enthält zwingend:

```text
model_signature_id
```

---

## 46. Systemprozesse als Akteur

Technische Aktionen können von:

```text
actor_type = system
```

ausgeführt werden.

Beispiele:

- Indexstatus aktualisieren;
- Checkpoint speichern;
- Blob verifizieren;
- Jobstatus verändern.

Ein Systemprozess darf dadurch keine autonome semantische Autorität erhalten.

---

## 47. Plugins als Akteur

Plugin-Aktionen werden als Plugin-Aktionen identifiziert.

Mindestens:

```text
actor_type = plugin
plugin_id
plugin_version
```

falls relevant.

Ein Plugin darf semantische Änderungen nur über die in Alpha und Kapitel 01 definierten Core-Grenzen veranlassen.

---

## 48. Importer als Akteur

Ein Importer darf technische Importobjekte erzeugen:

```text
Source
BlobRecord
SourceRepresentation
Derived SourceChunk Set
```

Er entscheidet nicht eigenständig, welche semantische Aussage kanonisches Wissen wird.

---

## 49. ModelSignature

Jeder semantisch relevante Modelllauf kann auf eine persistente:

```text
ModelSignature
```

verweisen.

Sie beschreibt die konkrete Modellkonfiguration, mit der eine Interpretation oder Wissensextraktion erzeugt wurde.

---

## 50. Pflichtfelder einer ModelSignature

Mindestens soweit tatsächlich bekannt:

| Feld | Bedeutung |
|---|---|
| `model_signature_id` | stabile Signatur-ID |
| `provider` | Backend beziehungsweise Provider |
| `model_identifier` | Modellname oder Modell-ID |
| `model_revision` | Version/Revision, falls bekannt |
| `quantization` | Quantisierung, falls relevant |
| `generation_parameters` | relevante Parameter |
| `context_configuration` | relevante Kontextkonfiguration |
| `created_at` | Erzeugung der Signatur |

Fehlende Werte werden als unbekannt gespeichert, nicht erfunden.

---

## 51. Wiederverwendung von ModelSignatures

Identische Modellkonfigurationen dürfen dieselbe ModelSignature referenzieren.

Die Signatur ist eine Beschreibung der Konfiguration, nicht eines einzelnen Modellaufrufs.

Einzelne Läufe werden über `ProcessingRun` dokumentiert.

---

## 52. ProcessingRun

Ein:

```text
ProcessingRun
```

repräsentiert einen konkreten reproduzierbaren Verarbeitungslauf.

Beispiele:

- Wissensextraktion;
- Dokumentzusammenfassung;
- Reinterpretation;
- Exhaustive Research;
- OCR-Pipeline;
- Embedding-Neuaufbau.

---

## 53. Pflichtfelder eines ProcessingRun

Mindestens:

```text
processing_run_id
run_type
started_at
finished_at
status
trigger_actor_id
pipeline_version
input_snapshot
configuration_hash
```

Falls ein Primärmodell beteiligt ist:

```text
model_signature_id
prompt_template_id
prompt_template_version
```

---

## 54. ProcessingStage

Langlaufende Verarbeitung wird in Stages unterteilt.

Jede Stage kann eine eigene:

```text
processing_stage_id
```

besitzen.

Beispiele:

```text
discover
extract
chunk
retrieve
rerank
interpret
synthesize
validate
persist
```

---

## 55. Processing Lineage

Processing Lineage verbindet:

```text
Input
↓
ProcessingRun
↓
ProcessingStage
↓
Output
```

Jeder provenance-relevante Output muss nachvollziehbar auf seine Inputs und Verarbeitung zurückgeführt werden können.

---

## 56. Keine versteckte Processing Drift

Ein ProcessingRun pinnt soweit relevant:

- Pipeline-Version;
- Modellkonfiguration;
- Prompt-Template;
- Chunking-Profil;
- Embedding-Konfiguration;
- Retrieval-Konfiguration.

Ändert sich eine dieser Grundlagen während eines unterbrochenen Jobs, muss ATHENA dies erkennen.

---

## Teil I – Raw Archive

## 57. Source

`Source` ist die logische Identität einer importierten oder erfassten Originalquelle.

Beispiele:

- Datei;
- Webseite als gespeicherter Snapshot;
- E-Mail;
- Bild;
- Audio;
- Video;
- Nachrichtendokument;
- Textimport;
- externe API-Antwort, sofern als Quelle archiviert.

Eine `Source` gehört zur **Raw-Archive-Domäne**.

---

## 58. Source-Pflichtfelder

Eine Source besitzt mindestens:

| Feld | Bedeutung |
|---|---|
| `source_id` | stabile Source-ID |
| `source_type` | Quellentyp |
| `created_at` | Erfassungszeit |
| `acquired_at` | Zeitpunkt der Aufnahme durch ATHENA |
| `original_name` | ursprünglicher Name, falls vorhanden |
| `mime_type` | Medientyp, falls bekannt |
| `blob_id` | Referenz auf Originaldaten, falls bytes-basiert |
| `content_hash` | Integrität/Deduplizierung, soweit zulässig |
| `source_uri` | ursprüngliche externe URI, falls vorhanden |
| `protection_scope_id` | Schutzbereich |
| `lifecycle_state` | Lebenszyklus |
| `provenance_id` | Erfassungsprovenienz |

---

## 59. Source-Type

Mindestens folgende logische Typen werden unterstützt:

```text
file
web_snapshot
email
text
image
audio
video
document
api_capture
chat_export
other
```

Die Liste ist erweiterbar.

---

## 60. Webquellen

Eine URL allein ist keine ausreichende Originalquelle.

Bei einer archivierten Webquelle speichert ATHENA soweit technisch möglich:

```text
URL
+
retrieved_at
+
gespeicherter Inhalt/Snapshot
+
HTTP-/Quellenmetadaten soweit relevant
```

Eine spätere Änderung der Webseite verändert den alten Snapshot nicht.

---

## 61. BlobRecord

Physische Originalbytes werden über einen:

```text
BlobRecord
```

adressiert.

Dieser trennt:

```text
Source identity
```

von:

```text
physical stored bytes
```

---

## 62. BlobRecord-Felder

Mindestens:

```text
blob_id
byte_length
media_type
storage_area
storage_locator
integrity_hash
encryption_state
created_at
verified_at
```

Der `storage_locator` ist austauschbar und darf nicht als Source-ID verwendet werden.

---

## 63. Content Hash

Für nicht geschützte Originaldaten wird standardmäßig ein kryptographischer Integritätshash gespeichert.

Die konkrete Hashfunktion wird in Kapitel 03 festgelegt.

Für geschützte Inhalte gelten zusätzliche Regeln:

- Hashwerte dürfen nicht unnötig im ungeschützten Metadatenraum liegen;
- Hashing darf keine Information über gesperrte Inhalte leaken;
- Integritätsprüfung muss trotzdem möglich bleiben.

---

## 64. Physische Deduplizierung

Identische Originalbytes dürfen physisch nur einmal gespeichert werden.

Mehrere Sources können auf denselben BlobRecord verweisen.

Beispiel:

```text
Source A ─┐
          ├── Blob X
Source B ─┘
```

Die Quellenidentitäten und ihre Provenienz bleiben trotzdem getrennt.

---

## 65. Semantische Deduplizierung ist etwas anderes

Gleiche oder ähnliche Bedeutung darf nicht allein aufgrund eines Hashes zusammengeführt werden.

Semantische Zusammenführung von Wissen benötigt eine semantische Entscheidung:

```text
Benutzer
oder
aktives Primärmodell
```

---

## 66. Originalbytes sind unveränderlich

Nach erfolgreicher Übernahme werden die Originalbytes eines BlobRecords nicht in-place verändert.

Eine geänderte Datei wird als neue Source beziehungsweise neue Source-Version aufgenommen.

---

## 67. Source-Versionen

Mehrere Versionen derselben externen Quelle werden durch Beziehungen verbunden.

Beispiel:

```text
Source v1
↓ superseded_by
Source v2
↓ superseded_by
Source v3
```

Jede gespeicherte Originalfassung behält ihre eigene `source_id`.

---

## 68. Source Family

Optional können zusammengehörige Source-Versionen über eine gemeinsame logische Gruppierung verbunden werden.

Die Gruppierung darf nicht dazu führen, dass einzelne Originalfassungen ihre eigene Identität verlieren.

---

## 69. SourceRepresentation

Aus einer Source können technische Repräsentationen entstehen.

Beispiele:

```text
extracted_text
ocr_text
transcript
normalized_text
thumbnail
page_images
```

Diese werden als `SourceRepresentation` behandelt.

---

## 70. SourceRepresentation und Autorität

Eine SourceRepresentation ist zunächst **technisch abgeleitet** und ersetzt niemals das Original.

Es gibt zwei Lifecyclefälle:

```text
disposable representation
→ vollständig rekonstruierbar
→ Derived State

retained representation
→ konkrete Fassung wird von langfristiger Provenienz/SourceAnchor referenziert
→ im Raw Archive dauerhaft erhalten, solange diese Provenienz bestehen muss
```

Wird eine Representation als Grundlage langfristiger Provenienz verwendet, müssen mindestens gespeichert und vor Derived-GC geschützt werden:

```text
representation_id
source_id
representation_type
processing_run_id
content_hash
created_at
retention_state = retained
```

Damit bleibt exakt nachvollziehbar, welche konkrete OCR-/Parser-/Transcriptfassung verwendet wurde, auch wenn spätere Processing-Versionen andere Ergebnisse erzeugen.

## 71. SourceChunk

`SourceChunk` ist eine **reproduzierbare Derived-State-Verarbeitungseinheit** einer eindeutig bestimmten SourceRepresentation.

Chunks dienen primär:

- Retrieval;
- LLM-Verarbeitung;
- großen Dokumenten;
- Indexierung;
- resumierbarer Verarbeitung.

Ein `SourceChunk` ist **keine autoritative Raw-Archive-Entität** und darf niemals der einzige langlebige Evidenzanker sein. Langfristige Herkunft verwendet `Source`, eine gegebenenfalls retained `SourceRepresentation` und `SourceAnchor`.

## 72. SourceChunk-Pflichtfelder

Ein persistierter Derived-Chunk benötigt mindestens:

```text
chunk_id
source_id
representation_id
chunk_index
chunking_profile_id
start_anchor
end_anchor
content_hash
created_at
processing_run_id
build_signature
```

`chunk_id` ist nur innerhalb des zugehörigen Chunk-Builds beziehungsweise solange das Derived Set existiert stabil. Dauerhafte Research-/Provenienzobjekte materialisieren zusätzlich die zugrunde liegenden stabilen Anchor-/Representation-Referenzen.

## 73. Chunk-ID ist nicht Inhalts-ID

Ein Chunk kann für technische Adressierung eine UUIDv7 erhalten.

Der `chunk_id` wird nicht ausschließlich aus dem Chunktext gehasht und ist **keine langlebige kanonische Objektidentität**.

Wenn sich Chunkgrenzen, Chunking-Algorithmus oder die zugrunde liegende Representation ändern, entsteht ein neues Derived Chunkset mit neuen Chunk-IDs.

## 74. Chunking-Versionierung

Jede Chunk-Erzeugung muss auf ein identifizierbares `chunking_profile_id` beziehungsweise eine versionierte Chunking-Konfiguration verweisen.

Sie umfasst soweit relevant:

- Algorithmus;
- Tokenizer;
- Zielgröße;
- Overlap;
- Strukturregeln;
- Version;
- verwendete SourceRepresentation.

Das ChunkingProfile ist reproduktionsrelevante technische Processing-/Configuration-Metadaten. Die daraus erzeugten Chunkrecords selbst bleiben Derived State.

## 75. Alte Chunks

Alte Chunksets dürfen jederzeit entfernt und aus den autoritativen Sources beziehungsweise retained SourceRepresentations neu aufgebaut werden.

Vor der Entfernung muss geprüft werden, dass kein noch laufender Job ausschließlich auf einer Derived `chunk_id` beruht. Persistente Research-/Jobzustände speichern deshalb stabile `SourceAnchor`-/`representation_id`-Referenzen beziehungsweise einen gepinnten Derived-Build, solange dieser für Resume benötigt wird.

Dauerhafte Claim-Evidenz referenziert niemals ausschließlich `chunk_id`.

## 76. SourceAnchor

`SourceAnchor` beschreibt eine stabile Stelle innerhalb einer Originalquelle beziehungsweise einer eindeutig bestimmten SourceRepresentation.

Ein Anchor erhält:

```text
anchor_id
```

---

## 77. Anchor-Typen

Mögliche Anchor-Typen:

```text
whole_source
text_range
page_range
page_region
audio_time_range
video_time_range
table_cell
message
structured_path
```

---

## 78. Text-Anchor

Ein Text-Anchor kann enthalten:

```text
representation_id
start_offset
end_offset
quoted_hash
```

Optional kann ein kurzer Preview-Text für die UI gespeichert werden, sofern Sicherheits- und Löschregeln dies erlauben.

---

## 79. Dokument-Anchor

Für Dokumente kann ein Anchor zusätzlich enthalten:

```text
page_start
page_end
bounding_box
```

Die genaue Geometriespezifikation wird nur verwendet, wenn das Dokumentformat dies sinnvoll unterstützt.

---

## 80. Audio- und Video-Anchor

Für zeitbasierte Medien:

```text
start_time_ms
end_time_ms
```

Optional:

```text
track
speaker
```

wenn zuverlässig vorhanden.

---

## 81. Evidenz darf Chunking überleben

Langfristige Claim-Evidenz soll nach Möglichkeit auf:

```text
source_id
+
anchor_id
```

verweisen.

Damit kann der Retrieval-Chunking-Algorithmus später geändert werden, ohne dass die ursprüngliche Evidenzbeziehung verloren geht.

---

## Teil II – Chats

## 82. Chat

Ein `Chat` ist eine persistierbare Gesprächseinheit im Raw Archive.

Pflichtfelder:

```text
chat_id
created_at
started_at
ended_at
archive_mode
lifecycle_state
protection_scope_id
```

---

## 83. Archive Mode

Mindestens:

```text
standard
temporary
do_not_store
```

`standard` folgt der in Alpha festgelegten Standardarchivierung.

`temporary` darf für die Dauer der aktuellen Sitzung und für ausdrücklich definierte Crash-/Resume-Anforderungen in einem **kontrollierten temporären Zustand mit TTL** persistiert werden. Es wird nach Ablauf dieses Lebenszyklus vollständig aus langfristigem Raw Archive und Derived State entfernt.

`do_not_store` ist strenger: Der vollständige Chat-Payload wird **nicht persistent gespeichert**. Er bleibt soweit technisch möglich RAM-only. Persistiert werden dürfen nur minimale technische Sitzungsdaten ohne Gesprächsinhalt, soweit für sicheren Betrieb unvermeidbar.

Der Benutzer kann aus `temporary` oder `do_not_store` ausdrücklich einzelne Knowledge- oder Personal-Memory-Einträge erzeugen. Diese erhalten Benutzeraktions-Provenienz; der vollständige Chat wird dadurch nicht heimlich archiviert.

## 84. ChatMessage

Jede persistierte Nachricht erhält eine:

```text
message_id
```

und gehört zu genau einem Chat.

---

## 85. ChatMessage-Pflichtfelder

Mindestens:

```text
message_id
chat_id
sequence_no
message_type
created_at
content
content_format
actor_id
revision_id
protection_scope_id
```

---

## 86. Message Type

Mindestens:

```text
user
assistant
tool_result
system_event
```

Interne Modellgedanken oder verborgenes Chain-of-Thought sind **kein erforderlicher Bestandteil des ATHENA-Archivs**.

ATHENA speichert die für den Benutzer sichtbaren beziehungsweise für Provenienz notwendigen Ergebnisse, nicht verborgene interne Reasoning-Tokens.

---

## 87. Nachrichtenbearbeitung

Wird eine bereits persistierte Nachricht bearbeitet, entsteht eine neue Revision.

Die ursprüngliche Revision bleibt historisch nachvollziehbar, solange keine Löschregel ihre Entfernung verlangt.

---

## 88. Nachrichtenanhänge

Anhänge werden nicht direkt als unstrukturierte Daten in ChatMessage eingebettet.

Stattdessen:

```text
ChatMessage
↓
Attachment Relationship
↓
Source
```

Dadurch bleiben Originaldateien im Raw Archive normal adressierbar.

---

## 89. Wissen aus Standard-Chats

Wissensextraktion aus archivierten Chats kann über folgende Provenienzkette erfolgen:

```text
ChatMessage
↓
SourceAnchor / Message Reference
↓
Interpretation
↓
KnowledgeUnit / Claim / PersonalMemoryEntry
```

---

## 90. Wissen aus temporären Chats

Ein temporärer Chat kann dennoch ausdrücklich freigegebenes Wissen erzeugen.

Dabei darf ATHENA nicht heimlich den vollständigen temporären Chat als Provenienz-Schattenkopie aufbewahren.

Zulässig ist beispielsweise:

```text
origin_actor = user
reason = explicit_user_memory_request
source_ref = null
```

oder eine andere minimale provenance-konforme Darstellung ohne Archivierung des verworfenen Gesprächsinhalts.

---

## 91. Chat-Löschung

Wird ein Chat endgültig gelöscht:

- werden persistierte Nachrichteninhalte gelöscht;
- werden Derived-State-Indizes bereinigt;
- werden nicht mehr zulässige Chunks/Embeddings entfernt;
- darf das Audit keine vollständige Schattenkopie behalten;
- verhindert ein minimaler DeletionMarker die Wiederbelebung durch Restore.

Bereits separat freigegebenes kanonisches Wissen wird nicht automatisch mitgelöscht, sofern der Benutzer nicht auch dessen Löschung verlangt.

---

## Teil III – Knowledge

## 92. KnowledgeUnit

`KnowledgeUnit` ist die grundlegende adressierbare semantische Einheit der Knowledge-Domäne.

Sie beschreibt **eine möglichst atomare dauerhaft relevante Wissenseinheit**.

Beispiele:

- Begriff;
- Entscheidung;
- Projektinformation;
- Ziel;
- Erfahrung;
- Verfahren;
- Ereignis;
- festgehaltene Beobachtung;
- kuratierte semantische Aussagegruppe.

---

## 93. KnowledgeUnit-Pflichtfelder

Stabile Entität:

```text
knowledge_id
current_revision_id
created_at
lifecycle_state
protection_scope_id
```

Revision:

```text
revision_id
revision_no
knowledge_kind
title
body
valid_from
valid_to
epistemic_status
provenance_id
created_by_actor_id
payload_hash
```

---

## 94. Knowledge Kind

Die v1-Kernmenge kann enthalten:

```text
concept
fact
decision
goal
idea
experience
procedure
event
project_knowledge
summary
other
```

Die Liste ist erweiterbar und darf nicht zu einer starren Ontologie werden.

---

## 95. Atomarität

Eine KnowledgeUnit soll nur so groß sein, dass sie:

- eigenständig referenzierbar;
- sinnvoll versionierbar;
- gezielt abrufbar;
- sinnvoll mit anderen Einheiten verknüpfbar

bleibt.

Große Synthesen gehören eher in Concept Notes.

---

## 96. KnowledgeUnit ist kein Claim-Ersatz

Eine KnowledgeUnit kann mehrere Claims enthalten oder auf mehrere Claims verweisen.

Beispiel:

```text
KnowledgeUnit:
Projektstatus ATHENA Beta

Claims:
- Alpha ist finalisiert.
- Beta Kapitel 01 existiert.
- Kapitel 02 ist in Bearbeitung.
```

Claims erlauben feinere Evidenz- und Widerspruchsmodellierung.

---

## 97. Claim

Ein `Claim` repräsentiert eine konkrete semantische Behauptung beziehungsweise attribuierte Aussage.

Er erhält eine stabile:

```text
claim_id
```

---

## 98. Claim-Pflichtfelder

Mindestens:

```text
claim_id
current_revision_id
claim_kind
statement
subject_ref
predicate
object_ref
attributed_to_ref
valid_from
valid_to
epistemic_status
protection_scope_id
```

Nicht jedes Claim benötigt zwingend strukturierte `subject/predicate/object`-Werte. Der natürliche Aussageinhalt in `statement` bleibt maßgeblich.

---

## 99. Claim Kind

Mindestens:

```text
factual_assertion
attributed_opinion
hypothesis
decision
intention
definition
observation
event_assertion
user_statement
other
```

---

## 100. Meinungen

Eine Meinung wird nicht als nackter Ereignisfakt modelliert.

Beispiel:

Nicht:

```text
Produkt X ist schlecht.
```

sondern:

```text
Claim Kind:
attributed_opinion

Statement:
Quelle A bewertet Produkt X negativ.

Attributed To:
Quelle A
```

---

## 101. Epistemic Status

Mögliche Kernwerte:

```text
asserted
supported
disputed
contradicted
retracted
superseded
uncertain
unknown
```

Der Status beschreibt ATHENAs aktuell gespeicherte Bewertungslage und ist selbst versionierbar.

Er ist keine ewige objektive Wahrheit.

---

## 102. Keine erzwungene Boolean-Wahrheit

Claims erhalten kein einfaches:

```text
true / false
```

als alleinige epistemische Darstellung.

ATHENA muss widersprüchliche, zeitabhängige und attribuierte Aussagen nebeneinander darstellen können.

---

## 103. ClaimEvidence

Die Verbindung zwischen Claim und Evidenz wird explizit gespeichert.

Logisch:

```text
Claim
↓
Evidence Link
↓
SourceAnchor / ChatMessage / andere Quelle
```

---

## 104. Evidence Relation

Ein Evidenzlink kann eine Rolle besitzen:

```text
supports
contradicts
mentions
contextualizes
originates
```

Damit kann dieselbe Quelle unterschiedliche Funktionen für verschiedene Claims besitzen.

---

## 105. Evidenz ist nachvollziehbar

Ein Claim mit externer Evidenz muss soweit möglich auf konkrete:

```text
source_id
+
anchor_id
```

beziehungsweise eine gleichwertig genaue Referenz zurückführbar sein.

---

## 106. Interpretation

`Interpretation` repräsentiert eine semantische Deutung, Zusammenfassung, Klassifikation oder Schlussfolgerung.

Sie erhält:

```text
interpretation_id
```

---

## 107. Interpretation-Pflichtfelder

Mindestens:

```text
interpretation_id
target_ref
interpretation_type
content
created_at
created_by_actor_id
provenance_id
model_signature_id
processing_run_id
protection_scope_id
```

`model_signature_id` und `processing_run_id` sind optional, wenn kein Modell beteiligt war.

---

## 108. Interpretation Type

Beispiele:

```text
summary
classification
explanation
inference
source_reading
contradiction_analysis
relevance_assessment
concept_synthesis
other
```

---

## 109. Mehrere Interpretationen

Eine Quelle oder Wissenseinheit kann mehrere Interpretationen besitzen.

Beispiel:

```text
Source
├── Interpretation Modell A
├── Interpretation Modell B
└── Benutzerinterpretation
```

Eine neue Interpretation löscht frühere Interpretationen nicht automatisch.

---

## 110. Reinterpretation

Ein Modellwechsel kann neue Interpretationen erzeugen.

Er verändert bestehende KnowledgeUnits oder Claims nur dann, wenn daraus ein kontrollierter semantischer Änderungsworkflow entsteht.

Reinterpretation ist nicht gleich automatische globale Wissensumschreibung.

---

## 111. Relationship

`Relationship` ist eine explizite Graphkante zwischen zwei adressierbaren Entitäten.

Sie erhält:

```text
relation_id
```

---

## 112. Relationship-Pflichtfelder

Mindestens:

```text
relation_id
source_ref
relation_type
target_ref
created_at
created_by_actor_id
provenance_id
lifecycle_state
protection_scope_id
```

---

## 113. Relation Types

Kernbeispiele:

```text
related_to
part_of
depends_on
supports
contradicts
supersedes
derived_from
mentions
about
belongs_to_project
version_of
same_as
different_from
```

Die Liste ist erweiterbar.

---

## 114. Keine semantische Beziehung ohne Herkunft

Automatisch erzeugte semantische Beziehungen benötigen Provenienz.

Wenn das Primärmodell eine Beziehung erzeugt:

```text
model_signature_id
```

muss über die Provenienz nachvollziehbar sein.

Direkte Benutzerbeziehungen benötigen keine Modellsignatur.

---

## 115. Symmetrische Beziehungen

Bestimmte Relationstypen können semantisch symmetrisch sein.

Beispiel:

```text
related_to
```

Andere sind gerichtet:

```text
depends_on
supersedes
part_of
```

Diese Eigenschaft wird durch die Relationstypdefinition festgelegt, nicht durch zufällige Duplikate.

---

## 116. Project

`Project` ist eine adressierbare semantische Gruppierung innerhalb der Knowledge-Domäne.

Es erhält:

```text
project_id
```

Ein Projekt ist **kein PersonalMemoryEntry**.

---

## 117. Project-Pflichtfelder

Mindestens:

```text
project_id
current_revision_id
name
description
project_state
created_at
protection_scope_id
provenance_id
```

---

## 118. Projektzuordnung

KnowledgeUnits, Claims, Concept Notes, Sources und Personal-Memory-Präferenzen können auf Projekte referenzieren.

Beispiel:

```text
PersonalMemoryEntry:
"Für Projekt ATHENA technische Antworten ausführlich."

scope_ref:
project://<project_id>
```

Das Projekt selbst bleibt Knowledge.

---

## 119. ConceptNote

`ConceptNote` ist eine kuratierte oder synthetisierte menschenlesbare Wissensdarstellung.

Sie erhält:

```text
concept_note_id
```

Sie kann mehrere KnowledgeUnits, Claims, Sources und Beziehungen zusammenführen.

---

## 120. ConceptNote-Pflichtfelder

Mindestens:

```text
concept_note_id
current_revision_id
title
body
created_at
created_by_actor_id
provenance_id
protection_scope_id
```

---

## 121. Concept Note als Synthese

Eine Concept Note darf neue Synthese enthalten.

Diese Synthese muss als Interpretation beziehungsweise semantische Benutzer- oder Modellleistung nachvollziehbar bleiben.

Eine Concept Note ersetzt die darunterliegenden Quellen nicht.

---

## Teil IV – Personal Memory

## 122. PersonalMemoryEntry

`PersonalMemoryEntry` repräsentiert eine langfristig relevante Zusammenarbeitseinstellung des Benutzers.

Es erhält:

```text
memory_id
```

Es gehört ausschließlich zur **Personal-Memory-Domäne**.

---

## 123. PersonalMemoryEntry-Pflichtfelder

Mindestens:

```text
memory_id
current_revision_id
memory_kind
content
scope_ref
learning_mode
sensitivity
confidence
created_at
last_confirmed_at
provenance_id
protection_scope_id
lifecycle_state
```

---

## 124. Memory Kind

Kernbeispiele:

```text
response_style
language_preference
detail_preference
workflow_preference
model_preference
tool_preference
recurring_setting
interaction_preference
other
```

---

## 125. Was nicht in Personal Memory gehört

Nicht als Personal Memory gespeichert werden:

- Projektinhalt selbst;
- fachliche Fakten;
- Entscheidungen des Projekts;
- Ideen;
- Ziele;
- Erfahrungen als Wissensinhalte.

Diese gehören in Knowledge.

Personal Memory darf lediglich beschreiben, **wie ATHENA damit arbeiten soll**.

---

## 126. Scope von Personal Memory

Ein Eintrag kann gelten:

```text
global
```

oder für einen konkreten Kontext:

```text
project
workflow
client
```

Der Scope wird über eine stabile Referenz gespeichert.

---

## 127. Learning Mode

Mindestens:

```text
explicit_user
model_inferred
imported
```

Sensible persönliche Informationen dürfen nur über einen ausdrücklich erlaubten Workflow langfristig in Personal Memory gelangen.

---

## 128. Sensitivity

Personal Memory besitzt mindestens eine Schutzklassifikation:

```text
normal
sensitive
protected
```

Die genaue Sicherheitslogik wird in Beta Kapitel 16 konkretisiert.

---

## 129. Confidence in Personal Memory

Bei automatisch erkannten Präferenzen darf optional eine Konfidenz gespeichert werden.

Sie muss als **Modell- beziehungsweise Systemeinschätzung** gekennzeichnet sein.

Eine explizite Benutzerpräferenz besitzt keine künstlich berechnete Modellkonfidenz.

---

## 130. Bestätigung von Präferenzen

Optional:

```text
last_confirmed_at
```

erlaubt ATHENA, zwischen:

- ausdrücklich bestätigten;
- lange nicht bestätigten;
- automatisch vermuteten

Präferenzen zu unterscheiden.

---

## 131. Konflikte im Personal Memory

Widersprüchliche Präferenzen werden versioniert.

ATHENA darf eine explizite neue Benutzerpräferenz nicht stillschweigend durch eine ältere Modellinferenz überschreiben.

---

## 132. Löschung von Personal Memory

Ein gelöschter PersonalMemoryEntry darf nicht durch:

- Embeddings;
- Cache;
- alte Projektionen;
- Restore

automatisch wiederhergestellt werden.

Die Löschregeln dieses Kapitels gelten vollständig.

---

## Teil V – Audit und Provenienz

## 133. ProvenanceRecord

`ProvenanceRecord` beantwortet:

> Woher stammt diese Information oder Änderung?

Es erhält:

```text
provenance_id
```

---

## 134. ProvenanceRecord-Pflichtfelder

Mindestens:

```text
provenance_id
subject_ref
operation
actor_id
created_at
source_refs
parent_provenance_refs
model_signature_id
processing_run_id
reason
protection_scope_id
```

Optionale Felder bleiben `null`, wenn sie nicht zutreffen.

---

## 135. Keine erfundene Modellsignatur

Direkter Benutzer-Write:

```text
actor_type = user
model_signature_id = null
```

Modellgestützter Write:

```text
actor_type = primary_model
model_signature_id = <id>
```

Diese Unterscheidung ist verbindlich.

---

## 136. Mehrere Ursprungsquellen

Eine semantische Einheit darf mehrere Quellen besitzen.

`source_refs` ist deshalb logisch eine Menge beziehungsweise eigene Relation und kein einzelnes Pflichtfeld.

---

## 137. Provenienzgraph

Provenienz kann verkettet werden.

Beispiel:

```text
Original Source
↓
OCR Representation
↓
Interpretation
↓
Claim
↓
Concept Note
```

Jeder Schritt bleibt einzeln adressierbar.

---

## 138. Provenienz und Benutzerkorrektur

Eine Benutzerkorrektur referenziert mindestens:

```text
neue Revision
+
vorherige Revision
+
actor = user
+
Zeitpunkt
+
Änderungsgrund soweit vorhanden
```

Sie benötigt kein Primärmodell.

---

## 139. Provenienz und Reinterpretation

Eine modellbasierte Reinterpretation speichert mindestens:

```text
Input Revision(s)
ProcessingRun
ModelSignature
Prompt/Pipeline Version
Output Revision / Interpretation
```

---

## 140. AuditEvent

`AuditEvent` beantwortet:

> Was ist im System passiert?

Es erhält:

```text
audit_event_id
```

Audit und Provenienz sind verwandt, aber nicht identisch.

---

## 141. AuditEvent-Pflichtfelder

Mindestens:

```text
audit_event_id
event_type
occurred_at
actor_id
target_refs
commit_id
result
reason_code
protection_scope_id
```

Optional:

```text
sanitized_summary
```

---

## 142. Audit ist append-only

Bestätigte AuditEvents werden nicht stillschweigend umgeschrieben.

Korrekturen erfolgen durch zusätzliche AuditEvents.

---

## 143. Audit ist kein Inhaltsarchiv

AuditEvents dürfen keine unnötigen vollständigen Kopien von:

- Chats;
- Dokumenten;
- Passwörtern;
- gelöschten Wissensinhalten;
- geschützten Inhalten

enthalten.

Audit dient Nachvollziehbarkeit, nicht Schattenarchivierung.

---

## 144. Audit nach Löschung

Nach endgültiger Löschung darf Audit nur die minimal notwendigen Informationen behalten.

Beispiel:

```text
entity type
entity id
deleted_at
deletion authority
reason code
```

Nicht:

```text
vollständiger gelöschter Inhalt
```

---

## 145. Audit und Schutzbereiche

AuditEvents, die geschützte Inhalte betreffen, dürfen im gesperrten Zustand keine vertraulichen Metadaten offenlegen.

Die UI kann beispielsweise nur anzeigen:

```text
geschützte Aktion
```

ohne Titel oder Inhalt offenzulegen.

---

## Teil VI – Configuration und Schutz

## 146. ConfigurationEntry

Persistente Konfiguration wird als versionierbare:

```text
ConfigurationEntry
```

modelliert.

Sie erhält:

```text
configuration_id
```

---

## 147. ConfigurationEntry-Pflichtfelder

Mindestens:

```text
configuration_id
config_key
config_scope
value_type
value
current_revision_id
created_at
protection_scope_id
```

---

## 148. Config Scope

Mögliche Scopes:

```text
system
user
project
module
provider
workflow
```

---

## 149. Secrets sind keine normalen Configuration Values

Passwörter, Schlüssel und Tokens werden nicht als Klartext in `ConfigurationEntry.value` gespeichert.

Stattdessen kann die Konfiguration auf einen:

```text
secret_ref
```

verweisen.

Der konkrete Secrets Store wird später spezifiziert.

---

## 150. ProtectionScope

Geschützte Inhalte können einem:

```text
ProtectionScope
```

zugeordnet werden.

Er erhält:

```text
protection_scope_id
```

---

## 151. ProtectionScope-Invariante

Ein ProtectionScope enthält außerhalb des entsperrten geschützten Kontextes keine unnötig verräterischen Namen oder Beschreibungen.

IDs sind neutral und nicht semantisch benannt.

---

## 152. Vererbung von Schutz

Abgeleitete Objekte dürfen nicht schwächer geschützt werden als ihre geschützte Quelle, wenn sie geschützte Information offenlegen.

Beispiel:

```text
geschützte Source
↓
Zusammenfassung mit vertraulichem Inhalt
```

Die Zusammenfassung erhält denselben oder einen mindestens gleichwertigen ProtectionScope.

---

## 153. Kein Schutzleck durch Metadaten

Auch folgende Felder müssen bei geschützten Objekten bewertet werden:

- Titel;
- Dateiname;
- Tags;
- Preview;
- Source URI;
- Hash;
- Projektname;
- Audit-Zusammenfassung.

Metadaten dürfen den Schutzbereich nicht umgehen.

---

## 154. RetentionRule

Benutzerkonfigurierte Aufbewahrungs-, Lebenszyklus- und Löschregeln werden als versionierbare:

```text
RetentionRule
```

modelliert.

Sie erhält:

```text
retention_rule_id
```

---

## 155. RetentionRule-Felder

Mindestens:

```text
retention_rule_id
scope
target_type
condition
action
created_at
created_by_actor_id
enabled
current_revision_id
```

Semantisch riskante Regeln benötigen eine klare Benutzerautorisierung.

---

## Teil VII – Löschung und Lebenszyklus

## 156. Lifecycle State

Autoritative Entitäten besitzen, soweit passend, einen Lebenszyklusstatus.

Kernwerte:

```text
active
archived
superseded
pending_deletion
deleted
```

Nicht jede Entität verwendet jeden Status.

---

## 157. Archivierung ist keine Löschung

`archived` bedeutet:

- weniger aktiv;
- weiterhin vorhanden;
- weiterhin referenzierbar;
- weiterhin durchsuchbar nach den geltenden Regeln.

Archivierung entfernt keine Originale.

---

## 158. Endgültige Löschung

Endgültige Löschung wird nur ausgelöst durch:

- ausdrückliche Benutzerentscheidung;
- ausdrücklich vom Benutzer konfigurierte RetentionRule.

Nicht durch:

- Speicherknappheit;
- Modellbewertung;
- geringe Retrieval-Nutzung;
- automatische Relevanzheuristik.

---

## 159. Löschworkflow

Ein Löschvorgang folgt logisch:

```text
Deletion Request
↓
Dependency Analysis
↓
Authorization Check
↓
pending_deletion
↓
purge canonical payload
↓
purge derived copies
↓
DeletionMarker
↓
Audit minimalisieren
↓
Backup/Restore-Regeln anwenden
```

---

## 160. Dependency Analysis

Vor endgültiger Löschung prüft ATHENA:

- welche Claims auf die Quelle verweisen;
- welche Concept Notes betroffen sind;
- welche Relationships betroffen sind;
- welche Derived-State-Einträge existieren;
- welche Backups die Daten enthalten können;
- ob geschützte Bereiche betroffen sind.

Die Analyse verhindert unbeabsichtigte Inkonsistenzen.

---

## 161. Keine automatische Kaskadenlöschung semantischer Daten

Eine Source-Löschung löscht nicht automatisch alle daraus entstandenen KnowledgeUnits.

Eine KnowledgeUnit-Löschung löscht nicht automatisch ihre Originalquellen.

Abhängige semantische Löschungen benötigen explizite Scope-Entscheidungen.

---

## 162. DeletionMarker

Nach endgültiger Löschung wird soweit erforderlich ein minimaler:

```text
DeletionMarker
```

gespeichert.

Er erhält:

```text
deletion_marker_id
```

---

## 163. DeletionMarker-Felder

Mindestens:

```text
deletion_marker_id
deleted_entity_type
deleted_entity_id
deleted_at
authority_type
retention_rule_id
restore_blocking_until NULL
```

Er enthält **nicht den gelöschten Inhalt**.

Für eine endgültige Benutzer- oder Policy-Löschung gilt:

```text
restore_blocking_until = NULL
```

`NULL` bedeutet hier **unbefristeter Restore-Block**. Ein konkreter Zeitwert ist nur für bewusst zeitlich begrenzte Tombstone-/Retentionfälle zulässig und darf niemals bewirken, dass eine endgültig gelöschte Entität nach Fristablauf automatisch wieder erscheint.

## 164. Zweck des DeletionMarker

DeletionMarker verhindern:

```text
Restore altes Backup
↓
gelöschtes Objekt erscheint wieder
```

Beim Restore werden Löschmarker gegen wiederhergestellte Daten angewendet.

---

## 165. Keine Content Hashes als Schattenkopie

Nach endgültiger Löschung soll ein DeletionMarker keine unnötigen Inhalts-Hashes behalten, wenn diese Rückschlüsse auf den gelöschten Inhalt erlauben könnten.

Die Objekt-ID reicht grundsätzlich für Restore-Sperren.

---

## 166. Derived-State-Löschung

Bei endgültiger Löschung müssen insbesondere entfernt oder invalidiert werden:

- Embeddings;
- FTS-Einträge;
- Vektorindex-Einträge;
- Cache;
- Preview;
- temporäre Zusammenfassungen;
- Suchstatistiken mit rekonstruierbarem Inhalt.

---

## 167. Backup-Löschkonsistenz

Das Datenmodell muss ermöglichen, dass Restore-Prozesse wissen:

```text
welche IDs nach dem Backup endgültig gelöscht wurden
```

Dadurch darf ein altes Backup die Löschung nicht stillschweigend rückgängig machen.

---

## Teil VIII – Durable Operational State

## 168. Job

Ein `Job` repräsentiert persistente Hintergrund- oder Langzeitverarbeitung.

Er erhält:

```text
job_id
```

---

## 169. Job-Pflichtfelder

Mindestens:

```text
job_id
job_type
created_at
created_by_actor_id
priority
state
requested_scope
processing_run_id
current_stage
last_checkpoint_id
retry_count
next_run_at
blocked_reason
pinned_configuration
```

---

## 170. Job States

Kernzustände:

```text
queued
waiting
running
paused
cancel_requested
cancelled
failed
completed
```

`waiting` besitzt einen maschinenlesbaren Grund, beispielsweise:

```text
waiting_resource
waiting_storage
waiting_network
waiting_user
```

---

## 171. Job-Spezifikation ist stabil

Ein Job speichert seine relevante Verarbeitungskonfiguration so, dass ein Neustart nicht stillschweigend andere Parameter verwendet.

Mindestens:

- Pipeline-Version;
- Modell-/Provider-Pinning soweit relevant;
- Prompt-Template-Version;
- Research Scope;
- Chunking-Konfiguration;
- Ressourcenklasse;
- Benutzeranforderung.

---

## 172. Checkpoint

Ein `Checkpoint` speichert einen bestätigten Wiederaufnahmepunkt eines Jobs.

Er erhält:

```text
checkpoint_id
```

---

## 173. Checkpoint-Pflichtfelder

Mindestens:

```text
checkpoint_id
job_id
processing_stage_id
created_at
progress_state
last_confirmed_input
last_confirmed_output
resume_metadata
commit_id
```

---

## 174. Checkpoint ist bestätigter Zustand

Ein Checkpoint darf nur Fortschritt markieren, der tatsächlich persistiert und validiert wurde.

Nicht zulässig:

```text
Checkpoint sagt "Chunk 100 fertig"
aber Chunk 100 wurde nie committed
```

---

## 175. Checkpoint-Payload

Checkpoint-Daten sollen klein und strukturiert bleiben.

Große Zwischenresultate erhalten eigene persistente IDs beziehungsweise Artifact-Referenzen.

Secrets und unnötige Quellinhalte gehören nicht in Checkpoint-Metadaten.

---

## 176. Resume

Nach Neustart:

```text
Job laden
↓
letzten bestätigten Checkpoint bestimmen
↓
Konfigurationsdrift prüfen
↓
Inputs validieren
↓
ab bestätigtem Punkt fortsetzen
```

---

## 177. Idempotency Key

Wiederholbare Verarbeitungsschritte verwenden soweit nötig einen:

```text
idempotency_key
```

Damit darf derselbe bestätigte Effekt nicht versehentlich doppelt erzeugt werden.

---

## 178. Idempotenz und Chunk-Verarbeitung

Beispiel:

```text
job_id
+
stage_id
+
chunk_id
+
pipeline_version
```

kann Grundlage eines Idempotency Keys sein.

Die konkrete Hash-/Serialisierungsform wird in Kapitel 03 festgelegt.

---

## 179. Pending Write

Ein noch nicht bestätigter autoritativer Write wird als Durable Operational State behandelt.

Er darf nicht nur im RAM existieren, wenn sein Verlust zu:

- Datenverlust;
- inkonsistentem Import;
- nicht nachvollziehbarem Jobfortschritt

führen würde.

---

## 180. Offline Buffer

Kann der konfigurierte `long_term_root` vorübergehend nicht erreicht werden, bleibt ein lokal transaktional bestätigter Commit in `athena.db` gültiger Bestandteil des aktuellen logischen ATHENA-Zustands.

Zusätzlich kann ATHENA einen lokalen Durable Replication Buffer verwenden. Dieser enthält nur die noch für verifizierte Langzeitreplikation benötigten Objekte:

```text
commit_id / commit_seq
stable object ids
replication payload oder payload refs
target storage root
integrity metadata
sync state
idempotency key
```

Bis zur bestätigten Replikation ist dieser Zustand **nicht vollständig aus dem Langzeitspeicher rekonstruierbar**. Er wird daher wie nicht rekonstruierbarer Pending State geschützt.

Die lokale aktive Datenbank selbst wird nach erfolgreicher Replikation nicht gelöscht; nur ausschließlich für den Transfer erzeugte Spool-/Outboxdaten können freigegeben werden.

## 181. OutboxItem

Persistente externe oder Speicher-Synchronisationsaktionen können über einen:

```text
OutboxItem
```

modelliert werden.

Er erhält:

```text
outbox_item_id
```

---

## 182. Outbox-Invariante

Eine Aktion gilt erst als erledigt, wenn:

```text
target write successful
+
verification successful
+
local state committed
```

ist.

Erst danach darf der lokale nicht rekonstruierbare Puffer bereinigt werden.

---

## Teil IX – Retrieval und Research State

## 183. CandidateSet

Ein `CandidateSet` ist die persistierbare Kandidatenmenge einer Suche oder Research-Phase.

Es erhält:

```text
candidate_set_id
```

---

## 184. CandidateSet-Pflichtfelder

Mindestens:

```text
candidate_set_id
research_scope_id
created_at
snapshot_commit_seq
retrieval_configuration
candidate_count
membership_manifest
state
```

---

## 185. Candidate Membership

Für jedes Candidate-Element können gespeichert werden:

```text
entity_ref
revision_id
rank
score
retrieval_method
selection_reason
```

Scores sind technische Werte und keine Wahrheitseinschätzung.

---

## 186. CandidateSet und Reproduzierbarkeit

Wenn ein finales Research-Ergebnis eine Coverage-Aussage enthält, muss nachvollziehbar sein, welche Kandidatenmenge dieser Aussage zugrunde lag.

Dafür darf ein relevanter CandidateSet-Metadatensatz nach Abschluss in langlebige Provenienz überführt werden.

---

## 187. ResearchScope

Ein `ResearchScope` definiert den Untersuchungsraum eines größeren Research-Jobs.

Er erhält:

```text
research_scope_id
```

---

## 188. ResearchScope-Pflichtfelder

Mindestens:

```text
research_scope_id
created_at
created_by_actor_id
query_or_goal
included_domains
filters
time_range
snapshot_commit_seq
snapshot_created_at
coverage_target
state
```

---

## 189. Snapshot Boundary

Der Snapshot wird mindestens durch:

```text
snapshot_commit_seq
```

begrenzt.

Damit gilt:

> Quellen, die nach dieser Commit-Grenze hinzukommen, verändern den laufenden Research Scope nicht stillschweigend.

---

## 190. Snapshot und Originalspeicher

Ein Snapshot muss nicht sämtliche Originaldaten physisch duplizieren.

Er benötigt eine reproduzierbare Menge von Revisionen beziehungsweise Source-IDs, die zum Snapshot gehören.

---

## 191. Delta Research

Neue Daten nach der Snapshot-Grenze können später als:

```text
Delta Research
```

verarbeitet werden.

Das Ergebnis darf klar unterscheiden:

```text
Original Snapshot
+
Delta
```

---

## 192. Coverage State

Research kann mindestens folgende Zähler speichern:

```text
candidate_total
processed_count
successful_count
failed_count
excluded_count
unavailable_count
```

Daraus kann Coverage berechnet und transparent erklärt werden.

---

## 193. Keine falsche Vollständigkeit

Ein Research-Ergebnis darf nur dann als vollständig für seinen Scope bezeichnet werden, wenn die gespeicherten Coverage-Daten dies stützen.

`100 %` darf nicht behauptet werden, wenn:

- Kandidaten fehlgeschlagen sind;
- Quellen nicht verfügbar waren;
- Filter nicht vollständig ausgewertet wurden.

---

## Teil X – Derived State

## 194. EmbeddingRecord

Embeddings gehören zum Derived State.

Ein EmbeddingRecord referenziert mindestens:

```text
entity_ref
revision_id
embedding_model_signature
embedding_version
vector
created_at
```

---

## 195. Embeddings sind revisiongebunden

Ein Embedding einer alten KnowledgeUnit-Revision darf nicht stillschweigend als Embedding der neuen Revision behandelt werden.

Bei Revision:

```text
old embedding = stale
new embedding = required
```

---

## 196. Embedding-Modellwechsel

Ein Wechsel des Embedding-Modells verändert kein kanonisches Wissen.

ATHENA kann:

```text
Derived State löschen
↓
Embeddings neu berechnen
↓
Vektorindex neu aufbauen
```

---

## 197. Full-Text Index

Volltextindex-Einträge referenzieren:

```text
entity_id
revision_id
commit_seq
```

Dadurch kann ATHENA erkennen, ob ein Index hinter dem autoritativen Zustand zurückliegt.

---

## 198. Derived-State-Version

Jeder größere Derived-State-Bestand besitzt eine technische Version beziehungsweise Build-Signatur.

Beispiele:

```text
index_schema_version
embedding_model_version
chunking_profile_version
build_commit_seq
```

---

## 199. Rebuild

Ein Derived-State-Rebuild darf:

- autoritative Daten lesen;
- technische Indizes erzeugen;
- alte Derived-State-Daten ersetzen.

Er darf keine semantischen autoritativen Inhalte eigenmächtig verändern.

---

## Teil XI – Datenintegrität

## 200. Referential Integrity

Persistente Referenzen müssen validiert werden.

Ein Commit darf keine neue autoritative Referenz auf eine nicht existente Ziel-ID erzeugen, außer ein bewusst definierter Pending-Zustand erlaubt dies.

---

## 201. Keine stillen Orphans

Wenn ein referenziertes Objekt gelöscht wird, muss die Beziehung kontrolliert behandelt werden.

Möglichkeiten:

- Relation entfernen;
- Relation als gebrochen markieren;
- minimalen Tombstone referenzieren;
- abhängige Entität aktualisieren.

Ein stiller ungültiger Fremdschlüssel ist nicht zulässig.

---

## 202. Content Integrity

Inhaltsführende persistente Objekte können einen:

```text
payload_hash
```

besitzen.

Er dient:

- Korruptionserkennung;
- Revisionsprüfung;
- Exportprüfung;
- Backupprüfung.

Der Hash ersetzt keine ID.

---

## 203. Canonical Serialization

Damit `payload_hash` stabil ist, benötigt jeder revisionierte Entitätstyp eine definierte kanonische Serialisierung.

Die konkrete Serialisierung wird in Kapitel 03 festgelegt.

Sie darf nicht von zufälliger JSON-Key-Reihenfolge oder UI-Formatierung abhängen.

---

## 204. Null und Unknown

ATHENA unterscheidet:

```text
false
0
empty
null
unknown
not_applicable
```

soweit semantisch relevant.

Fehlende Information darf nicht als `false` interpretiert werden.

---

## 205. Keine erfundenen Metadaten

Ist ein Wert unbekannt:

```text
model_revision
source_author
published_at
confidence
```

wird er als unbekannt beziehungsweise `null` gespeichert.

ATHENA erfindet keine Platzhalterwerte.

---

## 206. Schema Version

Jeder zentrale persistente Entitätstyp besitzt eine:

```text
schema_version
```

Diese ist von:

- ATHENA-App-Version;
- Alpha-Version;
- Beta-Version;
- Modellversion

getrennt.

---

## 207. Schema Evolution

Eine neue Schema-Version darf:

- Felder ergänzen;
- Strukturen normalisieren;
- technische Darstellungen verändern.

Sie darf keine semantische Information stillschweigend verwerfen.

---

## 208. Migration versus semantische Änderung

Technische Migration:

```text
gleiche Bedeutung
+
neue Datenstruktur
```

Semantische Änderung:

```text
Bedeutung oder Wissensinhalt ändert sich
```

Eine technische Migration darf nicht heimlich eine semantische Neubewertung durchführen.

---

## 209. Schema Migration Provenance

Relevante Migrationen werden auditierbar gespeichert.

Mindestens:

```text
from_schema_version
to_schema_version
migration_id
started_at
completed_at
result
```

---

## 210. Migration Failure

Schlägt eine Migration fehl:

- kein halb migrierter autoritativer Zustand;
- kontrollierter Rollback oder Recovery;
- keine stillschweigende Datenverwerfung.

---

## Teil XII – Physische Speichergrenzen

## 211. Logisches Modell versus physisches Schema

Dieses Kapitel definiert das **logische Modell**.

Kapitel 03 entscheidet:

- welche Entitäten eigene SQLite-Tabellen erhalten;
- welche Beziehungen Join-Tabellen verwenden;
- welche Felder normalisiert werden;
- welche Payloads als strukturierte Dokumentfelder gespeichert werden;
- wie Blobs physisch abgelegt werden;
- welche Indizes existieren.

---

## 212. Keine unkontrollierte Universal-JSON-Tabelle

Der Core darf nicht zu einem Modell degenerieren, in dem alle wichtigen Invarianten lediglich in einem beliebigen JSON-Blob stecken.

Kernfelder wie:

- IDs;
- Revisionen;
- Lifecycle;
- Provenienz;
- Protection Scope;
- Commit-Grenzen;
- Beziehungen

müssen strukturell validierbar bleiben.

---

## 213. Extensible Metadata

Erweiterbare Metadaten dürfen in strukturierten Zusatzfeldern gespeichert werden, wenn:

- Kerninvarianten nicht davon abhängen;
- Schema/Namespace dokumentiert ist;
- unbekannte Felder beim Roundtrip nicht verloren gehen.

---

## 214. Große Payloads

Große Binärdaten werden nicht unnötig direkt in relationalen Zeilen dupliziert.

Originaldateien und große Artefakte verwenden Blob-/Storage-Referenzen.

Die konkrete Grenze wird in Kapitel 03 festgelegt.

---

## Teil XIII – Markdown und Obsidian

## 215. Markdown ist Projektion

Markdown-Dateien beziehungsweise Obsidian-Notizen sind eine menschenlesbare Projektion, nicht die einzige kanonische Datenquelle.

Sie müssen auf stabile ATHENA-IDs zurückgeführt werden können.

---

## 216. Front Matter

Eine exportierte/editierbare Markdown-Projektion soll mindestens enthalten:

```yaml
athena_id: <stable-id>
entity_type: knowledge_unit
revision_id: <revision-id>
revision_no: 7
```

Weitere Metadaten können ergänzt werden.

---

## 217. Dateiname ist nicht Identität

Eine Datei darf umbenannt oder verschoben werden.

ATHENA verwendet weiterhin:

```text
athena_id
```

als Identität.

---

## 218. Externe manuelle Bearbeitung

Wird eine kontrolliert editierbare Projektion außerhalb ATHENAs geändert:

```text
Datei beobachten
↓
athena_id lesen
↓
expected revision prüfen
↓
Änderungsdiff erzeugen
↓
Benutzeränderung importieren
↓
neue Revision
↓
Provenienz + Audit
```

---

## 219. Konflikt bei externer Bearbeitung

Wenn die kanonische Entität nach Export bereits verändert wurde:

```text
revision mismatch
```

ATHENA überschreibt nicht blind.

Der Konflikt wird angezeigt beziehungsweise kontrolliert zusammengeführt.

---

## 220. Neue Datei ohne ATHENA-ID

Eine neue manuell angelegte Datei ohne `athena_id` wird nicht anhand ihres Dateinamens einem existierenden Objekt zugeordnet.

Sie kann als:

```text
new candidate object
```

importiert werden.

Semantische Zuordnung oder Merge erfolgt kontrolliert.

---

## Teil XIV – Export und Portabilität

## 221. Vollständiger Export

Ein vollständiger ATHENA-Export muss mindestens abbilden können:

- stabile IDs;
- aktuelle Revisionen;
- historische Revisionen nach geltender Aufbewahrung;
- Relationships;
- Sources;
- Originaldateien;
- Personal Memory;
- Provenienz;
- Audit nach den geltenden Schutzregeln;
- Projekte;
- Concept Notes;
- Konfiguration soweit exportierbar;
- DeletionMarker soweit für Restore nötig.

---

## 222. Export Manifest

Ein Export besitzt ein Manifest mit mindestens:

```text
export_id
created_at
schema_versions
entity_counts
hash_manifest
included_domains
protection_information
```

---

## 223. Roundtrip-Invariante

Export und Reimport dürfen stabile IDs nicht verändern.

Wenn:

```text
Export ATHENA A
↓
Import in neue ATHENA-Installation
```

müssen semantische Beziehungen auf dieselben IDs zeigen.

---

## 224. Keine absoluten Pfade im Export

Exportierte Beziehungen verwenden:

- IDs;
- relative Exportpfade;
- logische URIs.

Keine dauerhaften:

```text
C:\
D:\
\\NAS\
```

als Identität.

---

## 225. Export geschützter Inhalte

Geschützte Inhalte werden nur entsprechend ihrer Sicherheitsregeln exportiert.

Ein Export darf Schutz nicht versehentlich aufheben.

---

## Teil XV – Backup und Restore

## 226. Backup-Identität

Backups sind Wiederherstellungskopien und keine parallele aktive Source of Truth.

Das Datenmodell muss Restore auf:

- neue Hardware;
- neuen Speicherpfad;
- neue Installation

ermöglichen.

---

## 227. Restore-Reihenfolge

Logisch:

```text
Backup validieren
↓
ATHENA Persistent Data wiederherstellen
↓
Durable Operational State bewerten
↓
DeletionMarker anwenden
↓
Integrität prüfen
↓
Derived State neu aufbauen
```

---

## 228. Jobs nach Restore

Nicht jeder alte Job darf nach Restore blind fortgesetzt werden.

ATHENA prüft:

- Jobstatus;
- Inputs;
- Snapshot-Grenzen;
- Processing Drift;
- externe Nebenwirkungen;
- Idempotenz.

---

## 229. Derived State nach Restore

Embeddings und Indizes dürfen neu aufgebaut werden.

Sie müssen nicht zwingend Bestandteil jedes Backups sein, solange ihre Rekonstruktion möglich ist.

---

## Teil XVI – Change Feed und Index-Synchronität

## 230. Change Feed

Jeder autoritative Commit erzeugt einen maschinenlesbaren Änderungsstrom.

Mindestens:

```text
commit_seq
commit_id
changed_entity_refs
change_types
```

---

## 231. Verwendung des Change Feed

Der Change Feed dient:

- Suchindex-Aktualisierung;
- Embedding-Neuberechnung;
- UI-Updates;
- Obsidian-Projektion;
- Sync;
- Diagnose.

---

## 232. Derived-State-Watermark

Jede Derived-State-Komponente speichert, bis zu welchem:

```text
commit_seq
```

sie vollständig aktualisiert ist.

Beispiel:

```text
canonical commit_seq = 10540
vector index watermark = 10512
```

ATHENA weiß dadurch, dass der Vektorindex hinterherhinkt.

---

## 233. Suche bei stale Index

Ein veralteter Derived-State-Index darf nicht als vollständig aktuell ausgegeben werden.

Je nach Anfrage kann ATHENA:

- inkrementell nachziehen;
- zusätzlich Fallback-Suche verwenden;
- auf eingeschränkte Aktualität hinweisen;
- kritische Ergebnisse direkt aus autoritativen Daten prüfen.

---

## Teil XVII – Wissensqualität und Widersprüche

## 234. Keine automatische Wahrheitsverschmelzung

Mehrere widersprüchliche Claims bleiben getrennt.

Beispiel:

```text
Claim A:
Quelle 1 behauptet X.

Claim B:
Quelle 2 behauptet nicht-X.
```

ATHENA kann zusätzlich eine Interpretation des Widerspruchs speichern.

---

## 235. Same-As

`same_as` ist eine semantisch starke Relation.

Sie darf nicht allein durch Dateihash oder Stringähnlichkeit erzeugt werden, wenn damit semantische Identität behauptet wird.

Eine solche Entscheidung benötigt Benutzer oder Primärmodell.

---

## 236. Merge

Beim semantischen Merge zweier KnowledgeUnits:

```text
A
+
B
↓
C oder A'
```

bleiben die ursprünglichen IDs und Revisionen historisch nachvollziehbar.

Die nicht mehr aktuelle Einheit kann als `superseded` markiert werden.

---

## 237. Split

Wird eine KnowledgeUnit aufgeteilt:

```text
A
↓
B + C
```

werden B und C neue Entitäten mit neuen IDs.

Provenienz referenziert A als Ursprung.

---

## 238. Correction

Eine Korrektur derselben semantischen Entität erzeugt normalerweise:

```text
neue Revision derselben ID
```

Nicht automatisch eine neue KnowledgeUnit.

---

## 239. Neue Entität versus neue Revision

Faustregel:

**Neue Revision**, wenn die Identität des Wissensobjekts erhalten bleibt.

**Neue Entität**, wenn ein eigenständig adressierbares neues Wissensobjekt entsteht.

Grenzfälle werden durch Benutzer oder Primärmodell semantisch entschieden.

---

## Teil XVIII – API-Datenkontrakte

## 240. API-Serialisierung

Core-API-Objekte werden in einem dokumentierten, versionierbaren strukturierten Format serialisiert.

Kernanforderungen:

- IDs als kanonische UUID-Strings;
- Zeitstempel in UTC;
- explizite `null`-Werte;
- `schema_version`;
- keine internen Row-IDs;
- keine absoluten Speicherpfade als Identität.

---

## 241. Entity Envelope

Eine API-Antwort für revisionierte Entitäten kann logisch enthalten:

```json
{
  "entity_type": "knowledge_unit",
  "id": "...",
  "current_revision": {
    "revision_id": "...",
    "revision_no": 4,
    "schema_version": 1,
    "payload": {}
  },
  "lifecycle_state": "active"
}
```

Die exakte API wird in einem späteren Beta-Kapitel spezifiziert.

---

## 242. Write Request

Ein kontrollierter Edit enthält mindestens:

```text
entity_id
expected_revision_id
proposed_change
actor_context
reason
```

Der Core ergänzt:

```text
commit
provenance
audit
timestamps
```

---

## 243. Create Request

Bei Neuanlage kann der Client keine eigene kanonische ID erzwingen, außer eine ausdrücklich autorisierte Import-/Restore-Schnittstelle erlaubt dies.

Normal:

```text
Client requests create
↓
Core allocates ID
```

---

## 244. Restore und ID-Erhalt

Restore beziehungsweise autorisierter ATHENA-Import darf bestehende IDs wiederherstellen.

Dies ist keine normale Create-Operation.

---

## Teil XIX – Beispiele vollständiger Datenflüsse

## 245. Beispiel: Benutzer erstellt Wissen direkt

```text
Benutzer:
"Speichere: ATHENA Alpha wurde finalisiert."

↓
actor = user

↓
KnowledgeUnit ID erzeugen

↓
Revision 1 erzeugen

↓
ProvenanceRecord:
actor=user
model_signature=null

↓
AuditEvent

↓
atomarer Commit
```

Kein Primärmodell ist erforderlich.

---

## 246. Beispiel: Primärmodell extrahiert Wissen

```text
archivierter Chat
↓
ChatMessage
↓
Primary Model ProcessingRun
↓
Interpretation
↓
KnowledgeUnit + Claim
↓
Provenance:
source message
model signature
processing run
↓
Audit
↓
Commit
```

---

## 247. Beispiel: Benutzer korrigiert Modellwissen

```text
KnowledgeUnit Revision 3
erstellt durch Primärmodell

↓
Benutzer korrigiert Inhalt

↓
KnowledgeUnit Revision 4
actor=user
model_signature=null
parent_revision=Revision 3

↓
Audit + Provenance

↓
current_revision = Revision 4
```

Die Modellrevision bleibt historisch erhalten.

---

## 248. Beispiel: Dokumentimport

```text
Datei
↓
source_id + blob_id
↓
Integrität prüfen
↓
Raw Archive Commit
↓
Text Extraction Representation
↓
Chunks
↓
Retrieval
↓
Primärmodell
↓
Claims / KnowledgeUnits
↓
Source Anchors als Evidenz
```

---

## 249. Beispiel: identische Datei zweimal importiert

```text
Import A
↓
Source A
    \
     Blob X

Import B
↓
Source B
    /
```

Physische Deduplizierung ist möglich.

Provenienz beider Importereignisse bleibt erhalten.

---

## 250. Beispiel: Modellwechsel

```text
bestehender Claim
↓
keine automatische Änderung

Benutzer startet Reinterpretation
↓
neuer ProcessingRun
↓
neue ModelSignature
↓
neue Interpretation
↓
optional kontrollierte neue Claim-Revision
```

---

## 251. Beispiel: Exhaustive Research

```text
ResearchScope
snapshot_commit_seq = 5000
↓
CandidateSet
↓
Chunks / Sources verarbeiten
↓
Checkpoints
↓
Coverage State
↓
hierarchische Synthese
↓
Result + Provenance
```

Neue Quellen ab Commit 5001 gehören nicht stillschweigend zum ursprünglichen Scope.

---

## 252. Beispiel: Offline-Langzeitspeicher

```text
neue Source
↓
source_id sofort vergeben
↓
lokaler Durable Buffer
↓
OutboxItem
↓
Langzeitspeicher wieder online
↓
übertragen
↓
Hash verifizieren
↓
autoritativen Locator bestätigen
↓
Commit
↓
lokalen Buffer bereinigen
```

---

## 253. Beispiel: endgültige Löschung

```text
Benutzer löscht Source X
↓
Dependency Analysis
↓
Bestätigung
↓
Originalpayload entfernen
↓
Derived State entfernen
↓
minimaler DeletionMarker
↓
Audit ohne Inhaltskopie
↓
Restore-Schutz aktiv
```

---

## 254. Beispiel: temporärer Chat mit Memory-Befehl

```text
temporary chat
↓
Benutzer:
"Merke dir, dass ich kurze Antworten bevorzuge."
↓
PersonalMemoryEntry
actor=user
source_ref=null
reason=explicit_user_memory_request
↓
temporärer Chat wird später verworfen
```

Das Personal Memory bleibt bestehen, ohne den vollständigen Chat heimlich zu archivieren.

---

## Teil XX – Minimales v1-Entitätsinventar

## 255. Autoritative Kernentitäten

Für v1 sind mindestens folgende autoritative Entitäten vorgesehen:

### Knowledge

```text
KnowledgeUnit
Claim
Interpretation
Relationship
Project
ConceptNote
```

### Personal Memory

```text
PersonalMemoryEntry
```

### Raw Archive

```text
Source
BlobRecord
SourceRepresentation
SourceAnchor
Chat
ChatMessage
```

### Audit & Provenance

```text
ProvenanceRecord
AuditEvent
ModelSignature
ProcessingRun
ProcessingStage
CommitRecord
DeletionMarker
```

### Configuration

```text
ConfigurationEntry
RetentionRule
ProtectionScope
```

---

## 256. Durable Operational State

Mindestens:

```text
Job
Checkpoint
CandidateSet
ResearchScope
PendingWrite
OutboxItem
IdempotencyRecord
```

Die physische Tabellenaufteilung wird in Kapitel 03 konkretisiert.

---

## 257. Derived-State-Kernobjekte

Mindestens:

```text
EmbeddingRecord
FullTextIndex State
VectorIndex State
Preview/Cache State
Derived Build Metadata
```

Diese sind rekonstruierbar.

---

## Teil XXI – Verbindliche Invarianten

## 258. Invariante 1 – Stable ID

Jede langlebig adressierbare Entität besitzt genau eine stabile ID, die während ihres Lebenszyklus nicht geändert wird.

---

## 259. Invariante 2 – Keine Pfadidentität

Kein Dateipfad ist kanonische Objektidentität.

---

## 260. Invariante 3 – Revision statt Überschreiben

Semantisch relevante Änderungen an revisionierten autoritativen Entitäten erzeugen neue Revisionen.

---

## 261. Invariante 4 – Benutzeränderung ohne Modellzwang

Direkte Benutzeränderungen benötigen keine Modellsignatur.

---

## 262. Invariante 5 – Modelländerung mit Signatur

Semantische Modelländerungen sind auf eine ModelSignature und den zugehörigen ProcessingRun zurückführbar.

---

## 263. Invariante 6 – Original bleibt Original

Interpretation, OCR, Zusammenfassung oder Wissensextraktion verändert keine Originalbytes.

---

## 264. Invariante 7 – Raw Archive bleibt getrennt

Raw Archive ist keine Knowledge-Lebenszyklusstufe.

---

## 265. Invariante 8 – Personal Memory bleibt getrennt

Personal Memory speichert Zusammenarbeitseinstellungen, nicht Projektwissen selbst.

---

## 266. Invariante 9 – Provenienz ist mehrstufig

Jede wissensbildende Ableitung kann auf Ursprünge und Verarbeitung zurückgeführt werden.

---

## 267. Invariante 10 – Audit ist keine Schattenkopie

Audit enthält nur für Nachvollziehbarkeit notwendige Daten.

---

## 268. Invariante 11 – Kein Lost Update

Konkurrierende semantische Änderungen werden erkannt.

---

## 269. Invariante 12 – Commit atomar

Autoritative Multi-Objekt-Schreibvorgänge sind atomar.

---

## 270. Invariante 13 – Durable bedeutet geschützt

Noch nicht rekonstruierbarer operativer Zustand wird wie wichtige persistente Daten gegen Verlust geschützt.

---

## 271. Invariante 14 – Derived bleibt ersetzbar

Derived State darf keine einzige nicht rekonstruierbare Kopie relevanter Information enthalten.

---

## 272. Invariante 15 – Löschung propagiert

Endgültige Löschung entfernt auch rekonstruierbare Kopien und verhindert Restore-Resurrection.

---

## 273. Invariante 16 – Snapshot bleibt stabil

Research-Snapshots verändern ihren Scope nicht stillschweigend durch später importierte Daten.

---

## 274. Invariante 17 – Keine erfundene Sicherheit

Unbekannte Metadaten bleiben unbekannt.

---

## 275. Invariante 18 – Schutz vererbt sich

Abgeleitete Inhalte dürfen vertrauliche Quellinformation nicht in schwächer geschützte Bereiche leaken.

---

## 276. Invariante 19 – Export erhält IDs

Export und Restore erhalten stabile Identitäten und Beziehungen.

---

## 277. Invariante 20 – Core kontrolliert Persistenz

Modelle, Plugins und externe Clients schreiben nicht direkt an den kontrollierten Persistenzregeln vorbei.

---

## Teil XXII – Validierung

## 278. Validierungsstufen

Vor autoritativen Commits unterscheidet ATHENA mindestens:

```text
syntactic validation
referential validation
domain validation
security validation
concurrency validation
provenance validation
```

---

## 279. Syntactic Validation

Prüft beispielsweise:

- gültige UUID;
- gültigen Enum-Wert;
- gültigen Zeitstempel;
- erwarteten Datentyp;
- erforderliche Felder.

---

## 280. Referential Validation

Prüft:

- existieren referenzierte IDs;
- passt der erwartete Entitätstyp;
- ist die referenzierte Revision Teil der Entität;
- verletzt die Beziehung keine definierte Invariante.

---

## 281. Domain Validation

Prüft beispielsweise:

- Project gehört zur Knowledge-Domäne;
- PersonalMemoryEntry enthält kein Project als eigenes Objekt;
- Source ist Raw Archive;
- Derived State wird nicht als kanonisches Wissen markiert.

---

## 282. Security Validation

Prüft:

- Protection Scope;
- Berechtigung des Akteurs;
- geschützte Metadaten;
- erlaubte Export-/Write-Operation;
- keine Secret-Leaks.

---

## 283. Concurrency Validation

Prüft:

```text
expected_revision
vs
current_revision
```

und gegebenenfalls Snapshot-/Commit-Grenzen.

---

## 284. Provenance Validation

Prüft:

- ist ein semantischer Akteur angegeben;
- ist bei Modellbeteiligung eine ModelSignature vorhanden;
- fehlt bei reinem Benutzerwrite nicht fälschlich eine Pflichtsignatur;
- existieren Source-/Parent-Refs;
- passt der ProcessingRun.

---

## Teil XXIII – Tests

## 285. ID-Test

Erwartung:

```text
1.000.000 lokal erzeugte IDs
↓
keine Kollision
+
gültige UUIDv7
+
Roundtrip korrekt
```

Die konkrete Testmenge kann angepasst werden, muss aber Kollision und Serialisierung abdecken.

---

## 286. Stable-ID-Test

```text
KnowledgeUnit erstellen
↓
10 Revisionen
↓
Dateiprojektion umbenennen
↓
Storage verschieben
```

Erwartung:

```text
knowledge_id unverändert
```

---

## 287. Revision-Test

Änderung einer KnowledgeUnit erzeugt:

```text
neue revision_id
revision_no + 1
parent_revision korrekt
current_revision aktualisiert
alte Revision unverändert
```

---

## 288. User-Provenance-Test

Direkter Benutzeredit:

```text
actor=user
model_signature=null
```

muss erfolgreich validieren.

---

## 289. Model-Provenance-Test

Modellgestützte semantische Änderung ohne ModelSignature:

```text
REJECT
```

Mit gültiger ModelSignature:

```text
ACCEPT
```

---

## 290. Source-Immutability-Test

Nach Import wird versucht, Originalbytes eines bestehenden BlobRecords in-place zu verändern.

Erwartung:

```text
REJECT
```

Eine neue Fassung erhält neue Source-/Blob-Beziehung.

---

## 291. Chunk-Rebuild-Test

```text
Chunking Profile A
↓
Chunks A

Chunking Profile B
↓
Chunks B
```

Erwartung:

- alte Evidenz-SourceAnchors bleiben gültig;
- Knowledge-Provenienz bricht nicht;
- Derived State kann neu aufgebaut werden.

---

## 292. Chat-Temporary-Test

Temporärer Chat:

```text
nicht dauerhaft archiviert
```

aber explizites:

```text
"Merke dir X"
```

erzeugt zulässiges Personal Memory ohne versteckte Chatkopie.

---

## 293. Personal-Memory-Trennungstest

Versuch:

```text
vollständiges Projektobjekt
→ PersonalMemoryEntry
```

Erwartung:

```text
Domain validation warning/reject
```

Die Projektinformation gehört zu Knowledge.

---

## 294. Lost-Update-Test

Zwei Clients lesen Revision 5.

Client A schreibt Revision 6.

Client B versucht Write mit:

```text
expected_revision = 5
```

Erwartung:

```text
CONFLICT
```

kein stilles Überschreiben.

---

## 295. Atomic-Commit-Test

Während eines Commits mit:

```text
KnowledgeUnit
+
Provenance
+
Audit
```

wird künstlich ein Fehler erzeugt.

Erwartung:

```text
entweder alle drei bestätigt
oder keines
```

---

## 296. Deletion-Test

Endgültige Löschung eines Chats.

Prüfen:

- Chatpayload entfernt;
- Messages entfernt;
- Embeddings entfernt;
- FTS entfernt;
- Preview entfernt;
- Audit enthält keine Chatkopie;
- DeletionMarker vorhanden;
- Restore resurrectiert Chat nicht.

---

## 297. Protected-Content-Test

Geschützte Source erzeugt Interpretation und KnowledgeUnit.

Erwartung:

```text
kein ungeschützter Titel
kein Preview-Leak
kein Audit-Leak
kein ungeschützter Embedding-Zugriff
```

---

## 298. Resume-Test

Job wird nach Checkpoint beendet und ATHENA neu gestartet.

Erwartung:

```text
Fortsetzung ab letztem bestätigten Zustand
+
keine doppelte kanonische Ausgabe
```

---

## 299. Processing-Drift-Test

Zwischen Checkpoint und Resume ändert sich die gepinnte Modell- oder Pipelinekonfiguration.

Erwartung:

```text
Drift erkannt
+
kein stilles Mischen
```

---

## 300. Snapshot-Test

ResearchScope bei:

```text
snapshot_commit_seq = 1000
```

Neue Quellen werden bei Commit 1001–1010 importiert.

Erwartung:

```text
laufender Scope bleibt bei <=1000
+
neue Quellen sind Delta
```

---

## 301. Export-Roundtrip-Test

```text
ATHENA A
↓
vollständiger Export
↓
ATHENA B
```

Erwartung:

- IDs identisch;
- Beziehungen identisch;
- Revisionen nachvollziehbar;
- Provenienz erhalten;
- Originalhashes korrekt;
- keine absolute Pfadabhängigkeit.

---

## 302. Migration-Test

Altes Schema wird auf neues Schema migriert.

Erwartung:

```text
alle IDs erhalten
+
alle Revisionen erhalten
+
keine semantische Information still gelöscht
+
Audit der Migration vorhanden
```

---

## Teil XXIV – Entscheidungen und bewusste Grenzen

## 303. In diesem Kapitel festgelegt

Verbindlich festgelegt sind:

- UUIDv7 als stabile Entitäts-ID;
- revisioniertes Modell für veränderbare autoritative Entitäten;
- getrennte `revision_id`;
- logische URIs;
- `EntityRef`;
- UTC-Zeitstempel plus optionale Originalzeit;
- `commit_id` und lokales `commit_seq`;
- explizites Akteursmodell;
- keine Modellsignatur bei reinem Benutzerwrite;
- ModelSignature bei semantischer Modellbeteiligung;
- ProcessingRun und ProcessingStage;
- Source, BlobRecord, retained SourceRepresentation und SourceAnchor als Raw-Archive-Objekte;
- SourceChunk als reproduzierbares Derived-State-Processingobjekt;
- Chat und ChatMessage;
- KnowledgeUnit, Claim, Interpretation und Relationship;
- Project und ConceptNote;
- PersonalMemoryEntry;
- ProvenanceRecord und AuditEvent;
- ConfigurationEntry, RetentionRule und ProtectionScope;
- Job und Checkpoint;
- CandidateSet und ResearchScope;
- DeletionMarker;
- Outbox/Pending-State-Prinzip;
- Snapshot- und Coverage-Grundmodell;
- Export-/Roundtrip-Invarianten.

---

## 304. Noch nicht physisch festgelegt

Bewusst Kapitel 03 vorbehalten bleiben:

- genaue SQLite-Tabellennamen;
- SQLite-Spaltentypen;
- konkrete Foreign-Key-Definitionen;
- BLOB- versus TEXT-Speicherung von UUIDs;
- konkrete JSON-Spalten;
- konkrete Dateiverzeichnisstruktur;
- Blob-Store-Layout;
- WAL-/Journal-Konfiguration;
- genaue FTS5-Tabellen;
- konkreter Vektorindex;
- konkrete Hashfunktion;
- konkrete Verschlüsselungsbibliothek;
- exakte Transaktions- und Connection-Pool-Implementierung;
- konkrete Migrationsbibliothek;
- genaue Backup-Dateiformate.

---

## 305. Keine spätere semantische Umdeutung durch DDL

Kapitel 03 darf beispielsweise nicht entscheiden:

```text
PersonalMemoryEntry und KnowledgeUnit
in eine semantisch identische Tabelle zu verschmelzen,
wenn dadurch ihre Domänengrenze praktisch verloren geht.
```

Physische Konsolidierung ist nur zulässig, wenn logische Trennung, Regeln, Berechtigungen und Provenienz vollständig erhalten bleiben.

---

## 306. Performance ist kein Grund für Identitätsbruch

Falls Performanceoptimierungen später:

- Denormalisierung;
- Materialized Views;
- zusätzliche Indizes;
- Cachetabellen

erfordern, bleiben stabile IDs, Revisionen und autoritative Domänengrenzen unverändert.

---

## 307. Zukunft: Mehrgerätezugriff

UUIDv7 und revisionierte Entitäten werden bewusst so gewählt, dass spätere Mehrgeräte-Synchronisation möglich bleibt.

Beta v1 muss noch kein vollständiges verteiltes Conflict-Free-System implementieren.

Es darf jedoch keine Identitätsarchitektur gewählt werden, die Mehrgerätezugriff grundsätzlich verhindert.

---

## 308. Zukunft: andere Speichertechnologie

Ein späterer Wechsel von SQLite zu einer anderen Speichertechnologie darf durch Export/Migration möglich sein.

Die logischen Entitäten dieses Kapitels bleiben die Referenz.

---

## 309. Zukunft: neue Modellgenerationen

Neue Primär- oder Infrastrukturmodelle erzeugen:

- neue ModelSignatures;
- neue ProcessingRuns;
- gegebenenfalls neue Derived State;
- optional neue Interpretationen.

Sie ändern nicht rückwirkend die Identitäten alter Quellen oder Wissenseinheiten.

---

## 310. Zukunft: neue Entitätstypen

Neue Entitätstypen dürfen ergänzt werden, wenn:

- eine bestehende Entität nicht semantisch missbraucht wird;
- stabile IDs verwendet werden;
- Domain-Zugehörigkeit klar ist;
- Provenienz definiert ist;
- Export/Migration berücksichtigt wird.

---

## Teil XXV – Ergebnis

## 311. Ergebnis dieses Kapitels

ATHENA besitzt mit diesem Kapitel ein konkretes logisches Datenmodell, das:

- über Jahrzehnte stabile Identitäten ermöglicht;
- Benutzer- und Modelländerungen sauber trennt;
- Originalquellen und semantische Ableitungen auseinanderhält;
- historische Revisionen nachvollziehbar macht;
- Widersprüche statt Überschreiben unterstützt;
- große Quellen über Chunks verarbeitet, ohne Evidenz an Chunking zu binden;
- Personal Memory als eigene Domäne schützt;
- Provenienz und Audit getrennt modelliert;
- langlaufende Jobs crash-sicher fortsetzen kann;
- Research-Snapshots und Coverage reproduzierbar macht;
- Löschung auch gegenüber Derived State und Restore durchsetzbar macht;
- physische Speicherpfade austauschbar hält;
- Export und spätere Migration ermöglicht.

---

## 312. Referenzübersicht

Die wichtigste Objektstruktur lautet:

```text
ATHENA Persistent Data
│
├── Knowledge
│   ├── KnowledgeUnit
│   ├── Claim
│   ├── Interpretation
│   ├── Relationship
│   ├── Project
│   └── ConceptNote
│
├── Personal Memory
│   └── PersonalMemoryEntry
│
├── Raw Archive
│   ├── Source
│   ├── BlobRecord
│   ├── SourceRepresentation
│   ├── SourceAnchor
│   ├── Chat
│   └── ChatMessage
│
├── Audit & Provenance
│   ├── ProvenanceRecord
│   ├── AuditEvent
│   ├── ModelSignature
│   ├── ProcessingRun
│   ├── ProcessingStage
│   ├── CommitRecord
│   └── DeletionMarker
│
└── Configuration
    ├── ConfigurationEntry
    ├── RetentionRule
    └── ProtectionScope

Durable Operational State
│
├── Job
├── Checkpoint
├── CandidateSet
├── ResearchScope
├── PendingWrite
├── OutboxItem
└── IdempotencyRecord

Derived State
│
├── SourceChunk Sets
├── Embeddings
├── Full-Text Index
├── Vector Index
├── Caches
└── Previews
```

---

## 313. Nächstes Beta-Kapitel

**Beta Kapitel 03 – Storage, Datenbanken und Migrationen** übersetzt dieses logische Modell in eine konkrete persistente v1-Implementierung.

Es muss insbesondere festlegen:

- SQLite-Dateien und Datenbankgrenzen;
- konkrete Tabellen;
- Primär- und Fremdschlüssel;
- UUID-Speicherformat;
- Revisionstabellen;
- Commit-Transaktionen;
- WAL und Crash-Verhalten;
- Blob-Store;
- Raw-Archive-Dateilayout;
- Durable Operational Store;
- FTS5;
- Derived-State-Speicher;
- Migrationssystem;
- Integritätsprüfungen;
- Backup-relevante Datenbankgrenzen;
- lokaler Offline-Puffer;
- Atomic Write und Outbox-Mechanismus;
- Disk-Full-Verhalten auf physischer Ebene.

Kapitel 03 darf keine Entität oder Invariante dieses Kapitels stillschweigend entfernen.

---

## Leitregel von Beta Kapitel 02

> **Jede langlebige Information in ATHENA besitzt eine stabile Identität, eine klar definierte Domäne und eine nachvollziehbare Herkunft. Änderungen erzeugen Revisionen statt unsichtbarer Überschreibungen. Benutzerhandlungen benötigen keine erfundene Modellsignatur; semantische Modellhandlungen bleiben dagegen eindeutig auf Modell und Verarbeitung zurückführbar. Originalquellen, kanonisches Wissen, Personal Memory, Audit/Provenienz, langlebiger Betriebszustand und rekonstruierbare Indizes bleiben getrennt. Speicherorte dürfen wechseln – Identität, Geschichte und Beziehungen nicht.**
