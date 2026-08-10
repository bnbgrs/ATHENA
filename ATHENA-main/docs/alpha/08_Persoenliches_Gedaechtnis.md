# Kapitel 8 – Persönliches Gedächtnis

---

## Einleitung
ATHENA unterscheidet strikt zwischen **Knowledge** und **Personal Memory**.

Diese Trennung ist eine grundlegende Architekturentscheidung.

Die Knowledge-Domäne enthält semantisches Wissen über externe Sachverhalte sowie persönliches, projektbezogenes Wissen des Benutzers, etwa Projekte, Entscheidungen, Ziele, Ideen und Erfahrungen.

Die Personal-Memory-Domäne beschreibt dagegen vor allem, **wie ATHENA mit dem Benutzer zusammenarbeiten soll**: Präferenzen, Gewohnheiten, wiederkehrende Einstellungen und vergleichbare langfristige Zusammenarbeitshinweise.

Beide Domänen können einander referenzieren. Sie dürfen jedoch nicht miteinander verschmelzen oder ihre Provenienz-, Schutz- und Änderungsregeln vermischen.

---

## Grundprinzip
Das Persönliche Gedächtnis dient dazu, die Zusammenarbeit mit dem Benutzer langfristig zu verbessern.

Es ersetzt nicht den Wissensgraphen und ist keine ungezielte Sammlung privater Daten.

Es enthält gezielt solche dauerhaft relevanten Präferenzen, Gewohnheiten und Einstellungen, die für zukünftige Interaktionen oder Arbeitsabläufe nützlich sind.

---

## Trennung der drei Bereiche
ATHENA unterscheidet dauerhaft drei semantische Kategorien, die auf zwei persistenten Domänen verteilt sind.

### 1. Externes / referenziertes Wissen

Beispiele:

- Bücher
- Dokumentationen
- wissenschaftliche Erkenntnisse
- Nachrichten
- Definitionen

Diese Inhalte liegen in der **Knowledge-Domäne**.

### 2. Persönliches Wissen

Beispiele:

- Projekte
- Entscheidungen
- Ideen
- Ziele
- Erfahrungen

Auch diese Inhalte liegen in der **Knowledge-Domäne**, bleiben dort aber als persönliches Wissen attribuiert.

### 3. Persönliches Gedächtnis

Beispiele:

- bevorzugter Antwortstil
- bevorzugte Modelle
- bevorzugte Arbeitsweise
- langfristige Gewohnheiten
- wiederkehrende Einstellungen

Diese Inhalte liegen in der getrennten **Personal-Memory-Domäne**.

Personal Memory kann das Verhalten von ATHENA beeinflussen. Es verändert dadurch jedoch nicht automatisch externes/referenziertes oder persönliches kanonisches Wissen.

---

## Automatisch lernbare Informationen
ATHENA darf im Rahmen der dafür geltenden Benutzerregeln langfristig Zusammenarbeitseinstellungen lernen, beispielsweise:

- bevorzugte Sprache
- bevorzugte Antwortlänge
- bevorzugte Detailtiefe
- bevorzugte Arbeitsweise
- bevorzugte Modellkonfiguration
- wiederkehrende Arbeitsabläufe
- stabile Interaktionspräferenzen

Langfristige Projekte selbst gehören dagegen zur Knowledge-Domäne. Personal Memory darf auf solche Projekte referenzieren, etwa um eine bevorzugte Arbeitsweise für ein Projekt zu merken, besitzt aber nicht das Projektwissen selbst.

Das Ziel besteht darin, unnötige Wiederholungen zu vermeiden, ohne Personal Memory und Knowledge zu vermischen.

---

## Nicht automatisch lernbare Informationen
ATHENA übernimmt sensible persönliche Informationen niemals allein aufgrund ihres Auftretens automatisch in das Persönliche Gedächtnis.

Hierzu gehören insbesondere:

- Passwörter
- geheime Inhalte
- Gesundheitsdaten
- Finanzdaten
- private Identifikationsdaten
- andere ausdrücklich geschützte Informationen

