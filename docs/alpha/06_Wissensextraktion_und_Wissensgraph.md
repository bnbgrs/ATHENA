# Kapitel 6 – Wissensextraktion und Wissensgraph

---

## Einleitung

Das Roharchiv enthält Informationen.

Der Wissensgraph enthält Wissen.

Die Aufgabe von ATHENA besteht nicht darin, möglichst viele Dokumente zu sammeln, sondern aus ihnen ein langfristig konsistentes Wissensnetz aufzubauen.

Die Wissensextraktion ist deshalb der wichtigste Denkprozess des gesamten Systems.

Sie entscheidet, welche Informationen langfristig relevant sind und wie sie miteinander verbunden werden.

---

## Grundprinzip
Nicht alles wird automatisch zu kanonischem Wissen.

ATHENA übernimmt komplette Dokumente nicht ungeprüft in den Wissensgraphen. Originale verbleiben in der Raw-Archive-Domäne; semantische Wissenseinheiten werden davon getrennt erzeugt.

Bei automatisierter Verarbeitung bewertet das aktive Primärmodell, welche Inhalte langfristigen Mehrwert besitzen. Der Benutzer kann unabhängig davon Informationen ausdrücklich als Wissen festlegen, korrigieren oder ergänzen.

Das Ziel automatischer Extraktion ist nicht maximale Vollständigkeit, sondern langfristig nützliche, nachvollziehbare und atomare Wissensbildung.

---

## Verantwortlichkeit
Die **automatisierte semantische Wissensextraktion** wird durch das aktive Primärmodell durchgeführt.

Der Benutzer kann jederzeit selbst:

- Wissenseinheiten erzeugen
- Informationen zu kanonischem Wissen erklären
- semantische Klassifikationen festlegen
- Beziehungen anlegen oder korrigieren
- bestehendes Wissen ändern oder löschen

Infrastrukturmodelle dürfen technische Verarbeitung durchführen, beispielsweise:

- Inhalte vorbereiten
- transkribieren
- OCR durchführen
- Embeddings erzeugen
- technische Klassifikationen wie Sprache, Dateityp oder Seitentyp erzeugen

Sie dürfen jedoch keine **eigenständigen semantischen Wissensentscheidungen** treffen. Insbesondere dürfen sie nicht autonom bestimmen, was als kanonisches Wissen gilt, welche semantische Kategorie eine Wissenseinheit erhält, welche inhaltlichen Beziehungen verbindlich werden oder welche Information dauerhaft verworfen wird.

---

## Ablauf der Wissensextraktion

Die **automatisierte Wissensextraktion aus einer Quelle** folgt grundsätzlich derselben kontrollierten Reihenfolge:

```text
Originalquelle
        │
        ▼
technische Vorverarbeitung
        │
        ▼
aktives Primärmodell
        │
        ▼
Kandidaten für Wissenseinheiten / Claims / Beziehungen
        │
        ▼
Prüfung gegen vorhandenes Wissen
        │
        ▼
validierter semantischer Commit
        │
        ▼
Wissenseinheiten oder Ergänzungen
        │
        ▼
Verknüpfung im Wissensgraphen
```

Keine automatisiert extrahierte Wissenseinheit wird erstellt, ohne dass zuvor geprüft wurde, ob sie bereits existiert, bestehendes Wissen ergänzt oder mit vorhandenem Wissen in Konflikt steht.

Daneben existiert ein gleichwertiger direkter Benutzerpfad:

```text
Benutzeraktion
        │
        ▼
Validierung / Concurrency-Prüfung
        │
        ▼
semantischer Commit
        │
        ▼
Knowledge / Personal Memory gemäß Domänenregel
```

Direkte Benutzererstellung und Benutzerkorrektur benötigen weder eine künstliche Originalquelle noch eine künstliche ModelSignature. Ihre Provenienz verweist auf die originierende Benutzeraktion.

## Kriterien für eine Wissenseinheit

Eine Information sollte nur dann dauerhaft in den Wissensgraphen aufgenommen werden, wenn sie mindestens eines der folgenden Merkmale erfüllt:

- langfristige Relevanz

- wiederkehrende Bedeutung

- Entscheidungscharakter

- Projektbezug

- persönliche Erkenntnis

- Definition oder Konzept

- dauerhaft gültige Referenz

- neue Verbindung zwischen bestehenden Themen

Kurzlebige Gesprächsinhalte verbleiben ausschließlich im Roharchiv.

---

## Atomare Wissenseinheiten

ATHENA speichert Wissen möglichst atomar.

Eine Wissenseinheit beschreibt genau einen klaren Sachverhalt.

Nicht:

“Projekt ATHENA inklusive aller Ideen der letzten sechs Monate.”

Sondern viele kleinere Einheiten, beispielsweise:

- Ziel von ATHENA

- Architekturprinzipien

- Backup-Strategie

- News-System

- UI-Philosophie

Dadurch entstehen präzisere Verknüpfungen und bessere Suchergebnisse.

---

## Verknüpfungen

