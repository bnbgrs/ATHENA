# ATHENA Beta Specification v0.1 – Kapitel 12

## Job-System, Queue und Scheduler

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Research:** [Beta Kapitel 11](11_Exhaustive_Research.md)

---

## Teil I – Aufgabe

### 1. Ziel

Das Job-System macht alle länger laufenden und wiederholbaren ATHENA-Prozesse persistent, priorisierbar, pausierbar und nach Crash fortsetzbar.

Ein Job ist kein Thread. Er ist eine langlebige Beschreibung einer Aufgabe.

---

### 2. Welche Arbeit als Job läuft

Mindestens:

- Imports und nachgelagerte Repräsentationen;
- Embedding/Reembedding;
- Reindexing;
- Knowledge Extraction;
- Reinterpretation;
- Exhaustive Research;
- News Collection/Backfill;
- Backup/Restore;
- Integrity Sweeps;
- Migration Jobs;
- Offline-Sync;
- Projection Reconciliation.

---

### 3. Kurze direkte Aktionen

Sehr kurze atomare UI-Reads oder einzelne schnelle Writes benötigen nicht zwingend einen persistierten Job.

---

### 4. Durable State

Jobs, Checkpoints und OutboxItems gehören zu Durable Operational State und werden nicht als Cache behandelt.

Für Protected Workloads gilt zusätzlich: Der ungeschützte Job-/Checkpointzustand enthält nur neutrale technische Metadaten. Queries, Source-Titel, Textfragmente, semantische Zwischenresultate oder andere Protected Details werden über den ProtectionScope verschlüsselt persistiert. Ein Queue-Restart darf keine Klartext-Schattenkopie geschützter Arbeit erzeugen.

## Teil II – Jobmodell

### 5. Job Identity

Jeder Job besitzt eine stabile UUIDv7 `job_id`.

---

### 6. Job Type

`job_type` wird über eine kontrollierte Registry definiert. Plugins können namespaced Jobtypen registrieren, wenn Berechtigung vorhanden ist.

---

### 7. Job Payload

`requested_scope` und `pinned_configuration` enthalten kanonisches JSON. Große Inputs werden per EntityRef/BlobRef referenziert.

---

### 8. Parent/Child

Jobs können Child Jobs besitzen. Parent Completion hängt von explizit definierten Child-Policies ab, nicht allein von Prozesshierarchie.

---

### 9. Dependencies

Ein Job kann auf andere Jobs oder Zustände warten:

```text
job_dependency
resource_dependency
storage_dependency
network_dependency
user_dependency
```

---

## Teil III – Zustandsmaschine

### 10. Kernzustände

Verbindlich:

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

---

### 11. Terminal States

Terminal:

```text
cancelled
failed
completed
```

Ein `failed` Job kann über eine neue Retry-Attempt beziehungsweise Statusrevision wieder planbar werden, ohne seine Geschichte zu verlieren.

---

### 12. Waiting Reasons

Mindestens:

```text
waiting_resource
waiting_storage
waiting_network
waiting_dependency
waiting_schedule
waiting_user
waiting_backoff
```

---

### 13. State Transition Validation

Ungültige Sprünge wie `completed → running` werden verhindert. Ein bewusstes erneutes Ausführen erzeugt einen neuen Run/Attempt.

---

### 14. Heartbeat

Running Jobs aktualisieren einen Heartbeat beziehungsweise Lease. Nach Prozesscrash können verwaiste `running` Jobs erkannt und in Recovery/queued überführt werden.

---

## Teil IV – Queue

### 15. Persistent Queue

Die Queue wird in `athena.db` aus Jobzuständen und Prioritätsfeldern abgeleitet. Kein ausschließlich in-memory Queuezustand entscheidet über langfristige Arbeit.

---

### 16. Priority Classes

Grundreihenfolge:

```text
P0 data_safety
P1 interactive
P2 time_critical
P3 normal
P4 background
P5 maintenance
```

Direkte Benutzerinteraktion besitzt grundsätzlich Vorrang; datensicherheitskritische Arbeit darf P0 sein.

---

### 17. Within Priority

Innerhalb einer Klasse nutzt v1 grundsätzlich:

```text
eligible_at
+
created_at
+
fairness aging
```

um Starvation zu vermeiden.

---

### 18. Priority Inheritance

Wenn ein interaktiver Task auf einen niedrig priorisierten Dependency Job wartet, darf dessen effektive Priorität temporär angehoben werden.

---

### 19. No Infinite Starvation

Lange wartende Backgroundjobs erhalten Aging, sofern keine Ressourcen-/Sicherheitsgrenze dagegen spricht.

---

## Teil V – Scheduler

### 20. Scheduler Loop

Scheduler:

```text
eligible jobs lesen
↓
dependencies prüfen
↓
resource admission
↓
priority/fairness
↓
lease erwerben
↓
worker dispatch
```

---

### 21. Wakeup

Scheduler reagiert auf:

