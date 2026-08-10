# ATHENA Beta Specification v0.1 – Kapitel 08

## Primärmodell und Provider-System

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Architektur:** [Beta Kapitel 01](01_Systemarchitektur_und_Technische_Basis.md)
**Provenienz:** [Beta Kapitel 07](07_Provenienz_Audit_und_Versionierung.md)

---

## Teil I – Rollen und Grenzen

### 1. Ziel

Dieses Kapitel definiert die konkrete Modellintegration von ATHENA v1.

Es trennt:

- Primärmodell;
- Infrastrukturmodelle;
- Provider;
- Model Sessions;
- Fähigkeiten;
- Laden/Entladen;
- Refusal/Failure;
- ModelSignature;
- Kontextübergabe;
- Streaming;
- Tool-/Structured-Output-Grenzen.

---

### 2. Ein aktives Primärmodell

Zu einem Zeitpunkt besitzt ATHENA genau **ein aktives Primärmodell** für automatisierte semantische Wissensentscheidungen.

Mehrere Modelle können installiert, registriert oder testweise verfügbar sein. Nur eines besitzt die aktive Primärmodellrolle.

---

### 3. Benutzer bleibt höchste Autorität

Das Primärmodell ist keine autonome Systeminstanz über dem Benutzer. Direkte Benutzeränderungen können ohne Modell erfolgen und haben innerhalb der festgelegten Regeln Vorrang.

---

### 4. Infrastrukturmodelle

OCR, Embeddings, STT, TTS, technische Bildvorverarbeitung und ähnliche Modelle werden über spezialisierte Provider angesprochen. Sie erhalten keine autonome semantische Wissensautorität.

---

### 5. Model Backend ist austauschbar

ATHENAs Core hängt nur von Provider-Interfaces ab. Die v1-Referenz kann ein lokales Modellbackend verwenden, ohne dass dessen API zur Identität des Knowledge-Systems wird.

---

## Teil II – PrimaryModelProvider

### 6. Interface

Der Core definiert logisch:

```text
PrimaryModelProvider
```

mit mindestens:

```text
discover_models()
get_model_info()
load_model()
unload_model()
health()
generate()
generate_structured()
estimate_context_capacity()
cancel_generation()
```

---

### 7. Keine semantische Logik im Adapter

Der Provider übersetzt Requests und Responses zwischen ATHENA und Backend. Er entscheidet nicht, welches Wissen gespeichert wird.

---

### 8. Streaming

`generate()` unterstützt token-/chunkweises Streaming für Chat-UX. Ein gestreamter Text wird erst nach erfolgreichem Abschluss als vollständige Assistant Message behandelt.

---

### 9. Structured Output

`generate_structured()` verlangt eine definierte Output-Schema-ID beziehungsweise JSON-Schema. Der Core validiert die Antwort unabhängig vom Modell.

---

### 10. Capability Discovery

Provider melden Fähigkeiten, etwa:

```text
chat
structured_output
tool_calls
vision
audio
context_length
streaming
model_load_control
```

Nicht unterstützte Fähigkeiten werden explizit angegeben.

---

### 11. Health

Health unterscheidet mindestens:

```text
unavailable
starting
ready
busy
degraded
error
```

Ein Provider-Fehler darf Raw Archive oder Knowledge nicht beschädigen.

---

## Teil III – v1-Modellbackend

### 12. Lokales Backend

v1 priorisiert ein lokales OpenAI-kompatibles Modellbackend. Der erste Adapter wird für das in Kapitel 01 festgelegte lokale Backend implementiert.

Der Adapter bleibt intern als eigener Provider gekapselt.

---

### 13. Base URL

Die Backend-Adresse ist Configuration, nicht Codekonstante.

Defaultbindungen dürfen nur auf lokale Interfaces zeigen, solange der Benutzer keine andere vertrauenswürdige Konfiguration aktiviert.

---

### 14. Model Discovery

ATHENA liest die tatsächlich verfügbaren Modelle vom Backend, statt Modellnamen fest in der UI zu hinterlegen.

---

### 15. Model Identity

Providerantworten werden in eine stabile interne Beschreibung normalisiert:

```text
provider
backend_model_id
display_name
context_capacity
capabilities
known_revision
quantization
```

