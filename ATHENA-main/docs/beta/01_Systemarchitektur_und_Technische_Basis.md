# ATHENA Beta Specification v0.1 – Kapitel 01

## Systemarchitektur und technische Basis

**Status:** In Entwicklung – konsolidierte Fassung
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Zweck:** Technische Übersetzung der Alpha-Prinzipien in eine implementierbare v1-Grundarchitektur

---

## 1. Ziel und normative Grundlage

Dieses Kapitel übersetzt die verbindlichen Prinzipien von **ATHENA Alpha v2.0.1** in eine konkret implementierbare technische Grundarchitektur.

Alpha definiert, **was ATHENA sein soll und welche Systemgrenzen nicht verletzt werden dürfen**. Beta definiert, **wie diese Regeln technisch umgesetzt werden**.

Normative Grundlage ist die konsolidierte Alpha-Spezifikation unter [`../alpha/INDEX.md`](../alpha/INDEX.md). Für Konflikte gilt die dort festgelegte Hierarchie:

1. Alpha Kapitel 1–2: oberste Prinzipien.
2. Alpha Kapitel 3–27: normative Detailarchitektur.
3. Alpha Kapitel 28: Scope und Übergang zur Beta.
4. Alpha Kapitel 29: nicht-normative Zusammenfassung.

> **Beta darf Alpha technisch konkretisieren, aber nicht stillschweigend verändern.**

Eine technische Schwierigkeit ist kein ausreichender Grund, ein Alpha-Prinzip zu umgehen. Wenn eine Beta-Entscheidung mit Alpha kollidiert, muss die Entscheidung geändert oder der Konflikt ausdrücklich als Änderungsvorschlag an Alpha dokumentiert werden.

Dieses Kapitel legt die technische Ausgangsarchitektur fest. Das konkrete persistente Datenmodell, Tabellen, IDs und Schemas werden in **Beta Kapitel 02** definiert.

---

## 2. Referenzplattform für ATHENA v1

ATHENA v1 wird zunächst für die reale Zielumgebung des Benutzers entwickelt und optimiert.

```text
Betriebssystem:
Windows 11 x64

GPU:
AMD Radeon RX 7900 XTX
24 GB VRAM

Arbeitsspeicher:
32 GB RAM

Primäres Modellbackend:
LM Studio

Primärmodell:
vom Benutzer auswählbar und konfigurierbar

Wissensoberfläche:
ATHENA Desktop UI
+
optionale Obsidian-Integration
```

Diese Angaben sind **Beta-Referenzentscheidungen**, keine unveränderlichen Eigenschaften von ATHENA.

Die persistente Datenarchitektur, IDs, Wissenssemantik und Exportformate dürfen nicht von Windows, einer bestimmten GPU, LM Studio oder einem bestimmten Primärmodell abhängig sein.

Der Benutzer darf ein inhaltsneutraleres beziehungsweise weniger eingeschränktes lokales Primärmodell wählen. Eine bestimmte Modellfamilie oder die Bezeichnung „Heretic“ ist jedoch **keine technische Voraussetzung der Architektur**.

Ein Wechsel von Hardware, Modellbackend oder Primärmodell darf keinen Neuaufbau des kanonischen Wissens erfordern.

---

## 3. Architekturentscheidung: Modularer lokaler Monolith

ATHENA v1 wird **nicht** als Microservice-System entwickelt.

Die bevorzugte Architektur lautet:

> **Modularer lokaler Monolith mit klar getrennten internen Modulen und wenigen isolierten Hilfsprozessen.**

Damit vermeiden wir unnötige Komplexität durch Docker, Kubernetes, Message Broker, Service Discovery, mehrere Serverprozesse oder verteilte Datenbanken.

Aus Benutzersicht bleibt ATHENA eine Anwendung.

---

## 4. Logische Gesamtarchitektur

Die v1-Architektur folgt einem lokalen Core mit klar getrennten Verantwortlichkeiten.

```text
┌──────────────────────────────────────────────────────────┐
│                    ATHENA Desktop                        │
│ Chat | Wissen | Memory | News | Jobs | Einstellungen    │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                       ATHENA CORE                        │
│                                                          │
│ Request Router        Context Builder                    │
│ Knowledge Service     Personal Memory Service            │
│ Archive Service       Search Service                     │
│ Model Service         Job Service                        │
│ Security Service      Audit/Provenance Service           │
│ Resource Manager      Configuration Service              │
└──────────┬────────────────────┬─────────────────────┬─────┘
           │                    │                     │
           ▼                    ▼                     ▼
 PrimaryModelProvider     Persistence Layer      ExternalAccessGateway
           │                    │                     │
           ▼                    ▼                     ▼
      LM Studio        ATHENA Persistent Data    Privacy/Anonymization
                       Durable Operational State        Layer
                       Derived State                    │
                                                       ▼
                                                    Internet
```

Obsidian, Backup, Recovery, Infrastrukturmodelle und Plugins werden über definierte Adapter beziehungsweise Core-Schnittstellen angebunden.

Die Grafik beschreibt logische Verantwortlichkeiten. Sie schreibt nicht vor, dass jedes Modul ein eigener Prozess sein muss.

---

## 5. Hauptmodule

ATHENA v1 besteht mindestens aus folgenden logischen Modulen:

```text
athena-core
athena-ui
athena-model
athena-knowledge
athena-memory
athena-archive
athena-search
athena-jobs
athena-news
athena-network
athena-security
athena-audit
athena-storage
athena-backup
athena-recovery
athena-plugins
athena-observability
athena-config
```

Diese Namen beschreiben Verantwortlichkeiten und Package-Grenzen. Sie bedeuten nicht, dass jedes Modul einen eigenen Prozess erhält.

Module dürfen Daten nicht außerhalb ihrer definierten Berechtigungen und Core-Schnittstellen verändern.

---

## 6. ATHENA Core

Der Core ist die zentrale Koordinationsinstanz.

Er kontrolliert Benutzeranfragen, Kontextaufbau, Modellzugriff, Wissenszugriff, Berechtigungen, Hintergrundjobs und externe Kommunikation.

Andere Module dürfen zentrale Regeln des Core nicht umgehen.

---

## 7. Core-Regel und semantische Autorität

Alle Änderungen an autoritativen persistenten Daten laufen über kontrollierte Core-Schnittstellen.

Für semantische Änderungen am kanonischen Wissen gilt die Alpha-Regel:

> **Nur der Benutzer und das aktive Primärmodell dürfen semantische Änderungen am kanonischen Wissen veranlassen.**

Dabei gilt technisch:

- der **Benutzer** besitzt die höchste Autorität;
- das **aktive Primärmodell** ist die einzige automatisierte KI-Komponente mit semantischer Entscheidungsbefugnis;
- Infrastrukturmodelle dürfen technische Vorarbeit leisten, aber keine eigenständigen semantischen Wissensentscheidungen treffen;
- externe Quellen, Plugins und technische Algorithmen besitzen keine eigene semantische Autorität;
- eine ausdrückliche Benutzerkorrektur darf nicht stillschweigend durch eine spätere Modellinterpretation überschrieben werden.

Das Primärmodell erhält **keinen direkten Datenbank-Schreibzugriff**. Es liefert strukturierte Vorschläge beziehungsweise Ergebnisse an den Core.

Nicht zulässig:

```text
Plugin oder Modell
        ↓
direkter Write in Datenbank
```

Zulässig:

```text
Benutzer oder Primärmodell
        ↓
Core API / Knowledge Workflow
        ↓
Validierung
        ↓
Berechtigungsprüfung
        ↓
Provenienz + Versionierung
        ↓
atomarer Commit
```

Dadurch bleiben Benutzerhoheit, Audit, Provenienz, Versionierung und Integrität konsistent.

---

## 8. Desktop UI

Die Desktop-Oberfläche ist ein Client des ATHENA Core.

Sie enthält keine eigene Wissenslogik.

Die UI darf Daten anzeigen, Benutzeraktionen erfassen und Core-Funktionen aufrufen. Sie darf nicht selbst entscheiden, wie Wissen gespeichert oder interpretiert wird.

---

## 9. UI-Ausfall

Ein Fehler der Benutzeroberfläche darf den Wissensbestand nicht beschädigen.

Core und persistente Daten bleiben logisch unabhängig von der Darstellung.

Diese Trennung ermöglicht später neue Desktop-UIs, mobile Clients, CLI und Weboberflächen.

---

## 10. Interne Core API

Zwischen UI und Core wird eine klar definierte lokale API verwendet.

Die API muss langfristig ermöglichen:

```text
Desktop
     │
Mobile
     ├──→ ATHENA Core
CLI  │
     │
andere autorisierte Clients
```

Für v1 wird nur die Desktop-Anwendung zwingend implementiert.

---

## 11. Lokale Bindung

Die Core API ist in Version 1 standardmäßig ausschließlich lokal erreichbar.

Standard:

```text
127.0.0.1
```

Keine öffentliche Netzwerkfreigabe.

Remote-Zugriff wird erst später ausdrücklich aktiviert und abgesichert.

---

## 12. API-Versionierung

Die Core API besitzt von Beginn an eine Version.

Beispiel:

```text
/api/v1/chat
/api/v1/search
/api/v1/knowledge
/api/v1/jobs
```

Dadurch können zukünftige Clients mit älteren ATHENA-Versionen kontrolliert umgehen.

---

## 13. Prozessmodell

ATHENA soll möglichst wenige dauerhafte Prozesse benötigen.

Vorgesehen sind grundsätzlich:

```text
ATHENA Desktop
      │
      ▼
ATHENA Core
      │
      ├── Job Worker
      └── optionale isolierte Worker
```

LM Studio und Tor bleiben externe Prozesse beziehungsweise externe lokale Dienste.

---

## 14. Worker

Bestimmte Aufgaben können in isolierten Worker-Prozessen ausgeführt werden.

Beispiele:

- OCR
- Dokumentkonvertierung
- Plugin-Ausführung
- aufwendige Importjobs

Ein abstürzender Worker beendet nicht den ATHENA Core.

---

## 15. Keine unnötige Prozesszerlegung

Ein eigenes Modul benötigt nicht automatisch einen eigenen Prozess.

Knowledge Service, Search Service und Archive Service können beispielsweise innerhalb des Core-Prozesses laufen.

Isolation wird nur dort verwendet, wo sie einen konkreten Stabilitäts- oder Sicherheitsvorteil besitzt.

---

## 16. Modellarchitektur

ATHENA unterscheidet technisch strikt zwischen:

```text
Primary Model
```

und:

```text
Infrastructure Models
```

Das aktive Primärmodell übernimmt automatisierte semantische Aufgaben wie Interpretation, Wissensextraktion, Synthese und semantische Relationserkennung.

Infrastrukturmodelle übernehmen technische Hilfsaufgaben wie Embeddings, OCR, Speech-to-Text oder Text-to-Speech.

Technische Klassifikationen wie Dateityp, Sprache oder MIME-Typ sind zulässig. Infrastrukturmodelle dürfen daraus jedoch keine eigenständigen semantischen Entscheidungen über kanonisches Wissen ableiten.

---

## 17. Primary Model Interface

Das Primärmodell wird nicht direkt an ein bestimmtes Backend gekoppelt.

Es existiert eine abstrakte Schnittstelle:

```text
PrimaryModelProvider
```

Die erste Referenzimplementierung ist:

```text
LMStudioProvider
```

Dadurch kann später ein anderes lokales oder ausdrücklich erlaubtes Backend ergänzt werden, ohne Knowledge, Personal Memory, Raw Archive oder Provenienz neu aufzubauen.

Die Provider-Abstraktion darf die Alpha-Regel „genau ein aktives Primärmodell für automatisierte semantische Entscheidungen“ nicht verwässern.

---

## 18. Modellbackend

Der Core kennt nur die definierte Provider-Schnittstelle und nicht die internen Besonderheiten eines konkreten Modellservers.

```text
ATHENA Core
      │
      ▼
PrimaryModelProvider
      │
      ▼
LMStudioProvider
      │
      ▼
LM Studio
```

LM Studio ist damit eine **Beta-v1-Referenzimplementierung**, nicht Teil von ATHENAs Identität oder dauerhaftem Wissensformat.

