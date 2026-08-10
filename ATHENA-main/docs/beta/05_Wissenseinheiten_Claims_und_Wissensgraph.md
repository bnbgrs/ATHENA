# ATHENA Beta Specification v0.1 – Kapitel 05

## Wissenseinheiten, Claims und Wissensgraph

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Import:** [Beta Kapitel 04](04_Quellen_Roharchiv_und_Import-Pipeline.md)

---

## Teil I – Wissensmodell

### 1. Ziel

Dieses Kapitel definiert, wie ATHENA aus Quellen, Benutzerentscheidungen und Primärmodellinterpretationen ein langfristig nutzbares Knowledge-System bildet.

Es konkretisiert:

- KnowledgeUnits;
- Claims;
- Interpretations;
- Relationships;
- Projects;
- Concept Notes;
- Widersprüche;
- zeitliche Gültigkeit;
- Merge/Split;
- Wissenslebenszyklus;
- semantische Schreibworkflows.

---

### 2. Semantische Autorität

Nur Benutzer und aktives Primärmodell dürfen semantische Änderungen am kanonischen Knowledge veranlassen. Automatische Wissensextraktion ist eine Aufgabe des Primärmodells; der Benutzer kann Wissen jederzeit direkt erstellen oder korrigieren.

---

### 3. Knowledge ist nicht Raw Archive

Knowledge enthält semantisch organisierte Einheiten. Raw Archive enthält Originalquellen.

Beide bleiben über Provenienz verbunden, aber eine Source wird nicht dadurch zur KnowledgeUnit, dass sie importiert wurde.

---

### 4. Knowledge ist nicht Personal Memory

Projektinhalte, Entscheidungen, Fakten, Ideen, Ziele und Erfahrungen sind Knowledge. Arbeits- und Antwortpräferenzen sind Personal Memory.

---

### 5. Atomarität

KnowledgeUnits sollen klein genug sein, um einzeln:

- referenziert;
- versioniert;
- widersprochen;
- zeitlich begrenzt;
- projektbezogen;
- abgerufen

werden zu können.

---

## Teil II – KnowledgeUnit

### 6. Erstellung

Eine KnowledgeUnit wird erzeugt durch:

- direkten Benutzerbefehl;
- bestätigte manuelle Bearbeitung;
- Primärmodell-Extraktion aus Quellen/Chats;
- kontrollierten Merge/Split;
- Import einer strukturierten ATHENA-Exportentität.

Jede Erstellung erhält Provenienz.

---

### 7. Knowledge Kind

Die in Kapitel 02 definierte Kernmenge bleibt bewusst grob:

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

Zusätzliche Typen dürfen ergänzt werden, ohne eine starre Ontologie vorauszusetzen.

---

### 8. Titel

Ein Titel ist ein menschenlesbares Retrieval-/UI-Hilfsmittel, nicht die Identität. Er darf sich über Revisionen ändern.

---

### 9. Body

Der Body enthält die kanonische menschenlesbare Darstellung der Wissenseinheit. Er darf auf Claims und Relations verweisen, aber keine technischen IDs als einzigen verständlichen Inhalt voraussetzen.

---

### 10. Temporalität

`valid_from` und `valid_to` beschreiben reale Gültigkeit. `created_at` beschreibt ATHENAs Systemzeit.

Beispiel:

```text
created_at: 2026
valid_from: 2023
valid_to: 2025
```

---

### 11. Archivstatus

`archived` reduziert Aktivität/Priorität, löscht aber keine Wissenseinheit und keine Beziehungen.

---

## Teil III – Claims

### 12. Warum Claims

Claims erlauben feinere Evidenz- und Widerspruchsmodellierung als ein großer Wissensabsatz.

Eine KnowledgeUnit kann mehrere Claims bündeln, ohne dass jeder Claim eine eigene UI-Notiz werden muss.

---

### 13. Claim als Aussage

Der natürliche `statement` bleibt maßgeblich. Strukturierte Felder wie Subject/Predicate/Object unterstützen Graph und Filter, ersetzen aber keine natürliche Aussage.

---

### 14. Claim-Arten

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

### 15. Attributed Opinion

Meinungen werden ihrer Quelle zugeschrieben:

```text
Quelle A bewertet X als problematisch.
```

nicht:

```text
X ist problematisch.
```

sofern letzteres nur eine Quellmeinung wäre.

---

### 16. User Statement

Eine Aussage des Benutzers kann als `user_statement` gespeichert werden, ohne automatisch als extern überprüfte Tatsache klassifiziert zu werden.

---

### 17. Epistemic Status

Statuswerte aus Kapitel 02 bleiben versionierbar:

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

---

### 18. Keine Wahrheit als Boolean

ATHENA reduziert externe Realität nicht auf ein einziges `true/false`-Feld. Evidenzlage, Attribution, Zeit und Widerspruch bleiben explizit.

---

## Teil IV – Evidenz

### 19. ClaimEvidence

Evidenzlinks zeigen bevorzugt auf stabile SourceAnchors beziehungsweise ChatMessage-Revisionen.

---

### 20. Supports

`supports` bedeutet: Die referenzierte Quelle liefert Evidenz, die mit dem Claim vereinbar ist. Es bedeutet nicht, dass ATHENA dadurch absolute Wahrheit garantiert.

---

### 21. Contradicts

`contradicts` erhält gegenteilige Evidenz explizit. ATHENA löscht den ursprünglichen Claim nicht automatisch.

---

### 22. Mentions

`mentions` ist schwächer als `supports`. Eine Quelle kann eine Behauptung erwähnen, ohne sie selbst zu belegen.

---

### 23. Evidence Weight

Technische Source-Qualitäts- oder Evidenzgewichte dürfen später in Retrieval/Research verwendet werden. Sie müssen nachvollziehbar und getrennt vom Quellinhalt gespeichert werden.

---

### 24. Evidenzänderung

Wird eine Source gelöscht, verschwindet der Claim nicht automatisch. Seine Evidenzlage wird neu bewertet beziehungsweise als fehlend markiert.

---

## Teil V – Interpretations

### 25. Interpretation versus Claim

Eine Interpretation beschreibt eine Deutung oder Synthese. Ein Claim ist eine konkrete behauptbare Aussage.

Beispiel:

```text
Interpretation:
Die Quellenlage deutet auf einen Strategiewechsel hin.

Claims:
Quelle A meldet X.
Quelle B meldet Y.
```

---

### 26. Mehrere Interpretationen

Mehrere Modelle oder Benutzerinterpretationen dürfen koexistieren. Keine neue Modellversion überschreibt historische Interpretation automatisch.

---

### 27. Benutzerinterpretation

Eine vom Benutzer formulierte Interpretation benötigt keine ModelSignature.

---

### 28. Model Interpretation

Eine modellbasierte Interpretation verweist auf ModelSignature, ProcessingRun, Input-Revisionen und Prompt/Pipeline-Version.

---

### 29. Promotion zu Knowledge

Eine Interpretation wird nicht allein durch Existenz kanonisches Wissen. Wenn daraus KnowledgeUnits/Claims entstehen, geschieht dies über einen separaten semantischen Commit.

---

## Teil VI – Beziehungen und Graph

### 30. Graphmodell

ATHENAs Wissensgraph ist logisch ein Property-Graph über stabile Entitäten, physisch in v1 jedoch relational gespeichert.

---

### 31. Gerichtete Kanten

Standardmäßig sind Beziehungen gerichtet:

```text
source_entity
relation_type
target_entity
```

---

### 32. Symmetrische Typen

Für symmetrische Typen wie `related_to` erzwingt der Core eine kanonische Darstellung beziehungsweise behandelt beide Richtungen logisch gleich, statt zufällige Doppelkanten zu erzeugen.

---

### 33. Relationstyp-Registry

Relationstypen werden in einer versionierten Registry definiert mit:

- Name;
- Richtung;
- erlaubten Domain-Kombinationen;
- optionaler inverse Relation;
- Semantik;
- Deprecation-Status.

---

### 34. Keine automatische Ontologieexplosion

Das Primärmodell darf nicht für jede Formulierung einen neuen Relationstyp erfinden. Unbekannte Beziehungen fallen zunächst auf `related_to` oder einen kontrollierten `other`-Typ zurück und können später kuratiert werden.

---

### 35. Relation Provenance

