# Kapitel 2 – Philosophie und Leitprinzipien

---

## 1. Zweck dieses Kapitels

Dieses Kapitel definiert die grundlegenden philosophischen und architektonischen Prinzipien von ATHENA.

Diese Prinzipien stehen über konkreten technischen Implementierungen.

Technologien, Modelle, Datenbanken, Benutzeroberflächen und Infrastruktur dürfen sich ändern.

Die hier definierten Prinzipien bleiben bestehen.

---

## 2. Benutzerhoheit

ATHENA existiert ausschließlich als Werkzeug des Benutzers.

Der Benutzer besitzt die höchste Autorität über:

- gespeicherte Informationen
- persönliche Daten
- Wissensstrukturen
- Modelle
- externe Zugriffe
- Automatisierungen
- Plugins
- Sicherheitsbereiche
- Löschvorgänge
- Systemkonfiguration

ATHENA darf diese Hoheit nicht durch autonome Entscheidungen umgehen.

Der Benutzer kann gespeichertes Wissen einsehen, korrigieren, ergänzen oder löschen.

---

## 3. Semantische Autorität

ATHENA unterscheidet strikt zwischen:

- Benutzer
- aktivem Primärmodell
- Infrastrukturmodellen
- technischen Algorithmen
- externen Quellen

Für semantische Änderungen am kanonischen Wissensbestand gilt:

> **Nur der Benutzer und das aktive Primärmodell dürfen semantische Änderungen am kanonischen Wissen veranlassen.**

Der Benutzer besitzt dabei die höchste Autorität.

Eine ausdrückliche Entscheidung oder Korrektur des Benutzers hat Vorrang vor einer Interpretation des Primärmodells.

---

## 4. Rolle des Primärmodells

Das aktive Primärmodell ist ATHENAs einzige KI-Komponente mit semantischer Entscheidungsbefugnis über den Wissensbestand.

Es darf im Rahmen der vom Benutzer festgelegten Regeln:

- Wissen extrahieren
- Aussagen interpretieren
- Beziehungen erkennen
- Wissenseinheiten erzeugen
- bestehendes Wissen aktualisieren
- Widersprüche erkennen
- Zusammenfassungen erzeugen
- Relevanz semantisch bewerten

Diese Befugnisse gelten ausschließlich innerhalb der vom ATHENA Core kontrollierten Prozesse.

Das Primärmodell erhält keinen unkontrollierten direkten Schreibzugriff auf den persistenten Wissensspeicher.

---

## 5. Rolle des Benutzers

Der Benutzer darf kanonisches Wissen direkt:

- erstellen
- bearbeiten
- korrigieren
- ergänzen
- zusammenführen
- neu klassifizieren
- archivieren
- löschen

Manuelle Änderungen des Benutzers sind keine Ausnahme vom Wissensmodell.

Sie sind ein ausdrücklich vorgesehener Bestandteil von ATHENA.

ATHENA muss die Herkunft solcher Änderungen als Benutzeränderung nachvollziehbar speichern.

---

## 6. Benutzerentscheidung vor Modellentscheidung

Wenn eine explizite Benutzerentscheidung einer früheren Modellinterpretation widerspricht, darf ATHENA die Benutzerentscheidung nicht stillschweigend durch eine erneute Modellinterpretation überschreiben.

Beispiel:

```text
Primärmodell:
Person A arbeitet bei Unternehmen X.

↓

Benutzer korrigiert:
Person A arbeitet nicht mehr bei Unternehmen X.

↓

ATHENA:
Benutzerkorrektur wird gespeichert
+
alte Aussage bleibt historisch nachvollziehbar
+
Primärmodell darf die Korrektur nicht ohne neue Evidenz stillschweigend rückgängig machen
```

Benutzeränderungen müssen deshalb in Provenienz und Versionierung eindeutig erkennbar sein.

---

## 7. Infrastrukturmodelle

Infrastrukturmodelle unterstützen ATHENA technisch.

Beispiele:

- Embedding-Modelle
- OCR-Modelle
- Speech-to-Text-Modelle
- Text-to-Speech-Modelle
- Bildanalyse-Hilfsmodelle
- technische Klassifikatoren

Für diese Modelle gilt:

> **Infrastrukturmodelle dürfen keine eigenständigen semantischen Wissensentscheidungen treffen.**

Sie dürfen technische Repräsentationen oder Verarbeitungsergebnisse erzeugen.

Beispiele:

```text
Text
↓
Embedding-Modell
↓
Vektor
```

oder:

```text
Bild
↓
OCR
↓
extrahierter Text
```

Der resultierende Text oder Vektor ist dadurch noch keine autonome semantische Entscheidung über ATHENAs kanonischen Wissensbestand.

---

## 8. Technische Algorithmen

Auch deterministische Algorithmen besitzen keine semantische Autorität.

Beispiele:

- Volltextsuche
- Ranking
- Hashing
- Deduplizierung
- Dateierkennung
- Chunking
- Indexierung
- Scheduler
- Ressourcenmanager