Nicht gelieferte Felder bleiben unbekannt.

---

### 16. Backend Updates

Ändert ein Backend seine technische API, wird der Provider angepasst. Knowledge-, Source- und ModelSignature-IDs alter Läufe bleiben lesbar.

---

## Teil IV – Model Registry

### 17. Registry

ATHENA verwaltet eine `ModelRegistry` als Configuration-/Runtime-Schicht.

Ein Registry-Eintrag beschreibt:

- Provider;
- Modell-ID;
- Role Eligibility;
- technische Fähigkeiten;
- lokale Ressourcenanforderungen soweit gemessen;
- Benutzeralias;
- Aktivstatus.

---

### 18. Keine Modellfakten erfinden

VRAM-Bedarf, Quantisierung oder Kontextgröße werden nur gespeichert, wenn Backend, Modellmetadaten oder Messung sie zuverlässig liefern.

---

### 19. Primary Eligibility

Ein Modell kann nur als Primärmodell gewählt werden, wenn es die Mindestfähigkeiten des aktiven ATHENA-Workflows erfüllt.

---

### 20. Infrastructure Registry

InfrastructureProvider besitzen getrennte Registries. Ein Embedding-Modell wird nicht versehentlich als Primärmodell auswählbar.

---

## Teil V – Laden und Entladen

### 21. Load Ownership

ATHENA unterscheidet:

```text
loaded_by_athena
loaded_externally
unknown
```

Nur wenn ATHENA das Modell selbst geladen hat beziehungsweise der Backendvertrag dies sicher erlaubt, darf sie es automatisiert wieder entladen.

---

### 22. Manual Load

Der Benutzer kann in UI/Tray das Primärmodell laden.

---

### 23. Manual Unload

Der Benutzer kann es entladen, um VRAM freizugeben. Laufende modellabhängige Jobs wechseln in `waiting_resource` beziehungsweise werden kontrolliert pausiert.

---

### 24. Background Auto Load

Ein Hintergrundjob darf das Modell automatisch laden, wenn:

- Benutzer dies erlaubt hat;
- Ressourcenregeln erfüllt sind;
- keine höher priorisierte Interaktion beeinträchtigt wird.

---

### 25. Idle Unload

Optional kann ATHENA ein selbst geladenes Modell nach konfigurierter Idle-Zeit entladen. Der Benutzer kann dies deaktivieren.

---

### 26. Load Timeout

Laden hat einen Timeout und Health-Probe. Ein hängender Backendload blockiert nicht dauerhaft die Queue.

---

## Teil VI – Model Session

### 27. ModelSession

Jeder Generationslauf erhält eine temporäre `ModelSession` mit:

- ModelSignature;
- Request-ID;
- Context Budget;
- Cancellation Token;
- Streaming State;
- ProcessingRun falls persistent relevant.

---

### 28. Session ist kein Memory

ModelSession-Daten sind kein langfristiges Gedächtnis. Persistiert werden nur die dafür vorgesehenen Chat-, Provenance- oder Processing-Daten.

---

### 29. Conversation State

ATHENA verlässt sich nicht auf versteckten Backend-Conversation-State. Jeder relevante Request enthält den vom Context Builder definierten Kontext.

---

### 30. Stateless bevorzugt

Provider werden so verwendet, als seien sie semantisch stateless. Backend-Caches dürfen Performance verbessern, sind aber keine Source of Truth.

---

## Teil VII – ModelSignature

### 31. Erzeugungszeitpunkt

Vor einem wissensrelevanten Modelllauf wird die tatsächlich verwendete Modellkonfiguration bestimmt und eine ModelSignature referenziert.

---

### 32. Signature Hash

Gleiche normalisierte Modellkonfigurationen können denselben Signature Record verwenden.

---

### 33. Unknown

Kann der Provider die genaue Modellrevision nicht liefern, bleibt `model_revision=null`. ATHENA behauptet keine Genauigkeit, die nicht vorhanden ist.

---

### 34. Prompt Version

Prompttemplate und Pipelineversion gehören zum ProcessingRun, nicht in den freien Modellnamen.

---

### 35. Quantization

