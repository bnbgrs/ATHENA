# ATHENA Beta Specification v0.1 – Kapitel 03

## Storage, Datenbanken und Migrationen

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Technische Basis:** [Beta Kapitel 01](01_Systemarchitektur_und_Technische_Basis.md)
**Logisches Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)

---

## Teil I – Auftrag und verbindliche Entscheidungen

### 1. Ziel dieses Kapitels

Dieses Kapitel übersetzt das logische Datenmodell aus **Beta Kapitel 02** in eine konkrete persistente v1-Architektur.

Es legt fest:

- welche SQLite-Datenbanken existieren;
- wo sie physisch liegen;
- welche Tabellen und Schlüssel verwendet werden;
- wie UUIDv7, Zeitstempel, Hashes und JSON physisch gespeichert werden;
- wie atomare Commits umgesetzt werden;
- wie Originaldateien und große Repräsentationen abgelegt werden;
- wie FTS5 und Vektorindizes getrennt vom autoritativen Zustand betrieben werden;
- wie Netzwerk- und Offline-Speicher behandelt werden;
- wie Backup, Restore und Löschmarker physisch funktionieren;
- wie Schema- und Storage-Migrationen sicher durchgeführt werden;
- wie Disk-Full-, Crash- und Korruptionsfälle behandelt werden.

Dieses Kapitel verändert keine semantische Regel aus Alpha oder Beta Kapitel 02.

---

### 2. Normative Reihenfolge

Für Konflikte gilt:

1. ATHENA Alpha v2.0.1;
2. Beta Kapitel 01 – Systemarchitektur und technische Basis;
3. Beta Kapitel 02 – Persistentes Datenmodell und ID-System;
4. dieses Kapitel.

Eine physische Optimierung darf niemals eine logische Invariante aus Kapitel 02 aufheben.

---

### 3. v1-Storage-Entscheidung

ATHENA v1 verwendet:

```text
Structured authoritative state:
SQLite

Raw Archive / große immutable Payloads:
filesystembasierter Blob Store

Full-text search:
separate SQLite-Datenbank mit FTS5

Vector retrieval:
hnswlib-basierter HNSW-Index

Migrations:
SQLAlchemy 2.x + Alembic
mit zusätzlicher ATHENA-Sicherheitslogik

Protected payload encryption:
cryptography
Argon2id + AES-256-GCM
```

Alle externen Bibliotheken werden über Adapter gekapselt, damit spätere Austauschbarkeit erhalten bleibt.

---

### 4. Warum eine lokale SQLite-Hauptdatenbank

ATHENA v1 ist ein lokales Single-User-System mit genau einem kontrollierten Core als Schreibinstanz.

Die aktive strukturierte Datenbank `athena.db` liegt auf einem lokal zuverlässigen Dateisystem und stellt die **transaktionale Materialisierung des aktuellen logischen ATHENA-Zustands** bereit.

SQLite ist dafür geeignet, weil es:

- ACID-Transaktionen bereitstellt;
- keinen separaten Datenbankserver benötigt;
- portabel ist;
- Foreign Keys und robuste Integritätsprüfungen unterstützt;
- sehr gut zu einer modularen lokalen Monolith-Architektur passt.

Die lokale `athena.db` darf die aktuellsten lokal bestätigten Commits enthalten, deren Replikation auf einen optionalen `long_term_root` noch aussteht. Diese Commits sind gültiger ATHENA-Zustand und werden als `replication_pending` geschützt.

Große Originaldateien werden nicht in die Datenbank gezwungen.

---

### 5. Eine Hauptdatenbank statt vieler autoritativer Datenbanken

Alle strukturierten nicht rekonstruierbaren Domänen und der langlebige Betriebszustand werden für den aktiven Core innerhalb **einer lokalen Transaktionsgrenze** koordiniert:

```text
state_root/db/athena.db
```

Darin liegen beziehungsweise werden materialisiert:

```text
Knowledge
Personal Memory
Raw-Archive-Metadaten
Audit & Provenance
Configuration
Durable Operational State
Commit- und Change-Feed-Metadaten
Replication State
```

Der Grund ist die atomare Transaktionsgrenze. Ein Write wie:

```text
Knowledge Revision
+
Provenance
+
Audit
+
CommitRecord
+
Replication-Pending-Marker
```

muss in **einer** SQLite-Transaktion bestätigt werden können.

Das macht die lokale SQLite-Datei nicht zu einer von Pfad oder Hardware abhängigen semantischen Identität. Die logische Autorität bleibt `ATHENA Persistent Data` mit stabilen IDs und Commit-Historie.

---

### 6. Derived State bleibt außerhalb der Hauptdatenbank

Rekonstruierbare Such- und Performance-Strukturen werden bewusst getrennt:

```text
search.db
SourceChunk Sets
vector index files
cache
previews
temporary derived artifacts
```

Eine Beschädigung dieser Daten darf keinen Verlust von Knowledge, Personal Memory, Raw Archive, Audit/Provenance, Configuration oder noch nicht langzeitreplizierten Commits verursachen.

---

### 7. Keine live SQLite-Datenbank auf Netzwerkfreigaben

Die aktive Datei `athena.db` darf in v1 nicht direkt auf:

- SMB-Freigaben;
- NFS;
- UNC-Netzwerkpfaden;
- sonstigen entfernten Dateisystemen

betrieben werden.

SQLite ist auf zuverlässige Dateisystem-Locks und Synchronisationssemantik angewiesen. Netzwerk-Dateisysteme können diese Garantien verletzen; insbesondere wird der v1-WAL-Betrieb nicht über eine solche Dateifreigabe geführt.

ATHENA erkennt Netzwerkpfade für `state_root` und verweigert dort standardmäßig den normalen Schreibbetrieb.

Dies verhindert **nicht**, dass der langfristige ATHENA-Bestand auf NAS/externem Storage liegt: Dafür existieren `long_term_root`, `archive_root` und `backup_root`, die über verifizierte, versionierte Storage-Protokolle angebunden werden.

---

### 8. Zukünftiger Remote-Betrieb

Soll ATHENA später von mehreren Rechnern gleichzeitig auf denselben aktiven strukturierten Zustand zugreifen, wird nicht die SQLite-Datei über SMB geteilt.

Zulässige Modelle sind beispielsweise:

```text
ATHENA Core auf dem Speicherhost
↓
Clients greifen über Core API zu
```

oder:

```text
StorageProvider
↓
Client/Server-Datenbank
```

Die in v1 verwendete `long_term_root`-Replikation ist **kein Multi-Writer-Synchronisationsprotokoll**. v1 bleibt Single-Writer pro ATHENA-Instanz.

## Teil II – Storage Roots und Dateistruktur

### 9. Zentrale Storage Roots

ATHENA v1 unterscheidet physisch mindestens:

```text
state_root
long_term_root        optional, aber empfohlen für externe/NAS-Langzeitreplikation
archive_root
derived_root
backup_root
```

Optional:

```text
projection_root
```

`long_term_root` und `archive_root` dürfen auf demselben physischen Datenträger/NAS liegen, bleiben logisch getrennte Rollen.

Diese Roots sind Konfiguration und keine Objektidentitäten.

---

### 10. state_root

`state_root` enthält die lokal transaktional benötigte aktive Datenbank und nicht rekonstruierbare noch nicht extern bestätigte Zustände.

Standardstruktur:

```text
state_root/
├── db/
│   └── athena.db
├── spool/
│   ├── blobs/
│   ├── imports/
│   ├── replication/
│   └── outbox/
├── migration/
├── recovery/
├── secrets/
├── locks/
├── reserve/
└── state_manifest.json
```

`state_root` muss auf einem lokal zuverlässigen Dateisystem liegen.

Es ist **nicht vollständig rekonstruierbar**, solange lokale Commits oder Spooldaten noch nicht auf einen anderen dauerhaften Store repliziert beziehungsweise gesichert wurden.

#### long_term_root

`long_term_root` ist die optionale langlebige Replik autoritativer **strukturierter** ATHENA-Persistent-Data-Zustände. Er speichert keine live geöffnete SQLite-WAL-Datenbank, sondern verifizierbare versionierte Replikationsobjekte.

V1-Layout:

```text
long_term_root/
├── repository.json
├── commits/
├── snapshots/
├── manifests/
└── replication/
```

Ein `CanonicalCommitBundle` enthält mindestens `commit_id`, `commit_seq`, Schema-/Formatversion, Hash des Vorgängers beziehungsweise erwarteten Baselines, die für den Commit benötigten strukturierten Revisionen/Metadaten und ein Integritätsmanifest. Periodische strukturierte Snapshots begrenzen die Replay-Länge.

Replikation ist Single-Writer und monoton: Ein Ziel mit einer unerwarteten Historie wird nicht überschrieben, sondern erzeugt einen Recovery-/Conflict-State.

`long_term_root` ist **kein Backup-Ersatz**; versehentliche oder autorisierte Löschungen werden dorthin repliziert. Unabhängige Backups folgen Kapitel 21.

---

### 11. archive_root

`archive_root` enthält große immutable Payloads des Raw Archive.

Beispiel:

```text
archive_root/
├── blobs/
│   └── sha256/
├── protected/
├── representations/
└── quarantine/
```

`archive_root` darf lokal, extern oder auf NAS liegen.

Bei Nichterreichbarkeit übernimmt der lokale Durable Spool. Ein Source-Commit referenziert nur eine tatsächlich verifizierte BlobLocation beziehungsweise eine verifizierte lokale Spoollocation.

---

### 12. derived_root

`derived_root` enthält vollständig rekonstruierbare Daten:

```text
derived_root/
├── search/
│   └── search.db
├── vector/
├── cache/
├── previews/
└── temp/
```

Dazu gehören auch SourceChunk Sets. Standardmäßig soll dieser Root auf schnellem lokalem SSD-Speicher liegen.

---

### 13. backup_root

`backup_root` bezeichnet ein oder mehrere unabhängige Sicherungsziele.

Mindestens ein Backup-Ziel soll physisch vom aktiven `state_root` und möglichst auch vom primären `long_term_root`/`archive_root` getrennt sein.

Ein Backup-Ziel kann lokal, extern oder über das Netzwerk angebunden sein. Backup ist nicht dasselbe wie Langzeitreplikation.

---

### 14. projection_root

`projection_root` enthält menschenlesbare Projektionen wie Obsidian-Markdown.

Diese Daten sind weder aktive Transaktionsdatenbank noch eigenständige semantische Source of Truth.

Beispiel:

```text
projection_root/
└── obsidian/
```

---

### 15. Roots sind verschiebbar

Alle persistierten Storage Roots erhalten intern eine stabile `storage_root_id`.

Objekte referenzieren:

```text
storage_root_id
+
relative_storage_key
```

Nicht absolute Betriebssystempfade als Identität.

Zusätzlich besitzt ATHENA für einen optionalen `long_term_root` einen persistenten Replikations-Watermark:

```text
local_commit_seq
long_term_confirmed_commit_seq
last_verified_at
replication_state
```

Ein Root-Wechsel verändert keine Entity-, Revision-, Commit- oder Source-ID.

---

### 16. state_manifest.json

`state_manifest.json` ist eine kleine recovery-freundliche Datei außerhalb von SQLite.

Sie enthält ausschließlich nicht geheime technische Angaben, mindestens:

```json
{
  "format": "athena-state-manifest",
  "format_version": 1,
  "instance_id": "<uuid>",
  "database": "db/athena.db",
  "application_magic": "ATHN",
  "application_id": 1096042574,
  "storage_layout_version": 1
}
```

Sie enthält keine Passwörter oder vertraulichen Wissensinhalte.

---

### 17. Atomare Manifest-Schreibweise

`state_manifest.json` wird nie in-place überschrieben.

Ablauf:

```text
state_manifest.json.new schreiben
↓
flush + sync
↓
validieren
↓
atomisch ersetzen
```

Nach einem Crash darf entweder die alte oder die neue vollständige Fassung existieren, nicht eine halbe JSON-Datei.

---

### 18. Relative Storage Keys

`relative_storage_key` verwendet intern `/` als logischen Trenner.

Beispiel:

```text
blobs/sha256/ab/cd/abcdef....blob
```

Die Betriebssystemdarstellung wird erst im StorageProvider erzeugt.

---

### 19. Keine benutzerkontrollierten Pfadsegmente

Originaldateinamen werden nicht ungeprüft in kanonische Storage Keys übernommen.

Dadurch verhindert ATHENA:

- Path Traversal;
- ungültige Dateinamen;
- Kollisionen;
- problematische Unicode-Pfade;
- Leaks vertraulicher Dateinamen.

Der ursprüngliche Dateiname bleibt als Source-Metadatum erhalten.

---

## Teil III – SQLite-Laufzeit und Verbindungsregeln

### 20. Hauptdatenbankdatei

Die autoritative Datenbank heißt in v1:

```text
state_root/db/athena.db
```

Andere Namen können später unterstützt werden, sind aber keine Objektidentität.

---

### 21. application_id

ATHENA setzt beim Erstellen der Hauptdatenbank einen festen SQLite `application_id`.

SQLite erwartet dafür einen 32-Bit-Integer. v1 verwendet die Big-Endian-ASCII-Repräsentation von `ATHN`:

```text
"ATHN"
= 0x4154484E
= 1096042574
```

Daher wird konkret gesetzt:

```sql
PRAGMA application_id = 1096042574;
```

Recovery liest den Integer zurück und vergleicht ihn mit diesem Wert, bevor eine unbekannte SQLite-Datei als ATHENA-Datenbank behandelt wird.

Vor einem öffentlichen stabilen Release wird die gewählte Kennung noch einmal gegen die aktuelle SQLite-/`file(1)`-Magic-Registry geprüft und im Release dokumentiert; eine spätere Änderung nach produktiver Nutzung wäre eine formatrelevante Migration.

---

### 22. user_version

SQLite `user_version` enthält eine grobe numerische ATHENA-Schemaversion für Recovery-Werkzeuge.

Die eigentliche Migrationshistorie bleibt zusätzlich in Alembic und ATHENAs eigener `schema_metadata` erhalten.

`user_version` allein ist nicht die Migrationsquelle.

---

### 23. SQLite Capability Probe

ATHENA verlässt sich nicht blind auf eine Versionsnummer.

Beim Start werden benötigte Fähigkeiten geprüft:

- Foreign Keys;
- WAL;
- FTS5 für `search.db`;
- Backup API über den Python-Treiber;
- erforderliche PRAGMAs;
- Transaktionsverhalten.

Fehlt eine zwingende Fähigkeit, startet ATHENA nicht mit unsicheren Ersatzannahmen.

---

### 24. SQLAlchemy und Alembic

Die Persistenzschicht verwendet:

```text
SQLAlchemy 2.x
+
Alembic
```

SQLAlchemy dient:

- Verbindungsverwaltung;
- typisierten Tabellenmetadaten;
- expliziten Transaktionen;
- portableren Repository-Abstraktionen.

Alembic dient versionierten Schema-Migrationen.

Autogenerierte Migrationen sind nur Vorschläge und werden vor Commit manuell geprüft.

---

### 25. SQLAlchemy Core bevorzugt

Für das Storage-Layer wird **SQLAlchemy Core beziehungsweise eine dünne Repository-Schicht** bevorzugt.

Die Domänenlogik darf nicht in schwer nachvollziehbare ORM-Lifecycle-Magie verlagert werden.

Semantische Entscheidungen bleiben im ATHENA Core.

---

### 26. Single Writer Coordinator

Obwohl SQLite mehrere Leser erlaubt, koordiniert ATHENA alle autoritativen Writes über genau einen logischen:

```text
CanonicalWriteCoordinator
```

Dieser serialisiert Commit-Grenzen und verhindert unnötige Write-Lock-Konkurrenz.

---

### 27. Mehrere Reader

