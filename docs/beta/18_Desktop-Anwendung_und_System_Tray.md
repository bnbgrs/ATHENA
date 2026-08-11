# ATHENA Beta Specification v0.1 – Kapitel 18

## Desktop-Anwendung und System Tray

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Architektur:** [Beta Kapitel 01](01_Systemarchitektur_und_Technische_Basis.md)
**Security:** [Beta Kapitel 16](16_Sicherheitsarchitektur_und_Protected_Content.md)

---

## Teil I – Produktziel

### 1. Ziel

Die Desktop-Anwendung ist der primäre v1-Client für ATHENA.

Sie macht Chat, Knowledge, Memory, Jobs, News, Backup, Security und Diagnose bedienbar, ohne technische Interna im Normalfall zu erzwingen.

---

### 2. Client, nicht Core

Die Desktop-App ist ein autorisierter Client des ATHENA Core. Sie ist nicht selbst die Source of Truth.

---

### 3. UI-Ausfall

Ein UI-Crash darf den Core und persistente Backgroundjobs nicht automatisch beenden.

---

### 4. Progressive Disclosure

Standardansicht bleibt einfach. Technische Details werden bei Bedarf aufgeklappt.

---

## Teil II – UI-Technologie

### 5. Frameworkentscheidung

v1 verwendet **PySide6 / Qt 6** für die native Desktop-Oberfläche.

Gründe:

- Windows-Desktopfähigkeit;
- System Tray;
- native Fenster;
- Accessibility-Grundlagen;
- ausgereifte Model/View-Komponenten;
- Python-Integration.

---

### 6. Process Separation

UI und Core laufen als getrennte Prozesse.

---

### 7. Core Startup

UI kann einen lokalen Core starten, sofern nicht bereits eine Instanz läuft.

---

### 8. Core Independence

Beim Schließen des Hauptfensters kann Core weiterlaufen, wenn Tray-/Backgroundmodus aktiviert ist.

---

## Teil III – App Shell

### 9. Main Navigation

Hauptbereiche:

```text
Chat
Knowledge
Memory
News
Jobs
Models
Backup
Security
Settings
Diagnostics
```

---

### 10. Default Landing

Standardmäßig öffnet Chat beziehungsweise die zuletzt aktive Hauptansicht.

---

### 11. Global Search

Eine zentrale Suche kann Knowledge, Sources und Chats finden; sensible Scopes beachten Unlock.

---

### 12. Status Bar

Kompakte Statusinformationen:

- Core;
- Primary Model;
- Internet/Privacy Route;
- Background Jobs;
- Storage Alerts.

---

## Teil IV – Chat

### 13. Chat Layout

Chat ist primärer Interaktionsbereich mit:

- Conversation list;
- Message stream;
- composer;
- attachment;
- source indicators;
- internet toggle;
- model status.

---

### 14. Streaming

Antworten werden gestreamt. Cancel bleibt jederzeit verfügbar.

---

### 15. Source Panel

Verwendete Sources/Knowledge können in einem Seitenpanel geöffnet werden.

---

### 16. Temporary Chat

Neuer Chat kann ausdrücklich als `temporary` gestartet werden.

---

### 17. Archive Indicator

UI zeigt klar, ob ein Chat standardmäßig archiviert, temporär oder `do_not_store` ist.

---

### 18. Memory Action

Benutzer kann aus einer Nachricht explizit:

```text
merken
als Wissen speichern
nicht speichern
```

auslösen.

---

## Teil V – Knowledge View

### 19. Knowledge Browser

Filter:

- type;
- project;
- lifecycle;
- date;
- protection;
- source;
- epistemic status.

---

### 20. Entity Detail

Zeigt:

- current content;
- Claims;
- Relations;
- Sources/Evidence;
- History;
- Provenance.

---

### 21. Edit

Manueller Edit läuft über Core Write API mit expected_revision.

---

### 22. Conflict UI

Bei Revision Conflict werden beide Versionen und Diff gezeigt; kein stilles Overwrite.

---

### 23. Graph View

Graphvisualisierung ist ergänzend. Listen-/Suchzugriff bleibt primär und zugänglich.

