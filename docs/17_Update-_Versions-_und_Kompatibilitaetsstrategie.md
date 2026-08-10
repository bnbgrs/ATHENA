# Kapitel 17 – Update-, Versions- und Kompatibilitätsstrategie

---

## Einleitung
ATHENA ist als langfristiges System konzipiert.
Während der Lebensdauer des Wissensbestands werden sich nahezu alle technischen Komponenten verändern.
Dazu gehören:
- ATHENA selbst
- Betriebssysteme
- Modellbackends
- Obsidian
- Primärmodelle
- Infrastrukturmodelle
- Plugins
- Treiber
- Speicherhardware
- Netzwerkumgebungen
Diese Veränderungen dürfen niemals dazu führen, dass der Wissensbestand unbrauchbar wird.
Updates werden deshalb als kontrollierter Systemprozess behandelt.

---

## Grundprinzip
Software darf sich ändern. Wissen muss bestehen bleiben.
Der Wissensbestand besitzt Vorrang vor jeder Softwareversion.

---

## Trennung von Software und Wissen
ATHENA trennt konsequent:
```text
ATHENA Software
        │
        ▼
ATHENA Core
        │
        ▼
Kanonischer Wissensbestand
```
Ein Update der Software darf den Wissensbestand nicht automatisch neu definieren.

---

## Keine unkontrollierten Updates
ATHENA installiert keine kritischen Systemupdates unbemerkt.
Der Benutzer behält die Kontrolle darüber, wann wesentliche Komponenten aktualisiert werden.
Automatische Prüfungen auf verfügbare Updates sind zulässig.
Automatische Änderungen am Wissensbestand sind es nicht.

---

## Standardablauf eines Updates
Ein kontrolliertes Update folgt grundsätzlich diesem Ablauf:
```text
Update verfügbar
        │
        ▼
Kompatibilität prüfen
        │
        ▼
Integrität prüfen
        │
        ▼
Backup erstellen
        │
        ▼
Update durchführen
        │
        ▼
Selbsttests
        │
        ├── erfolgreich → neue Version freigeben
        │
        └── fehlgeschlagen → Rollback
```

---

## Backup vor kritischen Updates
Vor einem Update, das den Core, die Wissensverarbeitung oder die Speicherstruktur beeinflussen könnte, wird ein gültiger Wiederherstellungspunkt erstellt.
Das Update darf erst fortgesetzt werden, wenn dieser Sicherungspunkt erfolgreich angelegt wurde.

---

## Selbsttests
Nach einem Update prüft ATHENA automatisch die wichtigsten Systemfunktionen.
Hierzu gehören mindestens:
- ATHENA Core
- Zugriff auf den Wissensbestand
- Integrität des Wissensbestands
- Suche
- Primärmodell-Anbindung
- Infrastrukturmodelle
- Queue und Scheduler
- konfigurierte Privacy-/Anonymisierungsschicht
- Netzwerk- und Wissensspeicher
- Backup-System
- Plugin-Kompatibilität
Erst danach gilt das Update als erfolgreich.

---

## Rollback
Schlägt ein Update oder ein kritischer Selbsttest fehl, muss ATHENA soweit technisch möglich auf den letzten funktionierenden Zustand zurückkehren.
Der Benutzer wird über:
- Fehler
- betroffene Komponente
- Rollback
- aktuellen Systemzustand
informiert.
Ein fehlgeschlagenes Update darf nicht stillschweigend als erfolgreich behandelt werden.

---

## Wissensmigrationen
Manche zukünftigen Versionen können Änderungen an der kanonischen Wissensstruktur erfordern.
Solche Migrationen sind besonders kritisch.
Sie müssen:
- angekündigt,
- dokumentiert,
- vorab gesichert,
- überprüfbar,
- soweit technisch möglich reversibel
sein.
ATHENA darf keine irreversible Migration des einzigen Wissensbestands durchführen.

---

## Originale bleiben migrationsunabhängig
Unabhängig von späteren Wissensformaten bleiben Originalquellen gemäß den geltenden Aufbewahrungsregeln erhalten.
Eine Migration darf niemals das Roharchiv neu interpretieren und anschließend die Originale ersetzen.
Dadurch kann Wissen im Notfall aus den unveränderten Quellen erneut aufgebaut werden.

