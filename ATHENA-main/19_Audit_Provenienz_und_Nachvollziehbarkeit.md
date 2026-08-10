# Kapitel 19 – Audit, Provenienz und Nachvollziehbarkeit

---

## Einleitung
Ein Wissenssystem, das über Jahre oder Jahrzehnte wächst, muss nicht nur Informationen speichern.
Es muss erklären können, woher diese Informationen stammen und wie sie entstanden sind.
ATHENA darf deshalb niemals zu einem undurchsichtigen Speicher werden, in dem nach einigen Jahren nicht mehr nachvollziehbar ist:
- woher eine Aussage stammt,
- welcher Akteur, Prozess oder welches Modell an ihrer Entstehung beteiligt war,
- warum zwei Einträge miteinander verbunden wurden,
- wann etwas geändert wurde,
- oder welcher automatische Prozess eine Aktion ausgelöst hat.
Nachvollziehbarkeit ist deshalb Bestandteil der Kernarchitektur.

---

## Grundprinzip
Jede relevante Information besitzt eine Herkunft. Jede relevante automatische Änderung besitzt eine Geschichte.
ATHENA trennt dabei zwei Konzepte:
- Provenienz
- Audit

---

## Provenienz
Provenienz beantwortet die Frage:
Woher stammt dieses Wissen?
Sie gehört zur Wissenseinheit selbst.

---

## Audit
Audit beantwortet die Frage:
Was hat ATHENA mit diesem Wissen gemacht?
Das Audit Log beschreibt den Lebenszyklus einer Information und relevante Systemaktionen.

---

## Herkunftskette
Eine typische Herkunftskette kann beispielsweise so aussehen:
```text
Webseite
   │
   ▼
Originalquelle im Roharchiv
   │
   ▼
Primärmodell
   │
   ▼
Wissenseinheit
   │
   ▼
Concept Note
   │
   ▼
Antwort an den Benutzer
```
Jeder Schritt bleibt nachvollziehbar.

---

## Quellenidentität
Jede Originalquelle erhält eine stabile interne Identität.
Diese Identität bleibt bestehen, auch wenn:
- die Datei umbenannt wird,
- der Ordner geändert wird,
- die Festplatte gewechselt wird,
- der Netzwerkpfad geändert wird.
Dadurch bleiben Provenienzketten langfristig stabil.

---

## Mindestprovenienz einer Wissenseinheit
Jede dauerhaft erzeugte oder geänderte Wissenseinheit enthält mindestens, soweit anwendbar:

- stabile interne ID
- Originalquelle oder Originalquellen beziehungsweise originierende Benutzeraktion
- Erstellungs- oder Änderungszeitpunkt
- originierender Akteur beziehungsweise Prozess (`origin_actor`)
- Art der Extraktion, Interpretation oder manuellen Änderung
- Erstellungs- beziehungsweise Änderungsgrund

War ein Primärmodell beteiligt, enthält die Provenienz zusätzlich die zugehörige Modellsignatur.

Bei direkter Benutzererstellung oder Benutzerkorrektur ohne Modellbeteiligung wird keine fiktive Modellidentität gespeichert. Der Ursprung wird stattdessen eindeutig als Benutzeraktion dokumentiert.

Stammen Informationen aus externen Quellen, werden zusätzlich deren Herkunftsdaten gespeichert.

---

## Mehrere Quellen
Eine Wissenseinheit kann aus mehreren Quellen entstehen.
Beispiel:
```text
Quelle A ─┐
Quelle B ─┼──► Wissenseinheit
Quelle C ─┘
```
Alle Quellen bleiben einzeln referenzierbar.

---

## Ableitungen
ATHENA unterscheidet zwischen:
- direkt aus einer Quelle extrahierter Information,
- Zusammenfassung mehrerer Informationen,
- Interpretation,
- Schlussfolgerung,
- Vermutung.
Diese Kategorien dürfen nicht miteinander verwechselt werden.

---

## Modellsignatur
Jede semantische Modelloperation, deren Ergebnis dauerhaft gespeichert wird, erhält eine dauerhafte Modellsignatur.