Jede Wissenseinheit wird aktiv mit anderen Einheiten verbunden.

Verknüpfungen entstehen beispielsweise durch:

- gleiche Projekte

- gemeinsame Personen

- gleiche Konzepte

- Ursache und Wirkung

- zeitliche Beziehungen

- Abhängigkeiten

- Widersprüche

- Ergänzungen

Der Wissensgraph ist kein Baum.

Er ist ein Netzwerk.

---

## Concept Notes

ATHENA darf aus mehreren Wissenseinheiten übergeordnete Concept Notes erzeugen.

Eine Concept Note fasst ein Thema zusammen, ersetzt jedoch niemals die darunterliegenden Wissenseinheiten.

Concept Notes dienen der Orientierung.

Die Detailinformationen bleiben in den einzelnen Wissenseinheiten erhalten.

---

## Wissensentwicklung

Wissen verändert sich.

ATHENA unterscheidet deshalb zwischen:

- neuer Information

- Ergänzung

- Präzisierung

- Korrektur

- Widerspruch

- historischer Version

Bestehendes Wissen wird nicht stillschweigend überschrieben.

---

## Konflikte

Treffen widersprüchliche Informationen aufeinander, erzeugt ATHENA keinen automatischen Gewinner.

Stattdessen werden beide Aussagen dokumentiert.

Der Wissensgraph speichert beispielsweise:

- Aussage A

- Aussage B

- jeweilige Quelle

- Vertrauensniveau

- zeitlicher Kontext

Dadurch bleibt die Entwicklung eines Themas nachvollziehbar.

---

## Persönliches Wissen
Persönliche Erkenntnisse des Benutzers besitzen im Wissensgraphen einen klar attribuierten Status.

Beispiele:

- eigene Entscheidungen
- langfristige Ziele
- Projekte
- Ideen
- Erfahrungen

Sie sind von externem/referenziertem Wissen unterscheidbar, dürfen jedoch damit verknüpft werden.

Präferenzen, Gewohnheiten und wiederkehrende Einstellungen darüber, wie ATHENA mit dem Benutzer arbeiten soll, gehören in die getrennte Personal-Memory-Domäne und nicht in diese Wissenskategorie.

---

## Vertrauensmodell

Jede Wissenseinheit besitzt ein eigenes Vertrauensniveau.

Dieses ergibt sich unter anderem aus:

- Herkunft

- Anzahl unabhängiger Quellen

- persönlicher Bestätigung

- zeitlicher Aktualität

- Konsistenz mit vorhandenem Wissen

ATHENA verwechselt niemals Häufigkeit mit Wahrheit.

---

## Modellsignatur
Jede semantische Operation des Primärmodells, die langfristiges Wissen erzeugt oder verändert, erhält dauerhaft eine Modellsignatur.

Mindestens soweit verfügbar:

- Provider
- Modellidentität
- Modellversion
- Quantisierung
- relevante Einstellungen
- Erstellungszeitpunkt

Direkt vom Benutzer erzeugte oder geänderte Wissenseinheiten benötigen keine Modellsignatur, wenn kein Modell beteiligt war. Sie erhalten stattdessen eindeutige Benutzerprovenienz.

Dadurch bleibt nachvollziehbar, ob eine Interpretation von einem Modell oder unmittelbar vom Benutzer stammt.

---

## Audit Log
Die Entstehung und Änderung jeder Wissenseinheit wird protokolliert.

Mindestens:

- Quelle beziehungsweise Ausgangszustand
- Zeitpunkt
- Grund der Erstellung oder Änderung
- originierender Akteur beziehungsweise Prozess
- bei Modellbeteiligung die zugehörige Modellsignatur
- spätere Änderungen

Der Benutzer kann diese Informationen jederzeit einsehen.

---

## Kein automatisches Vergessen

ATHENA entfernt kanonische Wissenseinheiten niemals aufgrund eigener Heuristiken eigenmächtig.

Wissen kann:

- ergänzt,
- archiviert,
- historisiert

werden.

Eine endgültige Löschung erfolgt nur durch eine ausdrückliche Benutzerentscheidung oder aufgrund einer ausdrücklich vom Benutzer konfigurierten Aufbewahrungs- beziehungsweise Löschregel.

---

## Ziel des Wissensgraphen

Der Wissensgraph soll nicht möglichst groß werden.

Er soll möglichst verständlich werden.

Jede neue Wissenseinheit soll das bestehende Netz sinnvoll erweitern.

Das langfristige Ziel ist ein wachsender, konsistenter Wissensraum, in dem Zusammenhänge sichtbar werden, ohne dass der Benutzer sie aktiv suchen muss.

---

## Abschluss des Kapitels

Mit der Wissensextraktion beginnt der eigentliche Denkprozess von ATHENA.

Aus unveränderten Originalquellen entsteht ein strukturiertes, nachvollziehbares und langfristig stabiles Wissensnetz.

Die folgenden Kapitel bauen auf diesem Wissensgraphen auf und beschreiben dessen weitere Bestandteile im Detail.
