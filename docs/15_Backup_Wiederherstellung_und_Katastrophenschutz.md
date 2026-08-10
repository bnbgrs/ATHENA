# Kapitel 15 – Backup, Wiederherstellung und Katastrophenschutz

---

## Einleitung
Ein Wissenssystem, das über Jahrzehnte wachsen soll, muss davon ausgehen, dass Fehler auftreten werden.
Festplatten können ausfallen.
Dateien können beschädigt werden.
Software kann Fehler enthalten.
Updates können fehlschlagen.
Benutzer können versehentlich Daten löschen.
ATHENA darf deshalb nicht darauf ausgelegt sein, Fehler vollständig zu verhindern.
Die Architektur muss gewährleisten, dass Fehler überlebt werden können.

---

## Grundprinzip
Kein einzelner Fehler darf die autoritativen langfristigen Daten von ATHENA zerstören.
Der produktive persistente Datenspeicher ist niemals gleichzeitig die einzige Sicherung.

---

## Was gesichert wird
Backups umfassen alle langfristig nicht rekonstruierbaren Bestandteile von ATHENA.

Hierzu gehören insbesondere:

- Raw Archive
- Knowledge einschließlich Wissenseinheiten, Beziehungen, Concept Notes und Projekten
- Personal Memory
- geschützte Inhalte
- autoritative Konfiguration
- Audit- und Provenienzinformationen
- notwendige Metadaten

Durable Operational State wie noch nicht bestätigte Synchronisationspuffer, Transaktionsjournale oder kritische Checkpoints muss durch die Recovery- und Persistenzstrategie so geschützt sein, dass ein Absturz oder Neustart keinen Verlust noch nicht bestätigt persistierter Informationen erzeugt. Ob dieser Zustand zusätzlich in reguläre Backups einbezogen wird, ist eine Beta-Implementierungsentscheidung.

Rein rekonstruierbare Komponenten müssen nicht zwingend vollständig gesichert werden. Hierzu gehören insbesondere:

- Cache
- Embeddings
- Suchindex
- Vorschaudaten
- rein abgeleitete temporäre Dateien

Diese können nach einer Wiederherstellung aus den autoritativen Daten neu erzeugt werden.

---

## Automatische Sicherung
ATHENA erstellt Backups automatisch.
Der Benutzer soll nicht daran denken müssen, regelmäßig Sicherungen anzulegen.
Die Sicherungsprozesse laufen über das Hintergrundsystem.
Sie dürfen die aktive Nutzung nicht unnötig beeinträchtigen.

---

## Backup-Rotation
ATHENA bewahrt keine unbegrenzte Anzahl nahezu identischer Backups auf.
Die Standardstrategie lautet:
- 7 tägliche Sicherungen
- 4 wöchentliche Sicherungen
- 12 monatliche Sicherungen
- 5 jährliche Sicherungen
Dadurch existieren sowohl kurzfristige als auch langfristige Wiederherstellungspunkte.
Ältere Sicherungen außerhalb dieser Aufbewahrungsstrategie werden automatisch entfernt.

---

## Anpassbarkeit
Die Standardstrategie ist eine sinnvolle Voreinstellung.
Der Benutzer kann später:
- Anzahl,
- Zeitraum,
- Speicherort
der Sicherungen verändern.
Die Standardkonfiguration muss jedoch ohne manuelle Wartung langfristig funktionieren.

---

## Inkrementelle Sicherungen
Soweit technisch sinnvoll, verwendet ATHENA:
- inkrementelle Sicherungen,
- Deduplizierung,
- vergleichbare platzsparende Verfahren.
Unveränderte Daten sollen nicht unnötig mehrfach vollständig gespeichert werden.
Die konkrete Technik wird in der technischen Spezifikation festgelegt.

---

## Physische Trennung
Mindestens eine Sicherung soll auf einem anderen physischen Datenträger liegen als der primäre Wissensbestand.
Beispiel:
```text
Netzwerkfestplatte
        │
        │ Primärer Wissensbestand
        ▼

Zweiter Datenträger
        │
        │ Backup
        ▼
```
Ein Backup auf derselben physischen Festplatte schützt nicht vor einem vollständigen Laufwerksausfall.

---

## Integritätsprüfung
Die Existenz einer Backup-Datei bedeutet nicht automatisch, dass eine funktionierende Sicherung vorhanden ist.
ATHENA prüft deshalb regelmäßig:
- Lesbarkeit
- Vollständigkeit
- Prüfsummen
- Struktur
- notwendige Metadaten
Beschädigte Sicherungen werden gekennzeichnet und nicht als gültige Wiederherstellungspunkte behandelt.

---

## Restore-Test
ATHENA soll regelmäßig prüfen, ob Sicherungen tatsächlich wiederherstellbar sind.
Dies kann über kontrollierte Testwiederherstellungen erfolgen.
Ein Backup gilt erst dann als vollständig vertrauenswürdig, wenn seine Wiederherstellbarkeit geprüft wurde.

---

## Wiederherstellung
Der Benutzer kann über die ATHENA-Oberfläche einen vorhandenen Wiederherstellungspunkt auswählen.
ATHENA zeigt mindestens:
- Zeitpunkt
- Zustand
- Integritätsstatus
- Art der Sicherung
Vor der eigentlichen Wiederherstellung wird klar angezeigt, welcher Zustand wiederhergestellt wird.

---

