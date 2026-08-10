# ATHENA Beta Specification v0.1 – Kapitel 17

## Plugin-System und Berechtigungen

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Security:** [Beta Kapitel 16](16_Sicherheitsarchitektur_und_Protected_Content.md)
**Jobs:** [Beta Kapitel 12](12_Job-System_Queue_und_Scheduler.md)

---

## Teil I – Ziel und Sicherheitsannahme

### 1. Ziel

Das Plugin-System erweitert ATHENA, ohne Plugins direkten Zugriff auf kanonische Persistenz, Secrets oder unkontrolliertes Netzwerk zu geben.

---

### 2. Plugins sind optional

Der Core muss ohne Plugins vollständig start- und recoveryfähig bleiben.

---

### 3. Untrusted Extension

v1 behandelt Drittplugins **nicht als Core-Komponenten**, aber auch nicht so, als könne ein normaler separater Python-Prozess absichtlich bösartigen Code sicher sandboxen.

Die v1-Vertrauensannahme lautet:

> **Ein aktiviertes Drittplugin ist ausdrücklich vom Benutzer vertrauter lokaler Erweiterungscode.**

Das Capabilitymodell begrenzt offizielle Core-API-Zugriffe und schützt gegen Fehler, unbeabsichtigte Rechteausweitung und fehlerhafte Integrationen. Es ist **keine** vollständige Hostile-Code-Sandbox.

Soll ATHENA später nicht vertrauenswürdigen Plugin-Code ausführen, benötigt dies eine separate, technisch erzwungene OS-Sandbox, die insbesondere Dateisystem-, Netzwerk-, Prozess- und Secretzugriff begrenzt. Bis dahin darf die UI Plugins nicht als „sicher trotz bösartigem Code“ darstellen.

---

### 4. No Semantic Authority

Plugins dürfen Daten liefern und Aktionen anbieten. Eigenständige semantische Wissensentscheidungen bleiben Benutzer/Primärmodell vorbehalten.

---

## Teil II – Plugin Package

### 5. Manifest

Jedes Plugin besitzt ein manifestbasiertes Paket mit mindestens:

```text
plugin_id
name
version
api_version
entrypoint
permissions
capabilities
publisher metadata optional
```

---

### 6. Stable Plugin ID

`plugin_id` ist stabil über Updates. Displayname darf sich ändern.

---

### 7. Namespacing

Plugin-spezifische Jobtypes, config keys und event names verwenden den Plugin-ID-Namespace.

---

### 8. No Code from Manifest

Manifestfelder werden validiert und nicht als Shellcommand evaluiert.

---

## Teil III – Installation

### 9. Explicit Install

Installation erfolgt nur durch explizite Benutzeraktion.

---

### 10. Package Inspection

Vor Aktivierung zeigt ATHENA:

- Quelle;
- Version;
- angeforderte Permissions;
- Netzwerkziele soweit deklariert;
- Dateizugriffe;
- Connectorfähigkeiten.

---

### 11. Disabled after Install optional

Ein Plugin kann installiert, aber deaktiviert sein, bis Permissions bestätigt wurden.

---

### 12. No Auto Side Load

ATHENA lädt nicht automatisch beliebigen Python-Code aus zufälligen Verzeichnissen.

---

## Teil IV – Plugin Host

### 13. Out-of-process

v1 bevorzugt einen separaten `PluginHost`-Prozess für Drittplugins.

Zweck:

- Crash-Isolation;
- klare IPC-Grenze;
- kontrollierte offizielle Capabilities;
- einfacheres Kill/Restart-Verhalten.

Ein separater Prozess unter demselben Benutzerkonto ist **allein keine Security Sandbox**.

---

### 14. IPC

Kommunikation erfolgt über eine versionierte lokale IPC/RPC-Schicht.

---

### 15. No Core Memory

Pluginprozess erhält keinen direkten Python-Objektzugriff auf Core Services oder entschlüsselte Memorystrukturen.

---

### 16. Crash Isolation

Plugincrash beendet nicht den ATHENA Core.

---

### 17. Restart

PluginHost kann neu gestartet werden. Pending plugin jobs bleiben über die Core Queue nachvollziehbar.

---

## Teil V – Capability Model

### 18. Capabilities

Beispiele:

```text
read_selected_sources
create_import_candidate
request_search
request_external_access
read_project_scope
write_projection
register_ui_panel
schedule_job
request_secret_handle
```

---

### 19. Deny by Default

Nicht deklarierte oder nicht gewährte Capability ist denied.

---

### 20. Scope

Capabilities können auf Projects, Folders, Domains oder Entitytypes begrenzt werden.

---

### 21. Temporary Grant

