# ATHENA Beta Specification v0.1 – Kapitel 06

## Personal Memory

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)
**Knowledge:** [Beta Kapitel 05](05_Wissenseinheiten_Claims_und_Wissensgraph.md)

---

## Teil I – Auftrag

### 1. Ziel

Personal Memory speichert langfristige Regeln darüber, **wie ATHENA mit dem Benutzer arbeiten soll**.

Es speichert nicht einfach alles Persönliche und ist kein Ersatz für Knowledge.

---

### 2. Domain-Grenze

Knowledge beantwortet:

```text
Was weiß der Benutzer?
Woran arbeitet er?
Welche Entscheidungen/Ideen/Ziele existieren?
```

Personal Memory beantwortet:

```text
Wie soll ATHENA antworten und arbeiten?
Welche dauerhaften Präferenzen gelten?
```

---

### 3. Benutzerhoheit

Der Benutzer kann jeden Personal-Memory-Eintrag:

- ansehen;
- bearbeiten;
- bestätigen;
- deaktivieren;
- löschen;
- auf einen Scope begrenzen.

Explizite Benutzeränderungen besitzen Vorrang vor automatischen Inferenzvorschlägen.

---

## Teil II – Memory-Arten

### 4. Response Style

Beispiele:

- bevorzugte Sprache;
- gewünschte Detailtiefe;
- Markdown-Präferenz;
- Tabellenpräferenz;
- direkte versus ausführliche Erklärungen.

Diese Einträge beeinflussen Darstellung, nicht den Faktenbestand.

---

### 5. Workflow Preference

Beispiele:

- bevorzugter Exportpfad;
- gewünschter Arbeitsablauf;
- bevorzugtes Tool für bestimmte Aufgaben;
- Standardoptionen eines Projekts.

---

### 6. Model Preference

Beispiele:

- bevorzugtes Primärmodell;
- bevorzugte lokale Provider;
- Priorität Qualität versus Geschwindigkeit.

Dies ist Konfiguration der Zusammenarbeit, kein kanonischer Sachverhalt.

---

### 7. Recurring Setting

Wiederkehrende Einstellungen können in Memory liegen, wenn sie personenspezifische Arbeitspräferenz darstellen. Rein technische globale Systemparameter bleiben Configuration.

---

### 8. Project-scoped Memory

Eine Präferenz kann auf ein Project referenzieren:

```text
Für Projekt ATHENA:
technische Antworten ausführlich.
```

Der Projektinhalt selbst bleibt Knowledge.

---

## Teil III – Erzeugung

### 9. Explicit User

Explizite Formulierungen wie:

```text
Merke dir, dass ...
Ab jetzt bitte immer ...
Für dieses Projekt möchte ich ...
```

dürfen einen direkten Memory-Write auslösen.

---

### 10. Model Inferred

Das Primärmodell darf aus wiederholten Interaktionen einen Memory-Vorschlag ableiten, wenn der entsprechende Learning Mode aktiviert ist.

---

### 11. Keine Infrastruktur-Inferenz

Embedding-, OCR-, STT- oder technische Klassifikationsmodelle erzeugen keine Personal-Memory-Entscheidungen.

---

### 12. Inference Threshold

Eine einzelne zufällige Formulierung darf nicht automatisch zur dauerhaften Präferenz werden.

Automatische Memory-Erkennung berücksichtigt:

- Wiederholung;
- Explizitheit;
- Stabilität über Zeit;
- Konflikte;
- Scope.

---

### 13. Sensitive Gate

Sensible persönliche Informationen werden nicht automatisch als Personal Memory gespeichert.

Ein dauerhafter sensibler Eintrag benötigt eine explizite Benutzerentscheidung beziehungsweise einen ausdrücklich freigegebenen Workflow.

---

## Teil IV – Scope und Priorität

### 14. Scope-Hierarchie

Priorität:

```text
explizite aktuelle Benutzeranweisung
>
spezifischer Project/Workflow Memory
>
globaler Memory
>
Default-Konfiguration
```

---

### 15. Current-turn Override

Eine aktuelle Anweisung wie:

```text
Diesmal bitte sehr ausführlich.
```

ändert nicht automatisch den globalen Memory.

---

### 16. Scope Conflict

Widersprechen globaler und projektspezifischer Memory einander, gewinnt der spezifischere Scope.

---

### 17. Zeitliche Gültigkeit

Memory kann optional `valid_from`, `valid_to` oder `last_confirmed_at` besitzen. Alte Präferenzen können als reviewbedürftig markiert werden, ohne automatisch gelöscht zu werden.

---

## Teil V – Sensitivität und Schutz

### 18. Sensitivity Levels

Mindestens:

```text
normal
sensitive
protected
```

`protected` verwendet den Protected-Content-Mechanismus.

---

### 19. Raw Archive ist unabhängig

Eine Information kann von automatischer Personal-Memory-Aufnahme ausgeschlossen sein und trotzdem als Teil eines standardmäßig archivierten Chats im Raw Archive existieren.

Die UI erklärt diese Trennung ausdrücklich.

---

### 20. No Metadata Leak

Protected Memory darf nicht durch:

- Titel;
- Suchindex;
- UI-Preview;
- Audit Summary

im gesperrten Zustand sichtbar werden.

---

### 21. Deletion

Memory-Löschung entfernt:

- aktuelle und nach geltender Policy zu löschende Revisionen;
- Derived Search;
- Cache;
- geschützte temporäre Indizes.

DeletionMarker verhindert Restore-Resurrection.

---

## Teil VI – Kontextintegration

### 22. Memory Retrieval