- neue Jobs;
- Job Completion;
- Resource Change;
- Storage Online;
- Network State;
- Timer.

Zusätzlich existiert ein periodischer Fallback-Tick.

---

### 22. No Busy Polling

Der Scheduler soll nicht dauerhaft hochfrequent die DB pollen.

---

### 23. Clock

Zeitplanung verwendet UTC intern. Benutzerzeitpläne behalten zusätzlich lokale Zeitzone für DST-korrekte Wiederholungen.

---

## Teil VI – Zeitpläne

### 24. Scheduled Job Definition

Wiederkehrende Aufgaben besitzen eine persistente ScheduleDefinition getrennt von einzelnen Jobinstanzen.

---

### 25. One Instance per Occurrence

Jede geplante Ausführung erzeugt eine eigene Jobinstanz mit `scheduled_for`.

---

### 26. Missed Runs

Schedule definiert eine Missed-Run-Policy:

```text
skip
run_once
backfill_all
backfill_bounded
```

---

### 27. Daily News

Daily News verwendet `backfill_bounded` beziehungsweise eine domänenspezifische Backfillpolicy, damit Offline-Zeiträume historisch nachgearbeitet werden können.

---

### 28. DST

Tageszeitbasierte Jobs verwenden IANA-Zeitzonen und behandeln DST-Übergänge deterministisch.

---

## Teil VII – Leases und Worker

### 29. Worker Lease

Ein Worker bearbeitet einen Job nur mit einer zeitlich begrenzten Lease.

---

### 30. Lease Fields

Mindestens:

```text
worker_id
lease_token
lease_acquired_at
lease_expires_at
heartbeat_at
```

---

### 31. Renew

Lange Stages erneuern die Lease periodisch.

---

### 32. Expired Lease

Nach Ablauf darf ein Recoveryprozess den Job wieder verfügbar machen, aber erst nach Idempotenz-/Checkpointprüfung.

---

### 33. Fencing

Persistierende Stage-Writes prüfen das aktuelle Lease Token beziehungsweise eine Fencing Sequence, damit ein alter Zombie-Worker nach Leaseverlust keine Ergebnisse committen kann.

---

## Teil VIII – Checkpoints

### 34. Checkpoint Boundary

Checkpoints markieren **bestätigten** Fortschritt.

---

### 35. Granularity

Granularität wird jobtypabhängig gewählt. Große Jobs checkpointen häufiger als kurze.

---

### 36. Checkpoint after Commit

Ein Checkpoint darf nur auf Inputs/Outputs zeigen, die bereits durable committed sind.

---

### 37. Resume

Resume lädt:

- pinned configuration;
- letzten Checkpoint;
- completed Work Units;
- Idempotency Records;
- aktuelle Dependency/Resource States.

---

### 38. Checkpoint Pruning

Alte Zwischencheckpoints dürfen nach Jobabschluss kompakt aufbewahrt oder nach Policy reduziert werden, sofern die für Audit/Resume nicht mehr benötigten Details rekonstruierbar sind.

---

## Teil IX – Idempotenz

### 39. Job Attempts

Ein Retry derselben logischen Aufgabe darf nicht dieselbe kanonische Wirkung doppelt erzeugen.

---

### 40. Idempotency Record

Für effectful Work Units wird vor/mit Commit der Idempotency Key geprüft.

---

### 41. External Side Effects

Für externe Aktionen wird ein stabiler Idempotency Key soweit das Zielsystem ihn unterstützt mitgegeben. Wenn nicht, muss ATHENA vor Retry den bekannten Remotezustand prüfen.

---

### 42. At-least-once Execution

Workerdispatch darf technisch at-least-once sein. Korrektheit entsteht durch Idempotenz und Fencing, nicht durch die unrealistische Annahme exakt einmaliger Prozessausführung.

---

## Teil X – Retry und Backoff

### 43. Retryable Errors

Beispiele:

- temporäres Netzwerk;
- Provider busy;
- Archive offline;
- transiente DB busy;
- vorübergehender Resource Shortage.

---

### 44. Non-Retryable

Beispiele:

- ungültige Benutzerkonfiguration;
- Schema Validation Failure;
- fehlende Berechtigung;
- absichtlich gecancelte Aufgabe;
- reproduzierbare unsupported format condition.

Diese benötigen Änderung/Benutzereingriff.

---

### 45. Backoff

Standard:

```text
exponential backoff
+
jitter
+
max interval
```

Die Werte sind Job-Type-Configuration.

---

### 46. Retry Budget

Jobs besitzen maximale automatische Retryzahl beziehungsweise Zeitbudget. Danach `failed` oder `waiting_user`.

---

## Teil XI – Cancel und Pause

### 47. Pause

Pause ist reversibel und wartet auf einen sicheren Stage-/Checkpointpunkt.

---

### 48. Cancel

Cancel verlangt kontrolliertes Beenden. Bereits bestätigte autoritative Ergebnisse bleiben bestehen.

---

### 49. Cancel Requested

