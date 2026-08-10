# Kapitel 27 – Recovery Mode, Selbstdiagnose und Fehlerbehandlung

---

## Einleitung

ATHENA ist als langfristiges System konzipiert.

Deshalb muss davon ausgegangen werden, dass irgendwann Komponenten ausfallen.

Mögliche Ursachen sind:

beschädigte Dateien,

fehlerhafte Updates,

inkompatible Modelle,

defekte Plugins,

unterbrochene Schreibvorgänge,

ausgefallene Datenträger,

Netzwerkprobleme,

fehlerhafte Indizes,

beschädigte Konfigurationen,

nicht erreichbares Modellbackend,

nicht erreichbare Privacy-/Anonymisierungsschicht,

unerwartete Systemabbrüche.

Ein solcher Fehler darf nicht automatisch bedeuten, dass ATHENA vollständig unbenutzbar wird.

---

## Grundprinzip

ATHENA muss Fehler nicht nur erkennen. Sie muss wissen, wie sie in einen sicheren Zustand zurückkehrt.

---

## Fehlerklassen

ATHENA unterscheidet mindestens zwischen:

temporären Fehlern,

Komponentenfehlern,

Datenfehlern,

Konfigurationsfehlern,

Sicherheitsfehlern,

kritischen Systemfehlern.

Diese Kategorien bestimmen, wie ATHENA reagiert.

---

## Temporäre Fehler

Temporäre Fehler können sich ohne strukturelle Änderung wieder lösen.

Beispiele:

NAS kurzzeitig nicht erreichbar,

Privacy-/Anonymisierungsschicht unterbrochen,

das Modellbackend startet gerade,

VRAM momentan belegt.

ATHENA wartet oder versucht die Aufgabe später erneut.

---

## Komponentenfehler

Eine einzelne Komponente kann ausfallen, während der Rest des Systems funktioniert.

Beispiele:

```text
Embedding-System ausgefallen

↓

semantische Suche deaktiviert

↓

Volltextsuche bleibt verfügbar
```

oder:

```text
Obsidian-Integration ausgefallen

↓

Obsidian-Synchronisation pausiert

↓

ATHENA Core funktioniert weiter
```

---

## Datenfehler

ATHENA muss beschädigte oder unvollständige persistente Daten erkennen können.

Beispiele:

beschädigte Originaldatei,

inkonsistente Metadaten,

fehlende Referenz,

unvollständiger Schreibvorgang,

beschädigte Datenbankseite.

Solche Fehler werden niemals stillschweigend ignoriert.

---

## Konfigurationsfehler

Eine fehlerhafte Konfiguration darf ATHENA nicht dauerhaft unstartbar machen.

Wenn möglich, startet ATHENA mit:

letzter gültiger Konfiguration,

sicheren Standardwerten,

oder Recovery Mode.

Die fehlerhafte Konfiguration bleibt zur Diagnose erhalten.

---

## Sicherheitsfehler

Sicherheitsrelevante Fehler werden nach dem Prinzip Fail Closed behandelt.

Beispiel:

```text
Internet angefordert

↓

Privacy-/Anonymisierungsschicht nicht verfügbar

↓

kein direkter Internetzugriff
```

Komfort darf Sicherheitsregeln nicht automatisch außer Kraft setzen.

---

## Kritische Systemfehler

Ein Fehler gilt als kritisch, wenn die Integrität des kanonischen Wissensbestands nicht garantiert werden kann.

In diesem Fall beendet ATHENA nicht einfach den gesamten Zugriff.

Stattdessen kann der Wissensbestand in einen geschützten Nur-Lese-Modus wechseln.

---

## Read-Only Safe Mode

Kann ATHENA nicht sicher schreiben, aber vorhandene Daten zuverlässig lesen, wird ein Nur-Lese-Modus angeboten.

Beispiel:

ATHENA Recovery Mode

Wissensbestand:

lesbar

Schreibzugriff:

deaktiviert

Grund:

Integritätsprüfung erforderlich

Der Benutzer kann weiterhin vorhandenes Wissen einsehen, ohne weitere Schäden zu riskieren.

---

## Recovery Mode

ATHENA besitzt einen eigenständigen Recovery Mode.

Dieser muss mit möglichst wenigen Abhängigkeiten starten können.

Er darf insbesondere nicht voraussetzen, dass:

Primärmodell funktioniert,

Embedding-System funktioniert,

Obsidian funktioniert,

Plugins funktionieren,

Internet verfügbar ist.

---

## Aufgaben des Recovery Mode

Der Recovery Mode kann mindestens:

Systemzustand anzeigen,

Wissensspeicher lokalisieren,

Integrität prüfen,

Backup-Stände anzeigen,

Konfiguration prüfen,

problematische Plugins deaktivieren,

Indizes neu aufbauen,

Restore starten,

Diagnoseinformationen exportieren.

---

## Minimaler Recovery Stack

Der Recovery Mode soll technisch möglichst klein bleiben.

Vereinfacht:

```text
Recovery UI

↓

Recovery Core

↓

Dateisystem
```

+

Konfiguration

+

Backup-System

+

Integritätsprüfung

Je weniger Komponenten hierfür erforderlich sind, desto höher ist die Wahrscheinlichkeit, dass ATHENA repariert werden kann.

---

## Startfehler

Kann ATHENA mehrfach hintereinander nicht normal starten, soll automatisch ein Recovery-Angebot erscheinen.

Beispiel:

ATHENA konnte dreimal nicht vollständig gestartet werden.

[Recovery Mode starten]

[Erneut versuchen]

Die konkrete Schwelle wird später technisch festgelegt.

---

## Letzter funktionierender Zustand

ATHENA soll relevante funktionierende Konfigurationen historisieren.

Nach einem fehlerhaften Update oder einer beschädigten Einstellung kann dadurch auf einen bekannten funktionsfähigen Zustand zurückgegriffen werden.

---

## Startup Health Check

Beim Start prüft ATHENA zentrale Komponenten.

Beispielsweise:

Core                     OK

Konfiguration            OK

Wissensspeicher          OK

Wissensintegrität        OK

Suchindex                OK

Backup-System            OK

Modellbackend             nicht erreichbar

Anonymisierung            OK

Obsidian                 nicht gestartet

Nicht jede fehlende Komponente verhindert den Start.

---

## Abhängigkeitsgraph

ATHENA kennt die Abhängigkeiten seiner Komponenten.

Dadurch kann das System unterscheiden:

```text
Primärmodell ausgefallen
→ Chat-Generierung betroffen
→ Archivsuche weiterhin möglich

von:

kanonischer Wissensspeicher beschädigt
→ Schreibzugriff stoppen
→ Recovery erforderlich
```

---

## Selbstdiagnose

ATHENA soll häufige Probleme selbst diagnostizieren können.

Dazu gehören beispielsweise:

Speicherpfad nicht erreichbar,

zu wenig Speicherplatz,

Modellbackend nicht erreichbar,

Modell fehlt,

VRAM reicht nicht,

Privacy-/Anonymisierungsschicht nicht erreichbar,

Backup-Ziel nicht erreichbar,

beschädigter Suchindex,

Plugin inkompatibel.

---

## Verständliche Diagnose

Die normale Fehlermeldung beschreibt:

was nicht funktioniert,

welche Funktionen betroffen sind,

was ATHENA bereits versucht hat,

welche Handlung möglich ist.

---

## Beispiel

Nicht:

VectorStoreError 0x8019

Sondern:

Die semantische Suche ist momentan nicht verfügbar.

Der Suchindex scheint beschädigt zu sein.

Dein Wissensbestand ist davon nicht betroffen.

ATHENA kann den Index automatisch neu aufbauen.

[Index neu aufbauen]

Technische Details bleiben optional verfügbar.

