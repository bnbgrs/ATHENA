# ATHENA Beta Specification v0.1 – Kapitel 10

## Retrieval und Suche

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Context:** [Beta Kapitel 09](09_Context_Builder_und_Token-Budget.md)

---

## Teil I – Ziele

### 1. Ziel

Search und Retrieval finden relevante Informationen über sehr große Bestände, ohne den gesamten Bestand an das Primärmodell zu senden.

---

### 2. Search versus Retrieval

**Search** findet Kandidaten.

**Retrieval** wählt, kombiniert und strukturiert Kandidaten für einen konkreten Task.

---

### 3. Derived State

FTS5, Embeddings und HNSW sind Derived State. Ein Rebuild verändert kein kanonisches Wissen.

---

### 4. Normal und Exhaustive

v1 besitzt zwei Modi:

```text
Normal Retrieval
Exhaustive Research
```

Dieses Kapitel definiert Normal Retrieval. Kapitel 11 definiert Exhaustive Research.

---

## Teil II – Query Understanding

### 5. SearchRequest

Ein SearchRequest enthält mindestens:

- query text;
- allowed domains;
- time filters;
- project scope;
- protection context;
- requested result types;
- limit/latency profile.

---

### 6. Query Rewrite

Das Primärmodell darf optional Retrieval Queries erweitern/umformulieren. Die Originalfrage bleibt erhalten und Rewrites werden als technische Queryvarianten dokumentiert.

---

### 7. No Rewrite Required

Einfache exakte Suchanfragen müssen ohne Primärmodell möglich sein.

---

### 8. Filters before Ranking

Harte Filter wie Protection Scope, Project und Zeitbereich werden möglichst vor dem finalen Ranking angewendet.

---

## Teil III – Lexical Search

### 9. FTS5

Unprotected Volltextsuche verwendet die in Kapitel 03 definierte separate FTS5-Datenbank.

---

### 10. Knowledge Index

`fts_knowledge` indexiert aktuelle relevante Revisionen von KnowledgeUnits, Claims und Concept Notes.

---

### 11. Archive Index

`fts_archive` indexiert SourceChunks beziehungsweise technische SourceRepresentations.

---

### 12. Memory Index

`fts_memory` bleibt logisch separat, damit Preferences nicht wie externe Fakten gerankt werden.

---

### 13. Exact Match

Exakte Phrasen und IDs können gezielt lexical priorisiert werden.

---

### 14. BM25

FTS5-BM25 beziehungsweise dessen Rankingfunktion dient als lexical score. Der Rohscore wird nur innerhalb der entsprechenden Retrievalpipeline interpretiert.

---

## Teil IV – Semantic Search

### 15. Embeddings

EmbeddingProvider erzeugt Vektoren für aktuelle unprotected Revisionen und SourceChunks.

---

### 16. Embedding Spaces

Unterschiedliche Embeddingmodelle beziehungsweise inkompatible Dimensionen werden niemals in einem HNSW-Space vermischt.

---

### 17. HNSW

HNSW liefert Approximate-Nearest-Neighbor-Kandidaten. Ein hoher Vektorscore ist Relevanzsignal, keine Wahrheitseinschätzung.

---

### 18. Reembedding

Bei Modellwechsel wird ein neuer Embedding Space gebaut. Der alte kann während Übergang weiter verfügbar bleiben.

---

### 19. Protected Semantic Search

Protected Embeddings werden im entsperrten Runtime-Kontext gehalten und nicht in normalen persistenten HNSW-Dateien gespeichert.

---

## Teil V – Graph Retrieval

### 20. Graph Neighbors

Aus initialen Kandidaten können relevante Relation-Nachbarn expandiert werden.

---

### 21. Depth

Normal Retrieval begrenzt Graphdepth. Defaultstartpunkt:

```text
1–2 Hops
```

Der konkrete Wert ist Search Configuration.

---

### 22. Relation Weight

`supports`, `contradicts`, `belongs_to_project`, `part_of` können je Task unterschiedlich gewichtet werden.

---

### 23. No Graph Explosion

Hochgradige Nodes werden begrenzt. Ein globaler `related_to`-Hub darf nicht tausende Kandidaten ungefiltert hinzufügen.

---

## Teil VI – Hybrid Retrieval

### 24. Candidate Union

Normal Retrieval bildet eine Kandidatenunion aus:

```text
lexical
+
semantic
+
graph
+
recent/active
+
explicit references
```

---

### 25. Rank Fusion

v1 verwendet als robusten Ausgangspunkt **Reciprocal Rank Fusion (RRF)** für Ranglisten aus unterschiedlichen Retrievalmethoden.

Rohscores verschiedener Systeme werden nicht naiv addiert.

---

### 26. RRF Parameter

Der RRF-Konstantenwert ist Configuration und wird durch Retrievaltests kalibriert. Er ist keine Knowledge-Invariante.

---

### 27. Explicit Ref Boost

Wenn der Benutzer ein Projekt, Dokument oder eine bekannte Entity explizit nennt, wird diese Referenz nicht durch allgemeine semantische Treffer verdrängt.

---

### 28. Recency

Zeitliche Aktualität darf taskabhängig als Feature einfließen. Alte historische Quellen dürfen bei historischen Fragen nicht allein wegen Alter abgewertet werden.

---

## Teil VII – Reranking

### 29. Reranker Stage

Nach initialer Candidate Union kann ein Reranker Top-N genauer bewerten.

---

### 30. Model-independent Fallback

Reranking muss auch ohne Primärmodell möglich bleiben, etwa über lexical/vector/graph features.

---

### 31. Primary Model Reranking

Optional darf das Primärmodell für besonders komplexe Fragen Kandidaten semantisch reranken. Dies ist ein Model ProcessingRun, aber erzeugt kein Knowledge.

---

### 32. Evidence Diversity

Reranking berücksichtigt Diversität über Sources, damit eine einzige repetitive Quelle nicht alles dominiert.

---

## Teil VIII – CandidateSet

### 33. Persistence

Für normale kurze Searches muss nicht jeder CandidateSet dauerhaft archiviert werden.

Für wissensbildende oder reproduzierbarkeitsrelevante ProcessingRuns kann CandidateSet persistiert werden.

---

### 34. Fields

Kandidaten behalten:

- entity/revision;
- source/chunk;
- retrieval method;
- rank;
- score;
- selection reason.

---

### 35. Snapshot

Persistenzrelevante CandidateSets referenzieren die gültige `snapshot_commit_seq`.

---

## Teil IX – Domain Search

### 36. Knowledge

Knowledge Search bevorzugt aktuelle Revisionen und kann archived Knowledge einschließen.

---

### 37. Raw Archive

Archive Search liefert SourceAnchors/Chunks. Originalbytes werden erst bei Bedarf geladen.

---

### 38. Personal Memory

Memory Retrieval nutzt eigenen Scope und wird nie unkontrolliert in externen Faktensuchen vermischt.

---

### 39. Chats

Chats können über Message-Index und Source/Conversation-Metadaten gefunden werden.

---

### 40. Audit

Audit Search ist eine Diagnose-/Transparenzfunktion und wird nicht automatisch als semantische Evidence für normale Antworten verwendet.

---

## Teil X – Time Search

### 41. Temporal Filter

Queries können nach `valid_time`, Source time und system time filtern.

---

### 42. As-of Query

Eine Frage wie:

```text
Was wusste ATHENA am 1.1.2025?
```

benötigt historische Revisionen und eine definierte `commit_seq`-Grenze, nicht nur aktuelle Heads.

Zusätzlich wird der zu diesem Commit gültige Zustand aus `entity_state_history` verwendet. Damit werden insbesondere `lifecycle_state` und `protection_scope_id` nicht aus dem heutigen materialisierten `entity_registry`-Wert rückprojiziert. Eine As-of-Abfrage darf deshalb weder heute archivierte Inhalte fälschlich als damals archiviert behandeln noch historische Protection-Zustände verlieren.

---

### 43. Current Query

Aktuelle Fragen bevorzugen aktuelle gültige Claims, behalten aber relevante historische Evidenz für Veränderungen.

---

## Teil XI – Search Freshness

### 44. Watermarks

FTS- und Vector-Watermarks werden gegen aktuelle `commit_seq` geprüft.

---

### 45. Near-real-time Gap

Wenn ein User direkt nach einem Write sucht und Derived State noch hinterherhinkt, ergänzt ATHENA die letzten CommitChanges direkt aus autoritativen Daten.

---

### 46. Rebuild

Während vollständigem Rebuild bleibt Searchstatus sichtbar:

```text
lexical rebuilding
vector unavailable/rebuilding
```

