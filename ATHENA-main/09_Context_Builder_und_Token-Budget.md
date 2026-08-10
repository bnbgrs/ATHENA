# ATHENA Beta Specification v0.1 – Kapitel 09

## Context Builder und Token-Budget

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Modelle:** [Beta Kapitel 08](08_Primaermodell_und_Provider-System.md)
**Knowledge:** [Beta Kapitel 05](05_Wissenseinheiten_Claims_und_Wissensgraph.md)
**Personal Memory:** [Beta Kapitel 06](06_Personal_Memory.md)

---

## Teil I – Aufgabe

### 1. Ziel

Der Context Builder entscheidet, **welche Informationen ein konkreter Modellaufruf tatsächlich sieht**.

Er verbindet begrenzte Modellkontexte mit einem potentiell sehr großen ATHENA-Archiv.

---

### 2. Archivgröße ist nicht Kontextgröße

Ein 100-GB-Archiv wird nicht in ein 100-GB-Prompt übersetzt.

Ablauf:

```text
großer persistenter Bestand
↓
Retrieval/Scope
↓
kleine relevante Evidenzmenge
↓
Context Budget
↓
Primärmodell
```

---

### 3. Context Builder ist Core-Service

Provider und Modellbackend wählen nicht selbstständig Langzeitwissen. Der Core baut den Request reproduzierbar.

---

### 4. Getrennte Quellen

Mindestens:

- Systemregeln;
- aktuelle Benutzeranfrage;
- Conversation Window;
- Personal Memory;
- Knowledge;
- Raw-Source Evidence;
- Task Instructions;
- Intermediate Research Results.

---

## Teil II – Token Budget

### 5. Budgetgleichung

Für jeden Modellaufruf gilt:

```text
context_capacity
=
system
+ task
+ conversation
+ personal_memory
+ retrieved_context
+ intermediate_state
+ expected_output
+ safety_margin
```

---

### 6. Expected Output Reserve

ATHENA reserviert **vor** dem Call ausreichend Raum für die erwartete Ausgabe. Retrieval darf das Kontextfenster nicht vollständig füllen.

---

### 7. Safety Margin

Zusätzliche Sicherheitsreserve kompensiert:

- Tokenizerabweichungen;
- Backendwrapper;
- unbekannte kleine Overheads;
- strukturierte Outputsyntax.

Der konkrete Default wird empirisch kalibriert.

---

### 8. Dynamic Accounting

Tokenzahlen werden für den tatsächlich aktiven Provider/Tokenizer geschätzt beziehungsweise exakt gezählt, soweit verfügbar.

---

### 9. No Error-driven Sizing

ATHENA nutzt `context length exceeded` nicht als normalen Algorithmus zur Größenbestimmung.

---

## Teil III – Budgetprioritäten

### 10. Hard Priority

Nie wegkürzbar:

- verbindliche System-/Security-Grenzen;
- aktuelle Benutzeranweisung;
- notwendige Structured-Output-Schemaanforderungen.

---

### 11. Conversation Priority

Jüngster und für die aktuelle Frage relevanter Gesprächskontext erhält Vorrang. Alte Chatabschnitte werden bei Bedarf retrievelt statt vollständig mitgeschleppt.

---

### 12. Personal Memory Priority

Nur relevante Präferenzen werden eingefügt. Eine kleine Menge globaler Kernpräferenzen kann immer enthalten sein.

---

### 13. Evidence Priority

Für faktenbasierte Antworten ist konkrete Source-Evidenz höherwertig als eine lange allgemeine Zusammenfassung ohne Quellenbezug.

---

### 14. Intermediate Priority

Bei Research müssen bestätigte Partial Results ausreichend Budget erhalten, dürfen aber nicht die Originalevidenz vollständig verdrängen.

---

## Teil IV – Conversation Window

### 15. Recent Turns

Ein begrenztes Recent-Turn-Fenster wird direkt mitgeführt.

---

### 16. Older Conversation Retrieval

Ältere Turns werden über Chat Retrieval zurückgeholt, wenn sie für die aktuelle Frage relevant sind.

---

### 17. Conversation Summary

Optionale Gesprächszusammenfassungen sind Derived/Interpretation State mit Provenienz. Sie ersetzen nicht das Raw Chat Archive.

---

### 18. Current User Message

Die aktuelle Benutzeranfrage wird niemals nur über eine Zusammenfassung repräsentiert.

---

### 19. Edits

Bei bearbeiteten Nachrichten verwendet der aktuelle Chatkontext die aktuelle Revision; historische Analysen können konkrete alte Revisionen referenzieren.