Benutzer kann eine Permission nur für eine Aktion/Session freigeben.

---

### 22. Persistent Grant

Dauerhafte Permission wird in Configuration/Audit gespeichert und kann widerrufen werden.

---

## Teil VI – Datenzugriff

### 23. Query API

Plugin erhält Daten nur über Core APIs mit SecurityContext.

---

### 24. No Raw DB

Kein direkter SQLite-Zugriff.

---

### 25. No Arbitrary Archive Path

Plugin erhält keine absoluten Blobpfade, wenn eine streamende Source-API genügt.

---

### 26. Protected Content

Protected Daten benötigen explizite Capability **und** unlocked Scope.

---

### 27. Data Minimization

Core liefert nur die für die Pluginoperation erforderlichen Felder.

---

## Teil VII – Semantische Änderungen

### 28. Proposal Pattern

Plugin kann einen Import, Benutzeraktion oder Modellworkflow **anstoßen**, aber kein SQL-Write durchführen.

---

### 29. User-authored Plugin Data

Wenn der Benutzer über eine Plugin-UI eine semantische Änderung explizit erstellt, kann `actor=user` sein; Provenienz nennt zusätzlich den verwendeten Client/Plugin.

---

### 30. Plugin-generated Proposal

Automatisch vom Plugin abgeleitete semantische Kandidaten werden nicht als Primärmodellwissen ausgegeben. Sie müssen über Benutzerbestätigung oder Primary Model Processing laufen.

---

## Teil VIII – Netzwerk

### 31. Gateway Only

Pluginnetzwerk läuft über ExternalAccessGateway.

---

### 32. Declared Domains

Pluginmanifest kann gewünschte Domains/APIklassen deklarieren.

---

### 33. No Direct Socket

Konforme Plugins verwenden für externe Kommunikation ausschließlich die vom Core bereitgestellte Gateway Capability.

Solange v1 keine OS-Sandbox bereitstellt, kann nicht behauptet werden, dass absichtlich bösartiger lokal ausgeführter Plugin-Code technisch niemals selbst einen Socket öffnen könnte. Deshalb dürfen nur vom Benutzer ausdrücklich vertraute Drittplugins aktiviert werden.

Eine spätere Hardened Plugin Sandbox muss direkten Netzwerkzugriff auf Betriebssystemebene blockieren und ausschließlich Gateway-RPC erlauben.

---

### 34. Audit

Jeder Gatewayrequest ist dem Plugin und der Permission zuordenbar.

---

## Teil IX – Secrets

### 35. Secret Handle

Plugin kann einen referenzierten Secret Handle erhalten, nicht zwingend den Klartext.

---

### 36. Injection

Wenn eine API einen Token benötigt, kann Gateway/Connector den Secretwert serverseitig in Header einfügen, ohne ihn dem Pluginprozess offenzulegen.

---

### 37. No Secret Persistence

Plugin darf Secretwerte nicht in eigene Config oder Logs schreiben.

---

## Teil X – Plugin Storage

### 38. Private Plugin Data

Plugin erhält optional einen begrenzten eigenen Storagebereich.

---

### 39. Not Canonical

Plugin-private Daten sind kein kanonisches Knowledge.

---

### 40. Backup

Konfiguration/State eines wichtigen Plugins kann als Configuration/Operational Data gesichert werden, wenn für Wiederherstellung erforderlich.

---

### 41. Quota

Plugin Storage besitzt Quotas und Disk-Pressure-Regeln.

---

## Teil XI – UI Extensions

### 42. UI Panel

Plugins dürfen deklarative oder klar isolierte UI-Erweiterungen registrieren.

---

### 43. No UI Privilege Escalation

Ein Pluginpanel erhält keine zusätzliche Datenberechtigung nur weil es sichtbar ist.

---

### 44. Visual Trust

UI kennzeichnet Plugininhalte, damit sie nicht mit Core-Sicherheitsdialogen verwechselt werden.

---

### 45. Sensitive Input

Passwort-/Masterkey-Eingaben erfolgen ausschließlich in Core-kontrollierten UI-Flächen, niemals in Pluginpanels.

---

## Teil XII – Plugin Jobs

### 46. Registered Job Type

Plugin darf Jobtypen registrieren, wenn Capability erlaubt.

---

### 47. Core Scheduler

Scheduling, Lease, Retry und Resource Admission bleiben beim Core.

---

### 48. Fencing

Pluginworker kann nach Leaseverlust keine veralteten Resultate committen.

---

### 49. Cancel

Pluginjob muss Cancellation unterstützen oder als killable isolierter Worker behandelt werden.

---

## Teil XIII – Versioning

