# ATHENA Beta Specification v0.1 – Kapitel 11

## Exhaustive Research

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Retrieval:** [Beta Kapitel 10](10_Retrieval_und_Suche.md)
**Context:** [Beta Kapitel 09](09_Context_Builder_und_Token-Budget.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)

---

## Teil I – Ziel und Definition

### 1. Ziel

Exhaustive Research ist ATHENAs Modus für Fragen, bei denen **Coverage, Nachvollziehbarkeit und breite Evidenzsuche** wichtiger sind als interaktive Antwortlatenz.

---

### 2. Nicht jede Frage

Exhaustive Research wird nicht für normale Chats erzwungen. Es ist ein expliziter oder klar taskabhängig gewählter Modus.

---

### 3. Was „exhaustive“ bedeutet

`Exhaustive` bedeutet:

> vollständig innerhalb eines **definierten Research Scope und Snapshots**, soweit die darin enthaltenen Quellen technisch zugänglich und erfolgreich verarbeitet wurden.

Es bedeutet nicht „das gesamte Internet vollständig durchsucht“.

---

### 4. Coverage statt Marketing

ATHENA misst und zeigt Coverage. Kann ein Scope nicht vollständig verarbeitet werden, wird das Ergebnis als partial gekennzeichnet.

---

## Teil II – ResearchScope

### 5. Scope Definition

Vor Start wird ein persistenter ResearchScope erzeugt mit:

- Query/Goal;
- Domains;
- Projects;
- Source Types;
- Time Range;
- Protection Context;
- Internet Scope falls erlaubt;
- Coverage Target.

---

### 6. Snapshot Boundary

Lokale Daten werden mindestens durch `snapshot_commit_seq` eingefroren.

---

### 7. External Snapshot

Externe Webquellen erhalten ihre eigenen Capture-Zeiten. Eine laufende Recherche behauptet nicht, dass das Web über Stunden unverändert blieb.

---

### 8. Scope Review

Bei sehr breitem Scope kann die UI vor Start eine verständliche Zusammenfassung zeigen, etwa:

```text
Alle lokalen Quellen
Zeitraum 2020–2026
plus aktuelle Webquellen
```

---

## Teil III – Discovery

### 9. Discovery Phase

Zunächst wird eine möglichst breite Kandidatenmenge aufgebaut:

```text
lexical
semantic
graph
metadata
project
time
explicit source sets
optional external discovery
```

---

### 10. CandidateSet

Discovery persistiert einen CandidateSet für reproduzierbare Coverage.

---

### 11. Deduplication

Byte- und Sourceidentitäten werden berücksichtigt, damit identische Captures nicht mehrfach als unabhängige Coverage-Einheiten gezählt werden.

---

### 12. Semantic Near-Duplicates

Near-Duplicates dürfen als Cluster markiert werden, bleiben aber als einzelne Sources nachvollziehbar.

---

### 13. Discovery Expansion

Das Primärmodell darf Queryvarianten oder zusätzliche relevante Begriffe vorschlagen. Jede Erweiterungsrunde ist begrenzt und dokumentiert.

---

## Teil IV – Candidate Freeze

### 14. Freeze

Nach Discovery wird für die Hauptverarbeitung ein CandidateSet eingefroren.

---

### 15. New Data

Neue lokale Daten nach Snapshotgrenze werden nicht stillschweigend hineingezogen.

---

### 16. Delta

Neue relevante Daten können einen Delta-Research-Job erzeugen.

---

### 17. Scope Change

Ändert der Benutzer den Scope fundamental, entsteht eine neue ResearchScope-Revision beziehungsweise ein neuer ResearchJob, statt die Coveragebasis unsichtbar zu verschieben.

---

## Teil V – Work Units

### 18. Work Unit

Kandidaten werden in kleine idempotente Work Units zerlegt:

```text
source/revision
+
anchor/chunk range
+
research question
+
pipeline version
```

---

### 19. Stable Work ID

Aus dem Work Unit Descriptor wird ein Idempotency Key erzeugt.

---

### 20. Granularity

Eine Work Unit soll klein genug sein, um innerhalb eines Modellkontextes sicher verarbeitet zu werden und nach Crash ohne großen Verlust wiederholbar zu sein.

---

### 21. Large Source