Read-only Repository-Operationen dürfen mehrere Datenbankverbindungen verwenden.

Leser dürfen den Writer nicht unnötig blockieren.

Langlaufende Leser müssen begrenzt beziehungsweise paginiert werden, damit WAL-Checkpointing nicht dauerhaft verhindert wird.

---

### 28. Prozesssperre

Vor dem Öffnen im Schreibmodus erwirbt ATHENA eine Betriebssystem-Dateisperre:

```text
state_root/locks/core.lock
```

Nur ein Core darf denselben `state_root` im Schreibmodus besitzen.

Zweite Instanzen wechseln nicht heimlich in parallelen Schreibbetrieb.

---

### 29. Stale Lock Recovery

Die Lockdatei allein bestimmt nicht, ob ein Prozess aktiv ist.

ATHENA prüft:

- tatsächlichen OS-Lock;
- PID soweit verfügbar;
- Prozessstartkennung;
- Instance ID.

Eine veraltete Textdatei darf keinen dauerhaften Lockout verursachen.

---

### 30. PRAGMA foreign_keys

Jede Verbindung zur Hauptdatenbank setzt explizit:

```sql
PRAGMA foreign_keys = ON;
```

ATHENA liest den Wert anschließend zurück.

Es wird niemals auf SQLite-Defaultverhalten vertraut.

---

### 31. PRAGMA journal_mode

Die Hauptdatenbank verwendet:

```sql
PRAGMA journal_mode = WAL;
```

WAL wird nur auf lokalem unterstütztem Storage verwendet.

---

### 32. PRAGMA synchronous

Für die autoritative Hauptdatenbank gilt:

```sql
PRAGMA synchronous = FULL;
```

Datenintegrität und Commit-Durability besitzen Vorrang vor maximaler Schreibgeschwindigkeit.

---

### 33. PRAGMA busy_timeout

v1 setzt pro Verbindung mindestens:

```sql
PRAGMA busy_timeout = 5000;
```

Der konkrete Wert bleibt konfigurierbar.

ATHENA darf bei `SQLITE_BUSY` dennoch nicht unendlich blockieren, sondern verwendet begrenzte Retry-Logik.

---

### 34. PRAGMA secure_delete

Für `athena.db` wird standardmäßig:

```sql
PRAGMA secure_delete = ON;
```

gesetzt.

Dies reduziert zurückbleibende gelöschte Inhalte in normalen SQLite-Tabellen.

Es ist **keine Garantie für physische Löschung auf SSDs, Dateisystem-Snapshots oder Backups**.

---

### 35. PRAGMA auto_vacuum

Neue ATHENA-v1-Datenbanken werden vor dem ersten produktiven Schema mit:

```sql
PRAGMA auto_vacuum = INCREMENTAL;
```

erstellt.

Dadurch kann freier Datenbankplatz später kontrolliert in kleinen Wartungsschritten zurückgegeben werden.

---

### 36. Incremental Vacuum

ATHENA führt kein unkontrolliertes Voll-`VACUUM` während normaler Nutzung aus.

Stattdessen werden in Wartungsfenstern begrenzte:

```sql
PRAGMA incremental_vacuum(...)
```

Schritte verwendet.

Ein vollständiges `VACUUM` ist eine explizite Maintenance-/Migration-Operation mit Speicherplatzprüfung.

---

### 37. PRAGMA trusted_schema

Soweit die eingesetzte SQLite-Version dies unterstützt, setzt ATHENA:

```sql
PRAGMA trusted_schema = OFF;
```

Das Storage-Layer prüft den tatsächlich gesetzten Wert.

Schema-Features, die dadurch inkompatibel würden, dürfen nicht stillschweigend eingebaut werden.

---

### 38. PRAGMA read_uncommitted

ATHENA verwendet:

```sql
PRAGMA read_uncommitted = OFF;
```

Unbestätigte autoritative Writes werden nicht als Wissenszustand gelesen.

---

### 39. WAL Auto-Checkpoint

Ausgangspunkt:

```sql
PRAGMA wal_autocheckpoint = 1000;
```

Zusätzlich überwacht ATHENA die reale WAL-Größe.

Der Wert ist Performancekonfiguration, keine Datenmodell-Invariante.

---

### 40. WAL-Größenüberwachung

ATHENA beobachtet:

```text
athena.db-wal
```

und erkennt ungewöhnliches Wachstum.

Mögliche Ursachen:

- langlaufender Reader;
- blockiertes Checkpointing;
- sehr große Schreibtransaktion;
- Storage-Probleme.

ATHENA löscht eine WAL-Datei niemals manuell.

---

### 41. Checkpoint-Strategie

Normalbetrieb:

```text
PASSIVE checkpoints
```

in Hintergrundintervallen.

Wenn der Core idle ist und keine störenden Reader existieren, darf ATHENA:

```text
TRUNCATE checkpoint
```

verwenden.

Vor kontrollierten Offline-Kopien oder Migrationen wird ein sauberer Checkpoint durchgeführt.

---

### 42. Kein manuelles Kopieren einer offenen DB

Eine laufende `athena.db` wird nicht mit normalen Dateikopierbefehlen als Backup kopiert.

Für Live-Snapshots wird die SQLite Online Backup API verwendet.

Alternativ wird der Core vollständig beendet und die Datenbank einschließlich erforderlicher Journaldateien in einem konsistenten Zustand behandelt.

---

## Teil IV – Physische Datentypen

### 43. UUID-Speicherformat

UUIDv7 wird in SQLite als:

```text
BLOB mit exakt 16 Bytes
```

gespeichert.

Extern bleibt die kanonische UUID-Textform erhalten.

Vorteile:

- geringerer Platzbedarf;
- kleinere Indizes;
- keine Stringformatvarianten;
- schnelle Gleichheitsvergleiche.

---

### 44. UUID CHECK Constraint

UUID-Spalten erhalten soweit praktisch:

```sql
CHECK(length(<id>) = 16)
```

Ein `NULL` bleibt nur bei ausdrücklich optionalen Referenzen zulässig.

---

### 45. Zeitstempel

Normalisierte UTC-Zeitstempel werden physisch als:

```text
INTEGER
```

mit Mikrosekunden seit Unix Epoch gespeichert.

Beispielspalte:

```text
created_at_us
```

Die API konvertiert zu RFC-3339-UTC.

---

### 46. Originalzeit

Wenn die Quellzeit relevant ist, werden zusätzlich gespeichert:

```text
original_time_text TEXT
original_timezone TEXT
time_precision TEXT
```

Die UTC-Normalisierung löscht diese Information nicht.

---

### 47. Boolean

Booleans werden als:

```text
INTEGER
```

mit:

```sql
CHECK(value IN (0,1))
```

gespeichert.

---

### 48. Enums

Kleine stabile Zustandsmengen werden als `TEXT` gespeichert.

Kritische Kernzustände erhalten `CHECK` Constraints.

Erweiterbare semantische Kategorien werden primär im Core validiert, damit spätere Erweiterungen keine unnötig destruktive Tabellenmigration erzwingen.

---

### 49. Hashes

ATHENA v1 verwendet für:

- Blob-Integrität;
- Payload-Integrität;
- Backup-Manifest;
- kanonische Serialisierung

standardmäßig:

```text
SHA-256
```

Hashes werden physisch als 32-Byte-BLOB gespeichert, nicht als 64-stellige Hexstrings.

---

### 50. Geschützte Inhalte und Hashes

Für geschützte Inhalte wird außerhalb des entsperrten Schutzkontexts **kein deterministischer Klartext-Content-Hash** gespeichert.

Diese Regel gilt für **jede** content-derived Hashspalte, insbesondere:

```text
revisions.payload_hash
source_representations.content_hash
source_anchors.quoted_hash
Derived Chunk content_hash
search_documents.content_hash
embedding_records.content_hash
```

Physische Semantik:

```text
unprotected payload:
SHA-256(canonical plaintext bytes)

protected persisted payload:
SHA-256(ciphertext/envelope bytes)

protected quoted/content fingerprint, falls fachlich nötig:
keyed HMAC-SHA-256 mit einem Scope-spezifisch abgeleiteten Fingerprint-Key
oder NULL
```

Ein Klartext-SHA-256 eines Protected Payloads darf nur **innerhalb eines selbst verschlüsselten Protected Payloads** gespeichert werden, wenn er für interne Integritäts-/Deduplizierungszwecke ausdrücklich benötigt wird.

Protected Blobs werden im öffentlichen BlobRecord über den SHA-256-Hash des Ciphertexts adressiert. Klartext-Deduplizierung geschützter Dateien ist deaktiviert.

---

### 51. Kanonisches JSON

Strukturierte Payloads, deren Hash reproduzierbar sein muss, werden nach **RFC 8785 JSON Canonicalization Scheme** serialisiert.

Regeln:

- UTF-8;
- deterministische Property-Reihenfolge;
- keine bedeutungslose Whitespace-Variation;
- keine doppelten Property-Namen;
- keine NaN-/Infinity-Sonderwerte.

Der SHA-256 wird über die kanonischen Bytes gebildet.

---

### 52. JSON in SQLite

Erweiterbare strukturierte Parameter werden als:

```text
TEXT
```

mit kanonischem JSON gespeichert.

Beispiele:

- Generation Parameters;
- pinned configuration;
- Resume Metadata;
- Retrieval Configuration.

Kerninvarianten bleiben in normalen Spalten und werden nicht in JSON versteckt.

---

### 53. Große Binärpayloads

Originaldateien werden **unabhängig von ihrer Größe** im Blob Store gespeichert.

Große technische oder provenance-relevante Repräsentationen werden ebenfalls über Blob Storage abgelegt.

Die SQLite-Hauptdatenbank ist kein allgemeiner Datei-Container.

---

### 54. Große Textrepräsentationen

Extrahierte Volltexte von Dokumenten werden als immutable UTF-8-Representation-Blob gespeichert.

Chunks referenzieren Offsets beziehungsweise Anchors in dieser Representation.

Dadurch muss eine mehrmegabytegroße Dokumentrepräsentation nicht als einzelne SQLite-Zelle historisiert werden.

---

## Teil V – Kernschema und generische Tabellen

### 55. entity_registry

Jede langlebig adressierbare Entität wird zusätzlich in einer zentralen Registry geführt:

```text
entity_registry
```

Kernspalten:

```text
entity_id BLOB(16) PRIMARY KEY
entity_type TEXT NOT NULL
domain TEXT NOT NULL
created_at_us INTEGER NOT NULL
created_by_actor_id BLOB(16) NULL
lifecycle_state TEXT NOT NULL
protection_scope_id BLOB(16) NULL
schema_version INTEGER NOT NULL
```

`lifecycle_state` und `protection_scope_id` sind die **aktuelle materialisierte Sicht**.

Historisch relevante Zustandswechsel werden zusätzlich append-only in:

```text
entity_state_history
```

gespeichert:

```text
entity_id BLOB(16) NOT NULL
valid_from_commit_seq INTEGER NOT NULL
valid_to_commit_seq INTEGER NULL
lifecycle_state TEXT NOT NULL
protection_scope_id BLOB(16) NULL
changed_by_actor_id BLOB(16) NOT NULL
reason TEXT NULL
PRIMARY KEY(entity_id, valid_from_commit_seq)
```

Der vorherige Historieneintrag wird im selben Canonical Commit durch `valid_to_commit_seq` geschlossen. Dadurch können `as-of`-Abfragen den damaligen Lifecycle-/Protectionzustand rekonstruieren.

---

### 56. entity_registry WITHOUT ROWID

`entity_registry` wird als:

```sql
WITHOUT ROWID
```

angelegt.

Da die stabile UUID bereits der natürliche Primärschlüssel ist, wird kein zusätzlicher versteckter RowID benötigt.

---

### 57. Domain Constraint

`domain` akzeptiert mindestens:

```text
knowledge
personal_memory
raw_archive
audit_provenance
configuration
operational
```

Derived State wird nicht in der autoritativen Registry benötigt.

---

### 58. actors

`actors` speichert technische Akteursidentitäten:

```text
actor_id BLOB(16) PRIMARY KEY
actor_type TEXT NOT NULL
display_name TEXT NULL
plugin_id BLOB(16) NULL
created_at_us INTEGER NOT NULL
active INTEGER NOT NULL
```

Akteursdaten verleihen keine semantische Autorität; sie dokumentieren Herkunft.

---

### 59. revisions

Gemeinsame Revisionsmetadaten liegen in:

```text
revisions
```

Spalten:

```text
revision_id BLOB(16) PRIMARY KEY
entity_id BLOB(16) NOT NULL
revision_no INTEGER NOT NULL
parent_revision_id BLOB(16) NULL
created_at_us INTEGER NOT NULL
created_by_actor_id BLOB(16) NOT NULL
provenance_id BLOB(16) NOT NULL
schema_version INTEGER NOT NULL
payload_hash BLOB(32) NOT NULL
change_kind TEXT NOT NULL
commit_id BLOB(16) NOT NULL
UNIQUE(entity_id, revision_no)
```

---

### 60. entity_heads

Revisionierte Entitäten besitzen:

```text
entity_heads
```

mit:

```text
entity_id BLOB(16) PRIMARY KEY
current_revision_id BLOB(16) NOT NULL
current_revision_no INTEGER NOT NULL
```

Der Head wird nur in derselben Transaktion wie die neue Revision aktualisiert.

---

### 61. Revision-Payloads bleiben typspezifisch

`revisions` enthält nur gemeinsame Metadaten.

Semantische Payloads liegen in typisierten Tabellen wie:

```text
knowledge_unit_revisions
claim_revisions
project_revisions
concept_note_revisions
personal_memory_revisions
chat_message_revisions
configuration_revisions
retention_rule_revisions
```

ATHENA verwendet keine universelle `payload_json`-Tabelle für sein Kernwissen.

---

### 62. commit_records

Atomare Writes erhalten:

```text
commit_records
```

Spalten:

```text
commit_seq INTEGER PRIMARY KEY AUTOINCREMENT
commit_id BLOB(16) NOT NULL UNIQUE
committed_at_us INTEGER NOT NULL
actor_id BLOB(16) NOT NULL
operation_type TEXT NOT NULL
reason TEXT NULL
```

`commit_seq` ist die lokale monotone Snapshot-Grenze.

---

### 63. commit_changes

Zu jedem Commit werden betroffene Entitäten gespeichert:

```text
commit_changes
```

Spalten:

```text
commit_seq INTEGER NOT NULL
entity_id BLOB(16) NOT NULL
revision_id BLOB(16) NULL
change_type TEXT NOT NULL
PRIMARY KEY(commit_seq, entity_id, change_type)
```

Diese Tabelle ist zugleich Grundlage des Change Feeds.

---

### 64. schema_metadata

`schema_metadata` enthält mindestens:

```text
schema_epoch
schema_version
storage_layout_version
blob_format_version
created_at_us
last_migration_id
minimum_reader_version
```

Sie ergänzt Alembics `alembic_version`.

Für einen konfigurierten `long_term_root` existiert zusätzlich persistenter Replikationszustand:

```text
replication_targets
-------------------
target_root_id BLOB(16) PRIMARY KEY
repository_id BLOB(16) NOT NULL
confirmed_commit_seq INTEGER NOT NULL
confirmed_head_hash BLOB(32) NULL
state TEXT NOT NULL
last_verified_at_us INTEGER NULL

replication_commits
-------------------
target_root_id BLOB(16) NOT NULL
commit_seq INTEGER NOT NULL
commit_id BLOB(16) NOT NULL
bundle_hash BLOB(32) NOT NULL
state TEXT NOT NULL
verified_at_us INTEGER NULL
PRIMARY KEY(target_root_id, commit_seq)
```

