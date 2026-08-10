# ATHENA Beta Specification v0.1 – Kapitel 23

## Updates, Migrationen und Kompatibilität

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Plugins:** [Beta Kapitel 17](17_Plugin-System_und_Berechtigungen.md)

---

## Teil I – Ziel

### 1. Ziel

ATHENA muss sich über Jahre aktualisieren können, ohne Knowledge, Quellen, IDs, Provenienz oder Protected Content zu beschädigen.

---

### 2. Update Layers

Getrennt:

```text
ATHENA application
database schema
storage layout
plugins
model backend
models
embedding spaces
projection format
API
```

---

### 3. No Coupled Everything Update

Ein Appupdate erzwingt nicht automatisch Reinterpretation, Reembedding und Pluginupdates in einer unkontrollierten Transaktion.

---

### 4. Rollback

Kritische Updates benötigen einen klaren Rückweg, soweit irreversible externe Effekte nicht entgegenstehen.

---

## Teil II – Versioning

### 5. App Version

ATHENA verwendet Semantic Versioning für Releases.

---

### 6. Schema Version

Datenbankschema besitzt eigene Version/Alembic Revision.

---

### 7. Storage Layout

Blob-/Rootlayout besitzt eigene Version.

---

### 8. API Version

Core API wird unabhängig versioniert.

---

### 9. Projection Version

Obsidian Front Matter/Projectionformat besitzt eigene Version.

---

### 10. Plugin API

Plugins deklarieren kompatible Plugin API.

---

## Teil III – Update Channels

### 11. Stable

Default für normale Nutzer.

---

### 12. Beta

Optional für Nutzer, die neue ATHENA-Versionen früher testen.

---

### 13. Development

Nur Entwicklungsumgebung; nicht Standard auf Produktivdaten.

---

### 14. Channel Switch

Wechsel ist explizite Benutzerentscheidung.

---

## Teil IV – Pre-update

### 15. Preflight

Vor kritischem Update:

- aktuelle Version;
- Zielversion;
- Schemaweg;
- freier Speicher;
- DB health;
- letzte gültige Sicherung;
- Plugin Compatibility;
- Background Jobs;
- Protected State.

---

### 16. Backup

Vor Schema-/Storage-Migration wird ein verifizierter Pre-Update Restorepoint erstellt, sofern technisch möglich.

---

### 17. Jobs

Nichtkritische Jobs werden pausiert. Migrationsinkompatible laufende Jobs müssen beendet/checkpointed werden.

---

### 18. Disk

Migration Free-Space-Regeln aus Kapitel 03 gelten.

---

## Teil V – Application Update

### 19. Staged Install

Neue App wird zunächst neben beziehungsweise in Staging installiert.

---

### 20. Signature/Hash

Distributionspaket wird über dokumentierte Integritäts-/Publisherprüfung validiert.

---

### 21. No Self-overwrite Mid-run

Laufende Core-Binaries werden nicht unkontrolliert in-place ausgetauscht.

---

### 22. Restart

Update aktiviert sich über kontrollierten Restart.

---

## Teil VI – Schema Migration

### 23. Alembic

Kapitel 03 definiert clone-basierte Migrationen.

---

### 24. Migration Gate

Neue Appversion startet Normalbetrieb erst, wenn erforderliche Schema Migration erfolgreich validiert ist.

---

### 25. Old App after Migration

Wenn neue Schema-Version nicht rückwärtskompatibel ist, darf alte App nicht wieder normal auf derselben DB schreiben.

---

### 26. Rollback

Rollback verwendet Pre-Migration-DB statt riskanter Down-Migration, wenn Revision als irreversible markiert ist.

---

## Teil VII – Data Migration

### 27. Chunked

Große Datenmigrationen können nach Appstart als persistente MigrationJobs laufen.

---

### 28. Compatibility Window

Während Backfill muss Code sowohl alten als auch neuen Zwischenzustand kontrolliert lesen können.

---

### 29. Finalize

Erst nach vollständigem Backfill wird alte Representation in späterem Release entfernt.

---

### 30. No Semantic Rewrite

Data Migration verändert technische Darstellung, nicht Wissensbedeutung.

---

## Teil VIII – Derived State Compatibility

### 31. FTS

Inkompatibles Searchschema → rebuild.

---

### 32. Embeddings

Neues Embeddingmodell → neuer Embedding Space, keine Knowledge Migration.

---

### 33. HNSW

Providerformat inkompatibel → Index rebuild.

---

### 34. Cache

Cacheversion mismatch → discard.

---

## Teil IX – Model Backend Updates

### 35. Provider Health

Nach Backendupdate wird Capability Probe ausgeführt.

---

### 36. No Knowledge Rewrite

Neue Modellbackendversion verändert bestehendes Knowledge nicht.

---

### 37. Model Signature

Neue Modellrevisionen erhalten neue/angepasste ModelSignature bei künftigen Runs.

---