Ein großes Dokument erzeugt viele Work Units; Source Coverage wird erst vollständig, wenn alle erforderlichen Units abgeschlossen oder als fehlgeschlagen markiert sind.

---

## Teil VI – Map Stage

### 22. Map Output

Jede Work Unit erzeugt strukturierte Partial Findings:

- relevante Claims;
- Evidence Anchors;
- contradiction hints;
- entity mentions;
- relevance result;
- uncertainty;
- processing status.

---

### 23. No Hallucinated Evidence

EvidenceRefs werden vom Core validiert. Ein Modell darf keine nicht vorhandenen Page-/Anchor-IDs erzeugen.

---

### 24. Irrelevant

Eine Work Unit darf explizit `no_relevant_evidence` ergeben. Dieser Status zählt als verarbeitet, nicht als Failure.

---

### 25. Failure

Parser-/Model-/Storagefehler werden als Failure gezählt und senken Coverage.

---

## Teil VII – Hierarchische Synthese

### 26. Cluster

Partial Findings werden thematisch beziehungsweise nach Claims/Entities gruppiert.

---

### 27. Level 1

Cluster werden in begrenzten Contextwindows synthetisiert.

---

### 28. Higher Levels

Bei Bedarf folgen weitere Reduce-Ebenen.

---

### 29. Backlinks

Jede Synthese behält Referenzen auf ihre Input Partial Findings und letztlich SourceAnchors.

---

### 30. No Summary Collapse

Eine höhere Zusammenfassung darf Widersprüche nicht allein aus Platzgründen als gelöst darstellen.

---

## Teil VIII – Contradiction Matrix

### 31. Contradiction Detection

Research vergleicht relevante Claims gezielt auf Konflikte.

---

### 32. Source Cluster

Mehrere Artikel, die denselben Ursprung abschreiben, dürfen nicht automatisch als viele unabhängige Belege gezählt werden.

---

### 33. Attribution

Meinungen werden getrennt von extern überprüfbaren Sachbehauptungen behandelt.

---

### 34. Temporal

Zeitlich unterschiedliche Zustände werden vor Widerspruchsanalyse normalisiert.

---

## Teil IX – Coverage

### 35. Counters

Mindestens:

```text
candidate_total
processed_count
successful_count
irrelevant_count
failed_count
unavailable_count
excluded_count
```

---

### 36. Coverage Ratio

Eine Coverage Ratio wird aus **eligible candidates** und erfolgreich abgeschlossenen beziehungsweise explizit irrelevanten Work Units berechnet.

Die genaue Formel wird im ResearchResult gespeichert.

---

### 37. Source Coverage

Bei mehrteiligen Sources wird zusätzlich Source-interne Coverage gespeichert.

---

### 38. No 100 Percent

100 % ist nur zulässig, wenn alle eligible Work Units einen terminalen erfolgreichen/irrelevanten Zustand besitzen.

---

### 39. Unavailable

Offline Archive, geschützte Locked Sources oder fehlende externe Seiten werden sichtbar als unavailable behandelt, nicht als irrelevant.

---

## Teil X – Checkpoints und Resume

### 40. Checkpoint Cadence

Nach jeder kleinen validierten Batch werden Fortschritt, Counters und Partial-Artifact-IDs committed.

---

### 41. Crash

Nach Crash wird ab letztem bestätigten Work Unit Set fortgesetzt.

---

### 42. No Duplicate

Idempotency verhindert doppelte Partial Findings bei Retry.

---

### 43. Model Drift

Resume prüft gepinnte ModelSignature/Pipeline. Keine stille Mischverarbeitung.

---

### 44. Resource Pause

Resource Manager darf Research jederzeit pausieren; Scope und Snapshot bleiben stabil.

---

## Teil XI – External Research

### 45. External Access Authorization

Web Discovery erfolgt nur, wenn der ResearchScope gültige External-Access-Autorisierung besitzt.

---

### 46. Capture before Analysis

Wichtige externe Seiten werden als Source Snapshot aufgenommen, bevor ihre Inhalte in langfristige Research-Provenienz eingehen.

---

### 47. Privacy Route

Der ExternalAccessGateway erzwingt die konfigurierte Privacy-/Anonymisierungsschicht und Fail-Closed.

---

### 48. Dynamic Web

Nicht mehr erreichbare oder veränderte Webseiten werden als solche markiert. ATHENA erfindet keinen historischen Snapshot.

---

