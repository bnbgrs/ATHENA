# Kapitel 18 – Plugin- und Erweiterungssystem

---

## Einleitung
ATHENA soll über viele Jahre weiterentwickelt werden können, ohne dass jede neue Funktion den Kern des Systems verändert.
Dafür besitzt ATHENA eine modulare Erweiterungsarchitektur.
Neue Fähigkeiten werden grundsätzlich außerhalb des stabilen Kerns implementiert, sofern sie nicht zwingend Bestandteil der Kernfunktion sein müssen.
Das Plugin-System dient damit nicht dazu, ATHENA möglichst viele Funktionen hinzuzufügen.
Es dient dazu, den Kern klein und langfristig stabil zu halten.

---

## Grundprinzip
Der Core bleibt klein. Fähigkeiten dürfen wachsen.
Plugins erweitern ATHENA.
Sie definieren ATHENA nicht.

---

## ATHENA Core
Der Core enthält ausschließlich Funktionen, die für den grundlegenden Betrieb notwendig sind.
Hierzu gehören insbesondere:
- Koordination
- Wissenszugriff
- Sicherheitsregeln
- Aufgabenverwaltung
- Modellsteuerung
- Plugin-Verwaltung
- grundlegende Benutzerinteraktion
Optionale Funktionen gehören nicht automatisch in den Core.

---

## Plugins
Plugins stellen klar abgegrenzte Fähigkeiten bereit.
Beispiele können später sein:
- zusätzliche Importquellen
- spezielle Dokumentenverarbeitung
- Kalenderintegration
- E-Mail-Integration
- wissenschaftliche Datenquellen
- spezielle Exportfunktionen
- zusätzliche Visualisierungen
- Automatisierungen
Die konkrete Plugin-Auswahl gehört nicht zur Alpha-Spezifikation.

---

## Plugin-Unabhängigkeit
Der langfristige Wissensbestand darf niemals von der dauerhaften Existenz eines Plugins abhängig sein.
Ein Plugin darf Informationen importieren oder verarbeiten.
Nach der Übernahme durch ATHENA gehören diese Informationen jedoch dem Wissenssystem.
Nicht dem Plugin.

---

## Plugin-Lebenszyklus
Plugins können:
- installiert,
- aktiviert,
- deaktiviert,
- aktualisiert,
- ersetzt,
- entfernt
werden.
Keine dieser Aktionen darf bestehendes Wissen beschädigen.

---

## Entfernen eines Plugins
Wird ein Plugin entfernt, bleiben sämtliche bereits übernommenen Daten erhalten.
Dazu gehören insbesondere:
- Originalquellen
- Wissenseinheiten
- Beziehungen
- Provenienz
- Auditinformationen
Lediglich die durch das Plugin bereitgestellte Funktion steht anschließend nicht mehr zur Verfügung.

---

## Berechtigungen
Plugins erhalten ausschließlich die Berechtigungen, die für ihre Aufgabe notwendig sind.
Mögliche Berechtigungsbereiche können später beispielsweise sein:
- Lesen bestimmter Wissensbereiche
- Import von Dateien
- Internetzugriff
- Zugriff auf bestimmte externe Dienste
- Erstellen von Hintergrundaufgaben
Berechtigungen müssen nachvollziehbar sein.

---

## Vertrauensgrenze und Isolation

Least Privilege und Core-Capabilities begrenzen, **was ein konformes Plugin über ATHENAs offizielle Schnittstellen tun darf**.

Diese Berechtigungslogik ist jedoch nicht automatisch eine Betriebssystem-Sandbox für beliebigen absichtlich bösartigen nativen oder Python-Code.

Deshalb gilt:

- Ein Plugin darf nur nach einer ausdrücklichen Benutzerentscheidung installiert und aktiviert werden.
- Behauptet eine konkrete ATHENA-Version, auch absichtlich bösartigen Plugin-Code sicher ausführen zu können, muss sie diese Isolation technisch erzwingen, beispielsweise durch eine geeignete Betriebssystem-Sandbox mit getrennten Datei-, Netzwerk- und Prozessrechten.
- Solange eine solche Sandbox nicht Bestandteil der jeweiligen Beta-Implementierung ist, gilt Drittplugin-Code als **vom Benutzer ausdrücklich vertrauter lokaler Erweiterungscode**.
- Prozessisolation ohne OS-Sandbox dient der Fehler- und Crash-Isolation, nicht als Beweis gegen absichtliche Umgehungsversuche.