Diese Systeme dürfen Informationen technisch verarbeiten, sortieren und transportieren.

Sie dürfen jedoch nicht eigenständig bestimmen, was ATHENA als semantisch wahres oder kanonisches Wissen akzeptiert.

---

## 9. Externe Quellen

Externe Quellen besitzen keine direkte Autorität über ATHENAs Wissensbestand.

Dazu gehören beispielsweise:

- Webseiten
- Nachrichten
- wissenschaftliche Publikationen
- Bücher
- APIs
- soziale Netzwerke
- importierte Dokumente

Eine externe Aussage wird zunächst als Aussage einer Quelle behandelt.

Sie wird nicht allein aufgrund ihrer Existenz zur Wahrheit innerhalb ATHENAs.

---

## 10. Provenienz

Jede relevante Wissenseinheit muss nachvollziehbar machen können, woher sie stammt.

Mögliche Ursprünge sind insbesondere:

```text
Benutzer

Primärmodell aus Benutzerkommunikation

Primärmodell aus externer Quelle

importiertes Dokument

Nachrichtenquelle

manuelle Benutzerbearbeitung

abgeleitete Wissenseinheit
```

ATHENA soll soweit möglich zwischen:

- Quelle
- Interpretation
- Ableitung
- Benutzerkorrektur

unterscheiden.

---

## 11. Original vor Interpretation

Originalquellen besitzen Vorrang als historische Evidenz.

Interpretationen dürfen das Original nicht ersetzen.

Grundprinzip:

```text
Original
↓
Interpretation
↓
Wissen
```

Nicht:

```text
Interpretation
↓
Original wird überschrieben
```

Dadurch können spätere Modelle oder der Benutzer frühere Interpretationen erneut überprüfen.

---

## 12. Modellunabhängigkeit

ATHENA darf nicht mit der Identität eines bestimmten Sprachmodells gleichgesetzt werden.

Das Primärmodell ist austauschbar.

```text
ATHENA
≠
Primärmodell
```

Das Modell interpretiert den von ATHENA bereitgestellten Kontext.

ATHENAs dauerhaftes Gedächtnis liegt außerhalb des Modellkontextfensters.

---

## 13. Modellwechsel

Ein Modellwechsel darf nicht automatisch bedeuten:

- Verlust des Wissens
- Verlust des Archivs
- Verlust persönlicher Erinnerungen
- Verlust von Provenienz
- Neuaufbau des gesamten Systems

Ein neues Primärmodell übernimmt den bestehenden ATHENA-Wissensbestand über die dafür vorgesehenen Core-Schnittstellen.

---

## 14. Inhaltsneutralität

ATHENA soll technisch nicht davon abhängig sein, dass Informationen bestimmten politischen, gesellschaftlichen, philosophischen oder kulturellen Positionen entsprechen.

Das System speichert Quellen, Aussagen, Beziehungen und Provenienz.

Es darf unterschiedliche oder widersprüchliche Positionen nebeneinander abbilden.

---

## 15. Widersprüche

Widersprüchliche Informationen werden nicht automatisch gelöscht oder künstlich harmonisiert.

ATHENA kann beispielsweise speichern:

```text
Quelle A → Aussage X

Quelle B → Aussage Y

Benutzer → Einschätzung Z
```

Der Widerspruch selbst kann eine relevante Wissensinformation darstellen.

---

## 16. Unsicherheit

ATHENA muss Unsicherheit darstellen können.

Nicht jede Wissenseinheit besitzt denselben epistemischen Status.

Mögliche Zustände können später beispielsweise unterscheiden zwischen:

- bestätigt
- wahrscheinlich
- unklar
- umstritten
- widerlegt
- Interpretation
- persönliche Einschätzung

Die konkrete technische Modellierung wird in der Beta-Spezifikation festgelegt.

---

## 17. Keine erfundene Sicherheit

ATHENA darf fehlende Informationen nicht als bekannte Fakten darstellen.

Wenn Herkunft, Modellinformation, Zeitangabe oder Vertrauensstatus unbekannt ist, wird dies als unbekannt behandelt.

---

## 18. Nachvollziehbarkeit

ATHENA soll relevante semantische Veränderungen nachvollziehbar machen.

Dazu gehören insbesondere:

- wer oder was eine Änderung veranlasst hat
- welche Quelle zugrunde lag
- welches Primärmodell beteiligt war
- wann die Änderung erfolgte
- welche vorherige Version existierte

---

## 19. Reversibilität

Soweit technisch und rechtlich sinnvoll, sollen Änderungen reversibel sein.

Dies betrifft insbesondere:

- Wissensänderungen
- automatische Verarbeitung
- Modellinterpretationen
- Systemupdates
- Konfigurationsänderungen

Ausdrücklich endgültig bestätigte Löschungen bilden eine Ausnahme.

---

## 20. Keine versteckte Autonomie

ATHENA darf keine weitreichenden Aktionen allein deshalb durchführen, weil das Primärmodell sie für sinnvoll hält.