---

## Modellbackends
ATHENA darf nicht von einem bestimmten Modellbackend oder einer bestimmten Backend-Version abhängig sein.

Ändert sich das konfigurierte Modellbackend, prüft ATHENA nach einem Update die Verbindung und Kompatibilität.

Falls eine Inkompatibilität entsteht:

- wird sie erkannt
- verständlich angezeigt
- bleibt die übrige ATHENA-Funktionalität soweit sicher möglich verfügbar

Die autoritativen persistenten Daten bleiben davon unberührt.

---

## Obsidian
Obsidian ist eine optionale Oberfläche beziehungsweise ergänzende Wissensschnittstelle.
Ein Obsidian-Update darf ATHENA niemals beschädigen.
Änderungen an:
- Plugins
- Themes
- Darstellung
- internen Obsidian-Funktionen
dürfen den kanonischen Wissensbestand nicht gefährden.
ATHENA darf nicht von einem einzelnen Obsidian-Plugin abhängig sein.

---

## Primärmodelle
Neue Primärmodelle können jederzeit installiert und verwendet werden.
Ein Modellwechsel verändert bestehendes Wissen nicht automatisch.
Neue modellgestützte Wissenseinheiten und Interpretationen erhalten die Signatur des neuen Modells.
Alte modellgestützte Einheiten behalten ihre ursprüngliche Modellsignatur. Direkte Benutzeränderungen benötigen keine Modellsignatur, sofern kein Modell beteiligt war.

---

## Neue Modellgenerationen
ATHENA muss neue Modelle verwenden können, ohne die Architektur zu verändern.
Dies betrifft insbesondere Veränderungen bei:
- Modellgröße
- Quantisierung
- Kontextlänge
- Architektur
- Inferenz-Backend
Das Primärmodell bleibt eine austauschbare Komponente.

---

## Neuinterpretation mit neuem Modell
Ein leistungsfähigeres Primärmodell darf vorhandene Originalquellen später erneut analysieren.
Dies erfolgt ausschließlich bewusst.
Die neue Interpretation ersetzt niemals stillschweigend die alte.
Stattdessen bleiben beide Versionen nachvollziehbar.

---

## Infrastrukturmodelle
Auch Infrastrukturmodelle sind austauschbar.
Beispiele:
- neues Embedding-Modell
- neues OCR-Modell
- neues Speech-to-Text-Modell
Abgeleitete Daten dürfen anschließend neu erzeugt werden.
Das kanonische Wissen bleibt unverändert.

---

## Embedding-Wechsel
Ein Wechsel des Embedding-Modells darf niemals eine Migration des eigentlichen Wissens erfordern.
Der Ablauf lautet:
```text
Neues Embedding-Modell

↓

alten Index optional verwerfen

↓

Embeddings neu erzeugen

↓

neuen Suchindex aufbauen
```
Die Wissenseinheiten selbst werden nicht verändert.

---

## Plugin-Updates
Plugins unterliegen denselben Sicherheitsregeln.
Ein Plugin-Update darf niemals:
- Wissen löschen,
- Sicherheitsregeln umgehen,
- kanonische Daten unkontrolliert migrieren.
Kompatibilität wird nach Updates geprüft.

---

## Plugin-Lebenszyklus
Plugins können:
- installiert,
- aktiviert,
- deaktiviert,
- aktualisiert,
- entfernt,
- ersetzt
werden.
Keine dieser Aktionen darf das von einem Plugin verarbeitete Wissen zerstören.
Das Plugin besitzt niemals das Wissen.
ATHENA besitzt das Wissen.

---

## Entfernte Plugins
Wird ein Plugin entfernt, bleiben:
- dessen importierte Originalquellen,
- erzeugte Wissenseinheiten,
- Provenienz,
- Beziehungen
erhalten.
Lediglich die vom Plugin bereitgestellte Funktion steht nicht mehr zur Verfügung.

---

## Betriebssystemwechsel
ATHENA soll langfristig nicht unnötig an eine einzelne Betriebssysteminstallation gebunden sein.
Ein zukünftiger Umzug auf einen neuen Computer oder ein anderes unterstütztes System darf keine Änderung des Wissensbestands erfordern.