---

## Automatische Reparatur

ATHENA darf rekonstruierbare technische Komponenten selbst reparieren.

Beispiele:

Cache neu erzeugen,

Suchindex neu aufbauen,

Embeddings neu erzeugen,

rein rekonstruierbare temporäre Dateien bereinigen,

unterbrochenen Hintergrundjob erneut starten.

Diese Reparaturen dürfen weder autoritative persistente Daten noch nicht anderweitig bestätigten Durable Operational State verändern oder löschen.

---

## Semantische Reparaturen

Fehler im eigentlichen Wissen werden nicht stillschweigend automatisch „repariert“.

Wenn eine Wissenseinheit möglicherweise falsch ist, gelten die Regeln für:

Versionierung,

Reinterpretation,

Provenienz,

Benutzerkontrolle.

---

## Transaktionale Schreibvorgänge

Kritische persistente Änderungen sollen so implementiert werden, dass ein Abbruch nicht zu einem halb geschriebenen kanonischen Zustand führt.

Das technische Verfahren wird in der Beta-Spezifikation festgelegt.

Die Architektur verlangt jedoch:

Entweder eine Änderung ist vollständig übernommen oder sie gilt als nicht übernommen.

---

## Write-Ahead- und Journal-Prinzip

Für kritische Datenstrukturen sollen geeignete transaktionale beziehungsweise journalbasierte Verfahren verwendet werden.

Dadurch kann ATHENA nach einem Absturz erkennen:

welche Änderung geplant war,

welche abgeschlossen wurde,

welche verworfen oder erneut ausgeführt werden muss.

---

## Stromausfall

Nach einem unerwarteten Stromausfall führt ATHENA beim nächsten Start eine Konsistenzprüfung durch.

Unvollständige Hintergrundjobs werden über die persistente Queue wieder aufgenommen.

---

## Keine Doppelverarbeitung

Nach einem Neustart muss ATHENA erkennen können, ob ein Job bereits erfolgreich abgeschlossen wurde.

Dadurch wird verhindert, dass dieselbe Aufgabe aufgrund eines Absturzes mehrfach kanonische Daten erzeugt.

---

## Idempotente Hintergrundjobs

Soweit möglich werden Hintergrundaufgaben idempotent gestaltet.

Das bedeutet:

Eine sichere Wiederholung derselben Aufgabe darf nicht zu unkontrollierten Duplikaten oder mehrfachen Veränderungen führen.

---

## Checkpoints

Sehr lange Hintergrundaufgaben dürfen Zwischenstände speichern.

Beispiel:

```text
100.000 Dokumente analysieren

↓

Checkpoint nach 5.000

↓

Systemneustart

↓

bei 5.001 fortsetzen
```

Dadurch müssen große Aufgaben nach einem Fehler nicht vollständig neu beginnen.

---

## Modellfehler

Antwortet das Primärmodell nicht, stürzt es ab oder liefert technisch ungültige Ergebnisse, bleibt der ursprüngliche Auftrag erhalten.

ATHENA kann:

erneut versuchen,

Modell neu laden,

Aufgabe pausieren,

Benutzer informieren.

Es darf keine unvollständige Ausgabe als erfolgreich gespeichertes Wissen behandeln.

---

## Primärmodell und Recovery

Der Recovery Mode darf nicht von der Verfügbarkeit des konfigurierten Primärmodells abhängen.

Die Reparatur des Systems ist eine technische Kernfunktion.

Das Primärmodell kann nach erfolgreicher Wiederherstellung wieder zugeschaltet werden.

---

## Infrastrukturmodell-Fehler

Verweigert oder scheitert ein Hilfsmodell bei einem Inhalt, bleibt die Originalquelle erhalten.

Der Job erhält einen nachvollziehbaren Fehlerstatus.

Später kann:

dasselbe Modell erneut versucht,

ein anderes kompatibles Modell verwendet,

oder der Verarbeitungsschritt übersprungen