Eine dauerhafte Aufnahme solcher Informationen in Personal Memory erfolgt nur auf ausdrücklichen Wunsch des Benutzers und unter den jeweils geltenden Schutzregeln.

Die Regeln für **Personal Memory** und **Raw Archive** sind unabhängig. Eine Information kann von der automatischen Aufnahme in Personal Memory ausgeschlossen sein und dennoch als Bestandteil einer gemäß den Archivierungsregeln gespeicherten Originalquelle, beispielsweise eines Chats, im Raw Archive existieren. Ein temporärer beziehungsweise ausdrücklich nicht zu speichernder Chat wird davon nicht erfasst.

---

## Explizites Lernen

Der Benutzer kann jederzeit Aussagen treffen wie:

- „Merke dir das.“
- „Vergiss das.“
- „Das gilt dauerhaft.“
- „Speichere das nicht.“

Solche Anweisungen besitzen Vorrang vor automatischen Lernmechanismen.

---

## Transparenz

Das Persönliche Gedächtnis ist jederzeit vollständig einsehbar.

Der Benutzer kann:

- alle Einträge anzeigen,
- einzelne Einträge bearbeiten,
- Einträge löschen,
- das gesamte Persönliche Gedächtnis zurücksetzen.

ATHENA versteckt keine dauerhaft gespeicherten Präferenzen.

---

## Einfluss auf Antworten

Das Persönliche Gedächtnis darf Antworten beeinflussen.

Beispiele:

- bevorzugter Stil
- bevorzugte Struktur
- bevorzugte Arbeitsweise

Es darf jedoch niemals Fakten verändern.

---

## Konflikte

Widerspricht eine neue Präferenz einer älteren Präferenz, überschreibt ATHENA diese nicht unbemerkt.

Die Änderung wird nachvollziehbar dokumentiert.

---

## Historie

Änderungen am Persönlichen Gedächtnis werden protokolliert.

Mindestens:

- Zeitpunkt
- ursprünglicher Eintrag
- neuer Eintrag
- Grund der Änderung
- auslösender Benutzerbefehl

Dadurch bleibt die Entwicklung nachvollziehbar.

---

## Löschung

Der Benutzer besitzt jederzeit das Recht,

- einzelne Präferenzen,
- Gruppen von Präferenzen,
- oder das gesamte Persönliche Gedächtnis

dauerhaft zu löschen.

ATHENA führt keine automatische Wiederherstellung solcher Einträge durch.

---

## Schutz

Das Persönliche Gedächtnis unterliegt denselben Sicherheitsregeln wie der übrige Wissensbestand.

Geschützte Einträge können zusätzlich verschlüsselt gespeichert werden.

---

## Langfristigkeit

Das Persönliche Gedächtnis soll über viele Jahre stabil bleiben.

Neue Präferenzen ergänzen bestehende Informationen.

Kurzfristige Vorlieben sollen nicht dauerhaft gespeichert werden.

ATHENA bewertet deshalb die langfristige Relevanz einer Präferenz, bevor sie automatisch übernommen wird.

---

## Ziel

Das Persönliche Gedächtnis soll die Zusammenarbeit natürlicher machen.

Der Benutzer soll dieselben grundlegenden Wünsche nicht immer wieder erklären müssen.

Gleichzeitig bleibt jederzeit transparent, was ATHENA tatsächlich dauerhaft über den Benutzer gelernt hat.

---

## Leitregel

ATHENA lernt bevorzugte Zusammenarbeit – nicht ungefragt persönliche Details.

---

## Abschluss des Kapitels

Das Persönliche Gedächtnis bildet die langfristige Arbeitsbeziehung zwischen Benutzer und ATHENA ab.

Es ergänzt das Wissenssystem, ersetzt es jedoch niemals.

Diese Trennung sorgt dafür, dass ATHENA gleichzeitig persönlich, nachvollziehbar und kontrollierbar bleibt.
