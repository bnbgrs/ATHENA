# ATHENA Beta Specification v0.1 – Kapitel 24

## Logging, Monitoring und Observability

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Recovery:** [Beta Kapitel 22](22_Recovery_Mode_und_Selbstdiagnose.md)
**Security:** [Beta Kapitel 16](16_Sicherheitsarchitektur_und_Protected_Content.md)

---

## Teil I – Ziele

### 1. Ziel

Observability macht ATHENAs technischen Zustand nachvollziehbar, ohne Logs zu einem zweiten Archiv persönlicher Inhalte zu machen.

---

### 2. Drei Ebenen

ATHENA unterscheidet:

```text
structured logs
metrics
health/events
```

Audit/Provenienz bleiben davon getrennte autoritative Systeme.

---

### 3. Privacy by Default

Logs speichern standardmäßig technische IDs, Kategorien und Größen – nicht vollständige Chattexte, Dokumentinhalte oder Secrets.

---

### 4. Local First

Observabilitydaten bleiben standardmäßig lokal. Externe Telemetrie ist nicht Voraussetzung und nicht automatisch aktiv.

---

## Teil II – Structured Logging

### 5. Format

Core und Worker loggen strukturierte Events mit mindestens:

```text
timestamp
level
component
event
request_id
job_id optional
processing_run_id optional
error_code optional
duration_ms optional
```

---

### 6. JSON Lines

Persistente technische Logs verwenden v1 ein zeilenbasiertes JSON-Format, damit sie maschinenlesbar und recoveryfreundlich sind.

---

### 7. Levels

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

werden konsistent verwendet.

---

### 8. No semantic payload default

Normale Logs enthalten keine vollständigen KnowledgeBodies, Prompts, Modelloutputs oder Sourcechunks.

---

### 9. Context IDs

UUIDs können zur Korrelation geloggt werden, sofern der Schutzbereich dies zulässt.

---

## Teil III – Redaction

### 10. Secrets

Bekannte Secretfelder werden vor Serialisierung redigiert.

---

### 11. Headers

Authorization, Cookie, API-Key und vergleichbare Header werden nie vollständig geloggt.

---

### 12. URLs

Sensitive Queryparameter werden entfernt oder redigiert.

---

### 13. Protected Content

Für protected Entities werden neutrale IDs/Events geloggt; keine Titel oder Klartextinhalte im unprotected Log.

---

### 14. Exception Objects

Exceptions werden nicht blind per `repr()` serialisiert, wenn sie Request-/Payloaddaten enthalten könnten.

---

## Teil IV – Log Rotation

### 15. Files

Logdateien liegen in einem eigenen lokalen `logs_root`.

---

### 16. Rotation

Rotation ist größen- und zeitbegrenzt.

---

### 17. Default Retention

Technische Logs werden deutlich kürzer aufbewahrt als Audit. Ein sinnvoller v1-Default ist eine begrenzte Anzahl täglicher/rotierter Dateien; genaue Tage sind Configuration.

---

### 18. Disk Pressure

Bei Disk WARNING/CRITICAL dürfen alte technische Logs nach Retention sicher gelöscht werden. Audit folgt eigenen Regeln.

---

### 19. Compression

Rotierte Logs dürfen komprimiert werden.

---

## Teil V – Request Correlation

### 20. request_id

Jede Core-API-Anfrage erhält eine `request_id`.

---

### 21. job_id

Backgroundarbeit korreliert über `job_id`.

---

### 22. processing_run_id

Modell-/Pipelinearbeit kann zusätzlich `processing_run_id` führen.

---

### 23. No Global Trace Required

v1 benötigt keinen externen Distributed-Tracing-Server. IDs reichen für lokalen modularen Monolithen.

---

## Teil VI – Metrics

### 24. Core Metrics

Mindestens:

- request latency;
- error count;
- active clients;
- DB write latency;
- DB busy/retry count.

---

### 25. Job Metrics

- queue depth;
- running/waiting by class;
- completion/failure;
- retry count;
- stage durations.

---

### 26. Model Metrics

- model load time;
- generation latency;
- first-token latency soweit messbar;
- tokens/s soweit Provider liefert;
- model failures;
- VRAM/RAM peaks soweit verfügbar.

---

### 27. Search Metrics

- FTS latency;
- vector latency;
- candidate counts;
- index watermarks;
- rebuild progress.

---

### 28. Storage Metrics

- root free space;
- blob write throughput;
- spool size;
- archive offline duration;
- backup age.

---

### 29. Security Metrics

Nur aggregierte technische Werte, etwa denied requests, ohne Passwort-/Secretinhalte.

---

## Teil VII – Health Model

### 30. Health

Jede Komponente implementiert einen Healthstatus:

```text
ok
degraded
unavailable
error
recovery_required
```

---

### 31. Dependencies

Health zeigt nicht nur `red/green`, sondern betroffene Fähigkeiten.

---

### 32. Aggregate

Core-Gesamtstatus kann `degraded` sein, obwohl Searchvector oder News ausfällt.

---

### 33. Critical

DB-/Integritätsfehler können `recovery_required` erzeugen.

---

## Teil VIII – Performance History

### 34. Purpose

Lokale Langzeitmetriken helfen, Ressourcenprofile und Regressionen zu erkennen.