## Teil XII – Research Result

### 49. Result Entity

Ein ResearchResult ist zunächst ein versioniertes Processing Artifact beziehungsweise eine Interpretation. Es wird nicht automatisch vollständig zu kanonischem Knowledge.

---

### 50. Sections

Finales Ergebnis enthält mindestens:

- Scope;
- Snapshot;
- Method;
- Findings;
- Contradictions;
- Uncertainty;
- Coverage;
- Failed/Unavailable Areas;
- Evidence references.

---

### 51. Knowledge Promotion

Aus ResearchResult können Benutzer oder Primärmodell anschließend KnowledgeUnits/Claims erzeugen. Diese erhalten explizite Provenienz auf den ResearchResult und dessen Sources.

---

### 52. No Hidden Failure

Failed Work Units werden im Ergebnis nicht verschwiegen, wenn sie die Vollständigkeit beeinflussen.

---

## Teil XIII – Research Modes

### 53. Local Exhaustive

Nur lokale ATHENA-Daten.

---

### 54. Scoped Project Research

Nur ausgewählte Projekte/Sources.

---

### 55. Local plus Web

Lokaler Snapshot plus externe aktuelle Quellen.

---

### 56. Historical Backfill Research

Recherche über definierte historische Zeiträume, etwa für News-Backfill.

---

### 57. Delta Research

Verarbeitet nur Daten, die seit einem früheren Snapshot hinzugekommen sind.

---

## Teil XIV – Performance

### 58. Backpressure

Discovery darf nicht Millionen Work Units schneller erzeugen, als Queue/Storage sie handhaben können.

---

### 59. Batching

Work Units werden nach Source/Model/Resourceprofil sinnvoll gebatcht.

---

### 60. Priority

Direkte Benutzerinteraktion bleibt höher priorisiert als nichtkritisches Research.

---

### 61. Intermediate Storage

Partial Findings werden strukturiert und kompakt gespeichert; große redundante Prompt-/Outputkopien werden vermieden.

---

## Teil XV – UX

### 62. Progress

UI zeigt:

- Discovery;
- Candidate Count;
- Processed;
- Coverage;
- Failures;
- Current Stage;
- ETA nur wenn seriös schätzbar.

---

### 63. Pause

Benutzer kann pausieren und später fortsetzen.

---

### 64. Cancel

Cancel erhält bestätigte Intermediate Results, erzeugt aber kein fälschlich „vollständiges“ Final Result.

---

### 65. Partial Result

Auf Wunsch kann ein abgebrochener Researchjob einen klar als partial gekennzeichneten Bericht erzeugen.

---

## Teil XVI – Tests

### 66. Snapshot Test

Neue Sources nach Jobstart dürfen nicht still in den Scope gelangen.

---

### 67. 100 Percent Test

Eine Work Unit künstlich failen lassen. Ergebnis darf keine 100-%-Coverage anzeigen.

---

### 68. Resume Test

Job nach 60 % hart beenden. Nach Neustart muss er ohne doppelte Findings fortsetzen.

---

### 69. Model Drift Test

Primärmodell zwischen Pause/Resume wechseln. Job muss Drift erkennen.

---

### 70. Large Archive Test

CandidateSet weit größer als Modellkontext. Kein Einzelcall überschreitet Budget.

---

### 71. Contradiction Test

Zwei gegenteilige Quellen müssen im finalen Bericht beide sichtbar bleiben.

---

### 72. Unavailable NAS Test

Teil des Scopes offline: Coverage zeigt unavailable statt irrelevant.

---

### 73. External Capture Test

Webquelle muss als Source Snapshot/Provenienz existieren, bevor sie als dauerhafte Evidenz genutzt wird.

---

### 74. Cancel Test

Cancel während Reduce. Confirmed Partial Results bleiben, Finalresult wird nicht als complete markiert.

---

### 75. Delta Test

Nach abgeschlossenem Snapshot neue Sources importieren. Delta Research verarbeitet nur neue relevante Daten.

---

### 76. Abschluss

Exhaustive Research ist bestanden, wenn ATHENA sehr große Datenräume chunkweise, resumierbar und mit messbarer Coverage untersuchen kann, ohne Kontextlimits oder stille Vollständigkeitsbehauptungen.

---

## Nächster Schritt

**Beta Kapitel 12 – Job-System, Queue und Scheduler**.