### 38. Pinned Jobs

Langlaufende Jobs prüfen nach Restart, ob gepinnte Konfiguration noch verfügbar ist.

---

## Teil X – Plugin Compatibility

### 39. Before Update

Installierte Plugins werden gegen neue Plugin API geprüft.

---

### 40. Incompatible

Plugin wird deaktiviert, statt Coreupdate zu blockieren, sofern Plugin nicht für kritische Migration erforderlich ist.

---

### 41. Plugin Data

Deaktivierung löscht keine Plugin-Daten.

---

### 42. Rollback

Pluginversion kann separat zurückgerollt werden, soweit dessen private Datenmigration dies erlaubt.

---

## Teil XI – API Compatibility

### 43. UI/Core

Desktop UI und Core handeln Version/Capabilities beim Connect aus.

---

### 44. Grace Period

Patch/Minor Updates sollen bestehende API v1 Clients soweit möglich kompatibel halten.

---

### 45. Breaking

Breaking Change → `/api/v2` oder koordinierter Majorrelease.

---

## Teil XII – Projection Compatibility

### 46. Front Matter

Projection Writer kennt Version und kann ältere Projektionen einlesen/migrieren.

---

### 47. No Forced Rewrite

Großer Vault wird nicht bei jedem Appupdate vollständig neu geschrieben, wenn kein Formatwechsel nötig ist.

---

### 48. External Edits

Vor Projection Migration werden offene externe Änderungen reconciled.

---

## Teil XIII – Config Migration

### 49. Versioned

Configuration-Schema ist versioniert.

---

### 50. Safe Defaults

Neue Optionen erhalten sichere Defaults.

---

### 51. Unknown Fields

Bei Roundtrip sollen unbekannte zukunfts-/pluginbezogene Felder nicht unnötig verworfen werden.

---

### 52. Invalid Old Value

Bei nicht migrierbarem Wert wird letzte gültige Config/Benutzerentscheidung genutzt, nicht still ein riskanter Default.

---

## Teil XIV – Update Rollback

### 53. Activation Marker

Launcher/Core speichert aktive Version und letzten erfolgreichen Startup.

---

### 54. Health Window

Nach Update gilt Version erst nach Startup-/DB-/Core-Smoke-Test als good.

---

### 55. Failed Startup

Mehrere frühe Crashes → Rollbackangebot beziehungsweise Recovery Mode.

---

### 56. Data Compatibility

Approllback darf nur auf DBzustand schreiben, den die alte Version unterstützt.

---

## Teil XV – Release Artifacts

### 57. Changelog

Jedes Release dokumentiert:

- User changes;
- Storage/schema changes;
- Security changes;
- migrations;
- known limitations.

---

### 58. Migration Notes

Breaking/irreversible Migrations werden explizit markiert.

---

### 59. SBOM optional

Eine Software Bill of Materials soll für veröffentlichte Builds erzeugt werden, um Abhängigkeiten nachvollziehbar zu machen.

---

## Teil XVI – Security Updates

### 60. Priority

Kritische Sicherheitsupdates können höhere Empfehlung/Benachrichtigung erhalten.

---

### 61. No Forced Network

Local-First bedeutet nicht automatische ungefragte Updateinstallation. Updatecheck selbst folgt ExternalAccess-/Configuration-Regeln.

---

### 62. Offline Update

Manuelle Offline-Installationspakete sollen möglich bleiben.

---

## Teil XVII – Tests

### 63. Forward Migration Test

Jede unterstützte alte Schema-Version → aktuelle Version auf Testkopie.

---

### 64. Rollback Test

Irreversible Migration → Pre-Migration-DB + alte App wieder startbar.

---

### 65. Crash During Update Test

Prozess killen in Staging/Aktivierung. Entweder alte oder neue vollständige App, kein Mischbinaryzustand.

---

### 66. Plugin Incompat Test

Defektes Plugin darf neuen Corestart nicht verhindern.

---

### 67. Model Backend Upgrade Test

Backend verändert Capability. Provider degradiert sauber.

---

### 68. Config Migration Test

Alte Config mit unbekannten/ungültigen Werten migrieren ohne stillen Datenverlust.

---

### 69. Projection Migration Test

Vault mit externen Edits: keine Überschreibung ohne Reconciliation.

---

### 70. Derived Rebuild Test

Update macht FTS/HNSW inkompatibel. Rebuild ohne Knowledgechange.

---

### 71. Offline Update Test

Update aus lokalem Paket ohne Internet.

---

### 72. New Version Health Test

Neue Version wird erst nach Core-/DB-Smoke-Test als good markiert.

---

### 73. Abschluss

Update/Kompatibilität ist bestanden, wenn ATHENA technische Komponenten modernisieren kann, ohne seine persistente Geschichte oder die Fähigkeit zum sicheren Rollback zu verlieren.

---

## Nächster Schritt

**Beta Kapitel 24 – Logging, Monitoring und Observability**.
