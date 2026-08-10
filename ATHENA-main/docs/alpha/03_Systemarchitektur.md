# Kapitel 3 – Systemarchitektur

---

## Einleitung

Dieses Kapitel beschreibt die grundlegende Architektur von ATHENA.

Es definiert die logischen Hauptkomponenten des Systems und ihre Verantwortlichkeiten.

Die konkrete technische Umsetzung wird bewusst nicht beschrieben.

Unabhängig von Programmiersprache, Betriebssystem oder zukünftiger Hardware muss jede Implementierung dieser Architektur folgen.

---

## Architekturprinzip

ATHENA besteht aus einem stabilen Kern und klar voneinander getrennten Modulen.

Jede Komponente besitzt eine eindeutig definierte Aufgabe.

Keine Komponente darf Aufgaben übernehmen, die einer anderen Komponente zugewiesen sind.

Dadurch bleibt das System langfristig wartbar, austauschbar und nachvollziehbar.

---

## Die Architektur

ATHENA besteht logisch aus folgenden Hauptbereichen:

```text
Benutzer

        │

        ▼

Benutzeroberfläche

        │

        ▼

ATHENA Core

        │

 ┌──────┼───────────────┐

 │      │               │

 ▼      ▼               ▼

Wissenssystem     Modellsystem     Hintergrundsystem

 │      │               │

 └──────┼───────────────┘

        ▼

Persistenter Datenspeicher
```

Jede Kommunikation läuft über den ATHENA Core.

Keine Komponente kommuniziert direkt mit einer anderen, wenn dies den Core umgehen würde.

Der Core ist die zentrale Koordinationsinstanz.

---

## Der ATHENA Core

Der Core bildet das Herz des Systems.

Er besitzt folgende Aufgaben:

- Koordination aller Module

- Benutzeranfragen entgegennehmen

- Hintergrundaufgaben verwalten

- Regeln der Architektur durchsetzen

- Integrität des Wissens gewährleisten

- Prioritäten verwalten

- Sicherheitsregeln anwenden

Der Core enthält selbst keine fachlichen Wissensinhalte.

Er organisiert deren Verarbeitung.

## Persistente Datendomänen
„ATHENA Persistent Data“ ist der Oberbegriff für die autoritativen, langfristig zu erhaltenden Systemdaten. Darunter bleiben logisch getrennte Domänen bestehen:

- **Knowledge** – kanonisches semantisches Wissen, einschließlich externen/referenzierten und persönlichen projektbezogenen Wissens
- **Personal Memory** – dauerhaft relevante Präferenzen, Gewohnheiten und Einstellungen für die Zusammenarbeit mit dem Benutzer
- **Raw Archive** – Originalquellen und deren Versionen
- **Audit and Provenance** – Herkunft, Änderungen und Nachvollziehbarkeit
- **Configuration** – autoritative Benutzer- und Systemkonfiguration

Persönliches Gedächtnis ist damit Teil von ATHENA Persistent Data, aber keine Unterkategorie des Wissensgraphen. Die Domänen dürfen einander referenzieren, bleiben jedoch logisch sowie hinsichtlich ihrer Provenienz-, Schutz-, Aufbewahrungs- und Änderungsregeln getrennt.

Zusätzlich darf ATHENA **Durable Operational State** führen, etwa persistente Queue-Einträge, Checkpoints, Transaktionsjournale und noch nicht bestätigte Synchronisationspuffer. Dieser Zustand ist keine zusätzliche semantische Wissensdomäne und keine Quelle für bereits bestätigt persistiertes Wissen. Solange er jedoch noch nicht anderweitig bestätigte Informationen enthält, ist er nicht entbehrlich und muss gegen Verlust geschützt werden.

Davon getrennt steht **Derived State** wie Suchindizes, Embeddings, Caches und Vorschauen. Dieser Zustand ist aus autoritativen Daten rekonstruierbar und darf niemals die einzige Kopie relevanter Informationen enthalten.

---

## Das Wissenssystem

Das Wissenssystem verwaltet die kanonische Knowledge-Domäne innerhalb von ATHENA Persistent Data.

Hierzu gehören insbesondere:

- Wissenseinheiten
- aktives Wissensnetz
- Langzeitwissen und archivierte Wissenseinheiten
- Projekte
- Concept Notes
- Themen
- Beziehungen zwischen Wissenseinheiten
- semantische Versionen und Vertrauensinformationen

Originalquellen liegen in der getrennten Raw-Archive-Domäne. Persönliche Präferenzen liegen in der getrennten Personal-Memory-Domäne. Beide können mit der Knowledge-Domäne verknüpft werden, ohne mit ihr zu verschmelzen.

Die autoritativen persistenten Domänen bilden gemeinsam den maßgeblichen langfristigen Systemzustand von ATHENA; abgeleitete Indizes, Embeddings und Caches sind keine eigenständigen Wissensquellen.

---

## Das Modellsystem

Das Modellsystem stellt KI-Funktionen bereit.

Es besteht aus:

- genau einem Primärmodell

- beliebig vielen Infrastrukturmodellen

Das Modellsystem besitzt keine dauerhafte Wissenshaltung.

Es verarbeitet Informationen ausschließlich im Auftrag des ATHENA Core.

---

## Das Hintergrundsystem

Das Hintergrundsystem führt zeitlich unabhängige Aufgaben aus.

Hierzu gehören beispielsweise:

- News-Workflow

- Backfills

- Synchronisation

- OCR

- Reorganisation

- Backup

- Wartung

- Index-Neuaufbau

Alle Aufgaben werden über eine persistente Queue verwaltet.

