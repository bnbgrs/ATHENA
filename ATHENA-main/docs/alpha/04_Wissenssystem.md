# Kapitel 4 – Das Wissenssystem

---

## Einleitung
Das Wissenssystem bildet den eigentlichen Kern von ATHENA.
Nicht das Sprachmodell.
Nicht die Benutzeroberfläche.
Nicht die Software.
Der langfristige, benutzerkontrollierte Wissens- und Quellenbestand ist der wertvollste Bestandteil des gesamten Projekts.
Die übrigen Systemkomponenten dienen dazu, die autoritativen persistenten Daten aufzubauen, zu organisieren, zu schützen und nutzbar zu machen, ohne deren logische Domänengrenzen aufzuheben.
Deshalb wird das Wissenssystem unabhängig von konkreten Modellen, Programmen und Speicherorten entwickelt.

---

## Grundprinzip
ATHENA speichert nicht einfach Informationen.
ATHENA organisiert Wissen.
Der Unterschied ist entscheidend.
Informationen sind einzelne Fakten oder Dokumente.
Wissen entsteht erst durch:
- Beziehungen
- Kontext
- Zeit
- Herkunft
- Vertrauen
- Entscheidungen
- Zusammenfassungen
- Erfahrungen
Das Ziel besteht deshalb nicht darin, möglichst viele Dateien abzulegen.
Das Ziel besteht darin, ein wachsendes Wissensnetz aufzubauen.

---

## Speicherebenen und Wissensprozess
ATHENA trennt Speicherzustände strikt von Verarbeitungsschritten.

ATHENA unterscheidet zunächst die unveränderte Quellenbasis von den Zuständen des kanonischen Wissens:

```text
Raw Archive (Originalquellen)
        │
        │ Wissensextraktion
        ▼
Aktives Wissensnetz
        │
        ▼
Langzeitwissen
        │
        ▼
Archivierter Wissensstatus
```

Das Raw Archive ist eine eigene persistente Domäne. Aktives Wissen, Langzeitwissen und archiviertes Wissen sind Zustände beziehungsweise Prioritätsstufen innerhalb der Knowledge-Domäne.

Die Wissensextraktion ist keine Speicherebene. Sie ist der semantische Prozess, der Originalquellen analysiert und daraus – unter den Regeln von ATHENA – Vorschläge für kanonisches Wissen erzeugt.

Diese Taxonomie gilt kapitelübergreifend. Archivierung bedeutet eine Änderung des Aktivitäts- oder Speicherstatus, nicht das Vergessen oder Überschreiben der zugrunde liegenden Quelle.

---

## Quellendomäne – Raw Archive
Das Raw Archive ist keine Stufe innerhalb der Knowledge-Domäne, sondern eine getrennte persistente Quellen-Domäne.

Es enthält die gemäß den Archivierungs- und Aufbewahrungsregeln erhaltenen Originalquellen, beispielsweise:

- Chats
- PDFs
- Webseiten
- Bilder
- Audiodateien
- Videos
- Notizen
- Nachrichten
- Dokumente

Verarbeitung verändert oder ersetzt diese Originalquellen niemals. Solange eine Quelle gemäß den Aufbewahrungsregeln erhalten bleibt, dient sie als Referenz für daraus abgeleitete Interpretationen und Wissenseinheiten.

---

## Regeln
Originalquellen werden durch Verarbeitung niemals überschrieben oder stillschweigend verändert.

Sie dürfen analysiert, interpretiert und zusammengefasst werden. Sämtliche Interpretationen, Zusammenfassungen und Wissenseinheiten entstehen jedoch als getrennte, mit Provenienz verknüpfte Ableitungen.

Eine endgültige Löschung einer Originalquelle erfolgt nur auf ausdrücklichen Benutzerwunsch oder aufgrund einer ausdrücklich vom Benutzer konfigurierten Aufbewahrungsregel. Löschung und Ableitungsfolgen müssen nachvollziehbar behandelt werden.

---

## Prozess – Wissensextraktion
Die Wissensextraktion ist ein semantischer Prozess und keine Speicherebene.

Bei automatisierter Verarbeitung übernimmt das aktive Primärmodell die semantische Extraktion. Es kann unter den Regeln von ATHENA unter anderem folgende langfristig relevante Inhalte identifizieren:

- Erkenntnisse
- Entscheidungen
- Ideen
- Projekte
- Aufgaben
- Definitionen
- Beziehungen
- offene Fragen

Der Benutzer kann unabhängig davon selbst Wissenseinheiten erstellen, Inhalte ausdrücklich als kanonisches Wissen festlegen, korrigieren, klassifizieren oder verändern.

Nicht jede Unterhaltung wird automatisch zu Wissen. Automatische Extraktion filtert bewusst; ausdrückliche Benutzerentscheidungen besitzen Vorrang.

---

## Speicherebene – Aktives Wissensnetz
Hier entsteht das eigentliche zweite Gehirn.
Es enthält:
- Wissenseinheiten
- Concept Notes
- Projekte
- Themen
- Beziehungen
- Querverbindungen
- Zusammenfassungen
- Entscheidungsverläufe
Das Wissensnetz verändert sich kontinuierlich.
Es wächst mit jedem neuen Eintrag.

---