---

## 19. Provider-Funktionen

Der Provider muss mindestens unterstützen:

- Verbindung prüfen
- verfügbare Modelle ermitteln
- aktives Modell erkennen
- Anfrage senden
- Streaming empfangen
- Fehler erkennen
- Timeout behandeln

Modellladen und -entladen werden unterstützt, soweit das verwendete Backend dies zuverlässig ermöglicht.

---

## 20. Modellidentität und Herkunftsakteur

Jede persistierte semantische Änderung erhält einen eindeutigen **Herkunftsakteur**.

Mindestens mögliche Akteure sind:

```text
user
primary_model
import
system_process
```

Für direkte Benutzeränderungen wird **keine Modellsignatur erfunden**.

Wenn das aktive Primärmodell an einer wissensbildenden Operation beteiligt war, wird zusätzlich eine technische Modellsignatur gespeichert, soweit verfügbar:

```text
provider
model_identifier
model_name
model_version_or_hash
quantization
timestamp
relevant_generation_parameters
prompt_template_version
processing_pipeline_version
```

Nicht verfügbare Werte werden ausdrücklich als unbekannt gespeichert.

Die genaue Persistenzstruktur von `origin_actor`, Modellsignatur und Processing Lineage wird in Beta Kapitel 02 festgelegt.

---

## 21. Infrastructure Model Interface

Technische Modelle erhalten getrennte Provider-Schnittstellen.

Beispielsweise:

```text
EmbeddingProvider
OCRProvider
SpeechToTextProvider
TextToSpeechProvider
```

Sie besitzen keine `PrimaryModelProvider`-Rechte.

Damit wird die semantische Firewall technisch sichtbar.

---

## 22. Semantische Berechtigungen der Infrastrukturmodelle

Ein `EmbeddingProvider` darf Text erhalten und einen Vektor zurückgeben.

Ein OCR-Provider darf aus einem Bild Text extrahieren.

Ein technischer Klassifikator darf beispielsweise Sprache oder Dateityp erkennen.

Diese Komponenten erhalten jedoch keine Berechtigung, eigenständig:

- kanonische Wissenseinheiten umzuschreiben;
- Benutzerkorrekturen zu verwerfen;
- semantische Relevanz dauerhaft festzuschreiben;
- Wissensclaims als wahr oder falsch zu setzen;
- Inhalte aus thematischen Gründen zu löschen oder abzuschwächen.

Die semantische Firewall wird sowohl durch getrennte Interfaces als auch durch Core-Berechtigungen technisch erzwungen.

---

## 23. Services für autoritative persistente Domänen

ATHENA Persistent Data besteht aus logisch getrennten autoritativen Domänen. Die Services spiegeln diese Trennung wider.

### Knowledge Service

Der Knowledge Service verwaltet ausschließlich die **Knowledge-Domäne**, insbesondere:

- Wissenseinheiten;
- Claims und Interpretationen;
- Beziehungen;
- Concept Notes;
- Projekte;
- Wissensversionen;
- epistemische Zustände und Vertrauensinformationen.

### Personal Memory Service

Der Personal Memory Service verwaltet persönliche Zusammenarbeitseinstellungen, beispielsweise:

- Antwortpräferenzen;
- bevorzugte Modelle;
- wiederkehrende Arbeitsweisen;
- langfristig relevante Bedien- und Workflowpräferenzen.

Personal Memory ist **kein Teil des Wissensgraphen**. Es darf auf Knowledge-Objekte referenzieren, aber nicht stillschweigend mit ihnen verschmelzen.

### Audit/Provenance Service

Der Audit/Provenance Service verwaltet nachvollziehbare Herkunfts-, Änderungs- und Verarbeitungshistorie.

### Configuration Service

Der Configuration Service verwaltet Benutzer- und Systemkonfiguration. Konfiguration ist autoritativer persistenter Zustand, aber kein kanonisches semantisches Wissen.

Die konkreten Datenmodelle und IDs werden in Beta Kapitel 02 definiert.

---

## 24. Archive Service und Raw Archive

Der Archive Service verwaltet die **Raw-Archive-Domäne** mit unveränderten beziehungsweise originalgetreuen Quellen.

Beispiele:

- archivierte Chats;
- Dokumente;
- Webseiten-Snapshots;
- Bilder;
- Audio;
- importierte Nachrichtenquellen.

Das Raw Archive ist **keine Lebenszyklusstufe der Knowledge-Domäne**. Es ist eine getrennte autoritative Quellen-Domäne.

Verarbeitung darf Originalquellen lesen, chunk-en, interpretieren, transkribieren, zusammenfassen und verknüpfen, aber niemals durch abgeleitete Ergebnisse ersetzen oder überschreiben.

Endgültige Löschung erfolgt nur aufgrund einer ausdrücklichen Benutzerentscheidung oder einer ausdrücklich vom Benutzer konfigurierten Aufbewahrungs-, Lebenszyklus- oder Löschregel.

---

## 25. Search Service

Der Search Service abstrahiert sämtliche Suchverfahren.

Er kombiniert später:

```text
Full Text Search
+
Semantic Search
+
Graph Search
+
Metadata Filtering
```

Der Benutzer muss für normale Anfragen nicht auswählen, welches Verfahren verwendet wird.

---

## 26. Retrieval Pipeline

Eine normale Wissensfrage folgt grundsätzlich:

```text
User Query
      │
      ├── Current Conversation
      ├── relevant Personal Memory
      │
      ▼
Query Analysis
      │
      ▼
Candidate Retrieval
      │
      ├── Full Text
      ├── Semantic
      ├── Graph
      └── Metadata
      │
      ▼
Candidate Ranking
      │
      ▼
Context Builder
      │
      ▼
Primary Model
```

Personal Memory und Knowledge bleiben auch im Retrieval logisch getrennte Kontextquellen.

Die konkrete Rankinglogik und die Auswahlregeln für Personal Memory werden in späteren Beta-Kapiteln spezifiziert.

---

## 27. Context Builder

Der Context Builder entscheidet, welche Informationen tatsächlich in das Kontextfenster des Primärmodells gelangen.

Er berücksichtigt mindestens:

- aktuelle Unterhaltung;
- relevante Personal-Memory-Einträge;
- relevante Knowledge-Einheiten;
- ausgewählte Quellenpassagen aus dem Raw Archive;
- Suchergebnisse und Relevanz;
- Provenienz und Sicherheitsbereiche;
- Tokenbudget;
- erwartete Antwortlänge;
- Sicherheitsreserve;
- Aufgaben- und Systeminstruktionen.

Die Quellen bleiben im aufgebauten Kontext logisch unterscheidbar. Personal Memory wird nicht in Knowledge umklassifiziert, nur weil beides in einem Modellaufruf verwendet wird.

Der Context Builder ist die verbindliche technische Grenze zwischen großen ATHENA-Datenbeständen und dem begrenzten Kontextfenster eines Modells.

---

## 28. Kein direkter Archiv-Dump

Der Context Builder darf niemals standardmäßig große Archivbereiche vollständig in das Modell laden.

Auch bei sehr großen Kontextfenstern gilt:

```text
Retrieval first
```

Die Größe des Gesamtarchivs darf nicht direkt bestimmen, wie viele Tokens an das Primärmodell gesendet werden.

---

## 29. Kontextfenster ist keine Datenmengengrenze

Keine wissensrelevante Aufgabe darf davon abhängig sein, dass ihr gesamter Input gleichzeitig in das Kontextfenster des Primärmodells passt.

Das Kontextfenster begrenzt ausschließlich die Größe eines einzelnen Modellaufrufs beziehungsweise Verarbeitungsschritts.

Damit gilt:

```text
Context Window
≠
Maximum Knowledge Size
```

und:

```text
Context Window
=
Maximum Working Set per Model Call
```

ATHENA muss deshalb auch Datenbestände verarbeiten können, die um Größenordnungen größer sind als jedes verfügbare Modellkontextfenster.

---

## 30. Verbindliches Kontextbudget

Für jedes Primärmodellprofil wird ein Context Budget definiert.

Das Budget reserviert getrennte Bereiche für:

```text
System Instructions

Task Instructions

Conversation Context

Retrieved Knowledge

Current Source Chunk

Intermediate Results

Expected Output

Safety Margin
```

ATHENA darf das Kontextfenster nicht planmäßig bis zur technischen Maximalgrenze füllen.

Eine feste Sicherheitsreserve bleibt erhalten.

---

## 31. Dynamisches Token Accounting

Vor jedem Modellaufruf berechnet ATHENA die erwartete Kontextgröße.

Wenn:

```text
estimated_input
+
reserved_output
+
safety_margin
>
model_context_limit
```

darf die Anfrage nicht unverändert an das Modell gesendet werden.

ATHENA muss stattdessen:

- Retrieval-Material reduzieren,
- weniger relevante Passagen entfernen,
- einen Chunk weiter teilen,
- oder eine zusätzliche Verarbeitungsebene erzeugen.

Ein Context-Limit-Fehler darf nicht der normale Mechanismus zur Größenkontrolle sein.

---

## 32. Automatische Chunk-Verkleinerung

Falls ein vorbereiteter Chunk für das aktive Modell unerwartet zu groß ist, wird er automatisch weiter unterteilt.

Beispiel:

```text
Chunk 174
↓
zu groß
↓
Chunk 174-A
Chunk 174-B
Chunk 174-C
↓
separat verarbeiten
↓
Ergebnisse kontrolliert zusammenführen
```

Die Aufgabe wird dadurch nicht als gescheitert betrachtet.

Dies ist besonders wichtig, wenn später Modelle mit unterschiedlichen Kontextgrößen verwendet werden.

---

## 33. Chunking

Große Quellen und große Verarbeitungsvorgänge werden in begrenzte **reproduzierbare Derived-State-Verarbeitungseinheiten** zerlegt. `SourceChunk` ist keine autoritative Raw-Archive-Entität und darf niemals der einzige langlebige Evidenzanker sein.

Jeder Chunk besitzt mindestens:

```text
chunk_id
source_id
representation_id
anchor/source_range
sequence_number
content_hash
processing_state
chunking/build signature
```

Optional können zusätzlich Parent-Child-Beziehungen zwischen Chunks gespeichert werden. Dauerhafte Claims, Provenienz und Research-Snapshots materialisieren stabile `SourceAnchor`-/`SourceRepresentation`-Referenzen. Wird ein Chunkset neu gebaut, dürfen dessen technische `chunk_id`-Werte wechseln.

---

## 34. Semantische Chunk-Grenzen

Chunking soll nach Möglichkeit natürliche Grenzen bevorzugen.

Beispiele:

- Absätze
- Kapitel
- Nachrichten
- Dokumentabschnitte
- Sprecherwechsel
- Tabellen
- Seitenbereiche

Starres Abschneiden ausschließlich nach Zeichenanzahl wird nur als Fallback verwendet.

---

## 35. Chunk Overlap

Falls der Inhalt es erfordert, können benachbarte Chunks einen begrenzten Overlap besitzen.

Der Overlap dient dazu, Zusammenhänge an Chunk-Grenzen nicht zu verlieren.

ATHENA muss jedoch unterscheiden zwischen:

```text
Original Content
```

und:

```text
Processing Overlap
```

Overlap darf keine doppelten kanonischen Wissenseinheiten erzeugen.

---

## 36. Original bleibt unabhängig vom Chunking

Chunks sind Verarbeitungseinheiten, keine Ersatzquelle.

Das ursprüngliche Dokument beziehungsweise der ursprüngliche Chat bleibt vollständig erhalten.

Ein späteres Re-Chunking mit einer verbesserten Strategie muss möglich sein, ohne das Original neu importieren zu müssen.

---

## 37. Persistente Checkpoints

Jeder langlaufende Verarbeitungsvorgang muss fortsetzbar sein.

Nach jedem erfolgreich bestätigten Verarbeitungsschritt wird ein persistenter Checkpoint im **Durable Operational State** gespeichert.

Mindestens, soweit für den Job zutreffend:

```text
job_id
processing_stage
scope_or_source_reference
total_units
completed_units
next_unit
last_confirmed_checkpoint
processing_signature
status
```

Die `processing_signature` kann unter anderem Modell-, Prompt-, Pipeline-, Embedding- und Chunking-Versionen referenzieren.