---

## Der persistente Datenspeicher
Der persistente Datenspeicher von ATHENA hält die autoritativen Domänen von ATHENA Persistent Data dauerhaft vor.

Dazu gehören insbesondere:

- kanonische Wissenseinheiten und Beziehungen
- Originalquellen und Quellenversionen
- Personal-Memory-Einträge
- Audit- und Provenienzinformationen
- autoritative Konfiguration

Durable Operational State wird getrennt verwaltet, aber solange notwendig ebenso zuverlässig persistiert.

Rein abgeleitete oder flüchtige technische Daten gehören ausdrücklich nicht zur autoritativen Datenbasis. Dazu zählen beispielsweise rekonstruierbare Suchindizes, Embeddings, Caches und Vorschauen.

Die technische Implementierung darf diese Bereiche auf verschiedene Datenbanken, Dateisysteme oder Datenträger verteilen. Ihre logische Rollenverteilung bleibt davon unberührt.

---

## Benutzeroberfläche

Die Benutzeroberfläche besitzt ausschließlich Präsentationsaufgaben.

Sie darf keinerlei Geschäftslogik enthalten.

Anwendungslogik und Systementscheidungen werden durch den ATHENA Core koordiniert. Benutzerentscheidungen gelangen über autorisierte Clients in den Core und besitzen die in Kapitel 2 definierte Autorität.

Dadurch kann dieselbe Architektur später von verschiedenen Clients verwendet werden, beispielsweise:

- Desktop

- Mobile

- Web

- Terminal

- API

Alle greifen auf denselben logischen Core und denselben autoritativen persistenten Systemzustand zu.

---

## Kommunikationsprinzip

Sämtliche Kommunikation erfolgt ausschließlich über den ATHENA Core.

Beispielsweise:

```text
Benutzer

↓

Core

↓

Primärmodell

↓

Core

↓

Wissenssystem
```

Nicht zulässig:

```text
Primärmodell
↓
Wissenssystem

oder

UI
↓
Wissensspeicher
```

Der Core bleibt die einzige koordinierende Instanz.

---

## Single Source of Truth
ATHENA besitzt keine einzelne „Wahrheitsdatei“. Die gemeinsam verwalteten autoritativen Domänen von **ATHENA Persistent Data** bilden den maßgeblichen persistenten Systemzustand.

Innerhalb dieser Struktur gilt:

- **Knowledge** ist die autoritative Quelle für kanonisches semantisches Wissen.
- **Raw Archive** ist die autoritative Quelle für erhaltene Originalquellen und deren Versionen.
- **Personal Memory** ist die autoritative Quelle für dauerhaft gespeicherte Präferenzen und Zusammenarbeitseinstellungen.
- **Audit and Provenance** ist die autoritative Quelle für Herkunfts- und Änderungshistorie.
- **Configuration** ist die autoritative Quelle für Benutzer- und Systemkonfiguration.

Durable Operational State kann vorübergehend die einzige noch nicht bestätigt persistierte Kopie einer neuen Information enthalten. Er ist deshalb bis zum bestätigten Commit oder zur bestätigten Synchronisation geschützt, wird dadurch aber nicht zur alternativen kanonischen Wissensquelle.

Abgeleitete Komponenten wie:

- Cache
- Embeddings
- Suchindex
- Vorschauen
- rein abgeleitete temporäre Daten

sind rekonstruierbar und gelten niemals als Primär- oder Originalquelle.

---

## Modularität

Jedes Modul besitzt klar definierte Verantwortlichkeiten.

Module dürfen:

- ergänzt,

- entfernt,

- ersetzt,

- aktualisiert

werden, ohne den Kern des Systems zu verändern.

Dies gilt insbesondere für:

- Modelle

- Plugins

- Infrastrukturmodule

- Benutzeroberflächen

---

## Graceful Degradation
Fällt eine nichtkritische oder optionale Komponente aus, arbeitet ATHENA mit der bestmöglichen verbleibenden Funktionalität weiter.

Der Ausfall einer einzelnen nichtkritischen Komponente soll den Gesamtbetrieb nicht unnötig verhindern.

Beispiele:

- Embeddings ausgefallen → Volltextsuche bleibt verfügbar.
- OCR ausgefallen → Verarbeitung vormerken und später erneut versuchen.
- NAS offline → neue Daten in geschütztem Durable Operational State lokal puffern.
- Internet nicht verfügbar → lokales Wissen bleibt nutzbar.

Kann dagegen die Integrität autoritativer Daten, eines kritischen Schreibvorgangs oder einer Sicherheitsgrenze nicht garantiert werden, darf ATHENA betroffene Schreiboperationen bewusst stoppen und in einen Read-Only- oder Recovery-Zustand wechseln. Datenintegrität besitzt Vorrang vor erzwungenem Weiterbetrieb.

---

## Beobachtbarkeit

Der ATHENA Core überwacht kontinuierlich den Zustand aller wesentlichen Komponenten.

Hierzu gehören unter anderem:

- Primärmodell

- Infrastrukturmodelle

- Queue

- Wissensspeicher

- Netzwerkstatus

- Sicherungen

- Suchindex

- Hintergrunddienste

Fehler werden nachvollziehbar protokolliert und verständlich dargestellt.

---

## Abschluss des Kapitels

Die Systemarchitektur bildet das stabile Fundament von ATHENA.

Alle nachfolgenden Kapitel beschreiben einzelne Bereiche dieser Architektur im Detail.

Keine spätere Implementierung darf die in diesem Kapitel definierten Verantwortlichkeiten oder Kommunikationswege verändern.
