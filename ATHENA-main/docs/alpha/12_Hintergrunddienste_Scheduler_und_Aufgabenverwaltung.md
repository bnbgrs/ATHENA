# Kapitel 12 – Hintergrunddienste, Scheduler und Aufgabenverwaltung

---

## Einleitung
ATHENA arbeitet nicht nur dann, wenn der Benutzer eine Frage stellt.
Viele Aufgaben müssen unabhängig von einer aktiven Unterhaltung ausgeführt werden.
Hierzu gehören unter anderem:
- News-Workflow
- OCR
- Dokumentenimport
- Backups
- Synchronisation
- Wissensreorganisation
- Index-Neuaufbau
- Wartungsaufgaben
Diese Aufgaben werden vom Hintergrundsystem verwaltet.

---

## Grundprinzip
Der Benutzer arbeitet. ATHENA organisiert.

Nichtkritische Hintergrundaufgaben dürfen die aktive Arbeit des Benutzers nicht unnötig beeinträchtigen und werden entsprechend ihrer Priorität sowie der verfügbaren Ressourcen geplant.

Kritische Datenintegritäts-, Sicherheits-, Synchronisations- oder Recovery-Vorgänge dürfen bei Bedarf Ressourcen beanspruchen oder betroffene Operationen pausieren, wenn dies notwendig ist, um Datenverlust oder Inkonsistenz zu verhindern.

---

## Der Scheduler
Der Scheduler entscheidet ausschließlich:
- wann eine Aufgabe ausgeführt wird,
- mit welcher Priorität,
- unter welchen Bedingungen.
Er führt keine fachlichen Entscheidungen durch.
Semantische Entscheidungen folgen der Autoritätshierarchie aus Kapitel 2: Benutzerentscheidungen besitzen Vorrang; automatisierte semantische KI-Entscheidungen erfolgen über das aktive Primärmodell und werden durch den ATHENA Core kontrolliert persistiert.

---

## Die persistente Queue
Alle Hintergrundaufgaben werden in einer persistenten Queue gespeichert.
Die Queue übersteht:
- Programmneustarts,
- Computer-Neustarts,
- Stromausfälle,
- Software-Updates.
Keine Aufgabe geht verloren.

---

## Lebenszyklus einer Aufgabe
Jede Aufgabe besitzt mindestens einen der folgenden Zustände:
```text
Neu

↓

Geplant

↓

Wartet auf Voraussetzungen

↓

Läuft

↓

Erfolgreich abgeschlossen

↓

Archiviert
```
Optional:

```text
Fehlgeschlagen
↓
Wiederholen

oder

Vom Benutzer abgebrochen
```

---

## Voraussetzungen
Vor der Ausführung prüft ATHENA unter anderem:
- Rechner eingeschaltet
- Benutzer aktiv?
- ausreichend RAM
- ausreichend VRAM
- benötigtes Modell verfügbar
- konfigurierte Privacy-/Anonymisierungsschicht verfügbar (falls erforderlich)
- Netzwerkpfad erreichbar
- notwendige Plugins verfügbar
Sind die Voraussetzungen nicht erfüllt, verbleibt die Aufgabe in der Queue.

---

## Prioritäten
Die Prioritätsreihenfolge ist verbindlich.
1. Direkte Benutzerinteraktion
2. Speicherung neuer Informationen
3. Datensicherheit
4. Zeitkritische Hintergrundaufgaben
5. News-Workflow
6. News-Backfills
7. Wartungsaufgaben
8. Optimierungen
9. Bereinigungen
Niedrig priorisierte Aufgaben dürfen niemals höher priorisierte Aufgaben blockieren.

---

## Idle-Modus
Rechenintensive Aufgaben werden bevorzugt ausgeführt, wenn:
- der Benutzer längere Zeit inaktiv ist,
- ausreichend Systemressourcen vorhanden sind,
- keine GPU-intensiven Anwendungen aktiv sind.
Der Idle-Modus ist eine Optimierung.
Keine Voraussetzung.