Eine Modellsignatur ist nur verpflichtend, wenn in der betreffenden Stage tatsächlich ein Modell beteiligt war. Direkte Benutzeränderungen erhalten keine erfundene Modellsignatur.

---

## 38. Checkpoint-Regel

Ein Verarbeitungsschritt gilt erst dann als abgeschlossen, wenn:

1. das Ergebnis vollständig erzeugt wurde,
2. das Ergebnis validiert wurde,
3. das Ergebnis persistent gespeichert wurde,
4. der Checkpoint erfolgreich aktualisiert wurde.

Erst danach darf ATHENA zum nächsten Verarbeitungsschritt wechseln.

---

## 39. Fortsetzung nach Unterbrechung

Nach:

- ATHENA-Neustart
- Windows-Neustart
- Stromausfall
- Modellabsturz
- Modell-Entladung
- LM-Studio-Ausfall
- Ressourcenpause
- Netzwerkunterbrechung

wird der letzte bestätigte Checkpoint geladen.

Beispiel:

```text
420 Chunks insgesamt
173 bestätigt
↓
Neustart
↓
bei Chunk 174 fortsetzen
```

Bereits bestätigte Chunks werden nicht unnötig erneut analysiert.

---

## 40. Keine unbestätigten Ergebnisse übernehmen

Teilweise erzeugte, abgeschnittene oder technisch ungültige Modellantworten werden nicht als erfolgreich verarbeitet markiert.

Sie dürfen insbesondere nicht stillschweigend zu kanonischem Wissen werden.

Ein abgebrochener Chunk bleibt offen und kann erneut ausgeführt werden.

---

## 41. Idempotente Chunk-Verarbeitung

Die erneute Verarbeitung desselben Chunks darf nicht automatisch doppelte kanonische Objekte erzeugen.

Hierzu werden stabile IDs, Source References, Content Hashes und Processing IDs verwendet.

---

## 42. Hierarchische Verarbeitung

Sehr große Informationsmengen werden mehrstufig verarbeitet.

Beispiel:

```text
Original
↓
Chunks
↓
lokale Ergebnisse
↓
Gruppenergebnisse
↓
höhere Synthese
↓
Gesamtergebnis
```

Eine Gesamtsynthese darf nicht voraussetzen, dass sämtliche Original-Chunks gleichzeitig in das Modell geladen werden.

---

## 43. Hierarchische Provenienz

Eine höhere Zusammenfassung muss auf ihre zugrunde liegenden Teilresultate und letztlich auf die Originalquellen zurückgeführt werden können.

Beispiel:

```text
Global Summary
↓
Summary Group 12
↓
Chunk Results 110–119
↓
Source Document
```

Hierarchische Verarbeitung darf Provenienz nicht zerstören.

---

## 44. Zwischenresultate

Zwischenresultate können als **Derived State** gespeichert werden, sofern sie vollständig aus autoritativen Daten und dokumentierter Verarbeitung rekonstruiert werden können.

Sie dürfen später:

- wiederverwendet;
- invalidiert;
- neu erzeugt

werden.

Ist ein Zwischenresultat für die sichere Fortsetzung eines laufenden Jobs die einzige vorhandene Kopie eines noch nicht anderweitig bestätigten Zustands, gehört es bis zum bestätigten Commit stattdessen zum **Durable Operational State**.

Ob ein Zwischenresultat kanonisches Wissen wird, entscheidet der dafür vorgesehene Knowledge-Workflow unter Berücksichtigung der semantischen Autorität des Benutzers und des aktiven Primärmodells.

---

## 45. Trennung von Indexierung und LLM-Analyse

ATHENA unterscheidet strikt zwischen technischer Indexierung und semantischer LLM-Verarbeitung.

Volltextindexierung:

```text
Text
↓
FTS
↓
Index
```

benötigt kein Primärmodell.

Embedding-Erzeugung:

```text
Text Chunk
↓
EmbeddingProvider
↓
Vector
```

verwendet ein Infrastrukturmodell.

Das Primärmodell wird nur dort eingesetzt, wo tatsächlich semantische Interpretation erforderlich ist.

---

## 46. Keine Verschwendung von Primärmodell-Kontext

Das Primärmodell wird insbesondere verwendet für:

- Interpretation
- Wissensextraktion
- Zusammenfassung
- Relationserkennung
- Synthese
- semantische Konfliktanalyse

Nicht für:

- Dateinamen auflisten
- Hashes berechnen
- Volltextindex aufbauen
- Dateipfade auflösen
- simple Metadatenfilter
- reine Vektorberechnung

---

## 47. Suche in sehr großen Archiven

Eine Benutzerfrage darf unabhängig davon funktionieren, ob ATHENA:

- 1 GB
- 10 GB
- 100 GB
- 500 GB
- 1 TB

oder mehr Archivdaten verwaltet.

Das Primärmodell sieht niemals automatisch diese Datenmenge.

Die Archivgröße beeinflusst:

- Indexgröße
- Kandidatenmenge
- Suchzeit
- eventuell Dauer einer vollständigen Analyse

aber nicht direkt die Tokenmenge eines einzelnen Modellaufrufs.

---

## 48. Standard Retrieval Mode

Für normale Fragen verwendet ATHENA einen schnellen Retrieval-Modus.

Beispiel:

```text
100 GB Archiv
↓
lokale Indizes
↓
5.000 technische Kandidaten
↓
Filter + Ranking
↓
200 starke Kandidaten
↓
Re-Ranking
↓
20–40 beste Passagen
↓
Context Budget
↓
Primary Model
```

Die Zahlen sind illustrativ und werden später konfigurierbar beziehungsweise dynamisch bestimmt.

---

## 49. Standard Retrieval darf nicht linear scannen

Eine normale Benutzerfrage darf keinen vollständigen Scan des 100-GB-Roharchivs auslösen.

Normale Suche verwendet vorbereitete:

- Volltextindizes
- Vektorindizes
- Metadaten
- Graphbeziehungen

Originaldateien werden nur für die tatsächlich ausgewählten Passagen geöffnet.

---

## 50. Exhaustive Research Mode

Für Fragen, die ausdrücklich oder semantisch eine möglichst vollständige Untersuchung verlangen, besitzt ATHENA einen zweiten Suchmodus:

```text
EXHAUSTIVE_RESEARCH
```

Beispiele:

> Analysiere alles, was ich in den letzten zehn Jahren über Thema X geschrieben habe.

> Finde sämtliche Stellen, an denen Projekt Y erwähnt wird.

> Vergleiche meine gesamte Argumentation zu Thema Z über die Jahre.

Dieser Modus darf wesentlich länger dauern als normale Suche.

---

## 51. Exhaustive Research Pipeline

Grundsätzlich:

```text
User Question
↓
Query Plan
↓
breite Kandidatenermittlung
↓
Deduplication
↓
Relevance Filtering
↓
persistente Candidate Set
↓
Chunk Groups
↓
Primary Model Analysis
↓
Checkpoints
↓
Partial Syntheses
↓
Hierarchical Synthesis
↓
Final Answer
```

Auch Millionen potenzieller Treffer dürfen nicht gleichzeitig in das Modellkontextfenster geladen werden.

---

## 52. Persistente Candidate Sets

Bei großen Rechercheaufgaben wird die gefundene Kandidatenmenge persistent gespeichert.

Dadurch muss ATHENA nach einem Neustart nicht zwingend die gesamte Suche erneut durchführen.

Ein Research Job kann beispielsweise enthalten:

```text
research_job_id
query
search_scope
candidate_set_id
candidate_count
processed_candidate_count
current_stage
checkpoint
```

---

## 53. Vollständigkeit versus Geschwindigkeit

ATHENA unterscheidet explizit zwischen:

```text
FAST / NORMAL RETRIEVAL
```

und:

```text
EXHAUSTIVE RESEARCH
```

Normal Retrieval optimiert auf schnelle, hochwertige Antworten.

Exhaustive Research optimiert stärker auf Abdeckung und Vollständigkeit.

ATHENA darf diese beiden Ziele nicht so behandeln, als seien sie identisch.

---

## 54. Auswahl des Suchmodus

Der Request Router beziehungsweise Query Analyzer darf anhand der Benutzerfrage einen geeigneten Modus vorschlagen oder automatisch wählen.

Die Benutzeroberfläche soll bei umfangreichen Aufgaben den Modus sichtbar machen.

Langfristig kann beispielsweise angeboten werden:

```text
Suche:
Schnell
Umfassend
```

Eine automatisch gestartete sehr aufwendige Vollanalyse muss für den Benutzer erkennbar sein.

---

## 55. Kein Top-K-Verlust bei Vollständigkeitsfragen

Bei einer normalen Frage ist Top-K-Retrieval zulässig.

Bei einer Vollständigkeitsfrage darf ATHENA jedoch nicht einfach die ersten 20 Treffer analysieren und daraus behaupten, das gesamte Archiv untersucht zu haben.

Wenn vollständige Abdeckung technisch nicht garantiert werden kann, muss dies in Ergebnis und Provenienz sichtbar sein.

---

## 56. Coverage Tracking

Exhaustive Research speichert soweit sinnvoll Informationen über die untersuchte Abdeckung.

Beispielsweise:

```text
search_scope
sources_considered
sources_processed
sources_failed
chunks_processed
chunks_skipped
coverage_status
```

Mögliche Zustände:

```text
COMPLETE
PARTIAL
INCOMPLETE
UNKNOWN
```

ATHENA behauptet keine Vollständigkeit, wenn die Verarbeitung unvollständig war.

---

## 57. Kontextbudget bei Suchantworten

Nach dem Retrieval darf der Context Builder nur Material innerhalb des aktiven Modellbudgets auswählen.

Ist mehr relevantes Material vorhanden als hineinpasst, darf ATHENA nicht:

```text
alles hineinpressen
```

Stattdessen:

```text
weitere Verarbeitungsebene
↓
Teilanalysen
↓
komprimierte evidenzgebundene Zwischenergebnisse
↓
finaler Kontext
```

---

## 58. Evidenz darf durch Kompression nicht verschwinden

Wenn Suchergebnisse hierarchisch komprimiert werden, müssen wichtige Aussagen auf Originalpassagen zurückführbar bleiben.

ATHENA darf eine Zusammenfassung nicht zur einzigen verbleibenden Quelle machen.

---

## 59. Retrieval-Fehler sind keine Wissenslöschung

Wenn ein Index beschädigt ist oder ein Retrieval-Schritt fehlschlägt, bleibt das Originalarchiv unverändert.

Der Index kann rekonstruiert werden.

---

## 60. Persistence Layer

Alle persistenten Schreibvorgänge laufen über eine gemeinsame Persistenzabstraktion.

Andere Module greifen nicht unkontrolliert direkt auf konkrete Datenbanktabellen oder Dateien zu.

```text
Domain Services
      │
      ▼
Persistence Interface
      │
      ├── Database
      ├── Filesystem / Object Storage
      └── Durable Journal / Queue Storage
```

Die Persistenzschicht muss atomare beziehungsweise transaktional koordinierte Änderungen, Versionierung, Integritätsprüfungen und Recovery unterstützen.

Sie unterscheidet ausdrücklich zwischen:

- **ATHENA Persistent Data**;
- **Durable Operational State**;
- **Derived State**;
- **Temporary State**;
- **Secrets**;
- **Backups**.

---

## 61. Persistenzklassen

Die Alpha-Taxonomie wird technisch verbindlich übernommen.

```text
ATHENA Persistent Data
│
├── Knowledge
├── Personal Memory
├── Raw Archive
├── Audit & Provenance
└── Configuration

Durable Operational State
│
├── persistente Queue
├── Checkpoints
├── Transaktionsjournale
├── noch nicht bestätigte Synchronisationspuffer
└── sonstiger für sicheren Resume notwendiger Zustand

Derived State
│
├── Suchindizes
├── Embeddings
├── rekonstruierbare Caches
├── Previews
└── rekonstruierbare Processing-Artefakte

Temporary State
Secrets
Backups
```

Diese Klassen erhalten unterschiedliche Schutz-, Lebenszyklus-, Backup- und Bereinigungsregeln.

---