Quantisierung wird nur gespeichert, wenn sie bekannt und für Reproduzierbarkeit relevant ist.

---

## Teil VIII – Kontextübergabe

### 36. Context Builder ist Quelle

Der Provider entscheidet nicht selbst, welche Memory-/Knowledge-Daten geladen werden. Er erhält ein fertig gebautes `ModelRequest`.

---

### 37. Context Sections

Requests kennzeichnen logisch:

```text
SYSTEM POLICY
USER REQUEST
CONVERSATION
PERSONAL MEMORY
RETRIEVED KNOWLEDGE
SOURCE EVIDENCE
TASK INSTRUCTIONS
```

Externe Source-Texte werden als Daten markiert.

---

### 38. Prompt Injection Boundary

Instruktionen in Quellen werden nie automatisch zu System-/Task-Instruktionen angehoben.

---

### 39. Truncation

Provider dürfen Kontext nicht heimlich semantisch abschneiden. Wenn Backendlimits niedriger als erwartet sind, muss der Request vor dem Call neu budgetiert werden beziehungsweise fehlschlagen.

---

## Teil IX – Structured Semantic Operations

### 40. Operation Types

Primärmodelloperationen erhalten eine definierte `semantic_operation_type`, etwa:

```text
knowledge_extraction
claim_extraction
relationship_proposal
personal_memory_proposal
concept_note_synthesis
contradiction_analysis
research_synthesis
chat_response
```

---

### 41. Schemas

Für persistenzrelevante Operationen wird strukturierter Output verlangt. Freier Text darf nicht direkt als Datenbankmutation interpretiert werden.

---

### 42. Validation

Der Core prüft:

- JSON-/Schema;
- IDs;
- tatsächlich existierende References;
- SourceAnchors;
- erlaubte Enumwerte;
- Protection Scope;
- actor/model provenance.

---

### 43. Repair Loop

Ist Structured Output syntaktisch ungültig, darf ATHENA einen begrenzten Repair-Request stellen. Das fehlerhafte Rohresultat wird nicht als kanonisches Wissen gespeichert.

---

### 44. Max Repair

Repairversuche sind begrenzt. Danach gilt der ProcessingStage als failed/retryable.

---

## Teil X – Refusal und Failure

### 45. Refusal

Ein Modellrefusal wird als Verarbeitungsergebnis dokumentiert, nicht als Signal zum Löschen oder Zensieren der Source.

---

### 46. Backend Failure

Timeout, OOM, Connection Error, invalid response und Backendcrash werden technisch getrennt.

---

### 47. Fallback Model

ATHENA wechselt für **semantisch persistente** Operationen nicht heimlich auf ein anderes Primärmodell.

Ein Fallback ist nur zulässig, wenn Benutzer/Jobkonfiguration dies ausdrücklich erlaubt und Processing Drift korrekt dokumentiert wird.

---

### 48. Chat Fallback

Auch im normalen Chat wird ein Modellwechsel sichtbar. Eine Antwort darf nicht so erscheinen, als käme sie vom ausgewählten Modell, wenn tatsächlich ein anderes verwendet wurde.

---

### 49. Retry

Retries desselben Modellcalls sind idempotent bezüglich Persistenz: Erst der validierte Output erzeugt einen separaten Canonical Write.

---

## Teil XI – Cancellation und Timeouts

### 50. Cancel

Benutzer kann eine laufende Generation abbrechen. Provider versucht Backend-Cancel; falls nicht unterstützt, wird Response nach Rückkehr verworfen.

---

### 51. Partial Streaming

Partieller Text darf in der UI sichtbar sein, wird aber als `cancelled` markiert. Ob er im Raw Chat Archive bleibt, folgt Chatregeln und UI-Kennzeichnung.

---

### 52. Timeout Classes

Getrennte Timeouts für:

- Connect;
- Model Load;
- First Token;
- Total Generation;
- Structured Repair.

Werte gehören Configuration.

---

## Teil XII – Infrastructure Provider

### 53. EmbeddingProvider

Interface:

```text
embed_texts()
dimension()
model_signature()
health()
```

Embeddings erzeugen nur Derived State.

---

### 54. OCRProvider

Interface liefert Textsegmente, Seiten-/Regionanchors und technische Konfidenz.