---

## Ressourcenmanagement
ATHENA beobachtet kontinuierlich:
- CPU
- RAM
- GPU
- VRAM
- Datenträger
- Netzwerk
Rechenintensive Aufgaben starten nur, wenn genügend Ressourcen verfügbar sind.

---

## Primärmodell
Benötigt eine Hintergrundaufgabe das Primärmodell,
darf ATHENA dieses automatisch laden,
wenn:
- ausreichend VRAM vorhanden ist,
- keine aktive Nutzung gestört wird,
- die Aufgabe zulässig ist.
Nach Abschluss darf das Modell wieder entladen werden, sofern ATHENA es selbst geladen hat.

---

## Backfill
Kann eine Aufgabe nicht rechtzeitig ausgeführt werden,
wird sie nicht verworfen.
Sie bleibt in der Queue.
Beispiele:
- tägliche Nachrichten
- OCR
- Dokumentenanalyse
- Synchronisation
ATHENA arbeitet den Rückstand später automatisch ab.

---

## Wiederholungsstrategie
Fehlgeschlagene Aufgaben werden abhängig von der Fehlerursache behandelt.

Beispiele:

- **Privacy-/Anonymisierungsschicht nicht verfügbar:** später erneut versuchen; niemals direkt ins Internet ausweichen.
- **Netzwerkspeicher offline:** in geschütztem lokalen Durable Operational State puffern und später synchronisieren.
- **Primärmodell nicht geladen oder Ressourcen nicht verfügbar:** auf geeignete Ressourcen warten oder Aufgabe pausieren.
- **Nicht behebbare Fehler:** nachvollziehbar dokumentieren, Job in einen eindeutigen Fehlerzustand versetzen und dem Benutzer anzeigen.

Fehler dürfen nicht dazu führen, dass eine notwendige Aufgabe stillschweigend verloren geht.

---

## Benutzerkontrolle
Der Benutzer kann jederzeit:
- die Queue ansehen,
- Aufgaben pausieren,
- Aufgaben abbrechen,
- Aufgaben erneut starten,
- Prioritäten ändern.
Automatische Prozesse bleiben jederzeit nachvollziehbar.

---

## Audit
Alle Hintergrundaufgaben werden protokolliert.
Mindestens:
- Startzeit
- Endzeit
- Dauer
- Ergebnis
- verwendetes Primärmodell, falls beteiligt
- verwendete Infrastrukturmodelle, falls beteiligt
- Fehler
- Wiederholungen

---

## Graceful Degradation
Fällt ein benötigtes Modul aus,
arbeitet ATHENA mit der bestmöglichen verbleibenden Funktionalität weiter.
Beispiele:
- OCR fehlt → Dokument archivieren.
- Embeddings fehlen → Volltextsuche.
- NAS offline → lokal puffern.
- Privacy-/Anonymisierungsschicht nicht verfügbar → Internetaufgaben verschieben.
Der Scheduler versucht später automatisch erneut, die Aufgabe vollständig auszuführen.

---

## Ziel
Das Hintergrundsystem soll den Benutzer vollständig entlasten.
Routineaufgaben sollen möglichst automatisch erledigt werden,
ohne:
- Kontrolle zu verlieren,
- Ressourcen zu verschwenden,
- den Benutzer zu stören.

---

## Leitregel
Keine Aufgabe geht verloren. Keine Aufgabe wird stillschweigend übersprungen. ATHENA arbeitet Rückstände zuverlässig nach, sobald die Voraussetzungen erfüllt sind.

---

## Abschluss des Kapitels
Das Hintergrundsystem sorgt dafür, dass ATHENA auch außerhalb aktiver Gespräche kontinuierlich arbeitet.
Durch die Kombination aus Scheduler, persistenter Queue, Ressourcenmanagement und Backfill-Mechanismen bleibt das System zuverlässig, nachvollziehbar und langfristig wartbar.
