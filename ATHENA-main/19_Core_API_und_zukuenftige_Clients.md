# ATHENA Beta Specification v0.1 – Kapitel 19

## Core API und zukünftige Clients

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Desktop:** [Beta Kapitel 18](18_Desktop-Anwendung_und_System_Tray.md)
**Security:** [Beta Kapitel 16](16_Sicherheitsarchitektur_und_Protected_Content.md)

---

## Teil I – Ziel

### 1. Ziel

Die Core API ist die einzige reguläre Schnittstelle, über die Desktop UI, zukünftige Mobile Clients, CLI und Plugins mit ATHENAs Core interagieren.

---

### 2. Local v1

v1 bindet die API standardmäßig nur lokal. Remotezugriff ist nicht automatisch aktiv.

---

### 3. API ist nicht DB

Clients sehen Domainressourcen, Commands und Events – keine SQLite-Tabellen.

---

### 4. Versioned Contract

API wird explizit versioniert, damit Client/Core-Updates kontrolliert kompatibel bleiben.

---

## Teil II – Transport

### 5. v1 Transport

v1 verwendet eine lokale HTTP/ASGI-API mit:

```text
REST/JSON
+
WebSocket für bidirektionale Events/Streaming
```

Die konkrete Serverimplementation bleibt hinter `CoreApiServer`.

---

### 6. Loopback

Defaultbindung:

```text
127.0.0.1
```

und gegebenenfalls IPv6 Loopback, sofern sicher konfiguriert.

---

### 7. No 0.0.0.0 Default

ATHENA bindet nicht standardmäßig an alle Netzwerkschnittstellen.

---

### 8. Port

Port ist Configuration. Bei automatischer Wahl teilt der Core dem UI über einen lokalen Discoverymechanismus den tatsächlichen Port mit.

---

### 9. Future IPC

Ein späterer Named-Pipe/Unix-Socket-Transport darf ergänzt werden, ohne Domainendpoints zu ändern.

---

## Teil III – Authentifizierung lokal

### 10. Local Auth

Loopback allein ist keine ausreichende Authentifizierung gegen andere lokale Prozesse.

---

### 11. Session Token

Beim Start erzeugt der Core ein zufälliges kurzlebiges Client-Bootstrap-Secret beziehungsweise eine äquivalente lokale Authentifizierung.

---

### 12. Token Storage

Token liegt nur in restriktivem Runtimebereich/OS-Mechanismus und wird nicht in normalen Logs oder Configexports gespeichert.

---

### 13. Client Identity

Jede verbundene Clientinstanz erhält eine `client_id`.

---

### 14. CSRF/Browser Boundary

Falls Browsertechnologien lokal zugreifen können, werden Origin/CORS/CSRF-Grenzen strikt konfiguriert. Wildcard-CORS ist nicht Default.

---

## Teil IV – API Version

### 15. Path Version

v1 verwendet:

```text
/api/v1/...
```

---

### 16. Schema

OpenAPI/JSON-Schemas werden aus den tatsächlichen Contracts erzeugt beziehungsweise als Source of Truth versioniert.

---

### 17. Compatibility

Breaking Changes benötigen neue Major API-Version oder koordinierte Clientmigration.

---

### 18. Feature Discovery

`/capabilities` erlaubt Clients, optionale Funktionen zu erkennen.

---

## Teil V – Resource APIs

### 19. Health

```text
GET /api/v1/health
```

liefert Core-/Komponentenstatus ohne sensitive Inhalte.

---

### 20. Chat

Endpoints für:

- Chat list;
- create;
- messages;
- send;
- cancel generation;
- archive mode.

---

### 21. Knowledge

Read/Search/Create/Edit/Archive/Delete über kontrollierte Domainservices.

---

### 22. Memory

Separate Personal-Memory-Ressourcen, nicht unter Knowledge-Endpunkt versteckt.

---

### 23. Sources

Source metadata, Anchors, Representation status und autorisierte Contentstreams.

---

### 24. Jobs

Queue list, details, pause/resume/cancel/retry.

---

### 25. Models

Registry, active model, load/unload/switch.

