# Kapitel 9 – Suchsystem und Wissensabruf

---

## Einleitung
Der Wert eines Wissenssystems hängt nicht nur davon ab, was gespeichert wird.
Er hängt ebenso davon ab, wie zuverlässig Wissen später wiedergefunden werden kann.
ATHENA betrachtet die Suche deshalb nicht als einzelne Funktion, sondern als zentralen Bestandteil der Architektur.
Der Benutzer soll niemals überlegen müssen, wo etwas gespeichert wurde.
Er beschreibt lediglich, was er sucht.
ATHENA entscheidet anschließend selbstständig, welche Wissensebene durchsucht werden muss.

---

## Grundprinzip
Die Suche folgt immer dem Prinzip:
So wenig wie nötig. So viel wie erforderlich.
ATHENA durchsucht nicht sofort den gesamten Wissensbestand.
Sie beginnt mit dem wahrscheinlich relevantesten Bereich.
Erst wenn dort keine ausreichende Antwort gefunden wird, erweitert sie den Suchraum.
Dadurch bleiben Antworten schnell, nachvollziehbar und ressourcenschonend.

---

## Die Suchhierarchie
ATHENA verwendet eine **adaptive Suchstrategie**. Local First bedeutet, dass vorhandenes lokales Wissen bevorzugt und unnötige externe Zugriffe vermieden werden. Es bedeutet nicht, dass bei jeder Anfrage zwangsläufig sämtliche lokalen Ebenen vollständig durchsucht werden müssen, bevor eine bereits autorisierte und sachlich notwendige externe Recherche beginnen darf.

Grundsätzlich gilt:

```text
Benutzeranfrage
        │
        ▼
Anfrageart und Berechtigungsstatus bestimmen
        │
        ├── lokale Frage → relevantes lokales Retrieval
        │
        ├── aktuelle/externe Frage + Internet freigegeben → externe Recherche nach Bedarf
        │
        └── externe Recherche nötig + Internet nicht freigegeben → Benutzer um Freigabe bitten
```

Für lokales Retrieval erweitert ATHENA den Suchraum typischerweise von aktivem Wissen über Langzeitwissen bis zum Raw Archive. Welche Stufe tatsächlich benötigt wird, richtet sich nach der Anfrage und dem erwarteten Erkenntnisgewinn.

Eine ausdrückliche Web- oder Internetanfrage des Benutzers gilt für diese Anfrage als Freigabe, sofern keine übergeordnete Sicherheitsregel entgegensteht. Ein bereits aktivierter Internet-Schalter gilt innerhalb seines definierten Geltungsbereichs ebenfalls als Freigabe.

---

## Ebene 1 – Aktives Wissen
Zuerst durchsucht ATHENA den aktiven Wissensgraphen.
Dort befinden sich:
- aktuelle Projekte
- häufig genutzte Wissenseinheiten
- Concept Notes
- aktuelle Entscheidungen
- zuletzt relevante Zusammenhänge
Die meisten Fragen sollen bereits hier beantwortet werden können.

---

## Ebene 2 – Langzeitwissen
Reicht das aktive Wissen nicht aus, erweitert ATHENA die Suche auf den gesamten langfristigen Wissensbestand.
Hierzu gehören:
- ältere Projekte
- archivierte Wissenseinheiten
- selten genutzte Themen
- historische Entscheidungen

---

## Ebene 3 – Roharchiv
Kann eine Frage auch dadurch nicht beantwortet werden, durchsucht ATHENA das Roharchiv.
Dabei werden bei Bedarf erneut Originalquellen analysiert.
Dies ermöglicht spätere Neuinterpretationen mit verbesserten Primärmodellen.

---

## Ebene 4 – Internet
Externe Recherche ist zulässig, wenn sie für die Anfrage sachlich sinnvoll ist **und** eine gültige Benutzerautorisierung vorliegt.

Für normale Chats gilt:

- Internet AUS und keine ausdrückliche Web-Anfrage → ATHENA fragt vor einer externen Recherche nach Freigabe.
- Internet AN → ATHENA darf externe Quellen innerhalb dieses Geltungsbereichs bei Bedarf verwenden.
- ausdrückliche Web-/Internet-Anfrage → gilt für diese Anfrage als Freigabe.

Der definierte Daily-News-Workflow besitzt seine gesonderte, ausdrücklich vorgesehene automatische Berechtigung.

Alle externen Zugriffe unterliegen weiterhin Privacy-/Anonymisierungs-, Fail-Closed- und Auditregeln.

---

## Suchmethoden
ATHENA kombiniert mehrere Suchverfahren.
Volltextsuche
Für exakte Begriffe.

---

## Semantische Suche
Für ähnliche Inhalte.

---

## Wissensgraph
Für Beziehungen.

---

## Zeitbasierte Suche
Für historische Ereignisse.

---

## Quellenbasierte Suche
Für bestimmte Dokumente oder Nachrichten.

---

## Projektbasierte Suche
Für alle Informationen eines Projekts.
Die Verfahren werden automatisch kombiniert.

---

## Suchpriorität
Nicht alle Treffer besitzen dieselbe Relevanz.
ATHENA berücksichtigt unter anderem:
- thematische Nähe
- Vertrauensniveau
- Aktualität
- Projektbezug
- persönliche Relevanz
- Häufigkeit der Nutzung
- Beziehungen im Wissensgraphen

---

## Geschützte Inhalte
Ist der geschützte Bereich gesperrt:
- dürfen geschützte Inhalte nicht durchsucht werden,
- erscheinen keine inhaltlichen Vorschauen,
- werden keine geschützten Zusammenhänge offengelegt.
Nach erfolgreicher Entsperrung stehen diese Inhalte wieder vollständig zur Verfügung.

---

## Infrastrukturmodell-Ausfall
Fällt beispielsweise das Embedding-Modell aus:
- bleibt die Volltextsuche verfügbar,
- bleiben direkte Verknüpfungen verfügbar,
- bleibt der Wissensgraph verfügbar.
Die semantische Suche wird nach Wiederherstellung automatisch neu aufgebaut.

---

## Transparenz
ATHENA soll nachvollziehbar machen, wo gesucht wurde.
Beispielsweise:
Antwort gefunden in:

✓ Aktiver Wissensgraph

✓ Projekt ATHENA

✓ Zwei archivierte Notizen

Keine Internetrecherche erforderlich.
Oder:
Lokales Wissen reicht nicht aus.

Internetrecherche erforderlich.

Internetzugriff aktivieren?
Der Benutzer versteht jederzeit, warum eine bestimmte Quelle verwendet wurde.

---

## Performance
Die Suche muss auch bei sehr großen Wissensbeständen performant bleiben.
Cache und Suchindex dienen ausschließlich der Beschleunigung.
Sie sind niemals die eigentliche Wissensquelle.

---

## Fehlerbehandlung
Kann eine Suchmethode nicht verwendet werden, versucht ATHENA automatisch eine geeignete Alternative.
Beispiele:
- Embeddings fehlen → Volltext.
- Suchindex beschädigt → Neuaufbau.
- Archiv nicht erreichbar → Aktives Wissen verwenden und Hinweis anzeigen.
Die Suche fällt niemals vollständig aus, solange der Wissensbestand verfügbar ist.

---

## Ziel
Der Benutzer soll niemals überlegen müssen,
- wo Informationen gespeichert wurden,
- wie sie kategorisiert wurden,
- oder in welchem Dokument sie stehen.
Er beschreibt lediglich sein Anliegen.
ATHENA übernimmt die Suche.

---

## Leitregel
Der Benutzer sucht nach Wissen. Nicht nach Dateien.

---

## Abschluss des Kapitels
Die Sucharchitektur verbindet den Wissensgraphen, das Langzeitwissen, das Roharchiv und – sofern ausdrücklich erlaubt oder vorgesehen – externe Quellen zu einem einheitlichen Abrufsystem.
Damit bleibt Wissen unabhängig von seinem Speicherort dauerhaft auffindbar.