werden.

---

## Plugin-Crash-Isolation

Ein Plugin darf den ATHENA Core nicht mitreißen.

Plugin-Prozesse beziehungsweise Plugin-Aufrufe sollen soweit technisch sinnvoll isoliert werden.

Ein fehlerhaftes Plugin kann deaktiviert werden.

---

## Plugin Safe Mode

Der Recovery Mode kann ATHENA ohne optionale Plugins starten.

Dadurch lässt sich feststellen, ob ein Plugin für einen Fehler verantwortlich ist.

---

## Netzwerkfehler

Netzwerkfehler dürfen nicht zu Datenverlust führen.

Beispiel:

```text
NAS-Verbindung bricht während Synchronisation ab

↓

lokale Kopie bleibt erhalten

↓

Übertragung gilt als nicht bestätigt

↓

später erneut synchronisieren
```

---

## Backup-Fehler

Ein fehlgeschlagenes Backup wird deutlich angezeigt.

ATHENA darf niemals einen fehlerhaften Sicherungsvorgang als erfolgreich markieren.

Bestehende gültige Backups bleiben erhalten.

---

## Restore-Fehler

Scheitert eine Wiederherstellung, darf der Ausgangszustand nicht unnötig zerstört werden.

Soweit möglich arbeitet Restore deshalb:

in einen kontrollierten Zielzustand,

mit vorheriger Sicherung,

mit abschließender Validierung.

---

## Speicherdefekt

Erkennt ATHENA Anzeichen für beschädigte Dateien oder Datenträgerprobleme, erhält Datensicherung Vorrang vor nicht notwendigen Wartungsaufgaben.

Das System informiert den Benutzer klar über die Dringlichkeit.

---

## Diagnoseexport

ATHENA kann ein Diagnosepaket erzeugen.

Dieses enthält ausschließlich für die technische Fehleranalyse notwendige Informationen.

Beispielsweise:

Systemversion,

Komponentenstatus,

relevante Logs,

Fehlercodes,

Konfiguration ohne Geheimnisse.

---

## Keine Geheimnisse im Diagnosepaket

Diagnoseexporte dürfen standardmäßig nicht enthalten:

Passwörter,

Schlüssel,

geschützte Inhalte,

vollständige private Chats,

unnötige persönliche Dokumente.

---

## Lokale Diagnose

Selbstdiagnose funktioniert vollständig lokal.

ATHENA muss keine Telemetriedaten an einen externen Server senden, um Fehler analysieren zu können.

---

## Benutzerbestätigung bei riskanten Reparaturen

Reparaturen, die kanonische Daten oder Sicherheitskonfigurationen verändern könnten, benötigen eine klare Benutzerbestätigung.

Rekonstruierbare technische Komponenten dürfen dagegen automatisch repariert werden.

---

## Recovery nach Festplattenwechsel

Der Recovery Mode unterstützt den Fall, dass der ursprüngliche Datenträger nicht mehr existiert.

Beispiel:

```text
Neue Festplatte

↓

ATHENA neu installieren

↓

Recovery Mode

↓

Backup auswählen

↓

neuen Speicherpfad festlegen

↓

Wissen wiederherstellen

↓

Indizes rekonstruieren

↓

Normalbetrieb
```

---

## Recovery nach Computerwechsel

Dasselbe Verfahren gilt grundsätzlich nach einem vollständigen Hardwarewechsel.

ATHENA darf für die Wiederherstellung keine geheimen Informationen benötigen, die ausschließlich auf dem alten Rechner existierten, sofern dies durch die definierte Schlüssel- und Recovery-Strategie vermeidbar ist.

---

## Recovery-Dokumentation

ATHENA soll zusätzlich eine menschenlesbare Notfalldokumentation besitzen.

Diese erklärt unabhängig von der normalen Benutzeroberfläche:

wo sich der Wissensbestand befindet,

wo Backups liegen,

wie eine Wiederherstellung gestartet wird,