Mindestens soweit verfügbar:

- Provider
- Modellname oder Modell-Identifier
- Modellversion
- Quantisierung
- relevante Parameter
- Erstellungszeitpunkt

Dadurch kann später nachvollzogen werden, mit welcher Modellgeneration eine Interpretation entstanden ist.

Eine Modellsignatur wird nur gespeichert, wenn tatsächlich ein Modell beteiligt war. Für direkte Benutzeränderungen ist stattdessen die Benutzerprovenienz maßgeblich.

---

## Modellwechsel
Wird das Primärmodell später ersetzt, bleiben bestehende Modellsignaturen unverändert.
Neue modellgestützte Wissenseinheiten und Interpretationen erhalten die neue Signatur.
Dadurch kann der Wissensbestand über viele Modellgenerationen hinweg nachvollzogen werden.

---

## Neuinterpretation
Wird eine alte Quelle mit einem neuen Modell erneut analysiert, entsteht eine neue Interpretation.
Die alte Interpretation wird nicht still überschrieben.
Beispiel:
```text
Originalquelle

├── Interpretation 2026
│   └── Modell A
│
└── Interpretation 2030
    └── Modell B
```
Beide bleiben nachvollziehbar.

---

## Audit Log
Das Audit Log dokumentiert relevante automatische und manuelle Systemaktionen.
Hierzu gehören insbesondere:
- Erstellung von Wissenseinheiten
- Änderung von Wissenseinheiten
- Archivierung
- Löschung
- Wiederherstellung
- automatische Verknüpfungen
- Änderungen am Persönlichen Gedächtnis
- Internetzugriffe
- Plugin-Änderungen
- Backup und Restore
- Migrationen
- Sicherheitsereignisse

---

## Audit-Eintrag
Ein Audit-Eintrag enthält mindestens:
- Zeitpunkt
- Aktion
- auslösende Instanz
- betroffene Objekte
- Grund
- Ergebnis
Falls relevant zusätzlich:
- Primärmodell
- Plugin
- Hintergrundjob
- Benutzeraktion

---

## Beispiel
Zeitpunkt:
08.08.2026 19:42

Aktion:
Concept Note erstellt

Quelle:
Chat 182

Grund:
Mehrere zusammenhängende Wissenseinheiten erkannt

Primärmodell:
Modell X

Rückgängig möglich:
Ja

---

## Automatische Entscheidungen
ATHENA darf automatische Entscheidungen treffen, wenn dies innerhalb der definierten Architektur erlaubt ist.
Diese Entscheidungen dürfen jedoch niemals unsichtbar sein.
Der Benutzer muss später nachvollziehen können:
Warum hat ATHENA das gemacht?

---

## Rückgängigkeit
Soweit technisch sinnvoll, werden automatische Änderungen reversibel gestaltet.
Beispielsweise:
```text
Wissenseinheit verändert

↓

alte Version erhalten

↓

neue Version erstellt
```
Dadurch kann ein früherer Zustand wiederhergestellt werden.

---

## Löschungen
Löschungen besitzen besondere Bedeutung.
Eine endgültige Löschung kann durch eine ausdrückliche Benutzerentscheidung oder durch eine ausdrücklich vom Benutzer konfigurierte Aufbewahrungs-, Lebenszyklus- beziehungsweise Löschregel ausgelöst werden.
In beiden Fällen wird der Inhalt entsprechend den definierten Löschregeln entfernt und der auslösende Benutzerentscheid beziehungsweise die angewendete Regel nachvollziehbar dokumentiert.
Das Audit Log darf danach höchstens die für die technische Nachvollziehbarkeit notwendigen Informationen behalten.
Es darf nicht als versteckte Kopie des gelöschten Inhalts dienen.

---

## Audit ist kein Roharchiv
Das Audit Log speichert keine vollständigen Kopien aller Inhalte.
Es dokumentiert Aktionen.
Dadurch soll verhindert werden, dass durch Auditierung unkontrollierte Schattenkopien des Wissens entstehen.

---