Ein `CanonicalCommitBundle` wird kanonisch serialisiert und enthält ausschließlich die für die Replikation des strukturierten Persistent-State-Commits benötigten Revisionen/Metadaten. Protected Inhalte erscheinen darin nur als Ciphertext beziehungsweise opaque Protected-Payload-Referenzen.

Periodische strukturierte `long_term_root`-Snapshots begrenzen die Replay-Länge. Recovery kann eine neue `athena.db` aus einem verifizierten Snapshot plus nachfolgenden Commit Bundles rekonstruieren; danach werden Derived State und Indizes separat neu aufgebaut.

## Teil VI – Knowledge-Tabellen

### 65. knowledge_units

Stabile KnowledgeUnit-Entitäten liegen in:

```text
knowledge_units
```

Spalten:

```text
knowledge_id BLOB(16) PRIMARY KEY
```

Weitere gemeinsame Metadaten stammen aus `entity_registry` und `entity_heads`.

---

### 66. knowledge_unit_revisions

Strukturierte Revisionen enthalten mindestens:

```text
revision_id BLOB(16) PRIMARY KEY
knowledge_kind TEXT NULL
title TEXT NULL
body TEXT NULL
valid_from_us INTEGER NULL
valid_to_us INTEGER NULL
epistemic_status TEXT NULL
protected_payload_id BLOB(16) NULL
```

Bei geschütztem Inhalt dürfen vertrauliche Felder `NULL` sein und im verschlüsselten Payload liegen.

---

### 67. claims

`claims` enthält die stabile Claim-ID:

```text
claim_id BLOB(16) PRIMARY KEY
```

Die aktuelle Revision wird über `entity_heads` bestimmt.

---

### 68. claim_revisions

Mindestens:

```text
revision_id BLOB(16) PRIMARY KEY
claim_kind TEXT NULL
statement TEXT NULL
subject_entity_id BLOB(16) NULL
predicate TEXT NULL
object_entity_id BLOB(16) NULL
attributed_to_entity_id BLOB(16) NULL
valid_from_us INTEGER NULL
valid_to_us INTEGER NULL
epistemic_status TEXT NULL
protected_payload_id BLOB(16) NULL
```

---

### 69. claim_evidence

Claim-Evidenz wird normalisiert in:

```text
claim_evidence
```

Mindestens:

```text
claim_id BLOB(16)
anchor_id BLOB(16) NULL
message_id BLOB(16) NULL
evidence_entity_id BLOB(16) NULL
evidence_revision_id BLOB(16) NULL
evidence_role TEXT NOT NULL
provenance_id BLOB(16) NOT NULL
```

Mindestens eine konkrete Evidenzreferenz muss gesetzt sein.

---

### 70. interpretations

Interpretationen sind in v1 immutable Records:

```text
interpretation_id BLOB(16) PRIMARY KEY
target_entity_id BLOB(16) NOT NULL
target_revision_id BLOB(16) NULL
interpretation_type TEXT NOT NULL
content TEXT NULL
protected_payload_id BLOB(16) NULL
created_at_us INTEGER NOT NULL
created_by_actor_id BLOB(16) NOT NULL
provenance_id BLOB(16) NOT NULL
model_signature_id BLOB(16) NULL
processing_run_id BLOB(16) NULL
```

Eine neue Interpretation erzeugt eine neue `interpretation_id`.

---

### 71. relationships

Relationships werden in v1 als immutable Kanten gespeichert:

```text
relation_id BLOB(16) PRIMARY KEY
source_entity_id BLOB(16) NOT NULL
relation_type TEXT NOT NULL
target_entity_id BLOB(16) NOT NULL
created_at_us INTEGER NOT NULL
created_by_actor_id BLOB(16) NOT NULL
provenance_id BLOB(16) NOT NULL
lifecycle_state TEXT NOT NULL
protection_scope_id BLOB(16) NULL
superseded_by_relation_id BLOB(16) NULL
```

Eine semantische Änderung an Source, Target oder Typ erzeugt eine neue Relation und superseded die alte.

---

### 72. projects und project_revisions

`projects` enthält:

```text
project_id BLOB(16) PRIMARY KEY
```

`project_revisions` enthält mindestens:

```text
revision_id BLOB(16) PRIMARY KEY
name TEXT NULL
description TEXT NULL
project_state TEXT NULL
protected_payload_id BLOB(16) NULL
```

---

### 73. concept_notes und concept_note_revisions

`concept_notes` enthält die stabile ID.

`concept_note_revisions` enthält:

```text
revision_id BLOB(16) PRIMARY KEY
title TEXT NULL
body TEXT NULL
protected_payload_id BLOB(16) NULL
```

Verknüpfungen zu Claims, KnowledgeUnits und Sources erfolgen über Relationships beziehungsweise explizite Referenztabellen.

---

## Teil VII – Personal-Memory-Tabellen

### 74. personal_memory_entries

Stabile Personal-Memory-Identitäten:

```text
personal_memory_entries
```

Spalten:

```text
memory_id BLOB(16) PRIMARY KEY
```

Die Domain bleibt `personal_memory`.

---

### 75. personal_memory_revisions

Mindestens:

```text
revision_id BLOB(16) PRIMARY KEY
memory_kind TEXT NULL
content TEXT NULL
scope_entity_id BLOB(16) NULL
scope_kind TEXT NULL
learning_mode TEXT NULL
sensitivity TEXT NULL
confidence REAL NULL
last_confirmed_at_us INTEGER NULL
protected_payload_id BLOB(16) NULL
```

Projektinhalt selbst darf nicht als Personal-Memory-Payload gespeichert werden.

---

## Teil VIII – Raw-Archive-Tabellen

### 76. sources

`sources` ist die stabile Identität importierter Originalquellen.

Mindestens:

```text
source_id BLOB(16) PRIMARY KEY
source_type TEXT NOT NULL
acquired_at_us INTEGER NOT NULL
source_created_at_us INTEGER NULL
original_name TEXT NULL
mime_type TEXT NULL
primary_blob_id BLOB(16) NULL
source_uri TEXT NULL
original_time_text TEXT NULL
original_timezone TEXT NULL
time_precision TEXT NULL
provenance_id BLOB(16) NOT NULL
protection_scope_id BLOB(16) NULL
protected_metadata_payload_id BLOB(16) NULL
```

Für unprotected Sources können die menschenlesbaren Metadaten in den normalen Spalten liegen.

Für Protected Sources gilt dagegen:

- verräterische Metadaten wie `original_name`, `source_uri`, Originalzeit/-zone und gegebenenfalls genauer MIME-/Medientyp werden im normalen Row `NULL` beziehungsweise auf eine neutrale technische Klasse gesetzt;
- die echten Werte liegen im verschlüsselten `protected_metadata_payload_id`;
- Locked UI, Logs, Search und Audit dürfen nicht auf eine ungeschützte Schattenkopie zurückgreifen.

`source_type` darf nur so spezifisch sein, wie es die gewählte Protection Policy im gesperrten Zustand zulässt.

---

### 77. source_relations

Versionen und Familien von Sources werden explizit verbunden:

```text
source_relations
```

Beispiele für `relation_type`:

```text
version_of
supersedes
captured_from
attachment_of
```

---

### 78. blob_records

Blob-Metadaten liegen in:

```text
blob_records
```

Mindestens:

```text
blob_id BLOB(16) PRIMARY KEY
byte_length INTEGER NOT NULL
media_type TEXT NULL
hash_algorithm TEXT NOT NULL
integrity_hash BLOB(32) NOT NULL
encryption_state TEXT NOT NULL
created_at_us INTEGER NOT NULL
verified_at_us INTEGER NULL
blob_format_version INTEGER NOT NULL
```

Der BlobRecord enthält keinen absoluten Pfad.

Bei Protected Blobs ist `integrity_hash` der Ciphertext-Hash. `media_type` wird im Locked State nur in einer neutralen Form persistiert, wenn ein genauer Medientyp selbst sensitiv sein kann; der genaue Typ kann in den verschlüsselten Source-/Payloadmetadaten liegen.

---

### 79. blob_locations

Da ein Blob während Migration oder Synchronisation mehrere Kopien besitzen kann, werden Locations separat gespeichert:

```text
blob_locations
```

Mindestens:

```text
blob_id BLOB(16) NOT NULL
storage_root_id BLOB(16) NOT NULL
storage_key TEXT NOT NULL
location_state TEXT NOT NULL
verified_at_us INTEGER NULL
byte_length INTEGER NOT NULL
PRIMARY KEY(blob_id, storage_root_id, storage_key)
```

---

### 80. Location States

Mindestens:

```text
staged
verified
preferred
migrating
quarantined
pending_delete
```

Eine `preferred` Location muss vollständig verifiziert sein.

---

### 81. source_representations

Extrahierter oder transformierter Quellinhalt kann als `SourceRepresentation` gespeichert werden.

Mindestens:

```text
representation_id BLOB(16) PRIMARY KEY
source_id BLOB(16) NOT NULL
representation_type TEXT NOT NULL
blob_id BLOB(16) NOT NULL
processing_run_id BLOB(16) NOT NULL
content_hash BLOB(32) NOT NULL
retention_state TEXT NOT NULL
created_at_us INTEGER NOT NULL
```

`retention_state` unterscheidet mindestens:

```text
disposable
retained
```

Eine `retained` Representation ist immutable und wird wie Raw-Archive-Zustand geschützt, solange SourceAnchors, Claims oder andere langlebige Provenienz exakt diese Fassung referenzieren.

Eine `disposable` Representation darf als Derived State neu erzeugt und entfernt werden, wenn keine langlebige Referenz sie benötigt.

Für Protected Representations gilt die globale Ciphertext-/Hashregel aus Abschnitt 50.

---

### 82. source_chunks

`source_chunks` sind **Derived State** und werden in v1 in `search.db` beziehungsweise einem äquivalenten Derived-State-Store gespeichert, nicht als autoritative Raw-Archive-Tabelle in `athena.db`.

Derived Chunk-Metadaten:

```text
chunk_id BLOB(16) PRIMARY KEY
source_id BLOB(16) NOT NULL
representation_id BLOB(16) NOT NULL
chunk_index INTEGER NOT NULL
chunking_profile_id BLOB(16) NOT NULL
anchor_id BLOB(16) NULL
start_anchor_value INTEGER NULL
end_anchor_value INTEGER NULL
content_hash BLOB(32) NOT NULL
processing_run_id BLOB(16) NOT NULL
build_signature BLOB(32) NOT NULL
created_at_us INTEGER NOT NULL
```

Der eigentliche Chunktext liegt ebenfalls nur im Derived Search Store beziehungsweise wird aus der SourceRepresentation gelesen.

Persistente Claims, ProvenanceRecords oder langfristige ResearchResults dürfen **nicht ausschließlich** auf `chunk_id` verweisen; sie materialisieren stabile SourceAnchor-/Representation-Refs.

---

### 83. chunking_profiles

Versionierte Chunking-Konfigurationen werden als reproduktionsrelevante technische Processing-/Configuration-Metadaten in `athena.db` festgehalten:

```text
chunking_profiles
```

Mindestens:

```text
chunking_profile_id BLOB(16) PRIMARY KEY
algorithm TEXT NOT NULL
tokenizer TEXT NULL
target_size INTEGER NULL
overlap_size INTEGER NULL
structure_rules_json TEXT NOT NULL
profile_version INTEGER NOT NULL
created_at_us INTEGER NOT NULL
```

Die Profile sind notwendig, um Derived Chunksets nachvollziehbar neu zu erzeugen; die Chunkrecords selbst bleiben Derived State.

---

### 84. source_anchors

Stabile Evidenzanker:

```text
anchor_id BLOB(16) PRIMARY KEY
source_id BLOB(16) NOT NULL
representation_id BLOB(16) NULL
anchor_type TEXT NOT NULL
start_offset INTEGER NULL
end_offset INTEGER NULL
page_start INTEGER NULL
page_end INTEGER NULL
start_time_ms INTEGER NULL
end_time_ms INTEGER NULL
geometry_json TEXT NULL
quoted_hash BLOB(32) NULL
```

Nicht zutreffende Felder bleiben `NULL`.

---

### 85. chats

`chats` enthält mindestens:

```text
chat_id BLOB(16) PRIMARY KEY
started_at_us INTEGER NOT NULL
ended_at_us INTEGER NULL
archive_mode TEXT NOT NULL
lifecycle_state TEXT NOT NULL
protection_scope_id BLOB(16) NULL
```

---

### 86. chat_messages

Stabile Nachrichtenidentität:

```text
message_id BLOB(16) PRIMARY KEY
chat_id BLOB(16) NOT NULL
sequence_no INTEGER NOT NULL
message_type TEXT NOT NULL
actor_id BLOB(16) NULL
UNIQUE(chat_id, sequence_no)
```

---

### 87. chat_message_revisions

Mindestens:

```text
revision_id BLOB(16) PRIMARY KEY
content TEXT NULL
content_format TEXT NULL
protected_payload_id BLOB(16) NULL
```

Die allgemeinen Revisionsfelder liegen in `revisions`.

---

### 88. message_attachments

Anhänge werden über Sources referenziert:

```text
message_attachments
```

mit:

```text
message_id
source_id
ordinal
```

Die Dateibytes liegen ausschließlich im Blob Store.

---

## Teil IX – Provenienz, Audit und Modellmetadaten

### 89. provenance_records

Mindestens:

```text
provenance_id BLOB(16) PRIMARY KEY
subject_entity_id BLOB(16) NOT NULL
subject_revision_id BLOB(16) NULL
operation TEXT NOT NULL
actor_id BLOB(16) NOT NULL
created_at_us INTEGER NOT NULL
model_signature_id BLOB(16) NULL
processing_run_id BLOB(16) NULL
reason TEXT NULL
protection_scope_id BLOB(16) NULL
```

---

### 90. provenance_inputs

Mehrere Inputs werden in:

```text
provenance_inputs
```

gespeichert:

```text
provenance_id
input_entity_id
input_revision_id
input_role
ordinal
```

Damit bleibt die Ableitung aus mehreren Quellen nachvollziehbar.

---

### 91. provenance_parents

Mehrstufige Herkunft verwendet:

```text
provenance_parents
```

mit:

```text
provenance_id
parent_provenance_id
```

Zyklen sind auf Anwendungsebene verboten.

---

### 92. model_signatures

Mindestens:

```text
model_signature_id BLOB(16) PRIMARY KEY
provider TEXT NOT NULL
model_identifier TEXT NOT NULL
model_revision TEXT NULL
quantization TEXT NULL
generation_parameters_json TEXT NOT NULL
context_configuration_json TEXT NULL
signature_hash BLOB(32) NOT NULL
created_at_us INTEGER NOT NULL
UNIQUE(signature_hash)
```

Unbekannte Werte werden nicht erfunden.

---

### 93. processing_runs

Mindestens:

```text
processing_run_id BLOB(16) PRIMARY KEY
run_type TEXT NOT NULL
started_at_us INTEGER NOT NULL
finished_at_us INTEGER NULL
status TEXT NOT NULL
trigger_actor_id BLOB(16) NOT NULL
pipeline_version TEXT NOT NULL
input_snapshot_json TEXT NOT NULL
configuration_hash BLOB(32) NOT NULL
model_signature_id BLOB(16) NULL
prompt_template_id TEXT NULL
prompt_template_version TEXT NULL
```

---

### 94. processing_stages

Mindestens:

```text
processing_stage_id BLOB(16) PRIMARY KEY
processing_run_id BLOB(16) NOT NULL
stage_type TEXT NOT NULL
ordinal INTEGER NOT NULL
started_at_us INTEGER NULL
finished_at_us INTEGER NULL
status TEXT NOT NULL
input_manifest_json TEXT NULL
output_manifest_json TEXT NULL
```

---

### 95. audit_events

Mindestens:

```text
audit_event_id BLOB(16) PRIMARY KEY
event_type TEXT NOT NULL
occurred_at_us INTEGER NOT NULL
actor_id BLOB(16) NULL
commit_id BLOB(16) NULL
result TEXT NOT NULL
reason_code TEXT NULL
sanitized_summary TEXT NULL
protection_scope_id BLOB(16) NULL
```

---

### 96. audit_targets

Mehrere Audit-Ziele:

```text
audit_event_id
target_entity_id
target_revision_id
target_role
```

Vollständige Inhaltskopien werden nicht in Audit-Zeilen abgelegt.

---

## Teil X – Configuration, Retention und Schutz

### 97. configuration_entries

Stabile Konfigurationseinträge:

```text
configuration_id BLOB(16) PRIMARY KEY
config_key TEXT NOT NULL
config_scope TEXT NOT NULL
scope_entity_id BLOB(16) NULL
```

Ein einfaches `UNIQUE(config_scope, scope_entity_id, config_key)` reicht in SQLite **nicht**, weil mehrere `NULL`-Werte in Unique-Indizes als verschieden behandelt werden.

v1 verwendet deshalb zwei eindeutige Partial Indexes:

```sql
CREATE UNIQUE INDEX uq_configuration_global
ON configuration_entries(config_scope, config_key)
WHERE scope_entity_id IS NULL;

CREATE UNIQUE INDEX uq_configuration_scoped
ON configuration_entries(config_scope, scope_entity_id, config_key)
WHERE scope_entity_id IS NOT NULL;
```

Damit existiert pro globalem beziehungsweise entity-scoped Key genau ein ConfigurationEntry.

---

### 98. configuration_revisions

Mindestens:

```text
revision_id BLOB(16) PRIMARY KEY
value_type TEXT NOT NULL
value_text TEXT NULL
value_json TEXT NULL
secret_ref TEXT NULL
```

Secrets dürfen nicht als Klartext in `value_text` oder `value_json` stehen.

---

### 99. retention_rules und Revisionen

`retention_rules` enthält die stabile Regel-ID.

`retention_rule_revisions` enthält:

```text
revision_id
scope
target_type
condition_json
action
enabled
```

Eine Regeländerung erzeugt eine neue Revision.

---

### 100. protection_scopes

`protection_scopes` beschreibt ausschließlich den **persistenten Lifecycle** eines Schutzbereichs:

```text
protection_scope_id BLOB(16) PRIMARY KEY
lifecycle_state TEXT NOT NULL
created_at_us INTEGER NOT NULL
current_scope_key_id BLOB(16) NULL
neutral_label TEXT NULL
```

Erlaubte v1-Lifecyclewerte sind mindestens:

```text
active
retired
pending_delete
```

`locked` und `unlocked` sind **keine persistenten Scope-Zustände**. Sie gehören zum Runtime `SecurityContext`. Nach Prozessstart gilt jeder Protected Scope zunächst als locked.

`neutral_label` darf keine geschützten Inhalte offenlegen.

#### Persistente Schlüsselobjekte

Die in Kapitel 16 beschriebene Keyhierarchie wird physisch durch drei zusätzliche Strukturen abgebildet.

`key_slots` wickelt den zufälligen ATHENA Root Key für unterschiedliche Unlockwege:

```text
key_slot_id BLOB(16) PRIMARY KEY
slot_type TEXT NOT NULL              # password | recovery | os_secret
kdf_algorithm TEXT NULL
kdf_parameters_json TEXT NULL
salt BLOB NULL
wrap_algorithm TEXT NOT NULL
wrap_nonce BLOB NOT NULL
wrapped_root_key BLOB NOT NULL
created_at_us INTEGER NOT NULL
retired_at_us INTEGER NULL
status TEXT NOT NULL
```

Ein Password Slot verwendet Argon2id zur KEK-Ableitung. Ein Recovery Slot ist ein **separater Wrapper desselben Root Keys** und wird nicht neben dem Backup im Klartext gespeichert.

`protection_scope_keys` enthält versionierte Scope Keys, unter dem Root Key gewrappt:

```text
scope_key_id BLOB(16) PRIMARY KEY
protection_scope_id BLOB(16) NOT NULL
key_version INTEGER NOT NULL
wrap_algorithm TEXT NOT NULL
wrap_nonce BLOB NOT NULL
wrapped_scope_key BLOB NOT NULL
created_at_us INTEGER NOT NULL
retired_at_us INTEGER NULL
status TEXT NOT NULL
UNIQUE(protection_scope_id, key_version)
```

Große Protected Blobs erhalten zusätzlich ein `protected_blob_envelopes`-Record:

```text
blob_id BLOB(16) PRIMARY KEY
protection_scope_id BLOB(16) NOT NULL
scope_key_id BLOB(16) NOT NULL
wrapped_dek BLOB NOT NULL
dek_wrap_nonce BLOB NOT NULL
nonce_prefix BLOB NOT NULL            # 8 Bytes
chunk_size INTEGER NOT NULL
cipher_suite TEXT NOT NULL
format_version INTEGER NOT NULL
```

Damit sind Passwortwechsel, Recovery-Key-Slot, Scope-Key-Rotation und DEK-Rotation ohne implizite Schlüsselannahmen implementierbar.

Für v1 gilt für die kryptographischen Wrapping-Schritte konkret:

```text
wrap_algorithm = AES-256-GCM
nonce = kryptographisch zufällige 96 Bit pro Wrapping-Vorgang
AAD = typisierte kanonische Bindung aus Key-/Scope-/Objekt-ID, Key-Version und Format-Version
```

Ein Nonce darf unter demselben Wrapping-Key niemals wiederverwendet werden. `wrap_algorithm` bleibt als persistentes Feld erhalten, damit ein späterer, ausdrücklich migrierter Algorithmuswechsel möglich ist. Die Root-, Scope- und DEK-Schlüssel sind jeweils zufällige 256-Bit-Schlüssel.

---

### 101. protected_payloads

Verschlüsselte strukturierte Inhalte werden in `protected_payloads` gespeichert:

```text
protected_payload_id BLOB(16) PRIMARY KEY
protection_scope_id BLOB(16) NOT NULL
scope_key_id BLOB(16) NOT NULL
cipher_suite TEXT NOT NULL
ciphertext BLOB NOT NULL
nonce BLOB NOT NULL
wrapped_dek BLOB NOT NULL
dek_wrap_nonce BLOB NOT NULL
aad_version INTEGER NOT NULL
ciphertext_hash BLOB(32) NOT NULL
created_at_us INTEGER NOT NULL
```

Der entschlüsselte Payload wird gegen das typspezifische Schema validiert.

`wrapped_dek` ist eindeutig als per-Objekt Data-Encryption-Key definiert; der Scope Key wird selbst ausschließlich in `protection_scope_keys` unter dem Root Key gewrappt gespeichert.

---

### 102. Verschlüsselungsbibliothek

ATHENA v1 verwendet für den geschützten Bereich die Python-Bibliothek:

```text
cryptography
```

Benötigte Primitive:

```text
Argon2id
AES-256-GCM
```

Der Packaging-Prozess stellt eine Version bereit, die beide Primitive unterstützt.

---

### 103. Envelope Encryption

Geschützte Payloads verwenden Envelope Encryption:

```text
Benutzerpasswort / Recovery Secret / OS Secret
↓
Key Slot
↓
Argon2id-KEK beziehungsweise zugelassener Slot-Mechanismus
↓
ATHENA Root Key entschlüsseln
↓
versionierten Protection-Scope-Key entschlüsseln
↓
per-Objekt Data-Encryption-Key entschlüsseln
↓
AES-256-GCM
↓
Payload
```

Das Benutzerpasswort wird nicht dauerhaft gespeichert.

Ein Passwortwechsel erzeugt beziehungsweise ersetzt den Password `key_slot` für denselben Root Key. Er erfordert **keine** Neuverschlüsselung aller Scope Keys, DEKs oder Blobs.

Eine Scope-Key-Rotation erzeugt eine neue `key_version`; bestehende DEKs können kontrolliert unter den neuen Scope Key rewrapped werden, ohne die großen Datenpayloads zwingend vollständig neu zu verschlüsseln.

---

### 104. Große geschützte Blob-Dateien

Große geschützte Blobs werden chunkweise verschlüsselt.

v1-Format:

```text
4 MiB plaintext chunks
+
ein zufälliger 256-bit DEK pro Blob
+
AES-256-GCM pro Chunk
+
eindeutiger 96-bit Nonce pro Chunk
```

Die Chunkgröße ist Formatparameter und kann in zukünftigen Blobformat-Versionen geändert werden.

---

### 105. Nonce-Format für Blob-Chunks

Pro verschlüsseltem Blob wird ein zufälliger 64-bit Nonce-Prefix erzeugt.

Der 96-bit GCM-Nonce besteht aus:

```text
64-bit random prefix
+
32-bit chunk index
```

Da jeder Blob einen neuen zufälligen DEK erhält, werden Nonces innerhalb desselben Schlüssels eindeutig gehalten.

---

### 106. Associated Data

AES-GCM Associated Data enthält mindestens:

```text
blob format version
blob_id
chunk_index
plaintext_length
protection_scope_id
```

Manipulation an diesen Metadaten führt bei der Entschlüsselung zu einem Authentifizierungsfehler.

---

### 107. Protected Blob Hash

Der Blob Store adressiert geschützte Dateien über:

```text
SHA-256(ciphertext file)
```

Nicht über den Klartext-Hash.

Klartext-Deduplizierung geschützter Dateien ist in v1 bewusst deaktiviert.

---

### 108. Protected Search State

Geschützte Klartexte werden **nicht** dauerhaft in der normalen `search.db` gespeichert.

Im entsperrten Zustand verwendet v1:

- eine In-Memory-FTS5-Struktur;
- einen In-Memory-Vektorindex oder einen ausdrücklich geschützten temporären Bereich.

Beim Sperren werden diese Strukturen verworfen.

---

### 109. Storage Security versus Beta Sicherheitskapitel

Dieses Kapitel legt das physische Verschlüsselungsformat fest.

Beta Kapitel 16 definiert später detailliert:

- Passwort-UX;
- Argon2id-Kostenparameter;
- Recovery-Key-Verfahren;
- Auto-Lock;
- Key-Lifetime im RAM;
- Berechtigungsmodell;
- Angriffsmodell.

Kapitel 16 darf die hier definierten Storage-Invarianten sicher verschärfen.

---

## Teil XI – Durable Operational State

### 110. jobs

`jobs` enthält mindestens:

```text
job_id BLOB(16) PRIMARY KEY
job_type TEXT NOT NULL
created_at_us INTEGER NOT NULL
created_by_actor_id BLOB(16) NOT NULL
priority INTEGER NOT NULL
state TEXT NOT NULL
requested_scope_json TEXT NULL
processing_run_id BLOB(16) NULL
current_stage TEXT NULL
last_checkpoint_id BLOB(16) NULL
retry_count INTEGER NOT NULL
next_run_at_us INTEGER NULL
blocked_reason TEXT NULL
pinned_configuration_json TEXT NULL
protection_scope_id BLOB(16) NULL
protected_payload_id BLOB(16) NULL
updated_at_us INTEGER NOT NULL
```

Bei Protected Jobs enthalten die normalen JSON-/Textfelder nur neutrale IDs, Statuswerte und technisch notwendige nicht sensitive Daten. Sensitive Query-, Scope-, Pfad-, Titel- oder Konfigurationsdetails liegen im `protected_payload_id`.

---

### 111. checkpoints

Mindestens:

```text
checkpoint_id BLOB(16) PRIMARY KEY
job_id BLOB(16) NOT NULL
processing_stage_id BLOB(16) NULL
created_at_us INTEGER NOT NULL
progress_state_json TEXT NULL
last_confirmed_input_json TEXT NULL
last_confirmed_output_json TEXT NULL
resume_metadata_json TEXT NULL
commit_id BLOB(16) NULL
protection_scope_id BLOB(16) NULL
protected_payload_id BLOB(16) NULL
```

Protected Checkpoints dürfen außerhalb des verschlüsselten Payloads keine Source-Titel, Queries, Textfragmente oder semantischen Zwischenresultate enthalten.

---

### 112. pending_writes

Nicht bestätigte persistente Writes werden explizit modelliert:

```text
pending_write_id BLOB(16) PRIMARY KEY
operation_type TEXT NOT NULL
created_at_us INTEGER NOT NULL
state TEXT NOT NULL
payload_manifest_json TEXT NULL
target_root_id BLOB(16) NULL
idempotency_key BLOB(32) NOT NULL UNIQUE
protection_scope_id BLOB(16) NULL
protected_payload_id BLOB(16) NULL
```

Große Payloads liegen im Spool, nicht im JSON-Feld. Protected Pending Writes speichern sensitive Manifestbestandteile verschlüsselt.

---

### 113. outbox_items

Outbox-Einträge:

```text
outbox_item_id BLOB(16) PRIMARY KEY
operation_type TEXT NOT NULL
target_root_id BLOB(16) NOT NULL
payload_ref TEXT NULL
created_at_us INTEGER NOT NULL
state TEXT NOT NULL
attempt_count INTEGER NOT NULL
next_attempt_at_us INTEGER NULL
last_error_code TEXT NULL
idempotency_key BLOB(32) NOT NULL UNIQUE
protection_scope_id BLOB(16) NULL
protected_payload_id BLOB(16) NULL
```

`payload_ref` muss bei Protected Operationen ein neutraler opaque Identifier sein. Sensitive externe Ziele, Queries oder Manifestdetails liegen verschlüsselt.

---

### 114. idempotency_records

Bestätigte idempotente Effekte werden gespeichert:

```text
idempotency_key BLOB(32) PRIMARY KEY
operation_type TEXT NOT NULL
first_seen_at_us INTEGER NOT NULL
completed_at_us INTEGER NULL
result_entity_id BLOB(16) NULL
result_commit_id BLOB(16) NULL
state TEXT NOT NULL
```

---

### 115. research_scopes

Mindestens:

```text
research_scope_id BLOB(16) PRIMARY KEY
created_at_us INTEGER NOT NULL
created_by_actor_id BLOB(16) NOT NULL
query_or_goal TEXT NULL
included_domains_json TEXT NULL
filters_json TEXT NULL
time_range_json TEXT NULL
snapshot_commit_seq INTEGER NOT NULL
snapshot_created_at_us INTEGER NOT NULL
coverage_target_json TEXT NULL
state TEXT NOT NULL
protection_scope_id BLOB(16) NULL
protected_payload_id BLOB(16) NULL
```

Bei Protected Research liegen Query, Filter, sensible Projekt-/Sourcebezüge und Coveragebeschreibung im verschlüsselten Payload. Die ungeschützte Row enthält nur neutrale Ablaufmetadaten.

---

### 116. candidate_sets

Mindestens:

```text
candidate_set_id BLOB(16) PRIMARY KEY
research_scope_id BLOB(16) NOT NULL
created_at_us INTEGER NOT NULL
snapshot_commit_seq INTEGER NOT NULL
retrieval_configuration_json TEXT NULL
candidate_count INTEGER NOT NULL
state TEXT NOT NULL
protection_scope_id BLOB(16) NULL
protected_payload_id BLOB(16) NULL
```

Protected Retrievalkonfigurationen werden nicht im Klartext persistiert.

---

### 117. candidate_members

Mitgliedschaft:

```text
candidate_set_id BLOB(16)
ordinal INTEGER
entity_id BLOB(16) NULL
revision_id BLOB(16) NULL
source_id BLOB(16) NULL
representation_id BLOB(16) NULL
anchor_id BLOB(16) NULL
chunk_id BLOB(16) NULL
rank INTEGER NULL
score REAL NULL
retrieval_method TEXT NOT NULL
selection_reason TEXT NULL
protected_payload_id BLOB(16) NULL
PRIMARY KEY(candidate_set_id, ordinal)
```

