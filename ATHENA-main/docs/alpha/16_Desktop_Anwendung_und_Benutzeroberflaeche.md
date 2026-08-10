# Kapitel 16 – Desktop-Anwendung und Benutzeroberfläche

---

## Einleitung
Die erste produktive Version von ATHENA wird als Desktop-Anwendung konzipiert.
Die Benutzeroberfläche bildet den zentralen Zugang zum gesamten System.
Der Benutzer soll nicht mit einzelnen technischen Komponenten wie Modellbackends, Obsidian, Privacy-/Anonymisierungstechnik, Datenbanken, Embedding-Modellen oder Hintergrunddiensten arbeiten müssen.
Diese Komponenten bleiben im Hintergrund.
Für den Benutzer existiert im Alltag nur:
ATHENA.

---

## Grundprinzip
Eine Anwendung. Eine Oberfläche. Ein Wissenssystem.
Die technische Komplexität hinter ATHENA darf nicht zur Komplexität der Bedienung werden.

---

## Desktop First
Die erste Version konzentriert sich ausschließlich auf den Desktop.
Eine spätere mobile Nutzung ist ausdrücklich vorgesehen.
Sie darf jedoch die Entwicklung der ersten Desktop-Version nicht unnötig verkomplizieren.
Die Architektur wird deshalb mobile-fähig gestaltet.
Die erste Implementierung bleibt Desktop First.

---

## Hauptfenster
Das Hauptfenster bildet den zentralen Arbeitsbereich.
Der wichtigste Bestandteil ist der Chat mit ATHENA.
Von hier aus kann der Benutzer:
- Fragen stellen,
- Wissen hinzufügen,
- Dokumente übergeben,
- Projekte bearbeiten,
- bestehendes Wissen durchsuchen,
- Internetrecherche aktivieren,
- Systemzustände einsehen.
Der Chat bleibt der primäre Interaktionsweg.

---

## Keine Administrationsoberfläche als Hauptprodukt
ATHENA soll nicht wie ein Server-Dashboard wirken.
Technische Informationen sind verfügbar.
Sie dominieren jedoch nicht die Oberfläche.
Der Benutzer soll nicht ständig mit folgenden Begriffen konfrontiert werden:
- Embeddings
- Vektordatenbank
- Queue
- Kontextfenster
- Token
- Backend
- API
- Worker
Solche Informationen gehören in erweiterte Einstellungen oder Diagnoseansichten.

---

## Progressive Offenlegung
Die Oberfläche folgt dem Prinzip:
Einfach zuerst. Details bei Bedarf.
Die normale Ansicht zeigt ausschließlich die wichtigsten Funktionen.
Erweiterte technische Einstellungen bleiben verfügbar, werden jedoch nicht permanent angezeigt.

---

## System-Tray
ATHENA besitzt ein dauerhaftes Symbol im System-Tray neben der Uhr.
Das Hauptfenster kann vollständig minimiert werden.
ATHENA bleibt dabei im Hintergrund aktiv.
Das Tray-Symbol dient als schneller Zugang zu zentralen Funktionen.

---

## Tray-Funktionen
Über das Tray-Menü sollen mindestens erreichbar sein:
- ATHENA öffnen
- Primärmodell laden
- Primärmodell entladen
- Internet AN/AUS
- Hintergrundaufgaben pausieren
- Systemstatus
- ATHENA beenden
Die genaue visuelle Gestaltung wird später definiert.

---

## Status über das Tray-Symbol
Das Tray-Symbol darf einfache Systemzustände sichtbar machen.
Beispielsweise:
- normal
- Hintergrundarbeit aktiv
- Warnung
- Offline-Speicher
- Anonymisierungsschicht nicht verfügbar
Der Benutzer soll erkennen können, wenn ATHENA Aufmerksamkeit benötigt, ohne das Hauptfenster zu öffnen.

---

## Modellsteuerung
Die Benutzeroberfläche besitzt eine einfache Modellverwaltung.
Der Benutzer kann:
- verfügbares Primärmodell auswählen,
- Modell laden,
- Modell entladen,
- Modell wechseln.
Das Entladen dient insbesondere dazu, VRAM für andere Anwendungen freizugeben.