---

### 26. News

Digests, Events, Backfillstatus.

---

### 27. Backup

Backupstatus, manual run, restore preparation.

---

### 28. Security

Lock/unlock operations, aber keine API-Ausgabe roher Schlüssel.

---

## Teil VI – Commands versus Direct Mutation

### 29. Command Pattern

Folgenreiche Änderungen werden als Commands modelliert:

```text
POST .../commands
```

beziehungsweise spezifische action endpoints.

---

### 30. expected_revision

Editcommands tragen `expected_revision_id`.

---

### 31. Idempotency

Wiederholbare Create-/Actionrequests unterstützen einen `Idempotency-Key`.

---

### 32. No PUT Blind

Ein Client darf nicht durch blindes vollständiges Objekt-Replace alte Revisionen überschreiben.

---

## Teil VII – Streaming

### 33. Chat Stream

Chatgeneration streamt Events:

```text
generation_started
text_delta
source_update
generation_completed
generation_cancelled
generation_failed
```

---

### 34. Job Events

Clients können Jobstatusupdates abonnieren.

---

### 35. Model Events

Load/unload/health changes als Events.

---

### 36. Reconnect

Events besitzen monotone Sequenz beziehungsweise Resume Cursor, soweit nötig, damit UI nach Reconnect Status nachholen kann.

---

### 37. Canonical State after Reconnect

Client darf sich nicht nur auf verpasste Events verlassen. Nach Reconnect wird autoritativer State erneut abgefragt.

---

## Teil VIII – Error Model

### 38. Problem Details

Fehlerantworten besitzen ein einheitliches strukturiertes Format mit:

- code;
- message;
- request_id;
- retryable;
- details safe-for-client.

---

### 39. No Stacktrace Default

Stacktraces werden nicht an normale Clients gesendet.

---

### 40. Conflict

Revision Conflict liefert:

```text
HTTP 409
+
current_revision_id
+
expected_revision_id
```

ohne automatisches Merge.

---

### 41. Locked

Protected Scope locked liefert klaren Authorization/Locked-Fehler.

---

### 42. Rate/Busy

Temporäre Resource/Queuegrenzen liefern retrybare Fehler beziehungsweise accepted Jobstatus.

---

## Teil IX – Pagination

### 43. Cursor

Große Listen verwenden opaque Cursor.

---

### 44. Stable Ordering

Cursor basiert auf stabiler Sortierung und Snapshot/commit boundary, damit Seiten nicht chaotisch springen.

---

### 45. Max Page Size

Server erzwingt Maximalgröße.

---

### 46. No Unbounded Export Endpoint

Vollständige Exporte laufen als Job/Downloadartifact, nicht als gigantische normale JSON-Antwort.

---

## Teil X – Search API

### 47. Search

SearchRequest enthält Query, Domains, Filters, Scope und Limit.

---

### 48. Result Refs

Responses liefern EntityRefs/SourceAnchors und keine direkten DB rowids.

---

### 49. Protected

Authorization filtert vor Ergebnisbildung.

---

### 50. Explain

Optionaler Diagnosemodus liefert Rankingkomponenten, nicht interne Secrets.

---

## Teil XI – File/Blob API

### 51. Upload

Große Uploads werden gestreamt und erzeugen ImportJobs.

---

### 52. Download

Blobdownload benötigt Source-/Protectionauthorization.

---

### 53. Range

Große Medien dürfen HTTP Range beziehungsweise äquivalentes Streaming unterstützen.

---

### 54. No Path Exposure

Client erhält keine lokalen absoluten Archivepfade, wenn nicht explizit eine File-Reveal-Funktion angefordert und autorisiert ist.

---

## Teil XII – Security

### 55. Authorization

Jeder Endpoint besitzt definierte Capabilityanforderungen.

---

### 56. Request Size

JSON-/Uploadgrößen sind begrenzt.

---

### 57. Input Validation

Alle IDs, Enums, URLs, Filenames und Structured Payloads werden serverseitig validiert.

---

### 58. Log Redaction

API Logging redigiert Tokens, Passwörter, Protected Payloads und Secret Header.