`cancel_requested` erlaubt Worker, Cleanup und finalen Checkpoint durchzuführen.

---

### 50. Hard Kill

Wenn ein Worker nicht reagiert, kann Prozesskill nötig sein. Recovery behandelt den Job anschließend wie Crash, nicht wie sauber completed.

---

### 51. Child Jobs

Cancelpolicy definiert, ob Children ebenfalls gecancelt, detached oder zu Ende geführt werden.

---

## Teil XII – Backpressure

### 52. Queue Depth

Scheduler beobachtet Queuegröße und Jobklassen.

---

### 53. Producer Limits

Ein Discovery-/Importjob darf Work Units nur in begrenzten Batches erzeugen, wenn die downstream Queue wächst.

---

### 54. Resource Backpressure

Bei hoher RAM-/GPU-/Disk-Last werden neue schwere Jobs nicht admitted.

---

### 55. Storage Backpressure

Bei Disk CRITICAL werden Derived-State-Produzenten pausiert und große Imports blockiert.

---

### 56. No Silent Drop

Backpressure verzögert Arbeit; sie verwirft keine erforderlichen Jobs stillschweigend.

---

## Teil XIII – Concurrency Limits

### 57. Global Limits

Konfigurierbare Maxima für:

- CPU-heavy;
- IO-heavy;
- model-heavy;
- network-heavy;
- backup;
- migration

Jobklassen.

---

### 58. Per Resource

Beispiel:

```text
max_primary_model_jobs = 1
max_heavy_disk_jobs = 1
max_light_io_jobs = N
```

---

### 59. Per Root

Zwei große Blobmigrationen auf demselben langsamen Archive Root werden standardmäßig serialisiert.

---

### 60. Migration Exclusivity

Blockierende DB-Migration besitzt exklusive Storage-Admission.

---

## Teil XIV – Benutzerinteraktion

### 61. Interactive Request

Direkte Chats werden nicht zwingend als persistente Backgroundjobs modelliert, können aber modellabhängige ResourceReservations erhalten.

---

### 62. Preemption

Background Jobs werden an Checkpoint-/Batchgrenzen pausiert, wenn interaktive Ressourcen benötigt werden.

---

### 63. No Unsafe Preemption

Ein laufender atomarer DB-Commit oder Blobfinalisierung wird nicht mitten im kritischen Abschnitt abgebrochen.

---

### 64. Progress UI

Queueansicht zeigt verständlich:

- was läuft;
- warum etwas wartet;
- Fortschritt;
- Priorität;
- Retry;
- Pause/Cancel.

---

## Teil XV – Crash Recovery

### 65. Startup Recovery

Beim Start werden Jobs mit `running` und abgelaufener Lease untersucht.

---

### 66. Recovered State

Je nach Jobtyp:

```text
queued
paused
waiting_dependency
failed_recovery_required
```

---

### 67. No Assume Complete

Fehlender Workerprozess bedeutet niemals automatisch completed.

---

### 68. Side-effect Reconciliation

Bei möglichen externen Side Effects prüft Recovery Outbox/Idempotency/Remotezustand vor Retry.

---

## Teil XVI – Tests

### 69. Restart Test

100 Jobs queued, Core hart beenden. Nach Start müssen alle nicht terminalen Jobs wieder korrekt sichtbar sein.

---

### 70. Lease Expiry Test

Worker stirbt mit Lease. Zweiter Worker darf erst nach Expiry/Fencing übernehmen.

---

### 71. Zombie Test

Alter Worker versucht nach Leaseverlust Commit. Fencing muss Write verweigern.

---

### 72. Idempotency Test

Gleiche Work Unit zweimal dispatchen. Nur ein kanonischer Effekt.

---

### 73. Backpressure Test

Producer erzeugt schneller als Worker verarbeitet. Queue muss stabil begrenzt wachsen beziehungsweise Producer drosseln.

---

### 74. Priority Test

Großer Maintenancejob läuft, Userchat benötigt Modell. Maintenance pausiert/Resource gibt frei.

---

### 75. Disk Critical Test

Disk CRITICAL: Reembedding pausiert, notwendiger kleiner Userwrite bleibt möglich.

---

### 76. Schedule Missed Test

PC sieben Tage aus. Daily-News-Policy erzeugt korrekte Backfilljobs statt sieben parallele unkontrollierte Runs.

---

### 77. Cancel Test

Job während Batch canceln. Confirmed Output bleibt, unconfirmed Stage wird verworfen.

---

### 78. Retry Test

Temporärer Netzwerkfehler löst Backoff aus; permanenter Authfehler geht zu waiting_user/failed.

---

### 79. Abschluss

Das Job-System ist bestanden, wenn ATHENA tagelang oder wochenlang unterbrochene Arbeit zuverlässig wiederaufnehmen kann, ohne doppelte kanonische Effekte, verlorene Aufgaben oder eine blockierte interaktive Nutzung.

---

## Nächster Schritt

**Beta Kapitel 13 – Ressourcenmanagement**.