---

## VRAM-Kontrolle
ATHENA zeigt verständlich an:
- Modell geladen oder entladen
- aktuelle VRAM-Nutzung
- verfügbaren VRAM
Der Benutzer muss keine Kommandozeile verwenden, um Speicher freizugeben.

---

## Automatisches Modellmanagement
ATHENA darf Modelle für Hintergrundaufgaben automatisch laden und wieder entladen.
Der Benutzer kann diese Automatik jedoch über die Oberfläche kontrollieren.
Manuelle Benutzerentscheidungen besitzen Vorrang.

---

## Internet-Schalter
Der Internetstatus ist im Hauptfenster klar sichtbar.
Der Benutzer kann für normale Chats zwischen:
- Internet AUS
- Internet AN
wechseln.
Der Standardzustand ist AUS.
Der tägliche News-Workflow bleibt davon unabhängig.

---

## Anonymisierungsstatus
Neben dem Internetstatus zeigt ATHENA den Zustand der konfigurierten Privacy-/Anonymisierungsschicht.

Beispielsweise:

```text
Internet: AN
Anonymisierung: verbunden
```

oder:

```text
Internet: AN
Anonymisierung: nicht verfügbar
```

Bei nicht verfügbarer vorgeschriebener Anonymisierungsschicht erfolgt kein ungeschützter direkter Internet-Fallback.

---

## Geschützter Bereich
Die Benutzeroberfläche besitzt einen eigenen Bereich zur Verwaltung geschützter Inhalte.
Der Benutzer kann dort:
- Schutz konfigurieren,
- Passwort eingeben,
- Bereich entsperren,
- Bereich sperren,
- automatische Sperrzeit einstellen,
- aktuellen Status sehen.
Für die Nutzung sind keine externen Verschlüsselungsprogramme erforderlich.

---

## Persönliches Gedächtnis
Das Persönliche Gedächtnis besitzt eine einfache Verwaltungsansicht.
Dort kann der Benutzer:
- gespeicherte Präferenzen einsehen,
- bearbeiten,
- löschen,
- neue Präferenzen hinzufügen,
- das gesamte persönliche Gedächtnis zurücksetzen.
ATHENA versteckt keine dauerhaft gespeicherten persönlichen Präferenzen.

---

## Wissensansicht
Neben dem Chat kann eine Wissensansicht existieren.
Sie dient zum Erkunden von:
- Concept Notes
- Projekten
- Quellen
- Beziehungen
- zeitlichen Entwicklungen
Sie ist eine Ergänzung zum Chat.
Der Benutzer muss sie nicht verwenden, um ATHENA sinnvoll nutzen zu können.

---

## Obsidian
Obsidian kann als zusätzliche Oberfläche für den langfristigen Wissensbestand dienen.
ATHENA darf jedoch niemals voraussetzen, dass der Benutzer Obsidian zur normalen Bedienung verwendet.
ATHENA verwaltet den Wissensbestand selbst.
Obsidian bleibt ein optionaler zusätzlicher Zugang zum Wissen.

---

## Queue-Anzeige
Die Benutzeroberfläche zeigt den Zustand der Hintergrundaufgaben verständlich an.
Beispielsweise:
Hintergrundaufgaben

2 laufen
4 warten
13 News-Tage nachzuholen
7 Einträge warten auf Synchronisation
Der Benutzer kann Details öffnen, muss dies jedoch nicht.

---

## Synchronisationsstatus
Ist der langfristige Speicher nicht erreichbar, zeigt ATHENA dies klar an.
Beispiel:
Wissensspeicher offline

12 neue Einträge lokal gesichert.

Automatische Synchronisation erfolgt nach Wiederverbindung.
Dadurch weiß der Benutzer jederzeit, dass seine Daten trotzdem gesichert wurden.

---

## Backup-Status
Die Oberfläche zeigt einen einfachen Sicherungsstatus.
Beispielsweise:
Letztes Backup:
Heute, 03:14

Status:
Erfolgreich
Technische Details bleiben optional.

---