## Speicherebenen – Langzeitwissen und Archiv
Nicht jedes Wissen bleibt dauerhaft aktiv.
Selten genutzte Inhalte werden archiviert.
Archivierung bedeutet jedoch niemals Vergessen.
Archivierte Inhalte bleiben vollständig:
- durchsuchbar,
- referenzierbar,
- rekonstruierbar.
Sie beeinflussen lediglich den aktiven Arbeitsbereich weniger stark.

---

## Wissenseinheiten
Die kleinste logische Einheit des Systems ist die Wissenseinheit.
Eine Wissenseinheit beschreibt genau einen Zusammenhang.
Sie kann bestehen aus:
- Text
- Quelle
- Beziehungen
- Vertrauensniveau
- Zeitbezug
- Metadaten
Mehrere kleine Wissenseinheiten sind einem großen Dokument vorzuziehen.

---

## Beziehungen
Wissen wird nicht über Ordner organisiert.
Ordner dienen ausschließlich der physischen Speicherung.
Logische Beziehungen entstehen über Verknüpfungen.
Eine Wissenseinheit kann mit beliebig vielen anderen Wissenseinheiten verbunden sein.
Dadurch entsteht ein Wissensgraph.

---

## Provenienz
Jede Wissenseinheit besitzt eine nachvollziehbare Herkunft.

Mindestens dokumentiert werden, soweit anwendbar:

- stabile interne Identität
- originierende Quelle oder originierende Benutzeraktion
- **origin_actor**, beispielsweise `user` oder `primary_model`
- Erstellungs- beziehungsweise Änderungszeitpunkt
- Erstellungs- oder Änderungsgrund
- Vertrauens- beziehungsweise epistemischer Status

War ein Primärmodell an der semantischen Erzeugung oder Änderung beteiligt, wird zusätzlich dessen Modellsignatur gespeichert.

Bei einer direkten Benutzeränderung wird keine fiktive Modellsignatur erzeugt. Stattdessen bleibt eindeutig nachvollziehbar, dass die Änderung vom Benutzer veranlasst wurde.

Jede abgeleitete Aussage muss soweit möglich zu ihren Quellen und Verarbeitungsschritten zurückverfolgbar bleiben.

---

## Zeitliche Entwicklung
Wissen ist nicht statisch.
ATHENA unterscheidet:
- ursprüngliche Aussage
- spätere Ergänzungen
- Bestätigungen
- Widersprüche
- Korrekturen
Neue Informationen überschreiben bestehendes Wissen nicht automatisch.
Sie ergänzen den bisherigen Wissensstand.

---

## Vertrauen
Nicht jede Information besitzt dieselbe Zuverlässigkeit.
ATHENA unterscheidet ausdrücklich zwischen:
- Originalaussage
- Interpretation
- Vermutung
- bestätigter Information
- widersprochener Information
Vertrauen entsteht durch Quellenlage, nicht durch Wiederholung.

---

## Persönliches Wissen und externes Wissen
Die Knowledge-Domäne unterscheidet mindestens zwischen persönlichem Wissen des Benutzers und externem/referenziertem Wissen.

**Persönliches Wissen** umfasst beispielsweise:

- Projekte
- Entscheidungen
- Ideen
- Ziele
- Erfahrungen

**Externes / referenziertes Wissen** umfasst beispielsweise:

- Nachrichten
- Bücher
- Webseiten
- wissenschaftliche Quellen
- Dokumentationen

Präferenzen darüber, **wie ATHENA mit dem Benutzer zusammenarbeiten soll**, gehören dagegen in die getrennte Personal-Memory-Domäne.

Persönliches und externes Wissen dürfen miteinander verknüpft werden. Ihre Herkunft und ihr epistemischer Status bleiben unterscheidbar.

---

## Wissensentwicklung
Neue Informationen werden niemals unkontrolliert übernommen.
ATHENA prüft:
- Ist das wirklich neu?
- Ergänzt es bestehendes Wissen?
- Widerspricht es vorhandenem Wissen?
- Handelt es sich um dieselbe Information?
Erst danach erfolgt die Einordnung.

---

## Single Source of Truth
Die **Knowledge-Domäne** ist die autoritative Quelle für ATHENAs kanonisches semantisches Wissen. Sie ist jedoch nicht die einzige autoritative Persistenzdomäne des Gesamtsystems.

Raw Archive, Personal Memory, Audit and Provenance sowie Configuration bleiben eigenständige autoritative Domänen innerhalb von ATHENA Persistent Data.

Rekonstruierbare Komponenten wie:

- Suchindex
- Cache
- Embeddings
- Vorschauen
- rein abgeleitete temporäre Daten

dürfen jederzeit aus den autoritativen Daten neu erzeugt werden. Sie enthalten niemals die einzige bestätigte Kopie kanonischer Informationen.

---

## Ziel
Das langfristige Ziel des Wissenssystems besteht nicht darin, möglichst viele Informationen zu sammeln.
Das Ziel besteht darin, aus vielen Informationen ein konsistentes, nachvollziehbares und dauerhaft nutzbares Wissensnetz aufzubauen.

---

## Abschluss des Kapitels
Das Wissenssystem ist der wichtigste Bestandteil von ATHENA.
Modelle können ersetzt werden.
Programme können aktualisiert werden.
Hardware kann wechseln.
Der Wissensbestand bleibt bestehen.
Alle folgenden Kapitel beschreiben die einzelnen Bestandteile dieses Wissenssystems im Detail.