welche Datenformate verwendet werden.

Diese Dokumentation gehört zu den langfristig zu sichernden Projektunterlagen.

---

## Worst-Case-Szenario

Der strengste Recovery-Test lautet:

Hauptcomputer zerstört

+

Hauptfestplatte zerstört

+

```text
ATHENA nicht installiert

↓

neuer Computer

↓

ATHENA installieren

↓

gültiges Backup bereitstellen

↓

Wissensbestand wiederherstellen

↓

System rekonstruieren
```

Dieses Szenario muss grundsätzlich vorgesehen sein.

---

## Recovery ohne identisches Modell

Die Wiederherstellung darf nicht davon abhängen, dass exakt dasselbe Primärmodell noch verfügbar ist.

Das historische Wissen bleibt lesbar.

Ein neues kompatibles Primärmodell kann anschließend verwendet werden.

---

## Recovery ohne Obsidian

Dasselbe gilt für Obsidian.

Der Wissensbestand muss auch ohne Obsidian wiederherstellbar und lesbar bleiben.

---

## Recovery ohne das aktuelle Modellbackend

Auch das aktuell konfigurierte Modellbackend darf nicht die einzige Möglichkeit sein, die gespeicherten Daten zu rekonstruieren.

Falls das aktuell verwendete Modellbackend zukünftig nicht mehr existiert, müssen die autoritativen Daten weiterhin erhalten und wiederherstellbar bleiben.

Ein anderes Modellbackend kann später angebunden werden.

---

## Wiederherstellbarkeit als Testkriterium

Recovery ist keine Funktion, die erst nach einem Fehler getestet wird.

ATHENA soll regelmäßig prüfen, ob die Voraussetzungen für eine Wiederherstellung weiterhin erfüllt sind.

Dies ergänzt die bereits definierte Backup-Verifikation.

---

## Health Status

Die Oberfläche kann einen kompakten Gesamtzustand anzeigen.

Beispielsweise:

ATHENA Systemzustand

Core                 OK

Wissen               OK

Backup               OK

Primärmodell         OK

Suche                OK

Anonymisierung         OK

Speicher             OK

Recovery Readiness:

bereit

---

## Keine falsche Sicherheit

Ein grüner Status darf nur angezeigt werden, wenn die entsprechende Prüfung tatsächlich durchgeführt wurde.

„Nicht geprüft“ ist ein eigener Zustand.

---

## Recovery Readiness

ATHENA kann regelmäßig kontrollieren:

existiert ein gültiges Backup?

wurde dessen Integrität geprüft?

ist die Recovery-Dokumentation vorhanden?

sind notwendige Schlüssel beziehungsweise Recovery-Informationen verfügbar?

kann der kanonische Wissensbestand gelesen werden?

Dadurch wird Katastrophenschutz messbar.

---

## Ziel

ATHENA soll nicht dadurch robust sein, dass niemals etwas schiefgeht.

ATHENA soll robust sein, weil das System auf Fehler vorbereitet ist.

Ein defektes Plugin,

ein ausgefallenes Modell,

eine beschädigte Konfiguration,

ein Stromausfall

oder sogar ein vollständiger Hardwareverlust

dürfen nicht automatisch das Ende des Wissenssystems bedeuten.

---

## Leitregel

Ein Fehler ist erst dann eine Katastrophe, wenn es keinen getesteten Weg zurück gibt. ATHENA muss diesen Weg besitzen.

---

## Abschluss des Kapitels

Recovery, Selbstdiagnose und Fehlerisolierung bilden die letzte technische Verteidigungslinie des ATHENA-Wissenssystems.

Der Core muss Fehler erkennen, beschädigte Komponenten isolieren, rekonstruierbare Strukturen reparieren und bei kritischen Problemen in einen sicheren Zustand wechseln können.

Damit wird ATHENA nicht als fehlerfreies System entworfen, sondern als System, das Fehler überleben kann.