### 50. API Version

Pluginmanifest nennt kompatible Core Plugin API-Version.

---

### 51. Compatibility

Inkompatibles Plugin wird deaktiviert statt beim Startup Crash zu verursachen.

---

### 52. Upgrade

Pluginupdate ist eine explizite versionierte Änderung und wird auditiert.

---

### 53. Migration

Plugin-private Storage-Migrationen laufen getrennt von Core-Schema; ein Plugin darf keine Core-Tabellenmigration definieren.

---

## Teil XIV – Disable und Remove

### 54. Disable

Deaktivieren stoppt Pluginjobs, widerruft Runtimecapabilities und lässt Daten zunächst erhalten.

---

### 55. Uninstall

Uninstall entfernt Code. Plugin-private Daten können nach Benutzerwahl erhalten oder gelöscht werden.

---

### 56. Canonical Knowledge

Knowledge, das über einen legitimen Coreprozess unter Verwendung eines Plugins entstanden ist, wird nicht automatisch beim Plugin-Uninstall gelöscht.

---

### 57. Secrets

Plugin-spezifische Secretrefs werden bei Uninstall sichtbar zur Bereinigung angeboten.

---

## Teil XV – Built-in versus Third-party

### 58. Built-in Adapter

Interne offizielle Adapter können technisch im selben Capabilitymodell laufen, obwohl sie mit ATHENA ausgeliefert werden.

---

### 59. No Hidden Superuser

Auch Built-ins sollen Core APIs nutzen, statt versteckte Direktzugriffe zu etablieren.

---

## Teil XVI – Signing und Herkunft

### 60. Package Hash

Installierte Pluginpakete erhalten einen Integritätshash.

---

### 61. Signature optional v1

Kryptographische Publishersignaturen können unterstützt werden, sind aber v1 nicht zwingend Voraussetzung für lokale eigene Plugins.

---

### 62. Provenance

ATHENA zeigt klar, ob ein Plugin:

- lokal entwickelt;
- signiert;
- unverifiziert;
- aus bekannter Quelle

stammt.

---

## Teil XVII – Tests

### 63. Direct DB Test

Contracttest: Ein konformes Plugin erhält keine DB-Connection und keine offizielle Dateicapability auf `athena.db`.

Dieser Test beweist die Core-API-Grenze. Ein separater zukünftiger Sandbox-Test ist erforderlich, sobald ATHENA behauptet, absichtlich bösartigen Plugin-Code sicher isolieren zu können.

---

### 64. Permission Test

Plugin ohne Source Permission fragt Source ab. Denied.

---

### 65. Scope Test

Plugin darf Project A lesen, Project B nicht.

---

### 66. Protected Test

Permission vorhanden, Scope locked: Protected Read bleibt denied.

---

### 67. Network Test

Contracttest: Ein Plugin ohne Gateway Permission erhält über ATHENA keine externe Network Capability.

Bei einer zukünftigen Hostile-Code-Sandbox muss zusätzlich ein OS-Level-Test beweisen, dass direkte Sockets tatsächlich blockiert sind.

---

### 68. Secret Test

Secret-injection via Gateway funktioniert, Plugin bekommt Klartexttoken nicht.

---

### 69. Crash Test

Pluginhost hart beenden. Core bleibt verfügbar.

---

### 70. Zombie Job Test

Pluginworker nach Leaseverlust versucht Ergebnis einzureichen. Fencing reject.

---

### 71. Upgrade Test

Inkompatible API-Version: Plugin deaktiviert, Core startet normal.

---

### 72. Uninstall Test

Plugin entfernen. Kanonisches Knowledge bleibt; Plugin-private Daten folgen Benutzerwahl.

---

### 73. Prompt Injection Plugin Test

Plugin liefert Source mit Instruktion an Modell. Source bleibt Data; keine Capability-Eskalation.

---

### 74. Abschluss

Das Plugin-System ist für v1 bestanden, wenn Erweiterungen über die **offiziellen ATHENA-Schnittstellen** nur die ausdrücklich gewährten Capabilities besitzen, ein Plugincrash den Core nicht mitreißt, Secrets und kanonische Writes nicht direkt übergeben werden und die UI transparent macht, dass aktivierter Drittplugin-Code ohne OS-Sandbox eine Benutzer-Vertrauensentscheidung ist.

Die stärkere Behauptung, auch absichtlich bösartigen Plugin-Code sicher auszuführen, ist erst dann zulässig, wenn eine separate Hardened-Sandbox-Spezifikation und deren OS-Level-Tests implementiert sind.

## Nächster Schritt

**Beta Kapitel 18 – Desktop-Anwendung und System Tray**.