## Sicherung vor Restore
Soweit der aktuelle Zustand noch lesbar ist, erstellt ATHENA vor einer Wiederherstellung zunächst eine Sicherung des aktuellen Zustands.
Dadurch bleibt auch eine versehentlich ausgelöste Wiederherstellung reversibel.

---

## Wiederherstellung auf neuer Hardware
Ein Backup darf nicht an den ursprünglichen Computer gebunden sein.
Eine Wiederherstellung muss auch möglich sein auf:
- einer neuen Festplatte
- einem neuen NAS
- einem neuen Computer
- einer neuen ATHENA-Installation
Der Speicherpfad darf sich vollständig ändern.

---

## Rekonstruktion abgeleiteter Systeme
Nach einer Wiederherstellung können abgeleitete Systeme neu erzeugt werden.
Beispielsweise:
```text
Wissensbestand wiederhergestellt

↓

Suchindex neu aufbauen

↓

Embeddings neu erzeugen

↓

Cache neu erzeugen

↓

ATHENA vollständig betriebsbereit
```
Dadurch müssen abgeleitete Daten nicht zwingend über Jahrzehnte mitgeschleppt werden.

---

## Geschützte Inhalte
Geschützte Inhalte bleiben auch innerhalb der Sicherungen geschützt.
Ein Backup darf keine unverschlüsselte Kopie geschützter Inhalte erzeugen.
Dasselbe gilt für:
- sensible Metadaten
- geschützte Indizes
- private Zusammenfassungen

---

## Recovery-Schlüssel
Falls ATHENA für geschützte Inhalte einen Recovery-Schlüssel verwendet, darf dieser niemals unverschlüsselt zusammen mit dem Backup gespeichert werden.
Ein Angreifer, der ausschließlich Zugriff auf die Sicherung erhält, darf dadurch keinen Zugriff auf geschützte Inhalte bekommen.

---

## Benutzerpasswort
ATHENA darf niemals das Benutzerpasswort im Klartext in einem Backup speichern.
Das gilt unabhängig davon, welche Backup-Technologie später verwendet wird.

---

## Fehlgeschlagene Backups
Schlägt ein Backup fehl, wird dies nicht stillschweigend ignoriert.
ATHENA:
1. protokolliert den Fehler,
2. versucht die Sicherung später erneut,
3. informiert den Benutzer, wenn der Fehler fortbesteht.
Ein fehlgeschlagenes Backup darf niemals als erfolgreich angezeigt werden.

---

## Speicherplatz
ATHENA überwacht den verfügbaren Backup-Speicher.
Wird der Speicher knapp, darf ATHENA nicht willkürlich Sicherungen löschen.
Die definierte Retention-Policy entscheidet, welche Sicherungen entfernt werden dürfen.
Falls keine sichere automatische Bereinigung möglich ist, wird der Benutzer informiert.

---

## Audit
Backup- und Restore-Vorgänge werden protokolliert.
Mindestens:
- Zeitpunkt
- Sicherungstyp
- Speicherort
- Ergebnis
- Integritätsstatus
- Wiederherstellungen
- Fehler
Dadurch bleibt nachvollziehbar, welche Sicherungsstände tatsächlich existierten und verwendet wurden.

---

## Katastrophenszenario
ATHENA muss darauf vorbereitet sein, dass der komplette Hauptdatenträger verloren geht.
Der minimale Wiederherstellungsweg lautet:
```text
Neue Hardware

↓

ATHENA installieren

↓

Backup auswählen

↓

Wissensbestand wiederherstellen

↓

Speicherort festlegen

↓

Indizes rekonstruieren

↓

Primärmodell auswählen

↓

ATHENA weiterverwenden
```
Der Benutzer darf nicht auf die ursprüngliche Installation angewiesen sein.

---

## Langfristige Lesbarkeit
Backups müssen so gestaltet sein, dass der Wissensbestand nicht ausschließlich mit einer einzigen historischen ATHENA-Version lesbar ist.
Die langfristigen Originaldaten und kanonischen Wissensdaten sollen soweit möglich in dokumentierten, portablen Formaten vorliegen.
ATHENA darf kein proprietäres Backup-Format zur einzigen verfügbaren Kopie des Wissens machen.

---

## Verhältnis zu Git
Git dient der Entwicklung von ATHENA.
Dazu gehören:
- Quellcode
- Spezifikationen
- Dokumentation
- Konfigurationen
- Tests
Git ist nicht das primäre Backup-System des persönlichen ATHENA-Wissensbestands.
Der Wissensbestand besitzt seine eigene Sicherungsstrategie.

---

## Ziel
Das Backup-System soll im Alltag möglichst unsichtbar funktionieren.
Der Benutzer soll sich nicht regelmäßig mit Sicherungsdateien beschäftigen müssen.
Gleichzeitig muss im Ernstfall klar und einfach sein, wie der vollständige Wissensbestand wiederhergestellt wird.

---

## Leitregel
Ein Backup ist erst dann ein Backup, wenn ATHENA nachweisen kann, dass daraus der Wissensbestand wiederhergestellt werden kann.

---

## Abschluss des Kapitels
ATHENA wird als langfristiges System entwickelt.
Deshalb werden Hardwareausfälle, beschädigte Dateien, fehlgeschlagene Updates und menschliche Fehler nicht als außergewöhnliche Situationen betrachtet.
Sie gehören zum erwartbaren Lebenszyklus des Systems.
Die Architektur stellt sicher, dass solche Ereignisse den langfristigen Wissensbestand nicht zerstören.