## 62. ATHENA Persistent Data

**ATHENA Persistent Data** bezeichnet die autoritativen langfristig zu erhaltenden Systemdaten.

Die fünf Domänen bleiben logisch getrennt:

### Knowledge

Autoritative Quelle für kanonisches semantisches Wissen.

### Personal Memory

Autoritative Quelle für persönliche Zusammenarbeitseinstellungen und langfristige Benutzerpräferenzen.

### Raw Archive

Autoritative Quelle für Originalquellen und originalgetreue archivierte Inhalte.

### Audit & Provenance

Autoritative Quelle für Entstehungs-, Verarbeitungs- und Änderungshistorie.

### Configuration

Autoritative Quelle für Benutzer- und Systemkonfiguration.

Keine einzelne Datei oder einzelne Datenbanktabelle bildet allein die „Wahrheit“ von ATHENA. Die autoritativen Domänen bilden gemeinsam den maßgeblichen persistenten Systemzustand.

---

## 63. Raw Archive und Originalschutz

Das Raw Archive besitzt hohe Schutzpriorität, weil Originalquellen nicht aus späteren Interpretationen rekonstruiert werden können.

Originale werden durch Analyse niemals ersetzt.

```text
Original
   │
   ├── Chunking
   ├── OCR / Transkription
   ├── Interpretation
   ├── Zusammenfassung
   └── Wissensextraktion
```

Alle abgeleiteten Ergebnisse bleiben getrennt vom Original.

Die Aufbewahrung richtet sich nach Benutzerentscheidungen und ausdrücklich konfigurierten Lebenszyklusregeln. „Original bleibt erhalten“ bedeutet **nicht**, dass der Benutzer sein Recht auf endgültige Löschung verliert.

---

## 64. Durable Operational State

**Durable Operational State** enthält persistenten Betriebszustand, der noch nicht zwingend Teil des autoritativen Langzeitbestands ist, aber vorübergehend die einzige Kopie nicht bestätigter Informationen oder notwendigen Fortschritts enthalten kann.

Beispiele:

- persistente Job-Queue;
- bestätigte beziehungsweise notwendige Checkpoints;
- Transaktionsjournale;
- lokale Offline- und Synchronisationspuffer;
- aktive Research-Snapshots beziehungsweise Candidate Sets, soweit sie für Resume oder Nachvollziehbarkeit benötigt werden;
- Pending Writes.

Dieser Zustand ist **kein entbehrlicher Cache**.

Er muss Absturz, Neustart und vorübergehend nicht verfügbaren Langzeitspeicher überstehen.

Er wird erst dann bereinigt, wenn der betreffende Zustand nachweislich anderweitig bestätigt persistiert oder nicht mehr benötigt wird.

---

## 65. Derived State

**Derived State** ist vollständig aus autoritativen Daten beziehungsweise dokumentierten Verarbeitungsschritten rekonstruierbar.

Beispiele:

- Embeddings;
- Volltext- und Vektorindizes;
- Previews;
- rekonstruierbare Caches;
- rekonstruierbare Re-Ranking-Artefakte;
- rekonstruierbare Zusammenfassungs-Caches.

Derived State darf niemals die einzige Kopie relevanter Information enthalten.

Ein Verlust von Derived State darf Suchqualität oder Performance vorübergehend verschlechtern, aber keinen Verlust von Knowledge, Personal Memory, Raw Archive, Audit/Provenance oder Configuration verursachen.

---

## 66. Temporary State

Temporary State umfasst ausschließlich Daten, die ohne Informationsverlust verworfen werden können.

Beispiele:

- bereits bestätigte temporäre Downloads;
- entbehrliche Konvertierungsdateien;
- Worker-Scratch-Dateien;
- flüchtige UI-Caches.

Sobald eine temporär wirkende Datei die einzige Kopie eines noch nicht bestätigten Imports, Writes oder Jobfortschritts enthält, ist sie **kein Temporary State**, sondern muss als Durable Operational State geschützt werden.

---

## 67. Configuration, Secrets und Backups

**Configuration** gehört zu ATHENA Persistent Data und wird versioniert beziehungsweise migrierbar gespeichert.

Dazu gehören beispielsweise:

- UI-Einstellungen;
- Modellprofile;
- logische Speicherzuordnungen;
- Scheduler-Einstellungen;
- Ressourcenlimits;
- Kontextbudgets;
- Berechtigungsprofile.

**Secrets** werden technisch getrennt und besonders geschützt verwaltet.

Beispiele:

- Passwörter;
- Schlüssel;
- Tokens;
- Geräte-Credentials.

Secrets dürfen nicht in normalen Logs, Markdown-Projektionen, Git oder Diagnoseexports erscheinen.

**Backups** sind Wiederherstellungskopien und keine aktive alternative Source of Truth. Restore-Vorgänge müssen kontrolliert und nachvollziehbar erfolgen.

---

## 68. Speicherabstraktion

ATHENA verwendet logische Speicherbereiche statt dauerhafter physischer Pfade.

Beispiel:

```text
knowledge://
memory://
archive://
audit://
config://
operational://
derived://
temp://
backup://
```

Intern werden diese logischen Referenzen auf reale Speicherorte abgebildet.

Objektidentität und Beziehungen basieren auf stabilen IDs beziehungsweise logischen Referenzen, nicht auf Laufwerksbuchstaben oder absoluten Pfaden.

---

## 69. Keine Laufwerksbuchstaben im Wissen

Ein Wissensobjekt speichert einen physischen Pfad nicht als dauerhafte Identität.

Stattdessen verwendet ATHENA:

```text
Object ID
+
Storage Reference
```

Die Storage Reference wird über die Speicherabstraktion aufgelöst.

---

## 70. Lokaler schneller Speicher

Die lokale SSD wird bevorzugt für latenzkritische Daten verwendet.

Typische Kandidaten:

### Derived State

- Suchindizes;
- Embeddings;
- Caches;
- Previews.

### Durable Operational State

- persistente Queue;
- Checkpoints;
- lokale Offline-Puffer;
- aktive Candidate Sets, soweit sie für Resume benötigt werden.

Wichtig:

> **„Lokal“ bedeutet nicht automatisch „rekonstruierbar“.**

Durable Operational State auf der lokalen SSD muss ebenso zuverlässig behandelt werden wie andere nicht anderweitig bestätigte Daten.

---

## 71. Langzeitspeicher

Die autoritativen Domänen von ATHENA Persistent Data bilden **einen logischen versionierten Zustand**, dessen Identität nicht an einen einzelnen physischen Pfad gebunden ist.

Für v1 gilt die in Kapitel 03 konkretisierte Trennung:

```text
lokaler state_root
→ transaktionale aktive athena.db
→ lokale Commit-Historie und noch nicht replizierter Durable State

konfigurierter long_term_root
→ verifizierte langlebige Replik autoritativer strukturierter Zustände
→ darf lokal, extern oder auf NAS liegen

archive_root
→ Originalblobs und langlebige SourceRepresentations
→ darf ebenfalls lokal, extern oder auf NAS liegen
```

`long_term_root` und `archive_root` dürfen auf demselben physischen Langzeitspeicher liegen, bleiben logisch jedoch getrennte Rollen.

Die aktive SQLite-Datei wird in v1 nicht als live WAL-Datenbank über SMB/NFS geöffnet. Ein NAS wird über versionierte, immutable beziehungsweise atomar veröffentlichte Replikationsobjekte angebunden.

Ein Commit, der lokal transaktional bestätigt wurde, gehört zum aktuellen logischen ATHENA-Zustand. Solange seine Langzeitreplikation noch nicht verifiziert ist, wird er ausdrücklich als `replication_pending` behandelt und gegen Verlust geschützt.

Damit existieren keine zwei konkurrierenden Wahrheiten: Commit-IDs und `commit_seq` definieren die logische Historie; physische Stores halten bestätigte Replikationsstände dieser Historie.

## 72. Netzwerk- und Langzeitspeicherunterbrechung

Ist der konfigurierte Langzeitspeicher nicht erreichbar, schreibt ATHENA nicht stillschweigend in einen beliebigen Ersatzpfad und versucht insbesondere nicht, eine Netzwerk-SQLite-Datei als Notlösung zu verwenden.

Soweit sicher möglich:

```text
Long-term storage unavailable
      │
      ▼
lokaler Canonical Write in athena.db
      │
      ▼
CommitRecord = gültig
replication_state = pending
      │
      ▼
Durable Replication/Outbox Job
      │
      ▼
Storage returns
      │
      ▼
Commit Bundle / Snapshot validieren
      │
      ▼
übertragen
      │
      ▼
Zielhash / Manifest / Sequenz verifizieren
      │
      ▼
replication watermark bestätigen
      │
      ▼
nur reine Transfer-Spooldaten bereinigen
```

Kann der lokale nicht rekonstruierbare Zustand nicht zuverlässig persistiert werden, muss der betreffende Schreibvorgang pausieren oder in einen kontrollierten Fehlerzustand wechseln.

Ein Langzeitspeicher darf niemals durch einen älteren Replikationsstand neuere lokal bestätigte Commits überschreiben. Divergierende Historien erzeugen einen expliziten Konflikt-/Recoveryzustand.

## 73. Job System

Alle Aufgaben, die nicht zwingend innerhalb einer Benutzeranfrage abgeschlossen werden müssen, werden über ein persistentes Job-System ausgeführt.

Beispiele:

- Embedding
- Dokumentanalyse
- News-Import
- Backfill
- Reindexierung
- Backup
- Reinterpretation
- Exhaustive Research
- hierarchische Synthese

---

## 74. Jobzustände

Mindestens:

```text
PENDING
WAITING_RESOURCE
RUNNING
PAUSED
COMPLETED
FAILED_RETRYABLE
FAILED_PERMANENT
CANCELLED
```

Für lange Recherchejobs können zusätzlich Stage- und Checkpoint-Informationen gespeichert werden.

---

## 75. Persistente Queue

Die Queue wird auf persistentem Speicher geführt.

Ein Neustart darf wartende oder teilweise abgeschlossene Jobs nicht verlieren.

---

## 76. Job-Identität

Jeder Job erhält eine eindeutige ID.

Dadurch können Wiederholungen, Checkpoints, Audit und Fehlerdiagnose eindeutig zugeordnet werden.

---

## 77. Idempotenz

Jobs sollen soweit möglich idempotent sein.

Ein Dokument zweimal zu indexieren darf nicht automatisch zwei unabhängige Kopien derselben Wissenseinheiten erzeugen.

Dasselbe gilt für erneut ausgeführte Chunks und Research-Stages.

---

## 78. Resource Manager

Der Resource Manager koordiniert rechenintensive Aufgaben.

Er beobachtet:

- CPU
- RAM
- GPU
- VRAM
- Speicherplatz
- Benutzeraktivität

---

## 79. Prioritäten

Grundreihenfolge:

```text
1. direkte Benutzerinteraktion

2. sicherheitskritische Operationen

3. persistente Schreib-/Synchronisationsvorgänge

4. zeitkritische Jobs

5. normale Hintergrundjobs

6. Wartungsjobs
```

---

## 80. GPU-Koordination

Das Primärmodell darf nicht unnötig mit anderen GPU-intensiven Anwendungen konkurrieren.

Der Resource Manager kann Jobs verschieben, Modell entladen und Modell später wieder laden.

Ein pausierter Job bleibt durch Checkpoints fortsetzbar.

---

## 81. Model Load Policy

Grundsätzlich:

```text
User asks question
      │
      ▼
Primary model required?
      │
      ├── loaded → use
      │
      └── unloaded → resource check
                        │
                        ├── available → load
                        └── busy → user-visible state
```

Keine versteckte Übernahme der GPU.

---

## 82. External Access Gateway

Kein Core-Modul oder Plugin erhält unkontrollierten allgemeinen Internetzugriff.

Externe Kommunikation läuft über:

```text
ExternalAccessGateway
```

Das Gateway erzwingt:

- Benutzerberechtigungen;
- Zweck- und Aufruferprüfung;
- die konfigurierte Privacy-/Anonymisierungsschicht;
- Fail-Closed-Verhalten;
- Audit der externen Operation.

Direkte Netzwerkzugriffe außerhalb dieser Route sind für kontrollierte ATHENA-Komponenten nicht zulässig.