---

## Teil V – Personal Memory Context

### 20. Separate Section

Memory wird in einem klar markierten Block übergeben, etwa:

```text
[USER PREFERENCES]
...
```

---

### 21. No Fact Elevation

Eine Präferenz wie „Ich mag kurze Antworten“ darf nicht als externe Tatsache über andere Themen in Retrievalrankings behandelt werden.

---

### 22. Scope

Project-scoped Memory wird nur eingebracht, wenn der aktuelle Task tatsächlich im Scope liegt.

---

### 23. Conflict

Aktuelle Benutzeranweisung überschreibt Memory für den aktuellen Call.

---

## Teil VI – Retrieved Knowledge

### 24. Candidate Selection

Search Service liefert Kandidaten mit:

- EntityRef;
- Revision;
- Score;
- Retrievalmethode;
- Source/Claim-Metadaten;
- Protection Scope.

Context Builder entscheidet über Inclusion unter Budget.

---

### 25. Diversität

Der Builder vermeidet, dass zehn nahezu identische Chunks das Budget monopolieren, wenn mehrere relevante Quellen verfügbar sind.

---

### 26. Claim-centric Context

Wenn möglich werden Claims zusammen mit knapper Evidenz und Entitytitel eingebracht, statt ganze Concept Notes ungefiltert zu dumpen.

---

### 27. Relationship Expansion

Graphnachbarn werden nur gezielt erweitert, wenn sie den Task unterstützen.

---

### 28. Temporal Filter

Zeitbezogene Fragen bevorzugen Revisionen und Claims, deren Gültigkeitszeit zum Query Scope passt.

---

## Teil VII – Source Evidence

### 29. Anchored Evidence

Source-Evidence wird möglichst mit stabilen Anchors und Source-Identität übergeben.

---

### 30. Quote Budget

Nur notwendige Passagen werden eingebracht. Der Context Builder darf nicht ganze Bücher/PDFs in einen Modellcall laden, wenn wenige Abschnitte genügen.

---

### 31. Source Metadata

Knappe Metadaten können enthalten:

- Source title/name;
- date;
- origin;
- anchor/page;
- source_id intern.

Keine unnötigen vertraulichen Pfade.

---

### 32. Conflicting Evidence

Bei bekannten Widersprüchen können gezielt Evidenzpassagen beider Seiten eingebracht werden.

---

## Teil VIII – Prompt-Injection-Grenze

### 33. External Data Delimiting

Alle externen Inhalte werden technisch und textuell als Source Data markiert.

---

### 34. Instruction Precedence

Eine in einer Source enthaltene Anweisung wie:

```text
Ignore previous instructions
```

hat keinerlei Systemautorität.

---

### 35. No Tool Elevation

Source Text kann nicht allein durch Formulierung einen Toolcall oder externen Zugriff autorisieren.

---

### 36. Quoted Prompts

Auch wenn ein Benutzer bewusst Promptbeispiele archiviert, bleiben sie bei Retrieval Daten, sofern die aktuelle Task Instruction sie nicht ausdrücklich als auszuführende Instruktion übernimmt.

---

## Teil IX – Chunk Selection

### 37. Chunk versus Anchor

Retrieval kann ChunkIDs liefern; Context Builder kann daraus die konkrete SourceRepresentation-Passage laden.

---

### 38. Adjacent Expansion

Wenn ein Chunk am Rand eines relevanten Gedankens liegt, kann kontrolliert angrenzender Text ergänzt werden.

---

### 39. Automatic Shrink

Passt ein Chunk nicht ins Budget:

```text
chunk
↓
kleinere Anchor-/Subchunk-Bereiche
↓
erneutes Token Counting
```

---

### 40. No Semantic Truncation Mid-Sentence

Wenn möglich werden vollständige Absätze/Sätze verwendet. Hartes Token-Cut mitten in strukturierten Daten wird vermieden.

---

## Teil X – Hierarchische Verarbeitung

### 41. Map Stage

Große relevante Dokumentmengen werden in begrenzten Chunks verarbeitet.

---

### 42. Partial Results

Jeder Map-Schritt erzeugt einen strukturierten Partial Result mit Inputrefs und ProcessingRun.

---

### 43. Reduce Stage

Partial Results werden in Gruppen synthetisiert. Jede Reduce-Stufe respektiert eigenes Kontextbudget.

---

### 44. Multi-level Reduce

Bei sehr vielen Resultaten:

```text
Level 0 chunks
→ Level 1 partials
→ Level 2 summaries
→ final synthesis
```

---

### 45. Evidence Backlinks