---

### 55. SpeechToTextProvider

Liefert zeitverankerte Segmente und optionale Speakerlabels.

---

### 56. TTSProvider

TTS erzeugt Audioausgabe, aber kein kanonisches Wissen.

---

### 57. Provider Isolation

Jeder InfrastructureProvider hat eigene Failure-/Resource-Profile. Ein Ausfall degradiert nur die betroffenen Funktionen.

---

## Teil XIII – Ressourcen

### 58. Resource Requirement

Model Registry darf gemessene Ressourcenprofile speichern:

- VRAM Peak;
- RAM Peak;
- Load Time;
- Token/s.

Diese Daten sind Performance-Metadaten, keine Benutzerkenntnis.

---

### 59. GPU Contention

Resource Manager entscheidet vor Load/Generation, ob andere GPU-Last den Job warten lassen soll.

---

### 60. No Permanent Pin

Kein Modell wird allein wegen eines alten Jobs dauerhaft im VRAM gehalten.

---

## Teil XIV – Sicherheit

### 61. Provider Network Boundary

Lokale Providerzugriffe werden als interne vertrauensdefinierte Backendverbindung behandelt. Ein Remote Provider wäre eine explizite spätere Capability mit External-Access-/Privacy-Regeln.

---

### 62. Secret Handling

Provider-API-Keys, falls später vorhanden, liegen im Secrets Store und nicht im normalen ModelRegistry-JSON.

---

### 63. Model Output untrusted

Auch das Primärmodell ist kein direkter Code-/SQL-Ausführer. Outputs werden als untrusted structured proposals behandelt und validiert.

---

### 64. Tool Calls

Modell-Toolcalls werden nicht direkt an Betriebssystem oder Plugins weitergereicht. Sie durchlaufen Core Authorization und Capability Checks.

---

## Teil XV – UI

### 65. Model Manager

UI zeigt:

- verfügbares Modell;
- aktives Primärmodell;
- Provider;
- Status;
- geladen/entladen;
- bekannte Fähigkeiten;
- bekannte Ressourcenwerte.

---

### 66. Switch

Modelwechsel verlangt klare Auswahl und erzeugt ein AuditEvent. Bestehendes Knowledge wird nicht neu interpretiert.

---

### 67. Signature View

Bei einer Knowledge-Revision kann die UI auf Wunsch die verwendete ModelSignature anzeigen.

---

## Teil XVI – Tests

### 68. Provider Contract Test

Jeder Provider muss dieselbe Test-Suite für Health, Generate, Structured Output, Cancel und Fehlerzustände bestehen.

---

### 69. Stateless Test

Zwei identische unabhängige Requests dürfen nicht von verstecktem Backendchat abhängen.

---

### 70. Structured Validation Test

Modell erfindet eine `source_id`. Core muss den Output zurückweisen.

---

### 71. Refusal Test

Refusal bei kontroversem Sourceinhalt: Source bleibt intakt, ProcessingRun dokumentiert Failure.

---

### 72. Silent Fallback Test

Primärmodell fällt aus. Ohne explizite Fallbackregel darf kein anderes Modell semantisch schreiben.

---

### 73. Load Ownership Test

Extern geladenes Modell: ATHENA darf es nicht ungefragt entladen.

---

### 74. Cancel Test

Generation abbrechen. Kein unvollständiger Structured Output darf kanonisch committed werden.

---

### 75. Signature Test

Benutzerwrite ohne Modell bleibt ohne Signature; modellbasierter Write enthält korrekte Signature.

---

### 76. Context Limit Test

Backend meldet kleinere Context Capacity als Registrycache. ATHENA muss Request neu budgetieren oder sauber abbrechen, nicht still abschneiden.

---

### 77. Protected Test

Locked Protected Content darf nicht versehentlich im ModelRequest landen.

---

### 78. Abschluss

Das Provider-System ist bestanden, wenn ATHENA Modelle austauschen kann, ohne seine Wissensidentität zu verlieren, und wenn kein Modell die Core-Grenzen oder Benutzerautorität umgehen kann.

---

## Nächster Schritt

**Beta Kapitel 09 – Context Builder und Token-Budget**.