Jede automatisch erzeugte semantische Relation hat Provenienz und bei Modellbeteiligung eine ModelSignature.

---

### 36. Graph traversal

Graphtraversal ist Retrievaltechnik. Ein Traversal darf nicht allein dadurch neue kanonische Beziehungen erzeugen.

---

### 37. Same As

`same_as` ist stark und wird nur erzeugt, wenn semantische Identität hinreichend begründet ist. Stringähnlichkeit allein reicht nicht.

---

### 38. Different From

`different_from` kann explizit verhindern, dass ähnlich benannte Entitäten später versehentlich gemerged werden.

---

## Teil VII – Projekte und Concept Notes

### 39. Project

Project ist eine Knowledge-Entität, die laufende Vorhaben strukturiert. Der Projektname ist nicht seine ID.

---

### 40. Project Membership

Zuordnung erfolgt über `belongs_to_project` oder eine äquivalente relationale Verknüpfung. Eine KnowledgeUnit darf mehreren Projekten zugeordnet sein.

---

### 41. Concept Note

Concept Notes sind kuratierte Synthesen für Menschen. Sie dürfen:

- mehrere Claims;
- Quellen;
- Entscheidungen;
- Beziehungen;
- offene Fragen

zusammenführen.

---

### 42. Concept Note Provenance

Automatisch erzeugte Concept Notes müssen die verwendeten Knowledge-/Source-Revisionen festhalten. Manuelle Änderungen erhalten User-Provenienz.

---

### 43. Concept Note Aktualisierung

Eine Concept Note wird nicht bei jeder neuen Quelle blind neu geschrieben. Relevante Änderungen erzeugen einen Update-Vorschlag oder einen definierten automatischen, versionierten Workflow.

---

## Teil VIII – Wissensextraktion

### 44. Extraction Contract

Der Knowledge Extraction Service liefert strukturierte **Vorschläge**, mindestens:

- proposed KnowledgeUnits;
- proposed Claims;
- proposed Relations;
- Source/Evidence refs;
- Confidence/uncertainty;
- Merge candidates.

Der Core validiert vor Persistenz.

---

### 45. Kein direkter Model-DB-Zugriff

Das Primärmodell erhält keine DB-Connection und keine SQL-Schreibrechte.

---

### 46. Extraction Scope

Bei Chat- oder Dokumentverarbeitung sieht das Primärmodell nur den für die Aufgabe aufgebauten Kontext, nicht automatisch das gesamte Archiv.

---

### 47. Source Faithfulness

Extrahierte Claims müssen auf die tatsächlichen Quellen zurückführbar sein. Das Modell darf keine SourceAnchor-ID erfinden; Anchors werden vom Core aus tatsächlich vorhandenen Bereichen gebildet.

---

### 48. Unsicherheit

Ist eine Aussage nur wahrscheinlich oder unklar, wird dies im Claim/Interpretation-Status ausgedrückt, nicht durch erzwungene Sicherheit.

---

### 49. Keine Topic-Zensur

Inhaltsart allein ist kein Grund, eine technisch zulässige Source nicht zu extrahieren. Modellrefusals führen zu dokumentiertem Processing Failure, nicht zur Source-Löschung.

---

## Teil IX – Merge, Split und Korrektur

### 50. Merge Candidate

Ähnlichkeitsalgorithmen dürfen Merge-Kandidaten vorschlagen. Der eigentliche semantische Merge wird durch Benutzer oder Primärmodell veranlasst.

---

### 51. Merge

Bei Merge bleiben ursprüngliche IDs als superseded historisch erhalten. Die resultierende Einheit erhält entweder eine der bestehenden Identitäten, wenn die semantische Kontinuität klar ist, oder eine neue ID.

---

### 52. Split

Split erzeugt neue Entitäten für neu selbstständig adressierbare Wissensobjekte. Die alte Einheit wird superseded beziehungsweise in geeigneter Form erhalten.

---

### 53. Correction

Korrektur derselben Identität erzeugt eine neue Revision.

---

### 54. Reclassification

Ändert sich nur `knowledge_kind`, ist dies eine Revision, nicht automatisch eine neue Entität.

---

### 55. User Override