---

## 83. Gateway-Regel und Beta-v1-Privacy-Implementierung

Die Alpha-Spezifikation verlangt eine freigegebene Privacy-/Anonymisierungsschicht mit Fail-Closed-Verhalten, schreibt aber keine konkrete Technologie vor.

Für die **Beta-v1-Referenzimplementierung** wird Tor als erste vorgesehene Privacy-/Anonymisierungsschicht verwendet.

```text
Authorized Module
      │
      ▼
ExternalAccessGateway
      │
      ▼
Permission + Policy Check
      │
      ▼
Configured Privacy Layer
      │
      ▼
Tor Adapter (v1 reference)
      │
      ▼
Internet
```

Tor ist damit eine austauschbare Beta-Implementierung und keine Identitäts- oder Datenabhängigkeit von ATHENA.

Ein Plugin darf diese Route nicht umgehen.

---

## 84. Internet Policy und Benutzerautorisierung

Das Gateway prüft für jede externe Operation mindestens:

- ist Internet für diese Operation gültig autorisiert?
- welcher Dienst oder welches Plugin fordert Zugriff an?
- für welchen Zweck erfolgt der Zugriff?
- ist die erforderliche Privacy-/Anonymisierungsschicht verfügbar?
- welche Ziele beziehungsweise Quellen werden angefragt?
- welche Reichweite besitzt die Berechtigung?
- muss die Operation auditiert oder besonders geschützt werden?

Für v1 gelten folgende Berechtigungsformen:

### Internet AUS

Normale Chats und Funktionen dürfen keine externen Quellen abrufen. Benötigt eine Aufgabe externe Recherche, muss eine Freigabe eingeholt werden.

### Internet AN

Externe Recherche ist innerhalb der vom Benutzer erteilten allgemeinen Reichweite zulässig.

### Explizite Web-Anfrage

Eine ausdrückliche Benutzeranfrage wie „suche online“ gilt für die betreffende Operation als Autorisierung.

### Automationen und Plugins

Sie dürfen externe Aktionen nur ausführen, wenn der Benutzer dafür eine ausdrückliche, passend begrenzte Berechtigung erteilt hat.

### Daily News

Der definierte Daily-News-Workflow ist die vorgesehene automatische Standardausnahme und besitzt eine eigene kontrollierte Berechtigung.

Wissen allein autorisiert niemals eine externe Aktion.

---

## 85. Fail Closed

Ist für eine externe Operation die konfigurierte Privacy-/Anonymisierungsschicht vorgeschrieben und nicht verfügbar:

```text
Request denied or queued
```

Es gibt keinen stillen Fallback auf eine direkte Internetverbindung.

Je nach Aufgabe wird:

- die Operation abgelehnt;
- der Benutzer informiert;
- oder ein persistenter Job für einen späteren erneuten Versuch angelegt.

Lokale Funktionen arbeiten weiter, soweit keine kritische Integritäts- oder Sicherheitsgrenze betroffen ist.

---

## 86. Netzwerkisolierung

ATHENA wird so aufgebaut, dass versehentliche direkte Netzwerkaufrufe aus Modulen möglichst schwer werden.

Core-Dienste und Plugins erhalten Netzwerkfähigkeit nur über definierte Schnittstellen.

Die konkrete technische Durchsetzung – beispielsweise Prozessgrenzen, Adapter, Firewall-Regeln oder Capability-Checks – wird in einem späteren Beta-Kapitel spezifiziert.

---

## 87. News Service

Der News Service ist ein normaler Core-Dienst mit einer ausdrücklich definierten Berechtigung zur geplanten externen Recherche.

Er besitzt keine Sonderrechte gegenüber:

- Wissensintegrität;
- Provenienz;
- Prompt-Injection-Schutz;
- Privacy-/Anonymisierung;
- Fail-Closed;
- semantischer Autorität;
- Aufbewahrungsregeln.

Importierte Nachrichten sind zunächst Quellen beziehungsweise attribuierte Claims. Sie werden nicht allein aufgrund ihres Imports zu kanonisch wahren Fakten.

---

## 88. Security Service

Der Security Service ist verantwortlich für:

- Authentifizierung;
- geschützte Bereiche;
- Berechtigungen;
- Schlüsselzugriff;
- Unlock-/Lock-Zustände;
- Sicherheitsstatus;
- Autorisierung externer und sensitiver Operationen.

Andere Module erhalten geschützte Daten nur nach erfolgreicher Autorisierung.

Passwörter werden nicht dauerhaft im Klartext gespeichert. Sie werden nur so lange verarbeitet, wie dies für Authentifizierung beziehungsweise Schlüsselableitung erforderlich ist, und anschließend soweit technisch möglich aus dem Arbeitsspeicher entfernt.

---

## 89. Security Boundary

Geschützte Inhalte dürfen nicht versehentlich in ungeschützte Systeme gelangen.

Dies betrifft insbesondere:

- Suchindizes;
- Embeddings;
- Logs;
- temporäre Dateien;
- Obsidian-Projektionen;
- Diagnoseexports;
- Research Candidate Sets;
- Zwischenzusammenfassungen;
- externe Requests.

Geschützte Inhalte dürfen intern neutrale IDs und nicht verräterische Metadaten verwenden.

Die genaue Verschlüsselungs-, Schlüssel- und Indexierungsarchitektur wird in einem eigenen Beta-Kapitel spezifiziert.

---

## 90. Backup Service

Backup wird als eigenständige Core-Funktion implementiert.

Der Backup Service kennt die Datenklassen und weiß dadurch, welche Bereiche zwingend, optional oder rekonstruierbar sind.

Aktive persistente Jobs und für deren Fortsetzung notwendige Checkpoint-Daten müssen in die Recovery-Strategie einbezogen werden.

---

## 91. Recovery Service

Recovery wird nicht lediglich als Funktion der normalen Desktop-UI implementiert.

Es erhält einen möglichst unabhängigen minimalen Ausführungspfad.

Dadurch kann Recovery auch funktionieren, wenn die normale ATHENA-Oberfläche beschädigt ist.

---

## 92. Recovery langlaufender Jobs

Nach Recovery muss ATHENA unterscheiden können zwischen:

- vollständig abgeschlossenen Jobs
- sicher fortsetzbaren Jobs
- Jobs mit verlorenem Derived State
- Jobs, die neu gestartet werden müssen

Kanonisches Wissen darf durch einen verlorenen Verarbeitungscheckpoint nicht beschädigt werden.

---

## 93. Obsidian Adapter

Obsidian ist eine optionale Ansicht beziehungsweise Bearbeitungsoberfläche und **nicht** Source of Truth.

ATHENA kann ausgewählte Inhalte als Markdown projizieren.

Manuelle Änderungen des Benutzers in dafür freigegebenen editierbaren Bereichen werden über einen kontrollierten Import-/Reconciliation-Workflow zurückgeführt.

```text
ATHENA Persistent Data
        │
        ▼
Markdown Projection
        │
        ▼
Obsidian
        │
        ▼
optional user edit
        │
        ▼
Validation + Reconciliation
        │
        ▼
ATHENA Core
```

Obsidian-Pluginzustand darf niemals die einzige Kopie relevanter ATHENA-Daten sein.

---

## 94. Markdown ist Projektion

Die Obsidian-Darstellung wird technisch als menschenlesbare Projektion des Wissenssystems behandelt.

Damit kann sie neu erzeugt, aktualisiert und migriert werden.

Manuell editierbare Bereiche erhalten gesonderte Synchronisationsregeln.

---

## 95. Plugin Host

Plugins kommunizieren ausschließlich über eine kontrollierte Plugin-Schnittstelle.

Ein Plugin erhält nur explizit freigegebene Fähigkeiten.

Beispiele:

```text
read_authorized_data
submit_import
propose_change
request_internet
create_job
```

Eine Capability darf nicht implizit semantische Autorität verleihen.

Ein Plugin kann Daten liefern, Aktionen anfordern oder einen vom Benutzer ausgelösten Edit transportieren. Eigenständige semantische Änderungen am kanonischen Wissen dürfen jedoch nur innerhalb eines Core-Workflows erfolgen, der die Alpha-Regel für Benutzer und aktives Primärmodell einhält.

Internet-, Datei-, Protected-Content- und Schreibrechte werden getrennt vergeben.

---

## 96. Keine direkte Datenbankberechtigung

Plugins, Obsidian-Adapter, UI und Modellprovider erhalten keinen unkontrollierten direkten Schreibzugriff auf autoritative Persistenz.

Änderungen laufen über Core- beziehungsweise Domain-Service-Schnittstellen.

Ausnahmen für rein technische interne Migrationswerkzeuge müssen ausdrücklich definiert, getestet und auditiert werden.

---

## 97. Observability

ATHENA benötigt ein internes Observability-System.

Es sammelt mindestens:

- strukturierte Logs
- Komponentenstatus
- Jobstatus
- Fehler
- Ressourcenstatus
- Research- und Processing-Fortschritt

---

## 98. Logging-Level

Mindestens:

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Produktive Standardlogs sollen ausreichend zur Diagnose sein, ohne unnötig private Inhalte zu speichern.

---

## 99. Structured Logging

Logs sollen strukturiert erzeugt werden.

Beispiel:

```text
timestamp
component
severity
event_id
job_id
source_id
chunk_id
error_code
message
```

Keine ungeordnete Sammlung beliebiger Print-Ausgaben.

---

## 100. Privacy by Logging Design

Standardmäßig werden keine vollständigen Chattexte, Dokumentinhalte oder Modellprompts in technische Logs geschrieben.

Für Debugging kann später ein bewusst aktivierbarer Diagnosemodus existieren.

---

## 101. Konfigurationssystem

ATHENA besitzt eine zentrale versionierte Konfiguration.

Sie wird nicht über zahlreiche voneinander unabhängige Konfigurationsdateien verteilt.

---

## 102. Konfigurationsebenen

Vorgesehen sind mindestens:

```text
System Defaults
User Configuration
Session Overrides
```

Persistente Benutzerkonfiguration gehört zur Configuration-Domäne von ATHENA Persistent Data.

Flüchtige Session Overrides sind kein langfristiger autoritativer Zustand, solange sie nicht ausdrücklich gespeichert werden.

Jobstatus, Checkpoints, Pending Writes oder Synchronisationspuffer sind **keine Konfiguration**, sondern Durable Operational State.

Secrets bleiben technisch getrennt.

---

## 103. Modellprofile und Kontextprofile

Ein Modellprofil enthält neben Backend- und Generationseinstellungen auch Informationen über:

- maximales Kontextfenster
- reservierte Output-Tokens
- Sicherheitsreserve
- bevorzugte Chunk-Größe
- maximale Retrieval-Zulage
- unterstützte Fähigkeiten

Dadurch kann ATHENA bei einem Modellwechsel seine Verarbeitung automatisch anpassen.

---

## 104. Validierung

ATHENA validiert die Konfiguration vor Verwendung.

Ungültige Einstellungen dürfen nicht unkontrolliert in den laufenden Core gelangen.

Ein Kontextprofil, das die bekannte Modellgrenze überschreitet, wird abgelehnt oder auf einen sicheren Wert reduziert.

---

## 105. Config Migration

Ändert sich das Konfigurationsschema, wird es versioniert migriert.

Ein Update darf alte Konfigurationen nicht stillschweigend unbrauchbar machen.

---

## 106. Startup Sequence

Der normale Start erfolgt grundsätzlich in definierter Reihenfolge:

```text
1. Bootstrap

2. Konfiguration laden

3. Secrets-System initialisieren

4. Storage prüfen

5. kanonische Datenbank öffnen

6. Queue wiederherstellen

7. Checkpoints und unterbrochene Jobs prüfen

8. Core Services starten

9. Search prüfen

10. externe Komponenten prüfen

11. UI verbinden

12. Hintergrundjobs freigeben
```

---

## 107. Nicht-blockierende optionale Komponenten

Folgende Komponenten dürfen den Start nicht grundsätzlich verhindern:

- LM Studio
- Tor
- Obsidian
- optionale Plugins

ATHENA startet mit reduziertem Funktionsumfang.

---

## 108. Blockierende Fehler