---

## Konfigurationsversionierung
Wichtige ATHENA-Konfigurationen werden versioniert.
Dadurch bleibt nachvollziehbar:
- welche Einstellungen aktiv waren,
- wann sie geändert wurden,
- welche Version sie verändert hat.

---

## Softwareversionen
ATHENA verwendet nachvollziehbare Versionsstände.
Stabile Veröffentlichungen erhalten eindeutige Versionen.
Beispielsweise:
ATHENA 1.0
ATHENA 1.1
ATHENA 2.0
Entwicklungsstände werden eindeutig von stabilen Versionen getrennt.

---

## Spezifikationsversionen
Auch die Architektur besitzt feste Versionsstände.
Die vorliegende Spezifikation lautet:
ATHENA_ALPHA v2.0.1 FINAL
Sie definiert die eingefrorenen konzeptionellen Grundlagen.
Technische Details werden später separat versioniert.

---

## Git
Die Entwicklung von ATHENA wird in einem Versionskontrollsystem verwaltet.
Git ist hierfür die vorgesehene Referenzlösung.
Dort werden insbesondere gespeichert:
- Quellcode
- Architekturtexte
- technische Spezifikationen
- Tests
- Dokumentation
- Skripte
- Konfigurationsvorlagen
Der persönliche Wissensbestand gehört nicht in das Entwicklungsrepository.

---

## Branching
Die Entwicklungsstruktur soll stabile und experimentelle Änderungen voneinander trennen.
Eine mögliche Referenzstruktur lautet:
```text
main
  │
  └── stabile Entwicklung

develop
  │
  └── laufende Änderungen
```
Die konkrete Git-Strategie wird in der technischen Spezifikation festgelegt.

---

## Releases und Tags
Wichtige Entwicklungsstände werden dauerhaft markiert.
Beispielsweise:
alpha-v2.0.1-final
beta-v1.0
rc1
v1.0
Dadurch bleibt die Entwicklungsgeschichte des Systems langfristig nachvollziehbar.

---

## Abwärtskompatibilität
Neue ATHENA-Versionen sollen ältere Wissensbestände soweit sinnvoll direkt öffnen können.
Ist eine Migration erforderlich, muss diese kontrolliert erfolgen.
Ein Benutzer darf niemals feststellen, dass ein langjähriger Wissensbestand nur deshalb unbrauchbar geworden ist, weil die Software aktualisiert wurde.

---

## Graceful Degradation
Ist eine aktualisierte externe Komponente vorübergehend inkompatibel, arbeitet ATHENA soweit möglich ohne diese Komponente weiter.
Beispiele:

```text
Embedding-System inkompatibel
→ Volltextsuche bleibt verfügbar

Modellbackend nicht erreichbar
→ autoritative Daten bleiben zugänglich

Obsidian-Integration defekt
→ ATHENA selbst funktioniert weiter
```

---

## Update-Transparenz
Der Benutzer kann jederzeit einsehen:
- installierte ATHENA-Version
- verfügbare Updates
- zuletzt durchgeführtes Update
- Ergebnis der Selbsttests
- bekannte Kompatibilitätsprobleme
Updates dürfen kein unsichtbarer Prozess sein.

---

## Langfristiges Ziel
ATHENA soll auch dann weiter funktionieren, wenn die ursprüngliche technische Umgebung Jahre später nicht mehr existiert.
Das System darf nicht auf die dauerhafte Existenz eines bestimmten:
- Programms,
- Modells,
- Plugins,
- Betriebssystems,
- Datenträgers
angewiesen sein.

---

## Leitregel
Ein erfolgreiches Update bedeutet: neue Software, unverändertes Wissen.

---

## Abschluss des Kapitels
ATHENA wird unter der Annahme entwickelt, dass sich ihre gesamte technische Umgebung im Laufe der Zeit verändern wird.
Diese Veränderung ist kein Sonderfall.
Sie ist Bestandteil der Architektur.
Der Wissensbestand bleibt dabei die stabile Konstante, während Software, Modelle und Infrastruktur kontrolliert ausgetauscht werden können.
