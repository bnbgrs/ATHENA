# Kapitel 11 – Das Nachrichten- und Ereignissystem

---

## Einleitung
ATHENA soll nicht nur vorhandenes Wissen verwalten.
Sie soll den Wissensbestand langfristig aktuell halten.
Hierzu besitzt ATHENA ein eigenständiges Nachrichten- und Ereignissystem.
Seine Aufgabe besteht nicht darin, möglichst viele Nachrichten zu speichern.
Seine Aufgabe besteht darin, langfristig relevante Ereignisse zu erkennen, einzuordnen und mit dem bestehenden Wissensnetz zu verbinden.

---

## Grundprinzip
ATHENA speichert keine Zeitung.
ATHENA speichert Geschichte.
Kurzfristige Meldungen besitzen nur dann langfristigen Wert, wenn sie Teil eines größeren Ereignisses werden.
Das Nachrichtensystem arbeitet deshalb ereignisorientiert und nicht artikelorientiert.

---

## Ziel
Das System soll weltweit relevante Entwicklungen automatisch erkennen.
Hierzu gehören beispielsweise:
- Politik
- Wissenschaft
- Technologie
- Wirtschaft
- Umwelt
- Raumfahrt
- Medizin
- Gesellschaft
- Kultur
- bedeutende Unternehmensereignisse
Die genaue Themenauswahl bleibt später konfigurierbar.

---

## Täglicher Workflow
Einmal pro Tag startet ATHENA automatisch den News-Workflow.
Dieser Ablauf erfolgt unabhängig vom Internet-Schalter für normale Chats.
Der Workflow wird ausschließlich über die definierte anonyme Netzwerkverbindung ausgeführt.

---

## Ablauf
```text
Scheduler
        │
        ▼
Quellen abrufen
        │
        ▼
Artikel gruppieren
        │
        ▼
Ereignisse erkennen
        │
        ▼
Primärmodell
        │
        ▼
Zusammenfassung
        │
        ▼
Verknüpfung mit Wissensgraph
        │
        ▼
Archivierung
```

---

## Ereigniserkennung
Mehrere Nachrichten über dasselbe Ereignis werden zusammengeführt.
Beispielsweise:
Nicht:
- 25 einzelne Artikel
Sondern:
Ein Ereignis.
Mit:
- verschiedenen Quellen
- zeitlicher Entwicklung
- unterschiedlichen Sichtweisen
- Vertrauensbewertung

---

## Quellenvergleich
ATHENA vergleicht Berichte verschiedener Quellen.
Dabei werden unter anderem erkannt:
- Übereinstimmungen
- Ergänzungen
- Widersprüche
- neue Entwicklungen
Keine einzelne Quelle bestimmt allein die Wissenseinordnung.

---

## Zeitliche Entwicklung
Ein Ereignis entwickelt sich.
ATHENA speichert deshalb:
- erste Meldung
- spätere Ergänzungen
- Korrekturen
- Abschluss des Ereignisses
Dadurch entsteht eine vollständige Chronologie.

---

## News-Backfill
War ATHENA längere Zeit offline,
werden fehlende Zeiträume nicht übersprungen.
Beim nächsten geeigneten Zeitpunkt:
- erkennt ATHENA die fehlenden Tage,
- recherchiert historische Quellen,
- rekonstruiert die wichtigsten Ereignisse,
- ergänzt den Wissensbestand.
Historische Lücken bleiben transparent gekennzeichnet, wenn eine vollständige Rekonstruktion nicht mehr möglich ist.

---

## Einordnung in den Wissensgraphen
Langfristig relevante Ereignisse werden automatisch mit vorhandenem Wissen verbunden.
Beispiele:
Ein neues KI-Modell erscheint.
ATHENA verknüpft dies mit:
- bestehenden Projekten,
- vorhandenen Modellinformationen,
- früheren Versionen,
- persönlichen Notizen des Benutzers.
Dadurch entsteht kontinuierlich ein wachsender Wissenskontext.

---

## Vertrauensmodell
Jedes Ereignis besitzt:
- Quellen
- Anzahl unabhängiger Bestätigungen
- Widersprüche
- Vertrauensniveau
- Zeitstempel
ATHENA speichert Ereignisse als Ereignisse. Meinungen, Bewertungen und Kommentare dürfen ebenfalls gespeichert werden, müssen jedoch eindeutig als attribuierte Aussagen ihrer jeweiligen Quelle gekennzeichnet sein und dürfen niemals stillschweigend als Ereignisfakten behandelt werden.

---

## Zusammenfassungen
Das Primärmodell erstellt:
- Tageszusammenfassungen
- Wochenüberblicke
- Monatsrückblicke
- langfristige Ereigniszusammenfassungen
Dabei bleibt jede Aussage auf ihre Quellen zurückführbar.

---

## Speicherung
Nicht jeder Artikel wird dauerhaft Bestandteil des aktiven Wissens.
ATHENA unterscheidet zwischen:
- Rohartikeln
- Ereignissen
- langfristigen Erkenntnissen
Nur dauerhaft relevante Inhalte gelangen in den Wissensgraphen.
Die Originalquellen bleiben gemäß den geltenden Archivierungs- und Aufbewahrungsregeln erhalten.

---

## Fehlerbehandlung
Kann der tägliche Workflow nicht ausgeführt werden,
bleibt der entsprechende Zeitraum als offene Aufgabe in der persistenten Queue.
Beim nächsten geeigneten Zeitpunkt erfolgt automatisch ein Backfill.
Kein Tag wird stillschweigend übersprungen.

---

## Benutzerinteraktion
Der Benutzer kann jederzeit fragen:
- Was ist heute passiert?
- Was habe ich letzte Woche verpasst?
- Welche Entwicklungen gab es seit meinem Urlaub?
- Welche Ereignisse betreffen mein Projekt ATHENA?
- Wie hat sich Thema X in den letzten zwei Jahren entwickelt?
ATHENA beantwortet diese Fragen auf Grundlage ihres archivierten Ereigniswissens.

---

## Leitregel
ATHENA sammelt keine Nachrichten. ATHENA dokumentiert die Entwicklung der Welt.

---

## Abschluss des Kapitels
Das Nachrichten- und Ereignissystem erweitert den lokalen Wissensbestand kontinuierlich um relevante externe Entwicklungen.
Durch Ereignisorientierung, Quellenvergleich, zeitliche Einordnung und automatische Backfills entsteht langfristig eine belastbare historische Wissensbasis anstelle eines flüchtigen Nachrichtenarchivs.
