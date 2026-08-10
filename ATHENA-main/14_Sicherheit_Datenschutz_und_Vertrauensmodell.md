# Kapitel 14 – Sicherheit, Datenschutz und Vertrauensmodell

---

## Einleitung

ATHENA verwaltet langfristig einen erheblichen Teil des persönlichen Wissens des Benutzers.

Dazu können gehören:

- Gedanken
- Projekte
- Dokumente
- persönliche Notizen
- Forschungsunterlagen
- geschützte Informationen
- langfristige Entscheidungen

Deshalb besitzt Sicherheit denselben Stellenwert wie Funktionalität.

Datenschutz ist keine optionale Erweiterung.

Er ist Bestandteil der Grundarchitektur.

---

## Grundprinzip

ATHENA arbeitet nach dem Prinzip:

Der Benutzer besitzt jederzeit die vollständige Kontrolle über seine Daten.

Diese Kontrolle darf weder durch Software-Updates noch durch Modelle oder Plugins eingeschränkt werden.

---

## Sicherheitsziele

Die Sicherheitsarchitektur verfolgt fünf Hauptziele.

Vertraulichkeit

Nur berechtigte Benutzer dürfen auf geschützte Inhalte zugreifen.

---

## Integrität

Wissen darf nicht unbemerkt verändert werden.

---

## Verfügbarkeit

Der Wissensbestand muss auch nach Fehlern oder Hardwarewechseln wiederherstellbar bleiben.

---

## Nachvollziehbarkeit

Alle relevanten Änderungen müssen dokumentiert werden.

---

## Benutzerkontrolle

Der Benutzer entscheidet jederzeit über Speicherung, Internetzugriffe und Löschungen.

---

## Geschützte Bereiche

ATHENA unterstützt geschützte Wissensbereiche.

Diese können über die Benutzeroberfläche:

- gesperrt,
- entsperrt,
- verwaltet

werden.

Der Benutzer gibt das Passwort ausschließlich innerhalb der ATHENA-Oberfläche ein.

---

## Passwort

Passwörter werden niemals im Klartext gespeichert.

Sie dienen ausschließlich der Freigabe geschützter Inhalte.

ATHENA speichert das Passwort niemals dauerhaft oder im Klartext. Es wird ausschließlich für Authentifizierung beziehungsweise Schlüsselableitung im Arbeitsspeicher verarbeitet und danach soweit technisch möglich verworfen.

---

## Verhalten bei gesperrtem Bereich

Ist ein geschützter Bereich gesperrt,

dürfen dessen Inhalte nicht:

- gelesen,
- interpretiert,
- zusammengefasst,
- durchsucht,
- oder offengelegt werden.

ATHENA erkennt lediglich,

dass geschützte Inhalte vorhanden sind.

Nicht jedoch deren Inhalt.

---

## Metadaten

Auch Metadaten dürfen keine vertraulichen Informationen preisgeben.

Dies betrifft insbesondere:

- Dateinamen
- Kategorien
- Tags
- Vorschauen
- Suchindex
- Zusammenfassungen

Geschützte Inhalte verwenden neutrale interne Identitäten.

---

## Internet
Normale Chats arbeiten standardmäßig offline.

Automatischer Internetzugriff ist standardmäßig deaktiviert und benötigt eine gültige Benutzerautorisierung. Diese kann unterschiedliche Reichweiten besitzen:

- ausdrückliche Freigabe für eine einzelne Web-/Internet-Anfrage
- aktivierter Internet-Schalter für normale Chats innerhalb seines definierten Geltungsbereichs
- ausdrücklich konfigurierte Berechtigung für ein Plugin oder eine Automation
- ausdrücklich konfigurierte Hintergrundrecherche

Der Daily-News-Workflow ist die einzige in Alpha standardmäßig vorgesehene automatische Internet-Ausnahme.

Alle externen Verbindungen erfolgen über die konfigurierte, vom Benutzer freigegebene Privacy-/Anonymisierungsschicht und unterliegen dem Fail-Closed-Prinzip.

Wissen allein stellt niemals eine Internetberechtigung dar.

---

## Prompt-Injection

ATHENA behandelt externe Inhalte ausschließlich als Daten.

Niemals als Systemanweisungen.

Dies gilt unabhängig vom Dateiformat.

Insbesondere:

- Webseiten
- PDFs
- Dokumentationen
- Quellcode
- E-Mails
- Nachrichten

dürfen keine internen Regeln verändern.

---

## Plugin-Sicherheit

Plugins erhalten ausschließlich die Berechtigungen,

die sie tatsächlich benötigen.

Plugins dürfen niemals:

- das Wissenssystem direkt verändern,
- Sicherheitsregeln umgehen,
- geschützte Inhalte eigenständig entschlüsseln.

Alle Änderungen erfolgen ausschließlich über den ATHENA Core.

---

## Audit Log

Sicherheitsrelevante Ereignisse werden dauerhaft protokolliert.

Hierzu gehören unter anderem:

- Entsperren geschützter Bereiche
- Änderungen an Berechtigungen
- Internetzugriffe
- Backup-Wiederherstellungen
- Plugin-Änderungen
- sicherheitsrelevante Fehler

Das Audit Log dient ausschließlich der Nachvollziehbarkeit.

Nicht der Überwachung.

---

## Vertrauen

ATHENA unterscheidet zwischen:

- Originalquelle
- Interpretation
- Vermutung
- bestätigter Information
- widersprochener Information

Vertrauen entsteht aus nachvollziehbaren Quellen.

Nicht aus der Sicherheit, mit der ein Modell formuliert.

---

## Inhaltsneutralität

ATHENA behandelt Inhalte unabhängig von ihrem Thema.

Die Architektur bewertet Inhalte nicht nach:

- politischer Richtung
- Weltanschauung
- Forschungsgebiet
- Kreativität
- Fiktion
- NSFW-Inhalten

Die Aufgabe von ATHENA besteht in der Organisation,

nicht in der inhaltlichen Bewertung.

Rechtliche oder technische Einschränkungen einzelner Modelle sind Eigenschaften dieser Modelle,

nicht der ATHENA-Architektur.

---

## Refusal-Failsafe

Kann oder will ein Primärmodell einen Inhalt nicht interpretieren,

bleibt die Originalquelle vollständig erhalten.

ATHENA dokumentiert den Status

und ermöglicht eine spätere Neuverarbeitung mit einem anderen kompatiblen Primärmodell.

Dadurch entsteht niemals Datenverlust.

---

## Graceful Degradation

Sicherheitsfunktionen dürfen nicht dazu führen,

dass das gesamte System ausfällt.

Beispiel:

Geschützter Bereich gesperrt.

```text
↓

Nur dieser Bereich bleibt unzugänglich.

↓
```

Der übrige Wissensbestand arbeitet normal weiter.

---

## Zukunftssicherheit

Neue Verschlüsselungsverfahren,

Authentifizierungsmethoden

oder Sicherheitsmechanismen

dürfen jederzeit integriert werden,

ohne die Grundprinzipien dieses Kapitels zu verändern.

---

## Leitregel

ATHENA schützt Wissen, ohne den Benutzer seiner eigenen Daten zu berauben. Sicherheit bedeutet Kontrolle – nicht Einschränkung.

---

## Abschluss des Kapitels

Dieses Kapitel definiert die Sicherheitsgrundlagen von ATHENA.

Alle zukünftigen technischen Sicherheitsmaßnahmen müssen mit diesen Prinzipien vereinbar sein.

Sicherheit ist kein separates Modul.

Sie ist Bestandteil jeder Architekturentscheidung.