Normaler Schreibbetrieb darf nicht gestartet werden, wenn beispielsweise:

- kanonische Datenbank nicht sicher geöffnet werden kann
- kritische Migration fehlgeschlagen ist
- Datenintegrität nicht gewährleistet werden kann

Dann wird Recovery beziehungsweise Read-Only Mode verwendet.

---

## 109. Shutdown Sequence

Beim normalen Beenden:

```text
1. neue Hintergrundjobs stoppen

2. laufende Jobs checkpointen

3. ausstehende kritische Writes abschließen

4. Queue persistieren

5. Datenbanken sauber schließen

6. temporäre Ressourcen freigeben

7. Core beenden
```

---

## 110. Crash Recovery

Nach unerwartetem Abbruch prüft ATHENA beim nächsten Start:

- unvollständige Transaktionen
- RUNNING-Jobs
- letzte bestätigte Chunk-Checkpoints
- aktive Research Candidate Sets
- lokale Sync-Puffer
- notwendige Integritätsprüfungen

Ein alter `RUNNING`-Job wird nicht automatisch als erfolgreich behandelt.

---

## 111. Datenintegritätsprinzip

Für autoritative persistente Daten und nicht anderweitig bestätigten Durable Operational State gilt:

> **Ein logisch zusammengehöriger bestätigter Schreibvorgang wird entweder vollständig übernommen oder gar nicht.**

Teilweise Commits dürfen nicht als gültiger Zustand erscheinen.

Ein Fehler in UI, Modell, Retrieval, Indexierung, Plugin oder Worker darf nach Möglichkeit keine autoritativen Daten beschädigen.

Kann sichere Schreibintegrität nicht gewährleistet werden, darf ATHENA gezielt in einen Read-Only- oder Recovery-Zustand wechseln.

---

## 112. Architektur für große Archive

Die normale Suche darf nicht von der linearen Größe des Roharchivs abhängen.

```text
100 GB Archive
      │
      ▼
Index
      │
      ▼
kleine Kandidatenmenge
      │
      ▼
Ranking
      │
      ▼
Context
```

Das Roharchiv wird nur bei Bedarf direkt gelesen.

---

## 113. Lokale Indexstrategie

Performancekritische Suchstrukturen sollen auf schnellem lokalen Speicher liegen können, selbst wenn das Originalarchiv auf einem langsameren Datenträger oder NAS liegt.

Dadurch bleibt eine große Wissensbasis schnell durchsuchbar.

---

## 114. Keine Vollanalyse pro Anfrage

Eine normale Benutzerfrage darf niemals einen vollständigen erneuten Scan des Archivs auslösen.

Vollscans beziehungsweise breite vollständige Analysen sind explizite:

- Import-
- Rebuild-
- Recovery-
- Exhaustive-Research-

Operationen.

---

## 115. Inkrementelle Architektur

Jede neu importierte Quelle löst primär Verarbeitung für sich selbst, relevante Beziehungen und betroffene Indizes aus.

Nicht für den gesamten Wissensbestand.

---

## 116. Skalierungsprinzip

ATHENA wird so entworfen, dass steigende Archivgröße primär die Größe persistenter Indizes und die Dauer umfangreicher Batch-Aufgaben erhöht.

Sie darf nicht proportional die Kontextgröße jeder normalen Benutzerfrage erhöhen.

---

## 117. Technologieauswahl – Grundrichtung

Für ATHENA v1 wird folgende technische Richtung als Ausgangspunkt festgelegt:

```text
Core / Backend:
Python

Desktop UI:
noch festzulegen

lokale strukturierte Datenbank:
SQLite-basierte Lösung als bevorzugter Ausgangspunkt

Volltextsuche:
SQLite FTS5 als bevorzugter Ausgangspunkt

Vektorindex:
separat evaluieren

Wissensgraph:
zunächst relational modelliert

Model Backend:
LM Studio API

menschenlesbare Wissensprojektion:
Markdown
```

Diese Entscheidungen werden in den nächsten Beta-Teilen geprüft und endgültig festgelegt.

---

## 118. Warum Python

Python ist für ATHENA besonders geeignet wegen:

- sehr guter KI-Bibliotheken
- einfacher LM-Integration
- umfangreicher Dokumentverarbeitung
- schneller Entwicklungszyklen
- guter lokaler Automatisierung
- großer Bibliotheksauswahl

Performancekritische Teile können später durch spezialisierte Komponenten ersetzt werden.

---

## 119. Warum zunächst SQLite

ATHENA ist zunächst ein lokales Single-User-System.

SQLite bietet:

- Transaktionen
- Stabilität
- Portabilität
- sehr geringe Betriebsanforderungen
- Backupfähigkeit
- FTS5

Ein externer Datenbankserver wäre für v1 wahrscheinlich unnötige Komplexität.

---

## 120. Kein separater Graphserver in v1

ATHENA benötigt semantisch einen Wissensgraphen.

Das bedeutet jedoch nicht automatisch, dass Neo4j oder ein anderer Graphserver erforderlich ist.

Für Version 1 werden Beziehungen zunächst relational gespeichert.

Falls reale Anforderungen später einen Graphserver rechtfertigen, kann die Persistence-Abstraktion erweitert werden.

---

## 121. Kein separater Suchserver in v1

Elasticsearch, OpenSearch und ähnliche Systeme werden für v1 nicht vorausgesetzt.

Lokale Suche wird zunächst mit eingebetteten Technologien umgesetzt.

---

## 122. Keine Containerpflicht

ATHENA v1 setzt für den normalen Benutzer kein Docker voraus.

Installation und Betrieb sollen sich wie eine normale Windows-Anwendung verhalten.

---

## 123. Repository als technische Source of Truth

Git ist die technische Source of Truth für:

- Quellcode;
- Alpha- und Beta-Spezifikationen;
- Schemas;
- Migrationen;
- Tests;
- Build- und Entwicklungswerkzeuge.

Git ist **nicht** die Source of Truth für persönliche ATHENA-Daten.

Der produktive Wissensbestand, Raw Archive, Personal Memory, Secrets und persönliche Konfiguration gehören nicht in das öffentliche Entwicklungsrepository.

---

## 124. Persönliche Daten niemals ins Projekt-Git

Insbesondere gehören nicht in das Entwicklungsrepository:

- persönliche Chats;
- Raw-Archive-Quellen;
- Knowledge-Einheiten des Benutzers;
- Personal Memory;
- geschützte Inhalte;
- Secrets und Tokens;
- produktive Datenbanken;
- produktiver Durable Operational State;
- persönliche Backups.

Test-Fixtures müssen synthetisch oder ausdrücklich für Tests freigegeben sein.

`.gitignore` und Test-/Dev-Pfade müssen diese Trennung unterstützen.

---

## 125. Vorgesehene Repository-Struktur

Erster Entwurf:

```text
ATHENA/
│
├── docs/
│   ├── alpha/
│   ├── beta/
│   └── architecture/
│
├── src/
│   └── athena/
│       ├── core/
│       ├── api/
│       ├── model/
│       ├── knowledge/
│       ├── archive/
│       ├── search/
│       ├── jobs/
│       ├── news/
│       ├── network/
│       ├── security/
│       ├── storage/
│       ├── backup/
│       ├── recovery/
│       ├── plugins/
│       ├── observability/
│       └── config/
│
├── ui/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── recovery/
│   └── migration/
│
├── scripts/
│
├── migrations/
│
├── schemas/
│
├── README.md
├── CHANGELOG.md
└── LICENSE
```

Diese Struktur ist noch Beta-Draft und darf während der technischen Spezifikation angepasst werden.

---

## 126. Entwicklungsprinzip

Wir implementieren ATHENA nicht horizontal vollständig.

Wir bauen zunächst einen vollständigen vertikalen Kernfluss.

---

## 127. Erster Vertical Slice

Der erste funktionierende Prototyp soll exakt folgenden Weg beherrschen:

```text
ATHENA starten
      │
      ▼
LM Studio über Provider erkennen
      │
      ▼
Benutzer schreibt Nachricht
      │
      ▼
Primärmodell antwortet
      │
      ▼
Chat gemäß Archivierungsregel persistent speichern
      │
      ▼
ATHENA beenden
      │
      ▼
ATHENA erneut starten
      │
      ▼
früheren Chat laden
```

Für die Archivierungslogik gilt bereits im ersten Slice die Alpha-Regel:

- Gespräche, die über sehr kurze Einmalinteraktionen hinausgehen, werden standardmäßig als Rohhistorie archiviert;
- ein `temporary` Chat darf nur innerhalb seines definierten temporären Lebenszyklus persistieren und wird danach vollständig aus langfristigem Raw Archive/Derived State entfernt;
- `do_not_store` beziehungsweise „nicht speichern“ persistiert keinen vollständigen Chat-Payload und besitzt keine inhaltliche Crash-Resume-Garantie;
- ausdrücklich aus einem temporären oder nicht gespeicherten Chat erzeugtes Knowledge/Personal Memory darf mit Benutzeraktions-Provenienz fortbestehen;
- archivierter Rohchat und später daraus extrahiertes Knowledge bleiben getrennt.

Noch keine komplexe Wissensextraktion.

---

## 128. Zweiter Vertical Slice

Danach wird der erste vollständige Wissensfluss gebaut:

```text
Chat
      │
      ▼
automatisierte Wissensextraktion durch aktives Primärmodell
      │
      ▼
strukturierte Vorschläge
      │
      ▼
Core-Validierung + Provenienz
      │
      ▼
atomare Knowledge-Einheiten
      │
      ▼
persistente Knowledge-Domäne
      │
      ▼
spätere Frage
      │
      ▼
Retrieval + Context Builder
      │
      ▼
Primärmodell
```

Parallel muss der Benutzer Wissenseinheiten direkt erstellen oder korrigieren können, ohne dass dafür eine künstliche Modellsignatur erzeugt wird.

Damit ist die zentrale ATHENA-Idee erstmals vollständig funktionsfähig.

---

## 129. Dritter Vertical Slice: große Quellen

Danach wird die robuste Verarbeitung großer Quellen implementiert:

```text
großes Dokument
      │
      ▼
Chunking
      │
      ▼
persistenter Job
      │
      ▼
Chunk-Verarbeitung
      │
      ▼
Checkpoint
      │
      ▼
Fortsetzung
      │
      ▼
hierarchische Synthese
```

Dieser Slice muss gezielt mit künstlich kleinen Kontextgrenzen getestet werden.

---

## 130. Vierter Vertical Slice: große Archive

Anschließend:

```text
großes Testarchiv
      │
      ▼
Indexierung
      │
      ▼
Normal Retrieval
      │
      ▼
Exhaustive Research
      │
      ▼
Checkpointed Synthesis
      │
      ▼
Antwort mit Coverage
```

Damit wird früh geprüft, dass die Architektur nicht nur mit kleinen Testdaten funktioniert.

---

## 131. Erst danach Ausbau

Anschließend folgen schrittweise:

```text
Concept Notes
↓
Wissensgraph
↓
erweiterte Queue
↓
Ressourcenmanager
↓
News
↓
Privacy-/Anonymisierungsschicht
(v1-Referenz: Tor)
↓
geschützte Bereiche
↓
Backup
↓
Recovery
↓
Obsidian
```

Die genaue Reihenfolge wird in der Entwicklungs-Roadmap festgelegt.

---

## 132. Kein Feature darf den Kernfluss destabilisieren

Für jede Erweiterung gilt:

```text
bestehende Tests
↓
neues Feature
↓
neue Tests
↓
vollständige Regression
↓
Merge
```

---

## 133. Definition des technischen Kerns

Der technische Kern von ATHENA besteht aus den Mechanismen, die unabhängig von UI, Modellbackend und Speicherort stabil bleiben müssen:

- Core- und Berechtigungsgrenzen;
- semantische Autoritätsregeln;
- getrennte autoritative persistente Domänen;
- stabile IDs und Provenienz;
- kontrollierte Persistenz;
- Retrieval und Context Builder;
- persistentes Job-/Checkpoint-System;
- Security und External Access Gateway;
- Recovery- und Integritätsregeln.

Modelle, UI-Frameworks, Datenbankprodukte, Indextechnologien und physische Speicherorte sind austauschbare Implementierungskomponenten.