`chunk_id` ist nur ein optionaler Derived-State-Hinweis. Persistente Researchkandidaten, die auf Sourcecontent beruhen, materialisieren stabile `source_id`/`representation_id`/`anchor_id`-Referenzen, sodass ein Rechunking den Research Snapshot nicht unbrauchbar macht.

Bei Protected CandidateSets bleibt `selection_reason` `NULL` und wird bei Bedarf im verschlüsselten Payload gespeichert.

## Teil XII – Blob Store

### 118. Unprotected Blob Path

Nicht geschützte Blobs verwenden content-addressed Pfade:

```text
blobs/sha256/<first2>/<next2>/<64-hex-sha256>.blob
```

Beispiel:

```text
blobs/sha256/a1/5c/a15c....9f.blob
```

Der Dateiname enthält keine Originalbezeichnung.

---

### 119. Protected Blob Path

Geschützte Blobdateien verwenden:

```text
protected/<first2>/<next2>/<ciphertext-sha256>.athb
```

Der Pfad verrät weder Originalname noch Klartext-Hash.

---

### 120. Representation Blob Path

Unverschlüsselte SourceRepresentations verwenden:

```text
representations/sha256/<first2>/<next2>/<hash>.repr
```

Geschützte Repräsentationen verwenden dasselbe verschlüsselte Blobformat wie geschützte Originale.

---

### 121. Blob Write Protocol

Ein lokaler Blob-Write folgt:

```text
1. temporäre Datei im Ziel-Dateisystem erzeugen
2. bytes streamen
3. SHA-256 berechnen
4. Datei flushen und synchronisieren
5. Länge prüfen
6. vorhandenen Zielblob gegebenenfalls verifizieren
7. atomisch auf finalen Storage Key verschieben
8. finalen Blob verifizieren
9. erst danach DB-Referenz committen
```

Ein DB-Commit referenziert keinen unbestätigten finalen Blob.

---

### 122. Warum Blob zuerst, DB danach

Wenn der Blob finalisiert wurde, aber der DB-Commit scheitert, entsteht höchstens ein unreferenzierter Blob.

Dieser kann später sicher als Orphan erkannt werden.

Wenn dagegen die DB zuerst committed und der Blob anschließend verloren geht, wäre eine bestätigte Source beschädigt.

Deshalb gilt:

```text
durable blob
vor
canonical DB reference
```

---

### 123. Netzwerk-Blob Write Protocol

Bei einem Netzwerk-`archive_root` wird niemals direkt auf den finalen Namen gestreamt.

Ablauf:

```text
target/.athena-tmp/<random>.part
↓
vollständig schreiben
↓
close / flush
↓
Hash erneut prüfen
↓
rename auf finalen content-addressed Namen
↓
erneut prüfen
```

Scheitert dies, bleibt der lokale Spool autoritativ für den noch nicht synchronisierten Payload.

---

### 124. Deduplizierung

Bei ungeschützten Blobs gilt:

```text
gleicher SHA-256
+
gleiche Byte-Länge
+
erfolgreiche Verifikation
↓
physische Wiederverwendung zulässig
```

Source-Identitäten bleiben getrennt.

---

### 125. Hash Collision Handling

ATHENA behandelt einen Hash nicht blind als Beweis identischer Bytes.

Wenn ein Zielhash bereits existiert:

- Byte-Länge vergleichen;
- gespeicherten Blob-Hash verifizieren;
- bei Inkonsistenz Quarantäne und kritischen Integritätsfehler auslösen.

Ein widersprüchlicher SHA-256-Datensatz wird niemals überschrieben.

---

### 126. Orphan Blobs

Ein Blob ohne DB-Referenz kann nach:

- abgebrochenem Import;
- Crash zwischen Blobfinalisierung und DB-Commit

entstehen.

Solche Blobs werden nicht sofort gelöscht.

v1 verwendet eine konfigurierbare Grace Period, Standard:

```text
24 Stunden
```

Danach darf ein verifizierter Orphan-GC sie entfernen.

---

### 127. Blob Garbage Collection

GC löscht einen Produktionsblob nur, wenn:

- keine aktive Source ihn referenziert;
- keine retained SourceRepresentation ihn referenziert;
- kein PendingWrite ihn benötigt;
- kein OutboxItem ihn benötigt;
- keine lokale Migration ihn benötigt;
- **kein aktiver Backup Snapshot Pin** ihn benötigt;
- keine andere explizite Durable Pin-Regel ihn schützt.

Backup-Objekte besitzen einen separaten Lifecycle.

Die Prüfung und das Setzen/Entfernen von Pins müssen race-sicher sein. Ein GC darf nicht zwischen Backup-Snapshot und Blobkopie einen im Snapshot benötigten Blob entfernen.

---

### 128. Keine sichere physische SSD-Löschgarantie

ATHENA kann auf Anwendungsebene sicherstellen, dass gelöschte Inhalte nicht mehr referenziert oder normal lesbar sind.

Es kann **nicht allgemein garantieren**, dass ein SSD-Controller, Copy-on-Write-Dateisystem, Snapshot oder physisches Speichermedium keine alten Zellen mehr enthält.

Für besonders sensible Inhalte ist deshalb Verschlüsselung und gegebenenfalls kryptographische Schlüsselvernichtung wesentlich stärker als bloßes Überschreiben.

---

## Teil XIII – Offline Archive und Synchronisation

### 129. Archive Root Health

Jeder `archive_root` besitzt einen Health-State:

```text
online
degraded
offline
read_only
error
```

Der Core prüft den Status vor großen Imports und Hintergrundjobs.

---

### 130. Durable Local Spool

Ist das gewünschte Archive-Ziel offline, werden neue nicht rekonstruierbare Payloads unter:

```text
state_root/spool/
```

vollständig persistent gespeichert.

Der Spool ist **kein Cache**.

---

### 131. Spool Blob Record

Ein gespulter Blob besitzt bereits:

- `blob_id`;
- Integritätshash;
- Byte-Länge;
- lokale verifizierte BlobLocation;
- ausstehendes OutboxItem.

Dadurch kann ATHENA nach Neustart exakt fortsetzen.

---

### 132. Sync-Reihenfolge

Sobald das Archive-Ziel wieder verfügbar ist:

```text
lokalen Blob validieren
↓
remote temp write
↓
remote verify
↓
remote finalisieren
↓
remote BlobLocation in DB committen
↓
preferred location wechseln
↓
lokale Spoolkopie erst danach freigeben
```

---

### 133. Kein Silent Fallback

Wenn ein konfiguriertes Archive-Ziel ausfällt, darf ATHENA nicht heimlich einen beliebigen anderen dauerhaften Speicher wählen.

Der lokale Spool ist die definierte Sicherheitsausnahme.

Ein dauerhafter Zielwechsel benötigt eine Benutzer- oder explizite Konfigurationsentscheidung.

---

### 134. Spool Capacity

Der Spool besitzt ein eigenes Speicherbudget.

Wird es knapp:

- große neue Imports können pausiert werden;
- Hintergrundimporte werden gedrosselt;
- bestehende gespulte Daten werden niemals zur Platzgewinnung verworfen.

Der Benutzer erhält eine konkrete Speicherwarnung.

---

## Teil XIV – search.db und FTS5

### 135. Separate Suchdatenbank

Unverschlüsselter rekonstruierbarer Such- und Chunkzustand liegt in:

```text
derived_root/search/search.db
```

Sie ist **nicht** Bestandteil der autoritativen Persistenz.

Sie enthält insbesondere:

```text
source_chunks
search_documents
fts_knowledge
fts_archive
fts_memory
embedding_records
index_watermarks
```

`chunking_profiles` und ProcessingRun-Metadaten bleiben in `athena.db`, damit ein verlorenes `search.db` deterministisch beziehungsweise nachvollziehbar neu aufgebaut werden kann.

---

### 136. search.db darf gelöscht werden

Wenn `search.db` fehlt oder beschädigt ist:

```text
ATHENA Core
↓
autoritative Daten lesen
↓
search.db neu erstellen
↓
Index erneut aufbauen
```

Wissen, Provenienz oder Jobs dürfen dadurch nicht verloren gehen.

---

### 137. FTS5 Capability

Beim Erstellen von `search.db` prüft ATHENA explizit, ob FTS5 verfügbar ist.

Wenn nicht:

- Volltextsuche wird als nicht verfügbar markiert;
- autoritative Daten bleiben nutzbar;
- das System fällt nicht auf eine unkontrollierte alternative Indextechnologie zurück.

---

### 138. FTS-Tabellen

v1 verwendet getrennte logische FTS-Indizes:

```text
fts_knowledge
fts_archive
fts_memory
```

Dadurch können Retrieval-Regeln und Gewichtungen getrennt angewendet werden.

---

### 139. FTS-Dokumentmetadaten

`search.db` enthält eine normale Mapping-Tabelle:

```text
search_documents
```

Mindestens:

```text
doc_id INTEGER PRIMARY KEY
entity_type TEXT NOT NULL
entity_id BLOB(16) NOT NULL
revision_id BLOB(16) NULL
source_id BLOB(16) NULL
chunk_id BLOB(16) NULL
commit_seq INTEGER NOT NULL
content_hash BLOB(32) NOT NULL
index_class TEXT NOT NULL
```

---

### 140. FTS-Payload

Die zu indexierenden Textfelder liegen ausschließlich in `search.db`.

Beispiele:

```text
title
body
tags
chunk_text
```

Sie sind abgeleitete Kopien und dürfen jederzeit verworfen werden.

---

### 141. Keine Protected Payloads in search.db

Entitäten mit aktivem geschütztem ProtectionScope werden nicht in die persistente normale Suchdatenbank geschrieben.

Dies gilt auch für:

- Titel;
- Tags;
- Embeddings;
- Previewtext.

Geschützte Suche wird im entsperrten Runtime-Kontext aufgebaut.

---

### 142. FTS-Tokenizer

Default für normale Unicode-Texte:

```text
unicode61
```

mit diakritischer Normalisierung als Ausgangspunkt.

Sprachspezifische Spezialtokenizer werden später über den SearchProvider ergänzt, ohne kanonische Daten zu ändern.

---

### 143. Index Update über Change Feed

Der Suchindex liest:

```text
commit_changes
```

ab seinem letzten Watermark.

Ablauf:

```text
watermark = 10512
↓
Commits 10513..current lesen
↓
betroffene aktuelle Revisionen indexieren
↓
search transaction committen
↓
watermark erhöhen
```

---

### 144. Search Watermark

`search.db` enthält:

```text
index_watermarks
```

mit:

```text
index_name
build_signature
last_commit_seq
updated_at_us
state
```

Ein Watermark wird erst nach erfolgreichem Index-Commit erhöht.

---

### 145. Stale Search

Wenn:

```text
search watermark < canonical commit_seq
```

ist, weiß ATHENA, dass die Suche nicht vollständig aktuell ist.

Der Context Builder kann:

- inkrementell nachziehen;
- direkt aus autoritativen Daten ergänzen;
- Aktualitätsgrenze transparent behandeln.

---

### 146. FTS Deletion

Bei endgültiger Löschung wird der betroffene Derived-State-Eintrag unmittelbar entfernt.

Zusätzlich darf ATHENA `search.db` vollständig neu erzeugen, wenn ein sicherer Cleanup der alten FTS-Struktur erforderlich ist.

Da `search.db` derived ist, ist Rebuild der bevorzugte harte Reparaturweg.

---

### 147. FTS Maintenance

FTS5-Merge-/Optimize-Operationen laufen als niedriger priorisierte Maintenance-Jobs.

Sie dürfen direkte Benutzeranfragen nicht unnötig blockieren.

---

## Teil XV – Embeddings und Vektorindex

### 148. Embedding Storage

Unprotected Embedding-Vektoren werden in `search.db` gespeichert.

Tabelle:

```text
embedding_records
```

Mindestens:

```text
embedding_row_id INTEGER PRIMARY KEY
entity_id BLOB(16) NOT NULL
revision_id BLOB(16) NULL
chunk_id BLOB(16) NULL
embedding_space_id BLOB(16) NOT NULL
dimension INTEGER NOT NULL
vector_blob BLOB NOT NULL
content_hash BLOB(32) NOT NULL
commit_seq INTEGER NOT NULL
```

---

### 149. Vektorformat

Persistierte Embedding-Vektoren verwenden in v1:

```text
float32
little-endian
contiguous
```

Die Dimension wird separat gespeichert und beim Lesen validiert.

---

### 150. Embedding Space

Jede inkompatible Embedding-Konfiguration erhält einen eigenen:

```text
embedding_space_id
```

Dazu gehören mindestens:

- Embedding-Modell;
- Modellrevision;
- Dimension;
- Distanzmetrik;
- Normalisierung;
- Processing-Version.

---

### 151. HNSW als v1-Vektorindex

ATHENA v1 verwendet:

```text
hnswlib
```

als erste HNSW-Implementierung.

Der HNSW-Index ist vollständig rekonstruierbar und wird hinter einem:

```text
VectorIndexProvider
```

gekapselt.

---

### 152. Warum HNSW-Datei nicht autoritativ ist

`hnswlib` kann einen Index in eine Datei serialisieren.

Diese Datei enthält jedoch ausschließlich Derived State.

Wenn sie:

- fehlt;
- inkompatibel ist;
- beschädigt ist;
- nach Hardwarewechsel nicht geladen werden kann,

wird sie aus `embedding_records` neu aufgebaut.

---

### 153. Vector Directory

Pro Embedding Space:

```text
derived_root/vector/<embedding_space_id>/
├── index.hnsw
└── manifest.json
```

Das Manifest enthält:

```text
embedding_space_id
dimension
metric
build_commit_seq
element_count
provider
provider_version
```

---

### 154. HNSW Integer Labels

Da HNSW-Labels technisch Integerwerte verwenden, besitzt `search.db`:

```text
vector_labels
```

mit:

```text
embedding_space_id
vector_label INTEGER
embedding_row_id INTEGER
PRIMARY KEY(embedding_space_id, vector_label)
```

Diese Labels sind Derived State und keine ATHENA-IDs.

---

### 155. Crash-sicheres HNSW-Speichern

Ein neuer Index wird niemals direkt über die aktive Datei geschrieben.

Ablauf:

```text
index.hnsw.new
↓
vollständig speichern
↓
Load-Test
↓
Manifest schreiben
↓
atomisch ersetzen
```

Bei Crash bleibt die alte gültige Datei erhalten oder ein Rebuild wird ausgelöst.

---

### 156. Vector Watermark

Das HNSW-Manifest besitzt:

```text
build_commit_seq
```

Liegt es hinter `athena.db`, werden fehlende Änderungen nachgeführt oder der Index neu gebaut.

---

### 157. Gelöschte Vektoren

Gelöschte Elemente dürfen zunächst technisch als gelöscht markiert werden.

Wenn der Anteil gelöschter HNSW-Knoten einen konfigurierten Schwellenwert überschreitet, wird der Index kompakt neu aufgebaut.

Der exakte Schwellenwert wird in Beta Kapitel 10 – Retrieval und Suche festgelegt.

---

### 158. Kein Protected Embedding auf Disk

Embeddings geschützter Inhalte werden in v1 nicht unverschlüsselt in `search.db` oder HNSW-Dateien persistiert.

Sie werden nach Unlock im geschützten Runtime-Kontext erzeugt beziehungsweise geladen und beim Lock verworfen.

---

## Teil XVI – Atomare Writes

### 159. Canonical Write Transaction

Jede autoritative Änderung läuft über:

```text
CanonicalWriteCoordinator
↓
BEGIN IMMEDIATE
↓
Validation
↓
Entity/Revision Writes
↓
Provenance
↓
Audit
↓
CommitRecord
↓
CommitChanges
↓
Head Update
↓
COMMIT
```