## Geschützte Inhalte
Bei geschützten Inhalten gelten auch für das Audit Log die Sicherheitsregeln des geschützten Bereichs.
Ein Audit-Eintrag darf keine vertraulichen Informationen offenlegen, solange der entsprechende Bereich gesperrt ist.

---

## Internet-Audit
Jeder externe Netzwerkzugriff wird protokolliert.
Mindestens:
- Zeitpunkt
- auslösende Aufgabe
- Anonymisierungsstatus
- verwendete Quelle
- Ergebnis
Dadurch bleibt nachvollziehbar, wann ATHENA den lokalen Wissensraum verlassen hat.

---

## News-Provenienz
Jedes gespeicherte Ereignis des News-Systems behält seine Quellen.
ATHENA darf eine Ereigniszusammenfassung niemals von ihren ursprünglichen Nachrichtenquellen entkoppeln.

---

## Plugin-Provenienz
Von Plugins importierte Inhalte speichern:
- verantwortliches Plugin
- Plugin-Version, sofern relevant
- ursprüngliche externe Quelle
- Importzeitpunkt
Dadurch bleibt der Importweg langfristig nachvollziehbar.

---

## Backup- und Restore-Audit
Sicherungen und Wiederherstellungen werden ebenfalls protokolliert.
Dadurch kann ATHENA später nachvollziehen:
- welcher Zustand gesichert wurde,
- welcher Zustand wiederhergestellt wurde,
- ob ein Restore erfolgreich war.

---

## Systemdiagnose
Auditdaten können bei technischen Problemen zur Diagnose verwendet werden.
Beispielsweise:
```text
News-Workflow fehlgeschlagen

↓

Audit prüfen

↓

Privacy-/Anonymisierungsschicht war nicht verfügbar

↓

Job blieb in Queue

↓

später erfolgreich nachgeholt
```

---

## Benutzeroberfläche
Der Benutzer muss Auditdaten nicht im normalen Alltag sehen.
Eine separate Ansicht ermöglicht jedoch bei Bedarf:
- Verlauf anzeigen
- nach Datum filtern
- nach Wissenseinheit filtern
- nach Modell filtern
- nach Hintergrundjob filtern
- Änderungen nachvollziehen

---

## Aufbewahrung
Nicht jeder technische Logeintrag muss dauerhaft gespeichert werden.
ATHENA unterscheidet zwischen:
Langfristigem Audit
Für relevante Veränderungen am Wissensbestand und sicherheitsrelevante Vorgänge.
Temporären technischen Logs
Für Debugging und kurzfristige Diagnose.
Temporäre Logs können automatisch rotiert oder gelöscht werden.

---

## Performance
Auditierung darf die normale Nutzung nicht spürbar verlangsamen.
Das Audit-System wird deshalb so ausgelegt, dass auch über viele Jahre große Mengen an Ereignissen effizient verwaltet werden können.

---

## Integrität
Auditinformationen dürfen nicht stillschweigend verändert werden.
Korrekturen oder technische Migrationen müssen selbst nachvollziehbar bleiben.

---

## Datenschutz
ATHENA protokolliert nur Informationen, die für Nachvollziehbarkeit tatsächlich notwendig sind.
Auditierung darf nicht zu unnötiger Datensammlung führen.

---

## Ziel
ATHENA soll auch nach zehn oder zwanzig Jahren beantworten können:
- Woher weiß ich das?
- Welche Quelle steckt dahinter?
- Welches Modell hat das interpretiert?
- Wann wurde das geändert?
- Warum wurde diese Verbindung erstellt?
- Was geschah bei diesem Update?
- Warum wurde dieser Hintergrundjob nicht ausgeführt?

---

## Leitregel
ATHENA soll nicht nur wissen. ATHENA soll wissen, woher sie weiß.

---

## Abschluss des Kapitels
Provenienz und Audit machen den langfristigen Wissensbestand überprüfbar.
Sie verhindern, dass ATHENA über die Jahre zu einer undurchsichtigen Black Box wird.
Jede Quelle, Interpretation und relevante Veränderung bleibt in ihrer Entstehung nachvollziehbar, ohne dass dafür unnötige Schattenkopien des Wissens erzeugt werden.