Personal Memory wird als eigene Context-Quelle abgerufen, nicht mit Knowledge verschmolzen.

---

### 23. Always-on Kernpräferenzen

Eine kleine Menge stabiler globaler Preferences darf ohne semantische Suche direkt geladen werden, etwa Sprache und Antwortstil.

---

### 24. Relevant scoped Memory

Projekt- und Workflow-Memory wird anhand des aktuellen Scopes und Retrievals ergänzt.

---

### 25. Context Labeling

Im Modellkontext wird Memory eindeutig markiert:

```text
USER PREFERENCE
```

nicht:

```text
FACT ABOUT THE WORLD
```

---

### 26. Conflict Guard

Widerspricht ein Memory der aktuellen Benutzeranweisung, darf das Modell den Memory nicht bevorzugen.

---

## Teil VII – Review und UX

### 27. Memory View

Die UI bietet eine eigene Personal-Memory-Ansicht mit:

- Inhalt;
- Art;
- Scope;
- Herkunft;
- Erzeugungsart;
- Sensitivität;
- letzter Bestätigung;
- Revisionen.

---

### 28. Why is this remembered

Für jeden Eintrag kann ATHENA erklären:

- explizit vom Benutzer gespeichert;
- aus wiederholten Interaktionen vorgeschlagen;
- aus Import übernommen;
- wann zuletzt geändert.

---

### 29. Review Queue

Unsichere automatisch gelernte Präferenzen können in eine Review Queue gelangen, statt sofort kanonisch zu werden.

---

### 30. Bulk Reset

Der Benutzer kann Personal Memory vollständig zurücksetzen, ohne Knowledge oder Raw Archive zu löschen.

---

### 31. Export

Memory kann getrennt exportiert werden. Geschützte Einträge bleiben geschützt.

---

## Teil VIII – Konflikte und Versionierung

### 32. Revision

Jede semantische Memory-Änderung erzeugt eine neue Revision derselben `memory_id`, solange dieselbe Präferenzidentität fortbesteht.

---

### 33. Neue Präferenz

Eine unabhängige neue Präferenz erhält eine neue `memory_id`.

---

### 34. Opposite Preference

Wenn sich eine Präferenz bewusst umkehrt, wird normalerweise dieselbe Memory-Entität revisioniert, damit die Änderung historisch nachvollziehbar bleibt.

---

### 35. Inferred versus Explicit

Eine neue automatische Inferenz darf eine explizite Benutzerrevision nicht stillschweigend überschreiben.

---

### 36. Ambiguität

Ist unklar, ob zwei Präferenzen dieselbe Identität besitzen, erzeugt ATHENA lieber einen Review-Konflikt als einen zerstörerischen Merge.

---

## Teil IX – Automatisches Lernen

### 37. Learning Mode Global

Der Benutzer kann automatisches Personal-Memory-Lernen global:

```text
off
suggest
auto_non_sensitive
```

setzen.

---

### 38. Default

v1-Default:

```text
suggest
```

ATHENA darf offensichtliche nicht sensible Präferenzen vorschlagen, statt sie unsichtbar dauerhaft einzutragen.

---

### 39. Auto Non Sensitive

Bei `auto_non_sensitive` dürfen klar wiederkehrende nicht sensible Arbeitspräferenzen automatisch versioniert werden. Jede automatische Änderung bleibt sichtbar und rückgängig machbar.

---

### 40. Never Auto Sensitive

Unabhängig vom allgemeinen Learning Mode werden sensible persönliche Daten nicht ohne explizite Freigabe langfristig gespeichert.

---

### 41. Learning Feedback

Wenn der Benutzer einen Memory-Vorschlag ablehnt, kann ATHENA diese Ablehnung technisch berücksichtigen, ohne den abgelehnten sensiblen Inhalt selbst dauerhaft aufzubewahren.

---

## Teil X – Tests

### 42. Domain Test

Versuch, kompletten Projektinhalt als Memory zu speichern. Domain Validator muss dies als Knowledge statt Personal Memory behandeln.

---

### 43. Explicit Save Test

Benutzer sagt „Merke dir X“. Eintrag entsteht mit `actor=user` und ohne ModelSignature.

---

### 44. Inference Test

Primärmodell schlägt Präferenz vor. Provenienz enthält ModelSignature; im Defaultmodus wird zunächst Review verlangt.

---

### 45. Sensitive Test

Automatisch erkannte sensible Information darf nicht ohne explizite Freigabe kanonisch im Personal Memory landen.

---

### 46. Scope Test

Global „kurz antworten“, Projekt „ausführlich antworten“. Im Projekt muss die projektspezifische Präferenz gewinnen.

---

### 47. Current Instruction Test

Current-turn „ausführlich“ muss globalen „kurz“-Memory für diese Antwort übersteuern, ohne ihn zu ändern.

---

### 48. Delete Test

Memory löschen und altes Backup restoren. DeletionMarker verhindert Wiederbelebung.

---

### 49. Protected Lock Test

Protected Memory sperren. Kein Klartext in persistentem FTS/HNSW oder UI-Metadaten.

---

### 50. Reset Test

Kompletten Personal Memory resetten. Knowledge, Raw Archive, Projects und Sources bleiben unverändert.

---

### 51. Abschluss

Personal Memory ist bestanden, wenn ATHENA langfristig persönlicher arbeiten kann, ohne persönliche Präferenzen mit Faktenwissen zu vermischen oder dem Benutzer die Kontrolle über das Erinnern zu entziehen.

---

## Nächster Schritt

**Beta Kapitel 07 – Provenienz, Audit und Versionierung**.