Eine explizite Benutzerkorrektur darf nicht durch spätere automatische Extraktion ohne neue Evidenz stillschweigend rückgängig gemacht werden.

---

## Teil X – Widersprüche

### 56. Contradiction Detection

ATHENA darf potenzielle Widersprüche automatisch finden. Das Ergebnis ist zunächst ein Kandidat.

---

### 57. Contradiction Record

Ein bestätigter Widerspruch wird durch Claims und `contradicts`-Relations ausgedrückt. Optional kann eine Interpretation erklären, worin der Konflikt besteht.

---

### 58. Zeitliche Nicht-Widersprüche

Aussagen können aufgrund unterschiedlicher Gültigkeitszeiträume scheinbar widersprüchlich sein:

```text
A arbeitet 2024 bei X.
A arbeitet 2026 bei Y.
```

Temporalität wird vor Contradiction-Markierung berücksichtigt.

---

### 59. Attribution

Unterschiedliche Meinungen verschiedener Quellen sind nicht automatisch logische Widersprüche über einen objektiven Sachverhalt.

---

### 60. Resolution

Wird ein Widerspruch später aufgelöst, bleiben historische Claims erhalten. Status/Interpretation wird revisioniert.

---

## Teil XI – Lifecycle und Wartung

### 61. Active und Archived

Aktiv/archiviert ist primär Retrieval- und Wartungspriorität. Der Inhalt bleibt kanonisch erhalten.

---

### 62. Superseded

`superseded` bedeutet, dass eine neuere Einheit/Revision die bevorzugte Darstellung übernimmt. Historische Referenzen bleiben gültig.

---

### 63. Stale Knowledge

Zeitabhängiges Wissen kann als möglicherweise veraltet markiert werden, wenn Gültigkeit oder Quellenalter dies nahelegt. `stale` ist ein Wartungssignal, keine automatische Falschaussage.

---

### 64. Revalidation Job

Für wichtige zeitabhängige Claims können Revalidation Jobs erzeugt werden. Sie dürfen ohne neue Evidenz keine alten Claims löschen.

---

### 65. Orphan Knowledge

Knowledge ohne Source ist zulässig, etwa direkte Benutzerentscheidungen. Provenienz macht sichtbar, dass keine externe Source zugrunde liegt.

---

## Teil XII – Tests

### 66. Atomic Knowledge Test

Eine KnowledgeUnit mit Claim, Provenienz, Relation und Audit wird in einem Commit geschrieben. Künstlicher Fehler muss vollständigen Rollback erzeugen.

---

### 67. User Edit Test

Direkte Benutzerkorrektur erzeugt neue Revision mit `model_signature_id=null`.

---

### 68. Model Extraction Test

Automatische Extraktion ohne ModelSignature beziehungsweise ProcessingRun wird zurückgewiesen.

---

### 69. Contradiction Test

Zwei widersprüchliche Claims aus verschiedenen Sources bleiben parallel erhalten und sind gegenseitig verknüpft.

---

### 70. Temporal Test

Claims mit nicht überlappenden Gültigkeitszeiträumen dürfen nicht fälschlich als gleicher zeitlicher Widerspruch behandelt werden.

---

### 71. Merge Test

Merge zweier Units: keine alte ID verschwindet aus Historie; Provenienz zeigt den Merge.

---

### 72. Split Test

Split einer Unit erzeugt neue IDs, Beziehungen und nachvollziehbare Ableitung.

---

### 73. Source Delete Test

Source löschen: Knowledge bleibt, soweit nicht mitgelöscht; Evidence Link wird entsprechend aktualisiert/gebrochen dokumentiert.

---

### 74. Reinterpretation Test

Neues Primärmodell erzeugt neue Interpretation ohne automatische Umschreibung alter Knowledge.

---

### 75. Graph Integrity Test

Alle Relationship-Ziele müssen existieren oder einen kontrollierten Tombstone-Zustand besitzen.

---

### 76. Abschluss

Das Knowledge-System ist bestanden, wenn ATHENA Wissen über Jahre ändern, widersprechen, korrigieren, aufteilen und zusammenführen kann, ohne Herkunft, historische Identität oder Benutzerautorität zu verlieren.

---

## Nächster Schritt

**Beta Kapitel 06 – Personal Memory**.