---

## 134. Wichtigste Systemgrenze

ATHENAs dauerhaftes Wissen befindet sich nicht im Modellkontext.

```text
ATHENA Knowledge
≠
Model Context
```

und:

```text
ATHENA Identity
≠
Model Identity
```

Das Primärmodell verarbeitet vom Core bereitgestellten Kontext. Es besitzt weder das gesamte Gedächtnis noch direkten autoritativen Speicherzugriff.

Dies ist eine der wichtigsten Architekturgrenzen des Projekts.

---

## 135. Zweite zentrale Systemgrenze

Die Suchtechnologie besitzt ATHENAs Wissen nicht.

```text
Canonical Knowledge
      │
      ▼
Derived Search Index
```

Nicht umgekehrt.

Ein beschädigter oder ausgetauschter Index wird aus autoritativen Daten rekonstruiert.

---

## 136. Dritte zentrale Systemgrenze

Obsidian besitzt ATHENAs Wissen nicht.

```text
ATHENA Persistent Data
      │
      ▼
Markdown Projection
      │
      ▼
Obsidian
```

Nicht:

```text
Obsidian Plugin State
      │
      ▼
ATHENA Persistent Data
```

Manuelle Benutzeränderungen sind erlaubt, werden aber kontrolliert reconciliert und provenance-verknüpft.

---

## 137. Vierte zentrale Systemgrenze

LM Studio besitzt nicht ATHENAs Identität.

Es ist das erste Beta-v1-Modellbackend hinter `PrimaryModelProvider`.

ATHENA muss nach Austausch von LM Studio weiter funktionieren und seinen persistenten Bestand behalten können.

---

## 138. Fünfte zentrale Systemgrenze

Das Internet besitzt keine Autorität über ATHENA.

Externe Inhalte werden als Daten behandelt, niemals als Instruktionen an den Core.

Externe Quellen können Claims liefern. Sie dürfen weder Benutzerberechtigungen noch Systemregeln, Prompt-Injection-Grenzen oder kanonische Wahrheit automatisch festlegen.

---

## 139. Sechste zentrale Systemgrenze

Die Größe eines Datenbestands besitzt keine Autorität über das Modellkontextfenster.

```text
100 GB Archive
≠
100 GB Model Input
```

Der Search Service und die Processing Pipeline reduzieren große Datenräume kontrolliert auf begrenzte Arbeitseinheiten.

---

## 140. Siebte zentrale Systemgrenze

Ein Modellaufruf ist keine Transaktion über einen gesamten langlaufenden Job.

Ein Job besteht aus vielen einzeln bestätigten Verarbeitungsschritten.

Dadurch darf der Verlust eines einzelnen Modellaufrufs niemals den bereits erfolgreich verarbeiteten Gesamtfortschritt vernichten.

---

## 141. Verbindliche Robustheitsregel für Kontextgrenzen

Für jede Funktion, die das Primärmodell aufruft, gilt:

> **Kein Codepfad darf voraussetzen, dass eine unbekannte oder potenziell große Datenmenge vollständig in einen einzelnen Modellkontext passt.**

Dies gilt für:

- Dokumentanalyse
- Chatarchiv-Analyse
- Wissensextraktion
- Reinterpretation
- Recherche
- Zusammenfassungen
- News-Backfill
- Import
- globale Wissensanalysen

---

## 142. Verbindliche Robustheitsregel für Fortschritt

Für jeden langlaufenden wissensrelevanten Job gilt:

> **Bereits bestätigter Fortschritt darf durch Context Overflow, Modellfehler, Neustart oder Ressourcenunterbrechung nicht verloren gehen.**

---

## 143. Verbindliche Robustheitsregel für große Suchen

Für jede Suche gilt:

> **Die Gesamtgröße des durchsuchten Archivs darf niemals ungefiltert in das Modellkontextfenster übertragen werden.**

Bei normalen Fragen wird Retrieval verwendet.

Bei vollständigen Analysen werden Kandidaten persistent gesammelt und hierarchisch verarbeitet.

---

## 144. Verbindliche Ehrlichkeitsregel für vollständige Analysen

ATHENA darf nur dann behaupten, einen definierten Datenbereich vollständig analysiert zu haben, wenn die gespeicherten Coverage-Daten dies unterstützen.

Bei Fehlern, ausgelassenen Quellen oder nicht lesbaren Dateien wird die Analyse als teilweise beziehungsweise unvollständig gekennzeichnet.

---

## 145. Tests für Context Overflow

Die Test-Suite muss gezielt Situationen erzeugen, in denen:

- ein Chunk größer als das Modellfenster ist
- Retrieval mehr Material liefert als das Budget erlaubt
- ein Modell weniger Kontext besitzt als das vorherige Modell
- die Ausgabereserve unterschätzt wurde
- ein Modellaufruf wegen Context Limit scheitert

Erwartetes Verhalten:

```text
kein Datenverlust
+
kein falscher COMPLETED-Status
+
automatische Verkleinerung oder kontrollierter Retry
```

---

## 146. Tests für Resume

Ein Testjob mit vielen Chunks wird absichtlich unterbrochen.

Nach Neustart muss ATHENA:

- bestätigte Chunks erkennen
- unbestätigten Chunk erneut verarbeiten
- am richtigen Punkt fortfahren
- keine Duplikate erzeugen
- dasselbe vollständige Endergebnis erzeugen wie ein ununterbrochener Lauf

---

## 147. Tests für große Archive

ATHENA muss synthetische große Archive testen können, ohne dafür zwingend reale private Daten zu benötigen.

Geprüft werden mindestens:

- Indexskalierung
- Retrieval-Latenz
- Candidate Ranking
- Context Budget Enforcement
- Exhaustive Research
- Coverage Tracking
- Resume
- Index Rebuild

---

## 148. Beta-Regel für zukünftige Entscheidungen

Wenn in späteren Beta-Teilen zwei technische Lösungen möglich sind, wird bevorzugt:

1. geringere Gefahr für Datenintegrität,
2. geringere Abhängigkeit,
3. bessere Recovery-Fähigkeit,
4. einfachere Implementierung,
5. bessere Performance.

Performance allein rechtfertigt keine fragile Architektur.

---

## 149. Concurrency und autoritative Schreibkoordination

Parallele Berechnung ist erlaubt. Unkoordinierte parallele Änderungen autoritativer Daten sind nicht erlaubt.

Betroffen sind insbesondere:

- Knowledge;
- Personal Memory;
- Raw-Archive-Metadaten;
- Audit/Provenance;
- Configuration;
- kritischer Durable Operational State.

Der Persistence Layer beziehungsweise zuständige Domain Service muss konkurrierende Writes erkennen und transaktional koordinieren.

Die konkrete Strategie – Optimistic Concurrency, Revision Numbers, Compare-and-Swap, Locks oder eine Kombination – wird in Beta Kapitel 02 beziehungsweise dem Storage-Kapitel festgelegt.

---

## 150. Keine Lost Updates

Zwei konkurrierende Änderungen desselben autoritativen Objekts dürfen nicht dazu führen, dass eine bestätigte Änderung stillschweigend verschwindet.

Mögliche Reaktionen:

```text
Write A committed
Write B based on stale revision
        │
        ▼
Conflict detected
        │
        ├── safe merge
        ├── retry on new revision
        └── user/model conflict workflow
```

Ein stilles „last write wins“ ist für semantisch relevante Daten nicht der Standard.

---

## 151. Backpressure

ATHENA darf nicht unbegrenzt neue Arbeit erzeugen, wenn vorhandene Arbeit nicht schnell genug abgearbeitet werden kann.

Dies gilt insbesondere für:

- News-Backfill
- Massendokumentimport
- Embedding-Erzeugung
- Reindexierung
- Reinterpretation
- Exhaustive Research
- Synchronisationsjobs

Der Job Service und Resource Manager müssen Backpressure unterstützen.

---

## 152. Backpressure-Regel

Neue Arbeit wird abhängig von mindestens folgenden Faktoren erzeugt beziehungsweise freigegeben:

```text
Queue-Größe
CPU-Auslastung
RAM-Verfügbarkeit
GPU-/VRAM-Verfügbarkeit
freier Speicherplatz
Priorität
Benutzeraktivität
abhängige Jobs
```

ATHENA darf beispielsweise nicht Millionen konkrete Unterjobs vorab erzeugen, wenn diese auch kontrolliert in Batches materialisiert werden können.

---

## 153. Keine Informationslöschung durch Backpressure

Backpressure darf Arbeit verzögern, bündeln oder priorisieren.

Sie darf jedoch nicht:

- Originalquellen vergessen;
- bestätigte Benutzeränderungen verwerfen;
- notwendige Pending Work stillschweigend löschen;
- nicht anderweitig bestätigten Durable Operational State als Cache behandeln.

Wenn Arbeit noch nicht materialisiert wurde, muss persistent nachvollziehbar bleiben, dass sie aussteht, sofern sie für einen ausdrücklich geplanten Workflow erforderlich ist.

---

## 154. Kontrolliertes Cancel

Langlaufende Jobs müssen kontrolliert abgebrochen werden können.

Ein Cancel darf keinen undefinierten Zwischenzustand erzeugen.

Grundprinzip:

```text
Cancel requested
↓
aktuellen atomaren Schritt sicher beenden oder verwerfen
↓
Checkpoint aktualisieren
↓
keine weiteren Schritte starten
↓
Job = CANCELLED
```

---

## 155. Datenzustand nach Cancel

Nach einem kontrollierten Abbruch:

- bestätigte autoritative Daten bleiben erhalten;
- bestätigter und weiterhin benötigter Durable Operational State bleibt erhalten;
- rekonstruierbarer Derived State darf erhalten oder später verworfen werden;
- unbestätigte semantische Ergebnisse werden nicht übernommen;
- halbfertige autoritative Änderungen werden nicht committed;
- Provenienz und Jobstatus bleiben nachvollziehbar.

Der Benutzer kann später je nach Jobtyp:

- fortsetzen;
- neu starten;
- Derived State verwerfen;
- den Auftrag endgültig verwerfen.

Ein `CANCELLED`-Status darf nicht mit `COMPLETED` verwechselt werden.

---

## 156. Processing Reproducibility

Langlaufende Jobs müssen speichern, mit welcher Verarbeitungskonfiguration sie begonnen wurden.

Mindestens relevant sind, soweit zutreffend:

```text
model_provider
model_identifier
model_version_or_hash
quantization
generation_parameters
prompt_template_version
processing_pipeline_version
embedding_model_version
chunking_strategy_version
```

Nicht verfügbare Werte werden als unbekannt gekennzeichnet und nicht erfunden.

---

## 157. Model- und Prompt-Pinning

Ein laufender Job darf nach Modell-, Prompt- oder Pipelinewechsel nicht unbemerkt mit einer semantisch anderen Verarbeitung fortgesetzt werden.

Beispiel:

```text
Job beginnt
↓
Primary Model A
Prompt v3
Pipeline v5
↓
Unterbrechung
↓
System inzwischen:
Primary Model B
Prompt v4
Pipeline v6
```

ATHENA muss diese Abweichung erkennen.

---

## 158. Verhalten bei Processing Drift

Wenn die ursprüngliche Verarbeitungskonfiguration noch verfügbar und kompatibel ist, kann der Job damit fortgesetzt werden.

Andernfalls muss ATHENA kontrolliert entscheiden zwischen:

```text
betroffene Stage neu starten
```

oder:

```text
gemischte Verarbeitung ausdrücklich markieren
```

oder:

```text
Job pausieren und Benutzerentscheidung verlangen
```

Eine gemischte Verarbeitung darf niemals unsichtbar stattfinden.

---

## 159. Processing Lineage

Ergebnisse müssen soweit relevant auf die Verarbeitung zurückführbar sein, die sie erzeugt hat.

Damit kann ATHENA später beispielsweise feststellen:

- welche Wissenseinheiten mit einem alten Extraktionsprompt erzeugt wurden;
- welche Chunks mit einem anderen Primärmodell analysiert wurden;
- welche Embeddings oder Indizes nach einem Pipeline-Upgrade neu erzeugt werden sollten;
- welche Ergebnisse direkt durch den Benutzer erstellt oder korrigiert wurden.