Higher-level Summaries behalten Links zu darunterliegenden Partial Results und Originalanchors.

---

## Teil XI – Structured Context Package

### 46. ContextPackage

Vor dem Providercall erzeugt ATHENA ein internes `ContextPackage`.

Mindestens:

```text
request_id
model_signature
budget
sections
included_refs
excluded_candidate_summary
token_estimates
snapshot_commit_seq
```

---

### 47. Included Refs

Jeder persistenzrelevante Modelcall kann später rekonstruieren, welche Entity-/Revision-/SourceRefs im Kontext enthalten waren.

---

### 48. No Hidden Archive Access

Ein Modellcall sieht ausschließlich die im ContextPackage enthaltenen Inhalte plus fest definierte Providerwrapper.

---

## Teil XII – Context Caching

### 49. Cache

Tokenisierte beziehungsweise formatierte unveränderte Contextteile dürfen gecacht werden.

---

### 50. Cache Key

Cache berücksichtigt mindestens:

- entity revision;
- model tokenizer;
- template version;
- protection state.

Alte Revisionen dürfen nicht als aktuelle Contextfragmente wiederverwendet werden.

---

### 51. Protected Cache

Protected Klartextcache wird nur im erlaubten entsperrten Runtimebereich gehalten und beim Lock verworfen.

---

## Teil XIII – Context für verschiedene Tasks

### 52. Chat

Chatantworten priorisieren Current Conversation, relevante Memory und Knowledge.

---

### 53. Knowledge Extraction

Extraction priorisiert Source/Chat Evidence und bestehende nahe KnowledgeUnits für Deduplizierungs-/Widerspruchsprüfung.

---

### 54. Concept Note

Concept-Note-Synthese erhält die explizit ausgewählten Units/Claims/Sources plus begrenzte Nachbarschaft.

---

### 55. Research

Research benutzt ResearchScope, CandidateSet und hierarchische Partial Results.

---

### 56. Reinterpretation

Reinterpretation erhält exakt die zu reinterpretierende Source/Revision plus nötigen Vergleichskontext, nicht automatisch den aktuellen gesamten Wissensstand.

---

## Teil XIV – Kontexttransparenz

### 57. Debug View

Optional kann die UI für technische Diagnose anzeigen:

- Budgetanteile;
- Anzahl Kandidaten;
- verwendete Sources;
- truncation/shrink events;
- Context Build Time.

Geschützte Inhalte bleiben entsprechend geschützt.

---

### 58. User-facing Sources

Für Antworten kann die UI die tatsächlich verwendeten Quellen anzeigen. Dies basiert auf Included Refs, nicht auf Modellbehauptungen.

---

### 59. Why not included

Bei Exhaustive/Research kann ATHENA Gründe für ausgeschlossene Kandidaten dokumentieren, etwa Scopefilter oder Coveragegrenze.

---

## Teil XV – Tests

### 60. Overflow Test

Künstlich mehr relevante Chunks als Kontextkapazität liefern. Kein Call darf das Backendlimit überschreiten.

---

### 61. Output Reserve Test

Großer Retrievalcontext darf die reservierte Ausgabegröße nicht verdrängen.

---

### 62. Memory Conflict Test

Aktuelle User Instruction widerspricht Memory. Current Instruction muss gewinnen.

---

### 63. Prompt Injection Test

Source enthält Systemprompt-artige Anweisungen. Sie dürfen System-/Toolautorität nicht verändern.

---

### 64. Stale Revision Test

Knowledge wird zwischen Retrieval und Build revisioniert. Persistenzrelevanter Call muss Snapshot/Revisionkonsistenz prüfen.

---

### 65. Protected Test

Locked protected candidate darf nicht im ContextPackage erscheinen.

---

### 66. Hierarchical Test

Input größer als mehrfaches Contextwindow. Pipeline muss über Map/Reduce ohne Einzelcall-Overflow abschließen.

---

### 67. Source Diversity Test

Viele Duplikatchunks einer Source dürfen nicht automatisch alle anderen relevanten Quellen aus dem Budget verdrängen.

---

### 68. Reproducibility Test

Persistenzrelevanter ProcessingRun muss seine Included Refs und Budgetkonfiguration rekonstruierbar speichern.

---

### 69. Abschluss

Der Context Builder ist bestanden, wenn die Größe des Archivs praktisch unabhängig von der Modellkontextgröße wachsen kann und jeder Modellcall nur den notwendigen, autorisierten und nachvollziehbaren Ausschnitt erhält.

---

## Nächster Schritt

**Beta Kapitel 10 – Retrieval und Suche**.