Diese Klarstellung ändert nichts an der Pflicht, dass Plugins über die regulären Core-Schnittstellen weder kanonische Datenbankwrites noch Secrets oder externen Netzwerkzugriff ohne gültige Berechtigung erhalten.

---

## Kein direkter Zugriff auf kanonisches Wissen
Plugins dürfen den kanonischen Wissensbestand niemals direkt verändern.
Zulässig:

```text
Plugin
   │
   ▼
ATHENA Core
   │
   ▼
Validierung
   │
   ▼
Wissenssystem
```

Nicht zulässig über die offizielle Plugin-Schnittstelle:

```text
Plugin
   │
   ▼
Wissensdateien / Datenbank direkt verändern
```
Der Core bleibt die Kontrollinstanz.

---

## Wissensbildung
Plugins dürfen kein dauerhaftes Wissen eigenständig erzeugen.
Ein Plugin kann beispielsweise:
- Informationen abrufen,
- Dateien importieren,
- technische Daten vorbereiten.
Automatisierte inhaltliche Interpretation erfolgt über das aktive Primärmodell. Der Benutzer kann semantische Änderungen und Interpretationen ausdrücklich selbst veranlassen. Plugins besitzen dagegen keine eigenständige semantische Entscheidungsbefugnis.

---

## Infrastrukturplugins
Plugins dürfen Infrastrukturmodelle oder technische Verarbeitungsschritte bereitstellen.
Beispiele:
- OCR
- Transkription
- Bildanalyse
- Dateikonvertierung
Auch hierbei gilt:
Technische Verarbeitung ist nicht gleich Wissensbildung.

---

## Internetzugriff
Ein Plugin besitzt nicht automatisch Internetzugriff.

Externe Kommunikation unterliegt denselben Regeln wie alle anderen ATHENA-Komponenten. Ein Plugin darf das Internet nur verwenden, wenn für seine konkrete Funktion eine gültige Benutzerberechtigung besteht.

Eine solche Berechtigung kann ausdrücklich für das Plugin beziehungsweise dessen definierte Funktion konfiguriert werden. Sie darf weder stillschweigend ausgeweitet noch von einem Plugin selbst erteilt werden.

Insbesondere gelten weiterhin:

- Benutzerkontrolle
- Least Privilege
- freigegebene Privacy-/Anonymisierungsschicht
- Fail Closed
- Auditierung

Ein konformes Plugin darf diese Regeln über ATHENAs offizielle Schnittstellen nicht umgehen. Solange eine konkrete Beta-Version keine OS-Sandbox bereitstellt, ist diese Regel keine Behauptung, absichtlich bösartigen lokal ausgeführten Plugin-Code auf Betriebssystemebene sicher einzusperren.

---

## Geschützte Inhalte
Plugins erhalten keinen automatischen Zugriff auf geschützte Inhalte.
Ein Zugriff darf ausschließlich erfolgen, wenn:
- der Bereich entsperrt ist,
- die notwendige Berechtigung besteht,
- der Zugriff für die konkrete Funktion erforderlich ist.

---

## Prompt-Injection
Von Plugins gelieferte externe Inhalte gelten weiterhin ausschließlich als Daten.
Ein Plugin darf keine externen Anweisungen direkt an den ATHENA Core oder das Primärmodell weiterreichen, die interne Regeln überschreiben könnten.

---

## Plugin-Fehler
Der Ausfall eines Plugins darf ATHENA nicht vollständig beeinträchtigen.
Beispiel:
```text
Kalender-Plugin ausgefallen

↓

Kalenderintegration nicht verfügbar

↓

ATHENA funktioniert weiter
```
Pluginfehler müssen soweit isoliert sein, dass ein Plugin-Ausfall den Core nicht mitreißt. Eine Behauptung sicherer Ausführung absichtlich bösartigen Codes setzt zusätzlich eine technisch erzwungene OS-Sandbox voraus.