Für direkte Benutzeränderungen existiert ein Herkunftsakteur `user`, aber keine erfundene Modellsignatur.

Processing Lineage bildet die Grundlage für kontrollierte Reinterpretation, Migration und Audit.

---

## 160. Snapshot-Konsistenz bei großen Analysen

Eine langlaufende Recherche benötigt einen definierten Datenstand.

Wenn sich das Archiv während einer mehrstündigen oder mehrtägigen Analyse verändert, darf die untersuchte Grundgesamtheit nicht unkontrolliert mitwachsen.

Jeder Exhaustive-Research-Job erhält deshalb einen definierten Research Scope.

---

## 161. Research Scope

Ein Research Scope beschreibt mindestens:

```text
scope_id
query
included_collections
relevant_filters
snapshot_boundary
created_at
```

Die konkrete technische Snapshot-Implementierung wird später festgelegt.

Die logische Anforderung ist verbindlich:

> **ATHENA muss eindeutig bestimmen können, welche Daten zu einer behaupteten vollständigen Analyse gehörten.**

---

## 162. Snapshot Boundary

Die Snapshot Boundary kann beispielsweise durch:

- Datenbankrevision,
- Import-Sequenz,
- Zeitgrenze,
- Source-Versionen

repräsentiert werden.

Neue Quellen, die nach dieser Grenze eintreffen, werden nicht stillschweigend Teil des bereits laufenden Research Jobs.

---

## 163. Delta Research

Neue Daten können nach Abschluss eines Snapshot-basierten Research Jobs separat als Delta verarbeitet werden.

Beispiel:

```text
Research Snapshot A
↓
vollständig verarbeitet
↓
später neue Quellen
↓
Delta A→B
↓
inkrementelle Ergänzung
```

Damit muss eine große historische Analyse nicht zwingend vollständig neu gestartet werden.

---

## 164. Coverage bezieht sich auf Snapshot

Ein Coverage-Status wie:

```text
COMPLETE
```

bezieht sich immer auf den definierten Research Scope und dessen Snapshot Boundary.

`COMPLETE` bedeutet nicht automatisch:

> alle Daten, die zum Zeitpunkt der späteren Anzeige inzwischen in ATHENA existieren.

Diese Unterscheidung muss in Provenienz und UI nachvollziehbar bleiben.

---

## 165. Speicherplatz als harte Ressourcengrenze

Freier Speicherplatz wird als kritische Systemressource behandelt.

ATHENA darf lokale oder langfristige Datenträger nicht absichtlich bis zur vollständigen Erschöpfung füllen.

Der Resource Manager überwacht deshalb mindestens die für ATHENA relevanten Speicherorte.

---

## 166. Disk-Space-Schwellen

ATHENA definiert konfigurierbare Speicherzustände, beispielsweise:

```text
NORMAL
WARNING
CRITICAL
EMERGENCY
```

Die konkreten Grenzwerte werden später festgelegt und können absolute sowie prozentuale Reserven berücksichtigen.

---

## 167. Verhalten bei knappem Speicher

Bei sinkendem freien Speicherplatz werden Maßnahmen nach Schutzklasse ausgeführt.

Grundprinzip:

```text
nichtkritische neue Jobs drosseln
↓
große Derived-State-Jobs pausieren
↓
sicher löschbare Caches bereinigen
↓
rein rekonstruierbaren Temporary State bereinigen
↓
Benutzer deutlich warnen
↓
Emergency Reserve schützen
↓
notfalls nichtkritische Writes stoppen
```

ATHENA Persistent Data und nicht anderweitig bestätigter Durable Operational State werden **niemals automatisch gelöscht**, nur um Platz zu schaffen.

Einzig explizite Benutzerentscheidungen beziehungsweise definierte Aufbewahrungsregeln dürfen autoritative Inhalte löschen.

---

## 168. Emergency Reserve

ATHENA schützt nach Möglichkeit eine definierte Speicherreserve für kritische Integritätsoperationen.

Dazu gehören insbesondere:

- Abschluss oder Rollback einer Transaktion;
- Persistieren eines notwendigen Checkpoints;
- Schreiben eines kritischen Audit-/Recovery-Eintrags;
- sauberes Herunterfahren;
- Recovery-Metadaten;
- sichere Behandlung noch nicht bestätigter Writes.

Nichtkritische Verarbeitung wird vor Verbrauch dieser Reserve gestoppt.

---

## 169. Kein stiller Fallback auf anderen Speicher

Bei vollem oder nicht erreichbarem Zielmedium darf ATHENA autoritative Daten oder nicht bestätigten Durable Operational State nicht stillschweigend an einem beliebigen anderen Ort ablegen.

Ein alternativer Speicherort muss:

- vorab konfiguriert;
- eindeutig gekennzeichnet;
- und für den jeweiligen Zweck autorisiert

sein.

Andernfalls wird kontrolliert in vorgesehenem Durable Operational State gepuffert oder der Schreibvorgang gestoppt.

---

## 170. Verbindliche Robustheitsregeln

Zusätzlich zu den bisherigen Regeln gelten:

> **Concurrency darf keine bestätigten autoritativen Änderungen verlieren lassen.**

> **Backpressure darf Arbeit verzögern, aber keine notwendige Arbeit vergessen lassen.**

> **Cancel darf keinen halbfertigen autoritativen Zustand hinterlassen.**

> **Ein langlaufender Job darf Modell-, Prompt- oder Pipelinewechsel nicht unbemerkt über seine Verarbeitung mischen.**

> **Vollständigkeitsangaben beziehen sich auf einen definierten Snapshot beziehungsweise Research Scope.**

> **ATHENA schützt eine Speicherreserve für Datenintegrität, Checkpoints, Durable Operational State und Recovery.**

> **Kritische Integritäts- oder Sicherheitsfehler dürfen betroffene Schreiboperationen stoppen und ATHENA kontrolliert in Read-Only oder Recovery versetzen.**

---

## 171. Ergänzte Tests für Teil 1

Die spätere Test-Suite muss zusätzlich mindestens folgende Szenarien abdecken:

### Concurrent Write Test

Zwei Jobs versuchen konkurrierende Änderungen desselben kanonischen Objekts.

Erwartung:

```text
kein Lost Update
+
deterministisch behandelter Konflikt
```

### Queue Backpressure Test

Sehr viele Quellen erzeugen schneller Folgearbeit als Worker sie verarbeiten können.

Erwartung:

```text
stabile Queue
+
keine verlorene Arbeit
+
kein unkontrolliertes RAM-/Disk-Wachstum
```

### Cancel/Resume Test

Ein großer Job wird während der Verarbeitung abgebrochen.

Erwartung:

```text
kein halber Commit
+
bestätigter Fortschritt nachvollziehbar
+
kontrollierte Fortsetzung oder Neustart möglich
```

### Processing Drift Test

Zwischen zwei Job-Stages werden Modell, Prompt oder Pipeline geändert.

Erwartung:

```text
Drift erkannt
+
keine unsichtbare Mischverarbeitung
```

### Snapshot Consistency Test

Während eines Exhaustive-Research-Jobs werden neue passende Quellen importiert.

Erwartung:

```text
laufender Snapshot bleibt stabil
+
neue Quellen als Delta identifizierbar
```

### Disk-Full Test

Während eines Jobs wird künstlich kritischer Speichermangel erzeugt.

Erwartung:

```text
nichtkritische Arbeit stoppt
+
Checkpoint bleibt möglich
+
kein beschädigtes kanonisches Wissen
+
kein automatisches Löschen von Originalen
```

---

## 172. Ergebnis dieses Beta-Kapitels

Mit Kapitel 01 stehen die wichtigsten technischen Systemgrenzen für die erste Implementierung fest:

```text
Windows Desktop First

Python Core

modularer lokaler Monolith

lokale versionierte Core API

LM Studio über austauschbaren PrimaryModelProvider

genau ein aktives Primärmodell für automatisierte semantische Entscheidungen

Benutzer als höchste semantische Autorität

ATHENA Persistent Data:
Knowledge
Personal Memory
Raw Archive
Audit & Provenance
Configuration

Durable Operational State getrennt von Derived State

SQLite als Ausgangspunkt

Raw Archive getrennt vom Wissensgraph

persistente Queue und Checkpoints

dynamisches Context Budgeting

Personal Memory als separate Context-Quelle

automatische Chunk-Verkleinerung

hierarchische Verarbeitung

Normal Retrieval

Exhaustive Research

Coverage Tracking

Concurrency Control

Backpressure

kontrolliertes Cancel

Model-/Prompt-/Pipeline-Pinning

Processing Lineage

Snapshot-konsistentes Research

Delta Research

Disk-Space-Schutz und Emergency Reserve

zentraler Resource Manager

External Access Gateway

Privacy-/Anonymisierung mit Fail Closed

Tor als Beta-v1-Referenzimplementierung

Security Service

Backup + Recovery

Markdown/Obsidian als Projektion

Git für Code und Spezifikationen, nicht für persönliche ATHENA-Daten
```

---

## 173. Noch nicht endgültig festgelegt

Bewusst offen bleiben:

- Desktop-UI-Framework;
- konkretes SQLite-Schema;
- konkreter Vektorindex;
- Embedding-Modell;
- Verschlüsselungsbibliothek;
- Secrets-Speicher;
- konkrete lokale API-Technologie;
- genauer Tor-Integrationsweg beziehungsweise Adapter;
- Obsidian-Reconciliation-Format;
- Installer-Technologie;
- exakte Chunk-Größen;
- exakte Overlap-Werte;
- exakte Context-Safety-Margin;
- konkrete Retrieval-K-Werte;
- konkreter Re-Ranker;
- Schwellenwerte für automatischen Exhaustive Research Mode;
- konkrete Concurrency-Strategie;
- konkrete Persistenz- und Backup-Formate für jede Domäne.

Diese Entscheidungen werden nicht spontan beim Coding getroffen. Sie werden in den folgenden Beta-Kapiteln entschieden und anhand der realen Referenzplattform getestet.

---

## 174. Nächstes Beta-Kapitel

**Beta Kapitel 02 – Persistentes Datenmodell und ID-System** konkretisiert die in diesem Kapitel festgelegten Persistenz- und Identitätsanforderungen.

Es definiert insbesondere:

- globale ID-Regeln;
- `KnowledgeUnit`;
- `Claim`;
- `Interpretation`;
- `Source`;
- `SourceChunk`;
- `Chat`;
- `ChatMessage`;
- `PersonalMemoryEntry`;
- `Relationship`;
- `Project`;
- `ConceptNote`;
- `ProvenanceRecord`;
- `AuditEvent`;
- `ModelSignature`;
- `Job`;
- `Checkpoint`;
- `CandidateSet`;
- `ResearchScope`;
- `Configuration`;
- Versionierung;
- Revisionen und Concurrency;
- Processing Lineage.

Mindestens die folgenden IDs werden dort konkret spezifiziert:

```text
knowledge_id
claim_id
source_id
chunk_id
chat_id
message_id
memory_id
relation_id
project_id
concept_note_id
provenance_id
audit_event_id
job_id
checkpoint_id
candidate_set_id
research_scope_id
```

Kapitel 02 muss außerdem eindeutig festlegen, wie direkte Benutzeränderungen ohne Modellsignatur, modellgestützte Änderungen mit Modellsignatur und importierte Quellen provenance-seitig unterschieden werden.

---

## Leitregel von Beta Kapitel 01

> **ATHENA wird als lokaler, modularer Core gebaut. Der Benutzer behält die höchste semantische Autorität. Das aktive Primärmodell ist die einzige automatisierte KI-Komponente mit semantischer Entscheidungsbefugnis. Knowledge, Personal Memory, Raw Archive, Audit/Provenance und Configuration bleiben getrennte autoritative Domänen von ATHENA Persistent Data. Durable Operational State wird gegen Verlust geschützt, während Derived State rekonstruierbar bleibt. Modelle, Speicher, Suche, UI und externe Dienste sind austauschbare Komponenten. Das Kontextfenster begrenzt nur, wie viel ATHENA gleichzeitig verarbeitet – niemals, wie viel ATHENA insgesamt speichern, durchsuchen oder analysieren kann.**