---

### 47. No False Complete

ATHENA behauptet keine vollständige Suche, wenn relevante Indexbereiche fehlen.

---

## Teil XII – Ranking Features

### 48. Core Features

Mögliche Features:

- lexical rank;
- vector rank;
- explicit entity match;
- graph distance;
- project match;
- time match;
- source diversity;
- lifecycle state;
- source quality metadata;
- user-selected scope.

---

### 49. Epistemic Status

`contradicted` oder `uncertain` darf Retrieval nicht automatisch verstecken. Status wird als Kontextsignal mitgegeben.

---

### 50. User Corrections

Explizit aktuelle Benutzerrevisionen sollen bei derselben Entity bevorzugt werden, ohne historische Revisionen zu löschen.

---

### 51. No Popularity Truth

Häufige Wiederholung einer Behauptung macht sie nicht automatisch wahr. Rankinghäufigkeit und Evidenzqualität bleiben getrennt.

---

## Teil XIII – Search API

### 52. Search Response

Mindestens:

```text
result_id/ref
title/preview
entity type
revision
rank
retrieval methods
source anchor
protection state
```

---

### 53. Explain Score

Technische Diagnose kann die wichtigsten Rankingkomponenten zeigen. Eine pseudoexakte „Wahrheitswahrscheinlichkeit“ wird nicht dargestellt.

---

### 54. Pagination

Große Ergebnislisten verwenden Cursor/Keyset-Mechanismen, keine teuren unbounded Offsets.

---

## Teil XIV – Performance

### 55. Latency Classes

Normal Retrieval zielt auf interaktive Latenz. Teure Exhaustive-Schritte werden nicht heimlich in jede Chatfrage eingebaut.

---

### 56. Candidate Limits

Jede Retrievalstufe hat konfigurierbare Candidate Caps.

---

### 57. Caching

Query-/Embeddingcache ist revision- und providergebunden.

---

### 58. Batch Embedding

Indexing nutzt Batch Embedding entsprechend Providerkapazität und Resource Manager.

---

## Teil XV – Protected Search

### 59. Authorization first

Protected Candidates werden erst nach erfolgreichem Unlock und Authorization in die Suchpipeline aufgenommen.

---

### 60. No Metadata Leak

Locked Search darf nicht über Trefferzahl, Titel oder Score verraten, welche geschützten Inhalte existieren, außer der Benutzer hat eine bewusst gewählte Anzeigeebene aktiviert.

---

### 61. Mixed Search

Bei entsperrtem Scope können unprotected und protected Kandidaten gemeinsam gerankt werden. Protection Labels bleiben bis zum Context Builder erhalten.

---

## Teil XVI – Tests

### 62. Lexical Test

Exakte Phrase in Source muss über FTS auffindbar sein.

---

### 63. Semantic Test

Paraphrasierte Query muss relevante Embeddingkandidaten liefern, ohne lexical Match zu benötigen.

---

### 64. Hybrid Test

Lexical und semantic Treffer konkurrieren. RRF muss deterministisch reproduzierbare Fusion liefern.

---

### 65. Graph Test

Explizit verknüpfte Project/Claim-Nachbarn müssen bei geeignetem Task expandierbar sein.

---

### 66. Watermark Test

Write Commit 100, Search Watermark 99. Direkt danach Suche: neue Entity darf nicht vollständig unsichtbar bleiben.

---

### 67. Protected Test

Locked Protected Content erzeugt keinen persistenten Treffer oder Metadaten-Leak.

---

### 68. As-of Test

Historische Query muss alte Revision statt aktuellem Head liefern.

---

### 69. Rebuild Test

FTS/HNSW löschen und rebuilden. Semantische IDs/Knowledge bleiben unverändert.

---

### 70. Duplicate Diversity Test

Viele ähnliche Chunks derselben Source dürfen eine zweite hochrelevante Source nicht vollständig verdrängen.

---

### 71. No Truth Score Test

UI darf Vector/BM25 Score nicht als „95% wahr“ darstellen.

---

### 72. Abschluss

Normal Retrieval ist bestanden, wenn es interaktiv schnell, reproduzierbar genug, domänenbewusst, schutzkonform und unabhängig von der Gesamtarchivgröße relevante Evidenz findet.

---

## Nächster Schritt

**Beta Kapitel 11 – Exhaustive Research**.