---

## Teil VI – Personal Memory View

### 24. Memory List

Eigener Bereich, klar getrennt von Knowledge.

---

### 25. Fields

Zeigt:

- content;
- kind;
- scope;
- learning mode;
- sensitivity;
- last confirmed;
- origin.

---

### 26. Review

Memory Suggestions können angenommen, bearbeitet oder verworfen werden.

---

### 27. Reset

Bulk Reset benötigt klare Bestätigung und erklärt, dass Knowledge/Archive nicht mitgelöscht werden.

---

## Teil VII – Models

### 28. Model Manager

Zeigt verfügbare Modelle und Primary Model.

---

### 29. Load/Unload

Manuelle Buttons:

```text
Load Primary Model
Unload Primary Model
```

---

### 30. Switch

Model Switch zeigt Hinweis, dass bestehendes Knowledge nicht automatisch neu interpretiert wird.

---

### 31. Resources

VRAM/RAM/Loadstatus soweit verfügbar.

---

## Teil VIII – Jobs

### 32. Queue View

Zeigt Jobtype, Status, Progress, Waiting Reason, Priority.

---

### 33. Controls

Je nach Job:

```text
pause
resume
cancel
retry
details
```

---

### 34. Error Detail

Normale Ansicht verständlich; technische Stacktrace/IDs optional.

---

### 35. No Fake ETA

ETA wird nur angezeigt, wenn aus realen Messdaten sinnvoll ableitbar.

---

## Teil IX – News

### 36. Today

Daily Digest als übersichtliche Ereignisliste.

---

### 37. Timeline

Historische Tage/Wochen/Monate navigierbar.

---

### 38. Event Sources

Event Detail zeigt Quellenvergleich und Unsicherheit.

---

### 39. Backfill

Status verpasster Tage sichtbar.

---

## Teil X – Backup

### 40. Backup Dashboard

Zeigt:

- letzte erfolgreiche Sicherung;
- nächste geplante Sicherung;
- Backupziele;
- Integritätsstatus;
- letzte Restoreprüfung.

---

### 41. Manual Backup

Benutzer kann manuelles Backup auslösen.

---

### 42. Restore

Restoreworkflow ist geführt und zeigt Ziel, Snapshot, Deletion-Ledger-Status und Vorab-Sicherung.

---

## Teil XI – Protected Content

### 43. Lock State

Geschützter Bereich besitzt klar sichtbaren Lockstatus.

---

### 44. Unlock Dialog

Passwortdialog ist Core-kontrollierte UI, kein Pluginpanel.

---

### 45. Auto Lock

Einstellung für Auto-Lock plus sofortiger Lockbutton.

---

### 46. No Locked Preview

Gesperrte Inhalte zeigen keine vertraulichen Titel/Previews.

---

## Teil XII – Tray

### 47. Tray Icon

ATHENA besitzt ein System-Tray-Icon.

---

### 48. Tray Menu

Mindestens:

```text
Open ATHENA
Load Primary Model
Unload Primary Model
Internet On/Off
Lock Protected Content
Pause Background Jobs
System Status
Quit
```

---

### 49. Minimize to Tray

Konfigurierbar:

```text
Close button → minimize to tray
```

statt Prozessbeendigung.

---

### 50. Quit

`Quit` führt kontrollierten Shutdown aus beziehungsweise fragt, ob Backgroundjobs fortgesetzt werden sollen, falls Core als Autostart-Service weiterlaufen könnte.

---

## Teil XIII – Notifications

### 51. Notification Rules

Benachrichtigungen nur für relevante Ereignisse:

- benötigter Benutzereingriff;
- persistenter Fehler;
- Backupproblem;
- Research completed;
- wichtige Automation;
- Security alert.

Kein Spam für normale Backgroundschritte.

---

### 52. Sensitive Notification

Protected Content wird in OS-Notifications nicht im Klartext angezeigt, wenn Scope locked ist.

---

### 53. Action

Notifications dürfen sichere Deep Links in die entsprechende UI-Seite enthalten.

---

## Teil XIV – Settings

### 54. Categories

Settings:

- General;
- Models;
- Memory;
- Internet;
- News;
- Storage;
- Backups;
- Security;
- Resources;
- Plugins;
- Advanced.

---

### 55. Validation

Ungültige Pfade/Ports/Werte werden vor Save validiert.

---

### 56. Restart Required

Einstellungen zeigen klar, wenn Core/UI Restart nötig ist.

---

### 57. Danger Zone

Reset/Delete/Restore-Funktionen liegen in klar abgegrenzter Danger Zone.

---

## Teil XV – Diagnostics

### 58. Health View

Zeigt Modulstatus und verständliche Auswirkungen.

---

### 59. Technical Detail

Optional:

- component version;
- DB schema;
- watermarks;
- queue;
- provider health;
- logs;
- storage roots.

---

### 60. Export Diagnostics

Diagnoseexport redigiert Secrets und Protected Content.

---

## Teil XVI – Accessibility und UX

### 61. Keyboard

Kernfunktionen müssen per Tastatur erreichbar sein.

---

### 62. Scaling

Qt High-DPI-Skalierung muss unterstützt werden.

---

### 63. Long Operations

UI-Thread führt keine langen DB/Netzwerk/Modeljobs aus.

---

### 64. Error Language

Fehler sagen:

- was passiert ist;
- was betroffen ist;
- ob Daten sicher sind;
- was der Benutzer tun kann.

---

### 65. Confirmation

Bestätigungen nur bei wirklich folgenreichen Aktionen; keine Dialogflut.

---

## Teil XVII – Local API Connection

### 66. Connection

UI verbindet sich zur lokalen Core API auf Loopback beziehungsweise lokaler IPC gemäß Kapitel 19.

---

### 67. Authentication

Auch lokale UI verwendet Session-/Clientidentität; `localhost` allein gilt nicht als vollständige Authentifizierung.

---

### 68. Reconnect

Bei Core-Neustart versucht UI kontrolliert reconnect und zeigt Zwischenstatus.

---

### 69. Version Mismatch

Inkompatible UI/Core-Versionen zeigen Update-/Compatibilityhinweis statt undefiniertem Verhalten.

---

## Teil XVIII – State

### 70. UI Preferences

Fenstergröße, Panelzustand und rein visuelle Präferenzen sind Configuration/Client State, nicht Personal Memory.

---

### 71. Draft Composer

Unabgesendeter Chattext kann optional lokal als Draft gespeichert werden. Protected Draft erbt Protection Scope.

---

### 72. No Hidden Canonical State

Keine semantisch relevante Änderung darf ausschließlich im UI-State existieren.

---

## Teil XIX – Tests

### 73. Core Crash UI Test

Core beenden. UI zeigt disconnected und kann reconnect/start anbieten; keine falsche Datenansicht.

---

### 74. UI Crash Job Test

UI-Prozess hart beenden. Backgroundjob im Core läuft weiter.

---

### 75. Tray Test

Main Window schließen → Tray bleibt; Quit → kontrollierter Shutdown.

---

### 76. Protected Notification Test

Locked protected job completed. OS Notification darf keinen vertraulichen Inhalt zeigen.

---

### 77. Conflict Test

Zwei Editclients: zweiter Write erhält Conflictdialog.

---

### 78. Accessibility Test

Chat, Search, Model Load und Settings per Tastatur erreichbar.

---

### 79. Large List Test

Millionen KnowledgeUnits dürfen nicht komplett in UI geladen werden; pagination/virtual model.

---

### 80. Streaming Test

Lange Antwort streamt ohne UI Freeze und ist cancellable.

---

### 81. Offline Core Test

UI startet ohne vorhandenen Core und führt verständlichen Recovery/Startpfad.

---

### 82. Settings Validation Test

Network path als `state_root` → UI zeigt durch Storagepolicy erklärten Fehler statt Save.

---

### 83. Abschluss

Die Desktop-App ist bestanden, wenn ein Nicht-IT-Benutzer ATHENAs zentrale Funktionen sicher bedienen kann, während technische Komplexität, Backgroundarbeit und Persistenz im Core bleiben.

---

## Nächster Schritt

**Beta Kapitel 19 – Core API und zukünftige Clients**.