Fehler führen zu `ROLLBACK`.

---

### 160. BEGIN IMMEDIATE

Der Writer verwendet für kanonische Änderungen bevorzugt:

```sql
BEGIN IMMEDIATE;
```

Dadurch wird Write-Konkurrenz früh erkannt und eine halbe semantische Transaktion vermieden.

Reads bleiben unter WAL möglich.

---

### 161. expected_revision_id

Vor dem Write prüft der Core:

```text
expected_revision_id
==
entity_heads.current_revision_id
```

Bei Abweichung:

```text
CONFLICT
```

Kein Last-Write-Wins.

---

### 162. CommitRecord im selben Commit

`commit_records` und `commit_changes` werden in derselben Transaktion wie die eigentliche Änderung geschrieben.

Ein Commit ohne Change Feed beziehungsweise ein Change Feed ohne Commit darf nicht entstehen.

---

### 163. Nachgelagerter Derived State

FTS und HNSW werden **nicht** Teil der Canonical Write Transaction.

Nach Canonical Commit:

```text
commit_seq erzeugt
↓
Derived-State-Indexer erhält Arbeit
↓
search.db aktualisiert
↓
HNSW aktualisiert
```

Wenn der Indexer scheitert, bleibt der kanonische Commit gültig.

---

### 164. Transactional Outbox

Muss ein Canonical Commit später eine externe oder Filesystem-Aktion auslösen, wird im selben DB-Commit ein `outbox_item` erzeugt.

Damit geht die Folgeaktion nach Crash nicht verloren.

---

### 165. Filesystem und DB sind keine gemeinsame Transaktion

SQLite kann keinen atomaren Commit mit einem NAS-Dateisystem bilden.

ATHENA verwendet deshalb:

```text
durable staging
+
verification
+
DB state machine
+
idempotent outbox
```

statt vorzutäuschen, Filesystem und SQLite seien eine gemeinsame Transaktion.

---

## Teil XVII – Idempotenz

### 166. Idempotency-Key-Format

Idempotency Keys werden aus einer kanonischen JCS-Struktur erzeugt.

Beispiel:

```json
{
  "operation": "process_chunk",
  "job_id": "...",
  "stage_id": "...",
  "chunk_id": "...",
  "pipeline_version": "..."
}
```

Anschließend:

```text
SHA-256(JCS bytes)
```

---

### 167. Kein String-Concatenation-Hash

Nicht zulässig:

```text
job_id + ":" + chunk_id + ":" + version
```

ohne definierte Escaping- und Typregeln.

JCS verhindert Mehrdeutigkeiten der Inputstruktur.

---

### 168. Idempotency Cleanup

Abgeschlossene IdempotencyRecords dürfen erst entfernt werden, wenn kein Job, Restore oder Retry mehr auf ihre Deduplizierungswirkung angewiesen ist.

Sie sind Durable Operational State, kein kurzfristiger Request-Cache.

---

## Teil XVIII – Backup Repository v1

### 169. Backup-Format

ATHENA v1 verwendet ein dokumentiertes verzeichnisbasiertes Backup-Repository.

Struktur:

```text
backup_root/
├── repository.json
├── objects/
│   └── sha256/
├── snapshots/
│   └── <backup_id>/
│       ├── athena.db
│       ├── manifest.json
│       └── complete.marker
└── deletion/
    └── ledger.jsonl
```

Das Format ist ohne laufende ATHENA-Instanz untersuchbar.

---

### 170. Backup Repository Manifest

`repository.json` enthält:

```text
repository format version
repository_id
created_at
hash algorithm
snapshot format version
```

Keine Passwörter.

---

### 171. DB-Snapshot

Eine laufende Hauptdatenbank wird über die SQLite Online Backup API in:

```text
snapshots/<backup_id>/athena.db
```

kopiert.

Dadurch entsteht ein konsistenter Datenbank-Snapshot ohne unsichere rohe Dateikopie.

---

### 172. Snapshot Commit Boundary

Nach dem DB-Snapshot liest der Backup-Prozess aus der Snapshot-Datei:

```text
MAX(commit_seq)
```

Dieser Wert wird als:

```text
snapshot_commit_seq
```

im Backup-Manifest gespeichert.

---

### 173. Blob Manifest

Der Backup-Prozess bestimmt aus der Snapshot-Datenbank alle zu diesem Stand benötigten BlobRecords.

Bevor ein solcher Produktionsblob durch parallele Löschung/GC verschwinden könnte, persistiert der Backupjob in `athena.db` für alle noch nicht im Backup Repository verifizierten benötigten Blobs einen `backup_snapshot_pin`:

```text
backup_id
blob_id
created_at_us
state
```

Ablauf:

```text
DB-Snapshot erstellen
↓
required_blob_ids bestimmen
↓
benötigte noch nicht gesicherte BlobIDs durable pinnen
↓
Produktionsblobs in Backup Object Store kopieren
↓
Hash verifizieren
↓
Snapshot complete markieren
↓
Pins entfernen
```

Scheitert ein Backup, werden Pins erst nach kontrolliertem Cleanup beziehungsweise nachdem klar ist, dass kein Resume mehr erfolgt, entfernt.

Da Produktionsblobs immutable sind, können gepinnte Blobs nach erfolgreichem Pinning gefahrlos kopiert werden.

---

### 174. Backup Object Store

Backup-Blobs werden ebenfalls content-addressed gespeichert:

```text
objects/sha256/<aa>/<bb>/<hash>
```

Existiert ein korrekt verifiziertes Objekt bereits, wird es nicht erneut kopiert.

Damit deduplizieren sich unveränderte Originalblobs über viele Snapshots.

---

### 175. Protected Backup Objects

Geschützte Produktionsblobs werden **als Ciphertext** gesichert.

Der Backup-Prozess entschlüsselt sie nicht.

Dadurch entsteht im Backup keine neue Klartextkopie.

---

### 176. Backup Snapshot Manifest

`manifest.json` enthält mindestens:

```text
backup_id
created_at
snapshot_commit_seq
schema_version
storage_layout_version
database_sha256
required_blob_hashes
entity_counts
protection_state
previous_snapshot_id
```

Das Manifest selbst wird kanonisch serialisiert und gehasht.

---

### 177. complete.marker

Ein Backup-Snapshot gilt nur als verwendbar, wenn:

- DB-Snapshot vollständig;
- Manifest vollständig;
- alle erforderlichen Backup Objects verifiziert;
- abschließende Integritätsprüfung erfolgreich

und anschließend:

```text
complete.marker
```

atomar geschrieben wurde.

Unvollständige Snapshot-Verzeichnisse werden als Staging behandelt.

---

### 178. Keine unbegrenzte DB-Deduplizierung in v1

v1 speichert pro Snapshot eine vollständige SQLite-Snapshotdatei.

Blob-Medien werden dedupliziert.

Dies hält das Backupformat einfach und robust.

Spätere page-level inkrementelle Datenbankbackups dürfen ergänzt werden, wenn Restore und Integritätsprüfung mindestens gleich zuverlässig bleiben.

---

### 179. Backup-Retention

Default aus Alpha:

```text
7 daily
4 weekly
12 monthly
5 yearly
```

Retention entfernt Snapshot-Manifeste und danach nicht mehr referenzierte Backup Objects.

Kein Backup wird ausschließlich wegen Speicherknappheit außerhalb der festgelegten Policy stillschweigend gelöscht.

---

### 180. Deletion Ledger

Jedes Backup-Repository führt außerhalb einzelner Snapshots:

```text
deletion/ledger.jsonl
```

Es enthält minimale DeletionMarker, damit auch ein Restore eines älteren Snapshots spätere endgültige Löschungen berücksichtigen kann.

---

### 181. Deletion-Ledger-Eintrag

Ein Eintrag enthält mindestens:

```text
deleted_entity_type
deleted_entity_id
deleted_at
authority_type
retention_rule_id
previous_record_hash
record_hash
```

Kein gelöschter Payload.

---

### 182. Deletion Ledger Hash Chain

Jeder Ledger-Eintrag wird als JCS serialisiert.

```text
record_hash =
SHA-256(previous_record_hash || JCS(record_without_record_hash))
```

Dies erkennt unbeabsichtigte Änderungen oder Trunkierung besser.

Es ersetzt keine kryptographische Signatur.

---

### 183. Deletion Propagation

Nach einer endgültigen Löschung wird für jedes erreichbare Backup-Repository ein hoch priorisiertes OutboxItem erzeugt.

Ist ein Backupmedium offline, zeigt ATHENA:

```text
Deletion pending for backup target X
```

Die Löschung darf nicht fälschlich als vollständig auf allen Backupmedien propagiert angezeigt werden.

---

### 184. Grenze des Restore-Schutzes

Ein physisch offline befindliches altes Backup, das seit der Löschung nie wieder mit ATHENA verbunden wurde, kann die spätere Löschinformation naturgemäß nicht kennen.

ATHENA behauptet deshalb nur für **synchronisierte beziehungsweise mit aktuellem Deletion Ledger versehene Backup-Repositories** Restore-Resurrection-Schutz.

Diese Einschränkung wird in Diagnose und Restore sichtbar gemacht.

---

### 185. Backup-Integritätsprüfung

Mindestens geprüft werden:

- SQLite `quick_check` oder vollständiger `integrity_check` entsprechend Prüfprofil;
- DB-SHA-256;
- Manifest-Hash;
- Blob-Hashes;
- fehlende Objects;
- Schema-Kompatibilität;
- Deletion-Ledger-Konsistenz.

---

### 186. Restore-Test

Ein automatischer Restore-Test stellt einen Snapshot in ein separates Testverzeichnis wieder her.

Der Test darf niemals den produktiven `state_root` überschreiben.

Nach Restore werden mindestens:

- Datenbank geöffnet;
- Integrität geprüft;
- Blob-Stichproben beziehungsweise vollständige Hashprüfung nach Profil;
- Kernentitäten gezählt;
- Deletion Ledger angewendet.

Ergebnis wird auditiert.

---

## Teil XIX – Restore

### 187. Restore ist ein neuer kontrollierter Zustand

Ein Restore überschreibt die laufende Installation nicht in-place, während diese aktiv ist.

Ziel:

```text
recovery staging root
```

Erst nach erfolgreicher Prüfung wird der wiederhergestellte Zustand aktiviert.

---

### 188. Restore-Reihenfolge

v1:

```text
Snapshot auswählen
↓
Manifest prüfen
↓
DB kopieren
↓
DB integrity prüfen
↓
Blob Objects prüfen/kopieren
↓
aktuellstes verfügbares Deletion Ledger anwenden
↓
Schema-Kompatibilität prüfen
↓
neuen state/archive root binden
↓
Derived State verwerfen
↓
Aktivierung
↓
FTS und Vector Index rebuild
```

---

### 189. Restore vor bestehender Installation

Wenn die aktuelle Installation noch lesbar ist, wird vor Restore zunächst ein Notfall-Snapshot des aktuellen Zustands angelegt.

Scheitert dieser aufgrund kritischer Korruption, wird der Benutzer darüber informiert; Restore darf trotzdem möglich bleiben.

---

### 190. Restore auf neue Pfade

Da BlobLocations und Roots abstrahiert sind, darf Restore auf völlig andere:

- Laufwerksbuchstaben;
- Verzeichnisse;
- Computer;
- Archive Roots

erfolgen.

Stabile IDs bleiben unverändert.

---

### 191. Restore und commit_seq

Innerhalb eines wiederhergestellten DB-Snapshots bleiben vorhandene `commit_seq`-Werte erhalten.

Neue Commits setzen monoton oberhalb des wiederhergestellten Maximums fort.

---

### 192. Restore und offene Jobs

Jobs mit Zustand:

```text
running
```

werden nach Restore nicht als weiterhin laufend betrachtet.

Sie wechseln in einen Recovery-Zustand und werden erst nach:

- Inputprüfung;
- Idempotenzprüfung;
- Driftprüfung;
- Benutzer-/Schedulerentscheidung

fortgesetzt.

---

## Teil XX – Migrationen

### 193. Migrationstypen

ATHENA unterscheidet:

```text
Schema Migration
Data Migration
Storage Layout Migration
Blob Format Migration
Derived-State Rebuild
Semantic Reprocessing
```

Nur die ersten vier sind echte Storage-Migrationen.

Semantic Reprocessing ist **keine** Datenbankschema-Migration.

---

### 194. Alembic Revision

Jede Schemaänderung erhält eine versionierte Alembic-Revision unter:

```text
migrations/versions/
```

Dateien werden in Git committed.

Produktive Datenbanken werden nie durch ad-hoc SQL auf einen unbekannten Stand gebracht.

---

### 195. Autogenerate-Regel

Alembic `--autogenerate` darf Unterschiede vorschlagen.

Vor Aufnahme in Git muss ein Mensch beziehungsweise der Entwicklungsworkflow prüfen:

- Foreign Keys;
- CHECK Constraints;
- Defaultwerte;
- Datenverlust;
- Indexe;
- Batch-Migration;
- Downgrade-Strategie.

Autogenerate wird nicht blind ausgeführt.

---

### 196. SQLite Batch Migrations

Für Änderungen, die SQLite nicht direkt per `ALTER TABLE` durchführen kann, verwendet ATHENA Alembics Batch-/Move-and-Copy-Verfahren.

Dabei werden Tabellen kontrolliert neu aufgebaut und Daten übertragen.

Diese Migration läuft nicht ohne vorherige Sicherheitskopie.

---

### 197. Migration Clone

Vor einer blockierenden Schema-Migration erzeugt ATHENA eine **Migration Clone** der Hauptdatenbank über die SQLite Backup API.

Beispiel:

```text
state_root/migration/
├── athena.pre-migration.db
└── athena.migrating.db
```

Migrationen laufen zunächst auf der Clone-Datei.

---

### 198. Clone-basierter Aktivierungsablauf

Ablauf:

```text
Writer pausieren
↓
laufende Transaktionen beenden
↓
Online Backup auf migration clone
↓
Migration auf Clone
↓
foreign_key_check
↓
integrity_check
↓
ATHENA Schema-Smoke-Tests
↓
DB schließen
↓
Clone flush/sync
↓
alte DB als Rollback-Snapshot behalten
↓
atomischer Dateitausch
↓
Startup-Test
↓
Migration als erfolgreich markieren
```

---

### 199. Warum Clone statt ausschließlich In-Place

Auch wenn viele SQLite-DDL-Schritte transaktional sind, können komplexe Move-and-Copy-Migrationen, VACUUM-artige Operationen und Prozessabbrüche schwierig werden.

Die Clone-Strategie sorgt dafür, dass die produktive Ausgangsdatenbank bis zur vollständigen Validierung unangetastet bleibt.

---

### 200. Migration Free-Space Preflight

Vor einer Clone-Migration muss genügend freier Platz vorhanden sein.

v1 verlangt mindestens:

```text
aktuelle DB-Größe
+
25 % Sicherheitsaufschlag
+
512 MiB
+
Emergency Reserve
```

als freien Platz im relevanten Root.

Ist dies nicht erfüllt, startet die Migration nicht.

---

### 201. Rollback Snapshot

Die vorherige DB-Version bleibt mindestens bis zu:

```text
erfolgreichem neuen Startup
+
Post-Migration-Health-Check
+
nächstem bestätigten Backup
```

als Rollback-Kandidat erhalten.

Danach greift die Migration-Retention.

---

### 202. Reversibility Metadata

Jede Migration deklariert:

```text
migration_id
from_version
to_version
reversible
requires_clone
estimated_space_factor
requires_rebuild
```

Ist `reversible=false`, erfolgt Rollback über die Pre-Migration-DB, nicht über eine erfundene Down-Migration.

---

### 203. Große Data Migrations

Sehr große Datenmigrationen sollen nicht den Startup minuten- oder stundenlang blockieren.

Wenn möglich:

```text
Schema kompatibel erweitern
↓
Core starten
↓
persistenten MigrationJob anlegen
↓
Daten in Chunks backfillen
↓
Checkpoints
↓
nach Abschluss altes Feld/Format in späterer Migration entfernen
```

Damit bleiben große Archive handhabbar.

---

### 204. MigrationJob

Ein großer Data-Migration-Job verwendet normale Durable-Operational-Regeln:

- `job_id`;
- Checkpoints;
- gepinnte Migrationversion;
- Idempotency Keys;
- Fortschrittsstatus;
- Pause/Resume.

Er darf keine semantische Neuinterpretation durchführen.

---

### 205. Storage Layout Migration

Wird ein Blob Store verschoben:

```text
alte Location behalten
↓
Blob kopieren
↓
Hash verifizieren
↓
neue BlobLocation hinzufügen
↓
preferred wechseln
↓
alte Location später bereinigen
```

Kein Move ohne verifizierte zweite Kopie.

---

### 206. Blob Format Migration

Ein neues verschlüsseltes oder technisches Blobformat erzeugt zunächst eine neue Blobdarstellung.

Die alte Fassung bleibt bis zur vollständigen:

- Entschlüsselungs-/Lesbarkeitsprüfung;
- Hashprüfung;
- DB-Umschaltung

erhalten.

---

### 207. Derived State wird nicht migriert, wenn Rebuild einfacher ist

Bei inkompatibler Änderung von:

- FTS-Schema;
- Embedding-Format;
- HNSW-Provider;
- Cacheformat

wird Derived State bevorzugt gelöscht und neu aufgebaut.

Keine aufwendige Migrationskette für rekonstruierbare Daten.

---

### 208. Migration Lock

Während einer blockierenden Migration besitzt der Core einen exklusiven Migration Lock.

Andere Instanzen dürfen die alte oder neue Datenbank nicht parallel öffnen.

---

### 209. Migration Journal

Außerhalb der umzuschaltenden Datenbank liegt ein kleines:

```text
migration_state.json
```

mit:

```text
migration_id
phase
source_db
candidate_db
started_at
last_completed_step
```

Dadurch kann Recovery nach Prozessabbruch erkennen, welche Datei produktiv und welche nur Kandidat ist.

---

### 210. Keine automatische semantische Migration

Ein Schema-Upgrade darf nicht:

```text
alte Claims neu bewerten
Quellen neu interpretieren
Benutzerkorrekturen verändern
```

Solche Aktionen sind explizite ProcessingRuns außerhalb des Migrationssystems.

---

## Teil XXI – Integritätsprüfungen

### 211. Startup Quick Check

Beim normalen Start führt ATHENA einen kostengünstigen Integritätscheck durch.

Ausgangspunkt:

```sql
PRAGMA quick_check;
```

Bei Fehler:

```text
kein normaler Schreibbetrieb
↓
Read-Only / Recovery
```

---

### 212. Foreign Key Check

Nach Migrationen und in regelmäßigen Wartungsläufen:

```sql
PRAGMA foreign_key_check;
```

Jede zurückgegebene Zeile ist ein Integritätsfehler.

---

### 213. Full integrity_check

Ein vollständiges:

```sql
PRAGMA integrity_check;
```

läuft:

- vor kritischen Releases/Migrationen;
- im Backup-Restore-Test;
- periodisch als Maintenance;
- bei Verdacht auf Datenbankkorruption.

Es muss nicht bei jedem normalen Startup laufen.

---

### 214. Blob Integrity Sweep

Blobprüfung läuft inkrementell.

Jeder BlobRecord speichert `verified_at_us`.

Maintenance priorisiert:

- lange nicht geprüfte Blobs;
- neue Storage Locations;
- kürzlich migrierte Daten;
- zufällige Stichproben;
- Blobs mit I/O-Fehlerhistorie.

---

### 215. Missing Blob

Referenziert `athena.db` einen nicht verfügbaren Blob:

```text
Location offline
```

ist noch kein Korruptionsbeweis.

Wenn alle bekannten Locations online sein sollten und der Blob fehlt:

```text
integrity error
↓
keine stille Löschung der Source
↓
Backup/Recovery anbieten
```

---

### 216. Hash Mismatch

Ein Blob mit falschem Hash wird:

```text
quarantined
```

und nicht weiter als gültige Quelle ausgeliefert.

ATHENA versucht eine intakte andere Location oder ein Backup.

Keine automatische Überschreibung der beschädigten Datei mit unbekannten Bytes.

---

### 217. Database Corruption

Bei SQLite-Korruptionsindikatoren:

- Writer stoppen;
- DB nicht durch Reparaturschreibversuche weiter verändern;
- Recovery Mode;
- Backupstände prüfen;
- Diagnosekopie erstellen soweit sicher;
- Restore beziehungsweise dokumentiertes SQLite-Recovery-Verfahren nutzen.

Ein automatischer `VACUUM` ist kein allgemeiner Korruptionsfix.

---

## Teil XXII – Disk-Full-Verhalten

### 218. Speicherzustände

Jeder relevante lokale Root besitzt:

```text
NORMAL
WARNING
CRITICAL
EMERGENCY
```

Die Zustände basieren auf freiem Speicher und prognostiziertem Bedarf.

---

### 219. Default-Schwellen

v1-Defaults:

```text
WARNING:
free < max(10 GiB, 5 % der Volume-Größe)

CRITICAL:
free < max(5 GiB, 2 % der Volume-Größe)

EMERGENCY:
free < max(2 GiB, 1 % der Volume-Größe)
```

`max()` ist bewusst gewählt: Ein Zustand wird erreicht, sobald **entweder** die absolute Mindestreserve oder die prozentuale Mindestreserve unterschritten wird.

Beispiel: Auf einem 1-TiB-Volume beginnt WARNING bereits unter ungefähr 5 %, nicht erst unter 10 GiB.

Die Werte sind konfigurierbar, dürfen aber nicht unter sicherheitskritische Mindestwerte gesenkt werden, ohne deutliche Warnung.

---

### 220. Emergency Reserve

ATHENA reserviert auf `state_root` eine tatsächlich allokierte Datei:

```text
reserve/emergency.reserve
```

Defaultgröße:

```text
max(256 MiB, min(1 GiB, 1 % der Volume-Größe))
```

Die Datei dient ausschließlich dazu, im Notfall Platz für:

- Commit-/Rollback;
- Checkpoint;
- Audit;
- Recovery-Metadaten;
- kontrollierten Shutdown

freizugeben.

---

### 221. Reserve ist kein Sparse File

Die Emergency Reserve muss physisch allokierten Speicher belegen.

Eine rein sparse Datei würde im Disk-Full-Fall keinen verlässlich reservierten Platz bieten.

---

### 222. WARNING-Verhalten

Bei WARNING:

- Benutzer informieren;
- Cache-Wachstum reduzieren;
- große Derived-State-Jobs zurückstellen;
- Backup-/Archivprognose anzeigen;
- keine kanonischen Daten löschen.

---

### 223. CRITICAL-Verhalten

Bei CRITICAL:

- nichtkritische Imports pausieren;
- Re-Embedding pausieren;
- Cache und sicher rekonstruierbare Tempdaten bereinigen;
- große Migrationen blockieren;
- nur kleine notwendige autoritative Writes zulassen;
- Nutzerinteraktion auf Speicherrisiko hinweisen.

---

### 224. EMERGENCY-Verhalten

Bei EMERGENCY:

```text
nichtkritische Writes stoppen
↓
Emergency Reserve freigeben
↓
laufende Transaktion sauber abschließen/rollback
↓
Durable Checkpoints schreiben
↓
Read-Only Safe Mode vorbereiten
```

ATHENA löscht niemals Originale oder kanonisches Wissen, um Platz zu schaffen.

---

### 225. Disk Full während Blob Write

Ein unvollständiger `.part`-Blob wird niemals als finaler Blob registriert.

Nach Fehler:

- Write abbrechen;
- Partial als Staging markieren;
- bei sicherer Rekonstruierbarkeit entfernen;
- bei nicht rekonstruierbarem Eingang kontrolliert erhalten oder Benutzer informieren.

---

### 226. Disk Full während DB Commit

SQLite-Fehler wegen vollem Datenträger führt zu:

```text
ROLLBACK
```

soweit möglich.

Der Core interpretiert einen fehlgeschlagenen Commit niemals als erfolgreich.

---

## Teil XXIII – Concurrency und Locks

### 227. Core API statt direkter DB-Zugriff

UI, Plugins und zukünftige Clients öffnen `athena.db` nicht direkt.

Sie kommunizieren mit dem ATHENA Core.

Dadurch bleibt:

- Single Writer;
- Security;
- Provenienz;
- Audit;
- Concurrency Control

zentral.

---

### 228. Reader Transaction Lifetime

Read-Transaktionen sollen kurz bleiben.

Pagination, Streaming und Chunking werden verwendet, statt eine stundenlange SQLite-Snapshot-Transaktion offen zu halten.

---

### 229. Research Snapshot ist logisch, nicht offene DB-Transaktion

Ein `ResearchScope.snapshot_commit_seq` wird **nicht** dadurch implementiert, dass eine SQLite-Read-Transaktion über Stunden offen bleibt.

Stattdessen werden konkrete Entity-/Revision-IDs für den Scope materialisiert beziehungsweise über `commit_seq` stabil bestimmt.

Dadurch wird WAL nicht durch Langzeitreader blockiert.

---

### 230. Write Queue Fairness

Direkte Benutzerwrites erhalten hohe Priorität.

Datensicherheitskritische Outbox-/Sync-Aktionen dürfen priorisiert werden.

Massive Background-Inserts werden in begrenzte Transaktionen zerlegt.

---

### 231. Maximale Transaktionsgröße

ATHENA vermeidet Transaktionen mit tausenden Megabytes Payload.

Große Imports werden:

```text
Blob durable schreiben
↓
kleine Metadaten-Transaktion
↓
weitere Verarbeitung in Jobs
```

aufgeteilt.

---

## Teil XXIV – Löschung

### 232. Logical Delete versus Physical Purge

ATHENA unterscheidet:

```text
pending_deletion
logical removal
physical purge
backup propagation
```

Die UI darf `vollständig gelöscht` erst anzeigen, wenn der angeforderte Scope tatsächlich erreicht wurde.

---

### 233. Deletion Transaction

Der erste autoritative Löschcommit:

- setzt `pending_deletion` beziehungsweise entfernt den aktiven Head;
- erzeugt `DeletionMarker`;
- erzeugt Audit ohne Payload;
- erzeugt Derived-State-Cleanup;
- erzeugt Backup-Deletion-OutboxItems.

Abhängige Blobpurges können anschließend idempotent ausgeführt werden.

---

### 234. Blob Purge

Ein Produktionsblob wird physisch gelöscht, wenn keine verbleibende zulässige Referenz existiert.

Danach:

- BlobLocation entfernen;
- Dateiexistenz erneut prüfen;
- BlobRecord je nach Audit-/Deletion-Regel entfernen oder minimalisieren.

Shared Blobs werden erst nach letzter Referenz gelöscht.

---

### 235. SQLite Content Purge

Durch `secure_delete=ON` versucht SQLite gelöschte normale Tabelleninhalte zu überschreiben.

Zusätzlich kann nach umfangreichen sensiblen Löschungen eine geplante DB-Rewrite-/VACUUM-Operation angeboten werden.

Dies ändert nichts an der Einschränkung physischer SSD-Löschung.

---

### 236. Search Purge

Gelöschte unprotected Inhalte werden aus `search.db` entfernt.

Bei hoher Sensitivität oder Zweifel wird die Derived-Suchdatenbank vollständig aus surviving data neu aufgebaut und die alte Datei verworfen.

---

### 237. Protected Cryptographic Erasure

Wenn ein ganzer ProtectionScope endgültig gelöscht wird und kein anderer Inhalt dessen Schlüssel benötigt, kann das Entfernen des Scope-Key-Materials eine kryptographische Löschbarriere bilden.

Die genaue Schlüsselvernichtungslogik wird in Beta Kapitel 16 spezifiziert.

---

## Teil XXV – Performance und Skalierung

### 238. Structured DB bleibt metadata-first

Große Medien liegen außerhalb von SQLite.

Dadurch wächst `athena.db` hauptsächlich durch:

- Textwissen;
- Revisionen;
- Beziehungen;
- Chats;
- Provenienz;
- Audit;
- Jobs.

Dies hält Backup und Migration der strukturierten Daten beherrschbar.

---

### 239. Indizes in athena.db

Pflichtindizes werden für häufige Zugriffe angelegt, mindestens auf:

- `entity_registry(entity_type, lifecycle_state)`;
- `revisions(entity_id, revision_no)`;
- `commit_changes(commit_seq)`;
- `sources(acquired_at_us)`;
- `chat_messages(chat_id, sequence_no)`;
- `relationships(source_entity_id, relation_type)`;
- `relationships(target_entity_id, relation_type)`;
- `jobs(state, priority, next_run_at_us)`;
- `outbox_items(state, next_attempt_at_us)`;
- `audit_events(occurred_at_us)`;
- `processing_runs(status, started_at_us)`.

Exakte DDL-Namen werden in den Migrationen dokumentiert.

---

### 240. Keine übermäßige Indexierung

Jeder zusätzliche SQLite-Index erhöht Write- und Speicheraufwand.

Indizes werden nur nach konkreten Query Patterns hinzugefügt.

Performanceoptimierung darf nicht zu unkontrollierter Redundanz werden.

---

### 241. ANALYZE und optimize

Nach großen Migrationen beziehungsweise Datenimporten darf ATHENA SQLite-Statistiken aktualisieren.

Regelmäßige Wartung kann:

```sql
PRAGMA optimize;
```

verwenden.

Dies ist Maintenance, keine semantische Änderung.

---

### 242. Pagination

Listen über große Tabellen verwenden keyset-/cursorbasierte Pagination.

Große `OFFSET`-Scans werden in Performancekritischen Pfaden vermieden.

---

### 243. Batch Inserts

Große technische Inserts wie Chunks oder Embedding-Metadaten werden gebatcht.

Batchgröße wird dynamisch begrenzt, damit:

- Commit-Latenz;
- WAL-Größe;
- UI-Reaktionsfähigkeit

akzeptabel bleiben.

---

## Teil XXVI – Portabilität

### 244. Keine Maschinenbindung

`athena.db` enthält keine notwendige Abhängigkeit von:

- Windows-Benutzernamen;
- Laufwerksbuchstaben;
- Hostnamen;
- ursprünglichem Installationspfad.

Solche Informationen dürfen höchstens Diagnose-/Konfigurationsmetadaten sein.

---

### 245. Storage Root Rebinding

Nach Umzug:

```text
neuen Root auswählen
↓
Manifest prüfen
↓
Blob-Stichprobe/Hashprüfung
↓
storage_root binding aktualisieren
↓
keine Objekt-ID ändern
```

---

### 246. SQLite als dokumentiertes Format

SQLite ist zwar Implementierungstechnologie, aber der vollständige ATHENA-Export darf nicht ausschließlich aus einer undokumentierten Datenbankdatei bestehen.

Der Export aus Kapitel 02 erzeugt zusätzlich menschenlesbare beziehungsweise dokumentierte strukturierte Daten.

---

### 247. Future StorageProvider

Repository-Interfaces verhindern, dass Domänenlogik direkt SQL-Pfade kennt.

Ein späterer Provider kann:

- PostgreSQL;
- andere relationale DB;
- spezialisierten Blob Store

verwenden, ohne Knowledge IDs zu ändern.

---

## Teil XXVII – Recovery-spezifische Storage-Regeln

### 248. Read-Only Database Open

Recovery Mode kann `athena.db` read-only öffnen.