---

## Fehlerhafte Plugins
Verursacht ein Plugin wiederholt Fehler, darf ATHENA es automatisch deaktivieren.
Der Benutzer wird darüber informiert.
Die gespeicherten Daten bleiben erhalten.

---

## Plugin-Updates
Vor kritischen Plugin-Updates prüft ATHENA:
- Kompatibilität
- benötigte Berechtigungen
- mögliche Auswirkungen
Ein Update darf nicht stillschweigend zusätzliche Berechtigungen erhalten.

---

## Neue Berechtigungen
Fordert eine neue Plugin-Version zusätzliche Rechte, muss dies transparent angezeigt werden.
Der Benutzer entscheidet, ob diese Rechte gewährt werden.

---

## Plugin-Provenienz
Von Plugins importierte Informationen behalten ihre Herkunft.
ATHENA dokumentiert mindestens:
- Plugin
- Quelle
- Importzeitpunkt
- weitere externe Herkunft, sofern bekannt
Dadurch bleibt langfristig nachvollziehbar, wie eine Information in das System gelangt ist.

---

## Plugin-Konfiguration
Plugin-Einstellungen werden getrennt vom Wissensbestand gespeichert.
Ein Plugin darf nicht seine Konfiguration innerhalb von Wissenseinheiten verstecken.
Dadurch können Plugins entfernt oder zurückgesetzt werden, ohne Wissen zu verändern.

---

## Plugin-Daten
Falls ein Plugin eigene technische Daten benötigt, müssen diese klar vom kanonischen Wissensbestand getrennt sein.
Solche Daten gelten grundsätzlich als:
- rekonstruierbar,
- optional,
- oder plugin-spezifisch.
Langfristig relevantes Wissen muss in das reguläre ATHENA-Wissenssystem übernommen werden.

---

## Portabilität
Ein Wissensbestand muss auch auf einer ATHENA-Installation funktionieren, auf der bestimmte Plugins fehlen.
Fehlende Plugins dürfen lediglich die zugehörigen Funktionen deaktivieren.
Das Wissen selbst bleibt lesbar.

---

## Plugin-Transparenz
Der Benutzer kann jederzeit einsehen:
- installierte Plugins
- Status
- Version
- Berechtigungen
- letzte Aktivität
- Fehlerzustand

---

## Einfache Bedienung
Trotz der Erweiterbarkeit soll ATHENA nicht zu einem Plugin-Verwaltungsprojekt für den Benutzer werden.
Installation und Verwaltung sollen möglichst einfach bleiben.
Komplexe technische Details gehören in erweiterte Ansichten.

---

## Erweiterungen ohne Plugin
Nicht jede neue Funktion muss ein Plugin sein.
Kleine Verbesserungen am bestehenden Core dürfen direkt integriert werden, wenn sie eindeutig zur Kernfunktion gehören.
Die Entscheidung folgt dem Prinzip:
Ist diese Funktion notwendig, damit ATHENA grundsätzlich ATHENA bleibt?
Falls nein, sollte eine modulare Erweiterung bevorzugt werden.

---

## Zukunftssicherheit
Das Plugin-System darf technisch weiterentwickelt oder vollständig ersetzt werden.
Die zentrale Architekturregel bleibt jedoch bestehen:
Erweiterungen dürfen den kanonischen Wissensbestand nicht besitzen oder kontrollieren.

---

## Leitregel
Plugins besitzen Funktionen. ATHENA besitzt das Wissen.

---

## Abschluss des Kapitels
Das Erweiterungssystem ermöglicht es, ATHENA über viele Jahre um neue Fähigkeiten zu ergänzen, ohne den stabilen Kern kontinuierlich zu vergrößern.
Plugins bleiben austauschbar.
Der Wissensbestand bleibt unabhängig.
Damit kann sich die Funktionalität von ATHENA langfristig weiterentwickeln, während ihre grundlegende Architektur stabil bleibt.