Insbesondere externe Aktionen benötigen die dafür vorgesehenen Berechtigungen und Kontrollmechanismen.

Wissen über eine mögliche Handlung ist nicht automatisch die Erlaubnis, diese Handlung auszuführen.

---

## 21. Trennung von Denken und Handeln

ATHENA unterscheidet grundsätzlich zwischen:

```text
Information verstehen
```

und:

```text
externe Handlung ausführen
```

Das Primärmodell darf analysieren und Vorschläge erzeugen.

Externe Aktionen unterliegen separaten Berechtigungen.

---

## 22. Local-First-Prinzip

ATHENAs Kernwissen und zentrale Steuerung sollen unter Kontrolle des Benutzers bleiben.

Externe Dienste dürfen nicht zur zwingenden Voraussetzung für den Zugriff auf das eigene Wissen werden.

ATHENA muss seine wesentlichen lokalen Wissensfunktionen auch ohne Internetverbindung bereitstellen können.

---

## 23. Datenhoheit

Der Benutzer muss langfristig die Möglichkeit besitzen, seine Daten:

- zu exportieren
- zu sichern
- wiederherzustellen
- auf andere Datenträger zu verschieben
- mit zukünftigen ATHENA-Versionen zu migrieren

ATHENA darf keinen absichtlichen Vendor Lock-in für den eigenen Wissensbestand erzeugen.

---

## 24. Trennung von autoritativen, operationalen und abgeleiteten Daten

ATHENA unterscheidet drei grundlegende Zustandsklassen mit unterschiedlicher Schutzpriorität.

### Autoritative Persistent Data

Hierzu gehören insbesondere:

- Raw Archive und erhaltene Originalquellen
- Knowledge und kanonisches semantisches Wissen
- Personal Memory
- Audit and Provenance
- Configuration

Diese Domänen bilden gemeinsam den autoritativen persistenten Systemzustand. Die jeweilige Domäne ist für ihren Inhalt maßgeblich.

### Durable Operational State

Hierzu können insbesondere gehören:

- noch nicht bestätigte Schreibvorgänge
- persistente Queue-Einträge
- Checkpoints
- Transaktionsjournale
- lokale Offline- und Synchronisationspuffer

Durable Operational State ist keine alternative kanonische Wissensquelle. Er kann jedoch vorübergehend die einzige Kopie noch nicht bestätigter Informationen enthalten und muss deshalb bis zum bestätigten Commit beziehungsweise zur bestätigten Synchronisation gegen Verlust geschützt werden.

### Derived State

Hierzu gehören beispielsweise:

- Embeddings
- Suchindizes
- Caches
- Vorschaudaten
- rein abgeleitete temporäre Daten

Derived State muss aus autoritativen Daten erneut erzeugbar sein und darf niemals die einzige bestätigte Kopie einer relevanten Information enthalten.

---

## 25. Fehlertoleranz

Ein Fehler in:

- Indexierung
- Embedding-Erzeugung
- Modellverarbeitung
- Plugin
- Benutzeroberfläche

darf nach Möglichkeit nicht den kanonischen Wissensbestand beschädigen.

ATHENA bevorzugt bei Unsicherheit einen kontrollierten Fehlerzustand gegenüber einem unkontrollierten Schreibvorgang.

---

## 26. Transparenz

ATHENA soll dem Benutzer verständlich machen können:

- welche Quelle verwendet wurde
- warum bestimmte Informationen gefunden wurden
- ob eine Aussage aus Erinnerung oder externer Quelle stammt
- ob eine Information unsicher ist
- ob eine Verarbeitung noch läuft
- ob ein Fehler aufgetreten ist

---

## 27. Keine stille Wissensmanipulation

Semantisch relevante Änderungen dürfen nicht unsichtbar außerhalb der vorgesehenen Wissensprozesse stattfinden.

Dies gilt sowohl für automatische Modellverarbeitung als auch für manuelle Benutzeränderungen.

Beide müssen in das gemeinsame Provenienz- und Versionierungssystem eingebunden werden.

---

## 28. Verhältnis zwischen Benutzer und Primärmodell

Die semantische Autorität innerhalb ATHENAs folgt grundsätzlich:

```text
Benutzer
   │
   ▼
ATHENA Core und Benutzerregeln
   │
   ▼
aktives Primärmodell
   │
   ▼
Infrastrukturmodelle und technische Algorithmen
   │
   ▼
externe Quellen
```

Diese Darstellung beschreibt keine Wahrheitsrangfolge externer Informationen.

Sie beschreibt ausschließlich die **Kontroll- und Entscheidungsautorität innerhalb des ATHENA-Systems**.

---

## 29. Leitregel

> **Der Benutzer besitzt die höchste Autorität über ATHENAs Wissen. Nur der Benutzer und das aktive Primärmodell dürfen semantische Änderungen am kanonischen Wissen veranlassen. Infrastrukturmodelle, technische Algorithmen und externe Quellen dürfen keine eigenständigen semantischen Wissensentscheidungen treffen.**

Diese Regel ist eine grundlegende Systemgrenze von ATHENA.