Schreibende Recovery-Schritte benötigen eine explizite reparierbare Kopie beziehungsweise Restore-Ziel.

Die beschädigte Originaldatei wird nicht unnötig weiter verändert.

---

### 249. Recovery erkennt Sidecars

Recovery berücksichtigt:

```text
athena.db
athena.db-wal
athena.db-shm
```

und löscht Sidecar-Dateien nicht blind.

SQLite muss selbst Gelegenheit zur korrekten Recovery erhalten.

---

### 250. Candidate Database Files

Nach abgebrochener Migration können existieren:

```text
athena.db
athena.pre-migration.db
athena.migrating.db
migration_state.json
```

Recovery entscheidet anhand:

- Migration Journal;
- application_id;
- Schema-Version;
- integrity_check;
- Hash/Dateizeiten

welche Datei produktiv werden darf.

---

### 251. No Guess Recovery

Wenn zwei Kandidaten widersprüchlich und beide plausibel sind, wählt ATHENA nicht anhand des neueren Dateidatums allein.

Der Benutzer erhält eine nachvollziehbare Recovery-Auswahl.

---

## Teil XXVIII – Testkatalog

### 252. Fresh Database Test

Neue Datenbank erzeugen.

Prüfen:

- application_id;
- WAL;
- foreign_keys;
- synchronous;
- secure_delete;
- auto_vacuum;
- vollständiges Schema;
- initialer Actor;
- schema_metadata.

Erwartung: alle Pflichtwerte korrekt.

---

### 253. UUID Roundtrip Test

UUIDv7:

```text
string
↓
BLOB16
↓
DB
↓
BLOB16
↓
string
```

Erwartung: bit-identischer Roundtrip.

---

### 254. Commit Atomicity Test

Künstlicher Fehler nach Knowledge-Revision, aber vor Audit.

Erwartung:

```text
kein Knowledge-Write
kein Head-Update
kein CommitRecord
kein Audit
```

Alle Bestandteile rollen zurück.

---

### 255. Concurrent Write Test

Zwei Writes mit derselben `expected_revision_id`.

Erwartung:

```text
genau einer erfolgreich
zweiter CONFLICT
```

---

### 256. Power-Loss Simulation

Prozess während wiederholter SQLite-Writes hart beenden.

Nach Neustart:

- `quick_check=ok`;
- keine halben Commits;
- Jobs fortsetzbar;
- Change Feed konsistent.

---

### 257. Blob Crash Window Test

Crash nach finalem Blob-Rename aber vor DB-Commit.

Erwartung:

- kein kaputter DB-Verweis;
- Blob wird später als Orphan erkannt;
- nach Grace Period sicher bereinigbar.

---

### 258. Offline NAS Test

Archive Root während Import trennen.

Erwartung:

- Payload landet vollständig im Durable Spool;
- DB enthält verifizierte lokale Location;
- Outbox bleibt pending;
- nach Wiederkehr Sync + Verify;
- lokale Kopie erst danach löschbar.

---

### 259. Network Database Rejection Test

`state_root` auf erkannter SMB-/UNC-Freigabe konfigurieren.

Erwartung:

```text
normaler WAL-Schreibbetrieb wird verweigert
+
verständliche Erklärung
+
lokales state_root anbieten
```

---

### 260. FTS Rebuild Test

`search.db` löschen.

Erwartung:

- ATHENA startet;
- autoritative Daten intakt;
- Volltextstatus zunächst rebuilding;
- Index wird aus Change Feed beziehungsweise vollständigem Rebuild wiederhergestellt.

---

### 261. HNSW Rebuild Test

`index.hnsw` beschädigen.

Erwartung:

- keine Knowledge-Beschädigung;
- Vektorsuche deaktiviert/rebuilding;
- Neuaufbau aus `embedding_records`.

---

### 262. Protected Lock Test

Nach Sperren des Protected Scope prüfen:

- keine geschützten Klartexte in `search.db`;
- kein geschützter HNSW-Diskindex;
- In-Memory-Index verworfen;
- DB-Felder enthalten nur erlaubte neutrale Metadaten.

---

### 263. Backup While Writing Test

Während normaler Writes Online Backup ausführen und parallel eine im Snapshot enthaltene Source in der Live-DB löschen sowie Produktions-Blob-GC triggern.

Erwartung:

- Backup-DB konsistent;
- Snapshot hat eindeutige `snapshot_commit_seq`;
- `integrity_check` erfolgreich;
- Manifest passt zum Snapshot;
- alle für den Snapshot benötigten Blobs bleiben durch `backup_snapshot_pin` verfügbar, bis sie im Backup Object Store verifiziert sind;
- GC darf keinen gepinnten Snapshotblob löschen.

---

### 264. Backup Dedup Test

Zwei Backups ohne Blobänderungen.

Erwartung:

- zweiter Snapshot erhält eigenes DB-Snapshot/Manifest;
- identische Blob Objects werden nicht dupliziert.

---

### 265. Deletion Ledger Restore Test

1. Backup A erzeugen.
2. Entity X endgültig löschen.
3. Deletion Ledger synchronisieren.
4. Backup A wiederherstellen.

Erwartung:

```text
X wird nach Anwendung des Ledgers nicht reaktiviert.
```

---

### 266. Offline Backup Deletion Limitation Test

Backupmedium vor Löschung physisch trennen.

Nach Löschung muss UI anzeigen:

```text
Deletion not propagated to offline backup target
```

Keine falsche Behauptung vollständiger Backup-Löschung.

---

### 267. Migration Crash Test

Prozess während Migration auf `athena.migrating.db` beenden.

Erwartung:

- produktive Ausgangs-DB intakt;
- Migration Journal vorhanden;
- Recovery kann Kandidaten erkennen;
- kein halb migrierter aktiver Zustand.

---

### 268. Migration Disk-Full Test

Freien Speicher künstlich unter Preflight-Grenze bringen.

Erwartung:

```text
Migration startet nicht.
```

Kein Teilupdate.

---

### 269. Migration Validation Test

Clone-Migration mit absichtlich gebrochenem Foreign Key.

Erwartung:

- `foreign_key_check` schlägt fehl;
- Kandidat wird nicht aktiviert;
- alte DB bleibt produktiv.

---

### 270. Emergency Reserve Test

Datenträger bis EMERGENCY füllen.

Erwartung:

- Reserve freigegeben;
- Checkpoint/Audit möglich;
- nichtkritische Writes stoppen;
- Read-Only Safe Mode möglich;
- keine kanonische Datenlöschung.

---

### 271. Export Roundtrip Storage Test

Storage Root und Computer wechseln.

Erwartung:

- UUIDs gleich;
- Revisionen gleich;
- Beziehungen gleich;
- Blobhashes gleich;
- absolute alte Pfade nicht erforderlich.

---

## Teil XXIX – Implementierungsreihenfolge

### 272. Storage Slice 1

Zuerst implementieren:

```text
state_root
core.lock
athena.db
schema_metadata
actors
entity_registry
revisions
entity_heads
commit_records
commit_changes
```

Danach einfacher KnowledgeUnit-Write mit atomarer Revision.

---

### 273. Storage Slice 2

Danach:

```text
sources
blob_records
blob_locations
BlobStore
staging
SHA-256
import
```

Test: Datei importieren, Core neustarten, Quelle wieder lesen.

---

### 274. Storage Slice 3

Danach:

```text
provenance
audit
chats
personal memory
```

Test: Chat → Wissensextraktion → Provenienz → Restart.

---

### 275. Storage Slice 4

Danach:

```text
jobs
checkpoints
outbox
offline spool
```

Test: Netzwerkziel trennen und nach Restart fortsetzen.

---

### 276. Storage Slice 5

Danach:

```text
search.db
FTS5
embedding_records
HNSW
watermarks
```

Test: Derived State vollständig löschen und rekonstruieren.

---

### 277. Storage Slice 6

Danach:

```text
Backup Repository
Deletion Ledger
Restore
Migration Clone
Recovery
```

Erst nach bestandenen Recovery-Tests ist die Storage-Schicht v1-fähig.

---

## Teil XXX – Bewusste Grenzen dieses Kapitels

### 278. Nicht hier festgelegt: Retrieval Ranking

Dieses Kapitel speichert FTS- und Vektordaten.

Nicht festgelegt werden:

- finaler Hybrid-Ranking-Algorithmus;
- RRF-Gewichte;
- Top-K;
- Re-Ranker;
- Search Intent Classification.

Diese Entscheidungen gehören in Beta Kapitel 10.

---

### 279. Nicht hier festgelegt: vollständige Security UX

Argon2id und AES-256-GCM sind als Storage-Primitive festgelegt.

Nicht hier finalisiert werden:

- Passwortdialog;
- Auto-Lock-Dauer;
- Recovery-Key-UX;
- erlaubte Fehlversuche;
- Key-Rotation-UI.

Diese gehören in Beta Kapitel 16.

---

### 280. Nicht hier festgelegt: Backup Scheduling UI

Das physische Backupformat und Restore-Verhalten sind festgelegt.

Zeitplanung, UI und Benachrichtigung werden in Beta Kapitel 21 konkretisiert.

---

### 281. Nicht hier festgelegt: Multi-Device Sync

Dieses Kapitel verhindert Pfad- und ID-Bindungen, die Multi-Device unmöglich machen würden.

Ein vollständiges verteiltes Synchronisationsprotokoll ist nicht Bestandteil von v1.

---

### 282. Nicht hier festgelegt: alternative Datenbank

SQLite ist die konkrete v1-Implementierung.

Eine spätere alternative DB muss das logische Modell und die Invarianten aus Kapitel 02 vollständig abbilden.

---

## Teil XXXI – Verbindliche Storage-Invarianten

### 283. Invariante – SQLite lebt lokal

Die aktive SQLite-Hauptdatenbank liegt auf einem lokal zuverlässigen Dateisystem.

Netzwerkspeicher wird über Storage-/Sync-Grenzen angebunden, nicht als transparenter Live-DB-Dateipfad.

---

### 284. Invariante – Eine autoritative strukturierte Transaktionsgrenze

Knowledge, Personal Memory, Raw-Archive-Metadaten, Audit/Provenienz, Configuration und Durable Operational State können innerhalb derselben `athena.db` atomar koordiniert werden.

---

### 285. Invariante – Große Originale bleiben außerhalb SQLite

Originaldateien und große immutable Repräsentationen liegen im Blob Store.

SQLite hält Identität, Metadaten und Referenzen.

---

### 286. Invariante – Blob vor DB-Referenz

Ein neuer finaler Blob wird verifiziert, bevor eine bestätigte kanonische DB-Referenz darauf entsteht.

---

### 287. Invariante – Derived State ist rebuildable

`search.db`, Embeddings, HNSW, Cache und Previews dürfen zerstört und aus autoritativen Daten neu aufgebaut werden.

---

### 288. Invariante – Kein Protected Klartextindex auf Disk

Geschützte Klartexte oder Embeddings werden im gesperrten Zustand nicht in normalen persistenten Derived-State-Dateien gespeichert.

---

### 289. Invariante – Migration auf geprüfter Kopie

Komplexe blockierende Schema-Migrationen werden nicht blind auf der einzigen produktiven DB ausgeführt.

Eine verifizierbare Pre-Migration-Kopie beziehungsweise Clone-Strategie ist Pflicht.

---

### 290. Invariante – Backup ist Snapshot plus immutable Objects

Ein Backup besteht aus einem konsistenten SQLite-Snapshot, einem Manifest und allen referenzierten deduplizierten Blob Objects.

---

### 291. Invariante – Restore respektiert Löschung

Ein synchronisiertes Backup-Repository führt Deletion-Ledger-Informationen, damit ältere Snapshots endgültig gelöschte IDs nicht stillschweigend reaktivieren.

---

### 292. Invariante – Disk Full löscht kein Wissen

Speicherknappheit darf niemals automatisch Originale oder kanonische Wissensdaten opfern.

---

### 293. Invariante – Keine physische Löschlüge

ATHENA unterscheidet logische Löschung, kryptographische Löschung und physische Medienlöschung.

Es behauptet keine Garantie, die die zugrunde liegende Hardware nicht erfüllen kann.

---

### 294. Invariante – Core ist einziger DB-Schreiber

UI, Plugins, Modelle und externe Clients umgehen die Repository-/WriteCoordinator-Schicht nicht.

---

## Teil XXXII – Technische Referenzen

### 295. SQLite Referenzen

Für die v1-Implementierung sind insbesondere relevant:

```text
https://sqlite.org/wal.html
https://sqlite.org/pragma.html
https://sqlite.org/foreignkeys.html
https://sqlite.org/backup.html
https://sqlite.org/fts5.html
https://sqlite.org/useovernet.html
https://sqlite.org/howtocorrupt.html
```

Die ATHENA-Implementierung prüft Runtime-Capabilities und verlässt sich nicht auf undokumentierte SQLite-Annahmen.

---

### 296. Alembic Referenz

SQLite-kompatible Batch-Migrationen:

```text
https://alembic.sqlalchemy.org/en/latest/batch.html
```

---

### 297. Canonical JSON Referenz

ATHENA verwendet JCS gemäß:

```text
RFC 8785
https://www.rfc-editor.org/rfc/rfc8785.html
```

---

### 298. Cryptography Referenz

Für Protected Storage:

```text
https://cryptography.io/en/stable/hazmat/primitives/aead/
https://cryptography.io/en/stable/hazmat/primitives/kdf/argon2/
```

Nonce-Wiederverwendung mit AES-GCM ist verboten.

---

### 299. HNSW Referenz

v1 VectorIndexProvider verwendet hnswlib:

```text
https://github.com/nmslib/hnswlib
```

Der serialisierte HNSW-Index bleibt Derived State und kann jederzeit neu erzeugt werden.

---

## Teil XXXIII – Ergebnis und nächster Schritt

### 300. Ergebnis dieses Kapitels

Mit diesem Kapitel besitzt ATHENA eine konkrete physische v1-Persistenzarchitektur:

```text
lokale athena.db
+
filesystembasierter Raw-Archive Blob Store
+
lokaler Durable Spool
+
separate FTS5 search.db
+
HNSW Vector Index
+
manifestbasiertes Backup Repository
+
clone-basierte Migrationen
+
Recovery- und Disk-Full-Schutz
```

Die Architektur erhält alle stabilen IDs, Revisionen, Provenienzketten und Domänengrenzen aus Kapitel 02.

---

### 301. Nächstes Beta-Kapitel

Als nächstes folgt gemäß Beta-INDEX:

**Beta Kapitel 04 – Quellen, Roharchiv und Import-Pipeline**

Kapitel 04 definiert auf Basis des hier festgelegten Storage-Layers:

- Dateiimport;
- Drag-and-Drop;
- Folder Watch;
- Web-Snapshots;
- E-Mail-/Dokumentimporte;
- MIME-Erkennung;
- Extraktion;
- OCR;
- Transkription;
- SourceRepresentation;
- Chunking;
- Import-Deduplizierung;
- Quarantäne;
- Import-Fehler;
- Wiederaufnahme großer Imports;
- Provenienz der Importpipeline;
- geschützte Imports.

---

### 302. Leitregel von Beta Kapitel 03

> **ATHENAs aktueller strukturierter Zustand wird lokal transaktional und mit stabiler Commit-Historie materialisiert; ein konfigurierter Langzeitspeicher erhält verifizierte versionierte Replikationen, ohne eine live SQLite-Datei über das Netzwerk zu öffnen. Große Originale werden als immutable Blobs verwaltet. Noch nicht replizierte lokale Commits sind geschützter nicht rekonstruierbarer Zustand. Kein Commit darf auf unbestätigte Daten zeigen, kein Derived State darf zur einzigen Kopie werden, keine Migration darf die einzige gültige Datenbank riskieren und kein Restore darf eine bekannte endgültige Löschung stillschweigend rückgängig machen.**

---