---

### 59. Unlock

Passwortübertragung erfolgt nur über lokale authentifizierte Session; es wird nicht in Requestlogs gespeichert.

---

## Teil XIII – Future Remote Client

### 60. Not Default v1

Remote Mobile/Desktop Zugriff ist Zukunftserweiterung.

---

### 61. Same Core

Remote Clients nutzen denselben Core und dieselben IDs; keine zweite unabhängige Memory-Instanz.

---

### 62. Required Security

Vor Remote Enablement sind mindestens nötig:

- starke Geräteauthentifizierung;
- verschlüsselte Transportverbindung;
- Clientrevocation;
- Session expiry;
- Network exposure configuration;
- Protected Content Policy.

---

### 63. No Port Forward Suggestion

ATHENA soll nicht als einfache „Port 127.0.0.1 auf Router öffnen“-Lösung umgesetzt werden.

---

## Teil XIV – CLI

### 64. CLI Client

Eine spätere CLI nutzt dieselbe API und kann Diagnose/Backup/Jobaktionen ausführen.

---

### 65. Recovery

Minimaler Recovery Mode darf bei Coreproblemen niedrigere direkte Recoveryinterfaces besitzen; normale CLI umgeht API nicht.

---

## Teil XV – Plugins

### 66. Plugin RPC

PluginHost darf eine eigene interne, capabilitybeschränkte RPC-Sicht erhalten.

---

### 67. No Public API Superuser

Pluginendpoint kann nicht durch Kenntnis einer URL alle Permissions umgehen.

---

## Teil XVI – API Events und Audit

### 68. Request ID

Jeder Request erhält `request_id` für Logkorrelation.

---

### 69. Actor Attribution

Mutierende Commands werden dem tatsächlichen User/Client/Pluginactor zugeordnet.

---

### 70. Audit Boundary

Nicht jeder GET erzeugt dauerhaftes Audit. Sensitive Reads/Exports können auditiert werden.

---

### 71. External Actions

Commands, die externe Aktionen auslösen, referenzieren die gültige Benutzerautorisierung.

---

## Teil XVII – Performance

### 72. Async IO

Langsame Net-/Model-/Fileoperationen blockieren nicht den API Eventloop.

---

### 73. Job Offload

Lange Aktionen antworten früh mit `202 Accepted` + `job_id`.

---

### 74. Backpressure

Streamingclient, der nicht liest, darf unbounded Memorybuffer nicht verursachen.

---

### 75. Connection Limits

Lokale Verbindungslimits verhindern Fehlerloops/DoS durch defekte Clients.

---

## Teil XVIII – Tests

### 76. Unauthorized Local Process Test

Request ohne Sessiontoken → denied.

---

### 77. CORS Test

Beliebige Browserorigin darf nicht standardmäßig API lesen.

---

### 78. Conflict Test

Edit mit stale revision → 409.

---

### 79. Idempotency Test

Create mit gleichem Idempotency-Key zweimal → kein doppeltes Objekt.

---

### 80. Streaming Reconnect Test

UI trennt während Jobevents. Nach Reconnect kann State korrekt resynchronisiert werden.

---

### 81. Upload Test

Sehr große Datei streamen; Core-RAM wächst nicht proportional.

---

### 82. Protected Test

Locked Protected Source Download → denied.

---

### 83. No Path Leak Test

Normale Source API enthält keinen absoluten lokalen Storagepfad.

---

### 84. Version Test

Inkompatibler API-Client erhält klare Versionmeldung.

---

### 85. Rate Test

Defekter Client erzeugt tausende Requests; Core bleibt für Haupt-UI nutzbar.

---

### 86. Remote Disabled Test

API darf nach Defaultinstall nur Loopback lauschen.

---

### 87. Abschluss

Die Core API ist bestanden, wenn alle Clients dieselben kontrollierten Domainregeln verwenden und spätere Mobile-/CLI-Erweiterungen möglich sind, ohne direkte Datenbank- oder Dateisystemkopplung.

---

## Nächster Schritt

**Beta Kapitel 20 – Obsidian und externe Bearbeitung**.