## Diagnose
ATHENA besitzt eine zentrale Diagnoseansicht.
Dort können unter anderem angezeigt werden:
- CPU
- RAM
- GPU
- VRAM
- Primärmodell
- LM-Studio-Verbindung
- Privacy-/Anonymisierungsschicht
- Wissensspeicher
- Suchindex
- Queue
- Backup
- Infrastrukturmodelle
Diese Ansicht dient primär der Fehleranalyse.
Sie gehört nicht zum normalen Arbeitsablauf.

---

## Verständliche Fehlermeldungen
ATHENA zeigt keine unnötig technischen Fehlermeldungen.
Nicht:
ConnectionError 10061
Sondern beispielsweise:
Das konfigurierte Modellbackend ist momentan nicht erreichbar.

ATHENA kann weiterhin gespeichertes Wissen durchsuchen.

[Erneut versuchen]
Technische Details bleiben über eine zusätzliche Ansicht verfügbar.

---

## Graceful Degradation in der Oberfläche
Die Oberfläche muss deutlich machen, welche Funktionen momentan verfügbar sind.
Beispiel:
✓ Lokales Wissen
✓ Volltextsuche
✓ Wissensgraph

○ Semantische Suche vorübergehend nicht verfügbar
○ Internet vorübergehend nicht verfügbar
Ein Teilfehler darf nicht den Eindruck erzeugen, ATHENA sei vollständig ausgefallen.

---

## Benutzerkontrolle
Automatische Funktionen müssen kontrollierbar bleiben.
Der Benutzer kann insbesondere:
- Hintergrundaufgaben pausieren,
- Internet deaktivieren,
- Modelle entladen,
- Synchronisation prüfen,
- geschützte Bereiche sperren,
- Backups einsehen.
Die normale Nutzung soll dennoch ohne permanente manuelle Kontrolle funktionieren.

---

## UI-Philosophie
Die Benutzeroberfläche folgt dauerhaft folgenden Regeln:
- Eine Funktion besitzt einen eindeutigen Bedienweg.
- Häufige Aufgaben benötigen möglichst wenige Schritte.
- Komplexität bleibt im Hintergrund.
- Sicherheitsrelevante Zustände sind sichtbar.
- Automatische Entscheidungen sind nachvollziehbar.
- Erweiterte Funktionen bleiben erreichbar.
- Der Benutzer behält jederzeit die Kontrolle.

---

## Keine unnötigen Funktionen
Neue UI-Funktionen werden nicht allein deshalb hinzugefügt, weil sie technisch möglich sind.
Jede sichtbare Funktion muss einen klaren Nutzen besitzen.
ATHENA soll nicht mit jeder Version komplexer werden.

---

## Zukunft: Mobile Zugriffsmöglichkeit
Die Architektur berücksichtigt von Beginn an, dass später ein mobiler Client hinzukommen kann.
Dieser soll auf denselben:
- ATHENA Core,
- Wissensbestand,
- Sicherheitsregeln,
- persönlichen Kontext
zugreifen.
Die konkrete mobile Implementierung ist jedoch ausdrücklich nicht Bestandteil der ersten Desktop-Version.

---

## Ziel
Die Benutzeroberfläche soll den Eindruck vermitteln, mit einem einzigen zusammenhängenden System zu arbeiten.
Nicht mit einer Sammlung aus:
- Modellbackend,
- Obsidian,
- Privacy-/Anonymisierungsschicht,
- Modellen,
- Datenbanken,
- Skripten,
- Hintergrunddiensten.
Diese technischen Komponenten verschwinden hinter ATHENA.

---

## Leitregel
Der Benutzer soll ATHENA benutzen – nicht die Infrastruktur hinter ATHENA verwalten.

---

## Abschluss des Kapitels
Die Desktop-Anwendung bildet die sichtbare Ebene von ATHENA.
Sie reduziert die technische Komplexität des Gesamtsystems auf eine einfache, kontrollierbare und verständliche Oberfläche.
Die Architektur bleibt gleichzeitig offen für spätere mobile Clients und weitere Benutzeroberflächen, ohne den gemeinsamen Wissenskern zu verändern.