---

### 35. Aggregation

Rohmetriken werden zeitlich aggregiert, damit Observability nicht selbst unbeschränkt wächst.

---

### 36. No Personal Behavior Profile

Metriken erfassen technische Last, nicht detaillierte persönliche Arbeitszeiten oder Inhaltspräferenzen als verstecktes Profil.

---

### 37. Retention

Hochauflösende Werte kurz, aggregierte Werte länger.

---

## Teil IX – Diagnostics

### 38. Recent Errors

Diagnostics View zeigt gruppierte Fehler nach Komponente/Code.

---

### 39. Explain

Für bekannte Fehlercodes existieren menschenlesbare Erklärungen und sichere Handlungsvorschläge.

---

### 40. Stacktrace

Advanced Diagnostics kann Stacktraces anzeigen, nach Redaction.

---

### 41. Environment

Diagnose kann OS-/App-/Provider-Versionen enthalten, aber keine unnötigen persönlichen Dateipfade.

---

## Teil X – Audit Boundary

### 42. Audit

Sicherheits-, Datenänderungs-, Backup-/Restore- und relevante externe Aktionen gehören ins Audit, nicht nur in technische Logs.

---

### 43. Logs can rotate

Wenn ein technisches Log rotiert, darf dadurch keine notwendige Provenienz verschwinden.

---

### 44. No double payload

Audit und Logs duplizieren nicht denselben vollständigen Content.

---

## Teil XI – External Access Logging

### 45. Gateway Event

Log/Audit enthält Host, Zweck, Route, Ergebnis, Dauer, Größe.

---

### 46. Privacy Status

Ob Privacy Route aktiv war, wird dokumentiert.

---

### 47. No Query Leak

Suchquery wird nur gespeichert, wenn für Provenienz notwendig und erlaubt; sonst sanitisiert.

---

## Teil XII – Model Debugging

### 48. Prompt Debug

Vollständige Prompts werden standardmäßig **nicht** in technische Logs geschrieben.

---

### 49. Explicit Debug Mode

Ein bewusst aktivierter lokaler Debugmodus kann Contextstruktur/Tokenzahlen zeigen. Protected/Secretredaction bleibt trotzdem aktiv.

---

### 50. Outputs

Vollständige Modelloutputs gehören in Chat/ProcessingArtifacts, wenn fachlich gespeichert, nicht in generische Debuglogs.

---

## Teil XIII – Crash Reporting

### 51. Local Crash Report

Bei Crash schreibt ATHENA soweit möglich einen kleinen lokalen Crashreport mit:

- component;
- version;
- exception class;
- sanitized stack;
- recent technical event IDs.

---

### 52. No Automatic Upload

Crashreports werden nicht automatisch an einen externen Dienst gesendet.

---

### 53. User Export

Benutzer kann Diagnosebundle bewusst exportieren.

---

## Teil XIV – Alerting

### 54. User Alerts

Alerts für:

- Backup zu alt/failed;
- Disk Critical;
- DB integrity;
- repeated job failure;
- privacy route failure bei Automation;
- plugin crash loop;
- protected integrity failure.

---

### 55. Dedup

Gleicher persistenter Fehler erzeugt keine Notification pro Minute.

---

### 56. Resolution

Wenn Fehler behoben ist, kann Status zurück auf normal wechseln und Alert als resolved gelten.

---

## Teil XV – QA und Entwicklung

### 57. Dev Logging

Entwicklungsbuilds dürfen detaillierter loggen, aber Testdaten und Redactionregeln bleiben.

---

### 58. Performance Baseline

CI/Benchmarks können ausgewählte Kernpfade messen, um grobe Regressionen zu erkennen.

---

### 59. Log Schema Test

Logevent-Schemas werden getestet, damit Tools nicht durch zufällige Feldänderungen brechen.

---

## Teil XVI – Tests

### 60. Secret Redaction Test

Bekannte API Keys/Passwords in Fehlerpfade injizieren. Kein Secretstring darf in Logfiles erscheinen.

---

### 61. Protected Redaction Test

Protected Testphrase durch Import/Chat/Search. Unprotected Logs dürfen sie nicht enthalten.

---

### 62. Rotation Test

Viele Logs erzeugen. Retention begrenzt Speicher und löscht kein Audit.

---

### 63. Correlation Test

API → Job → ProcessingRun muss über IDs nachvollziehbar sein.

---

### 64. Health Degradation Test

HNSW kaputt: Gesamtstatus degraded, Core/Knowledge weiterhin ok.

---

### 65. Critical Health Test

DB integrity failure: recovery_required.

---

### 66. Crash Bundle Test

Crashreport enthält Stack, aber keine Secretheader.

---

### 67. No Auto Upload Test

Ohne Benutzeraktion darf kein Diagnosebundle extern übertragen werden.

---

### 68. Metric Retention Test

Rohmetriken rotieren; Langzeitaggregation bleibt im vorgesehenen Umfang.

---

### 69. Abschluss

Observability ist bestanden, wenn technische Fehler reproduzierbar diagnostizierbar sind, ohne dass der Preis dafür ein unkontrolliertes zweites Archiv privater Inhalte ist.

---

## Nächster Schritt

**Beta Kapitel 25 – Repository- und Code-Struktur**.
