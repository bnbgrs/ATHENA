# Kapitel 26 – Mobile Zukunft und Mehrgerätezugriff

---

## Einleitung
ATHENA wird zunächst als lokale Desktop-Anwendung entwickelt.
Langfristig soll der Benutzer jedoch nicht zwingend vor dem Hauptcomputer sitzen müssen, um auf ATHENA zuzugreifen.
Ein zukünftiger mobiler Client kann beispielsweise ermöglichen:
- unterwegs Fragen an ATHENA zu stellen,
- Gedanken und Notizen zu erfassen,
- vorhandenes Wissen abzurufen,
- Dokumente oder Bilder an ATHENA zu übergeben,
- Aufgaben und Systemzustände einzusehen.
Diese Möglichkeit wird bereits in der Alpha-Architektur berücksichtigt.
Sie ist jedoch nicht Bestandteil der ersten Implementierungsphase.

---

## Grundprinzip
Mehrere Geräte dürfen auf ATHENA zugreifen. Es existiert trotzdem nur ein logisches Wissenssystem.
Ein Smartphone erhält deshalb kein unabhängiges zweites ATHENA-Gedächtnis.

---

## Desktop als primäre Instanz
Die erste ATHENA-Version läuft auf dem Hauptcomputer des Benutzers.
Dort befinden sich beziehungsweise werden koordiniert:
- ATHENA Core,
- Primärmodell,
- Modellrouting,
- Wissenssystem,
- Queue,
- Scheduler,
- Sicherheitslogik.
Der Desktop bildet zunächst die zentrale Recheninstanz.

---

## Mobile Client
Ein zukünftiger mobiler Client dient primär als entfernte Benutzeroberfläche.
Vereinfacht:
```text
Smartphone
    │
    ▼
sichere Verbindung
    │
    ▼
ATHENA Core
    │
    ├── Primärmodell
    ├── Wissenssystem
    └── Hintergrunddienste
```
Die Wissenslogik bleibt zentral.

---

## Kein separates mobiles Gedächtnis
Der mobile Client darf keinen unabhängigen langfristigen Wissensbestand erzeugen.
Neue Informationen werden dem zentralen ATHENA-System übergeben.
Dadurch entstehen keine konkurrierenden Gedächtnisse.

---

## Einheitliche Identität
Eine Unterhaltung auf dem Smartphone und eine Unterhaltung am Desktop gehören zum selben ATHENA-System.
Der Benutzer soll beispielsweise unterwegs eine Idee erfassen und später am Desktop fragen können:
Was hatte ich heute Nachmittag unterwegs zu Projekt X notiert?
ATHENA muss diese Information wiederfinden können.

---

## Synchronisation
Falls der mobile Client temporär offline ist, darf er freigegebene neue Eingaben lokal puffern.
Nach Wiederherstellung der Verbindung erfolgt eine kontrollierte Synchronisation.
Der Ablauf entspricht grundsätzlich:
```text
Mobile Eingabe

↓

lokal verschlüsselt puffern

↓

Verbindung verfügbar

↓

Authentifizierung

↓

ATHENA Core

↓

Integritätsprüfung

↓

Speicherung

↓

Synchronisation bestätigt

↓

lokalen Puffer bereinigen
```
Die lokale Kopie darf erst entfernt werden, wenn die erfolgreiche Übernahme bestätigt wurde.

---

## Offline-Modus
Ein zukünftiger mobiler Client kann eingeschränkte Offline-Funktionen besitzen.
Beispielsweise:
- neue Notiz erfassen,
- Datei vormerken,
- Aufgabe vorbereiten.
Ein vollständiges unabhängiges ATHENA auf dem Smartphone ist für die Alpha-Architektur nicht erforderlich.

---

## Lokale Daten auf Mobilgeräten
ATHENA soll möglichst wenig langfristiges Wissen dauerhaft auf mobilen Geräten speichern.
Mobile Geräte besitzen ein erhöhtes Risiko durch:
- Verlust,
- Diebstahl,
- fremden Zugriff.
Temporäre lokale Daten müssen entsprechend geschützt werden.

---

## Authentifizierung
Ein mobiler Client darf niemals allein deshalb Zugriff erhalten, weil er sich im selben Netzwerk befindet.
Jedes Gerät muss ausdrücklich autorisiert werden.

---

## Geräteidentität
Jedes autorisierte Gerät erhält eine eindeutige Identität.
ATHENA kann dadurch nachvollziehen:
- welches Gerät verbunden ist,
- wann es zuletzt verwendet wurde,
- welche Berechtigungen bestehen.

---

## Geräteverwaltung
Der Benutzer kann über die Desktop-Oberfläche später mindestens:
- autorisierte Geräte anzeigen,
- neues Gerät autorisieren,
- Gerät sperren,
- Gerät entfernen.
Ein verlorenes Smartphone kann dadurch vom ATHENA-System ausgeschlossen werden.

---

## Berechtigungen pro Gerät
Nicht jedes Gerät muss sämtliche Rechte besitzen.
Beispielsweise kann ein mobiles Gerät Zugriff erhalten auf:
- normale Chats,
- Notizerfassung,
- allgemeine Wissenssuche,
aber keinen Zugriff auf:
- geschützte Bereiche,
- Systemadministration,
- Backup-Wiederherstellung.
Die genaue Berechtigungsstruktur wird später spezifiziert.

---

## Geschützte Bereiche
Geschützte Wissensbereiche sind nicht automatisch mobil verfügbar.
Der Benutzer muss mobilen Zugriff ausdrücklich erlauben.
Die Tatsache, dass ein Bereich am Desktop entsperrt wurde, darf nicht automatisch bedeuten, dass ein Smartphone ebenfalls Zugriff erhält.

---

## Ende-zu-Ende-Schutz
Kommunikation zwischen Client und ATHENA Core muss kryptografisch geschützt sein.
Unverschlüsselte Übertragung persönlicher Wissensinhalte ist nicht zulässig.
Die konkrete technische Lösung wird in der Beta-Spezifikation festgelegt.

---

## Zugriff außerhalb des Heimnetzes
Ein späterer Zugriff über das Internet darf nicht durch ungeschütztes öffentliches Freigeben eines ATHENA-Ports umgesetzt werden.
Die Architektur verlangt eine authentifizierte und verschlüsselte Zugriffsschicht.

---

## Keine verpflichtende Cloud
Mobiler Zugriff darf keine externe Cloud als zwingende zentrale Datenhaltung voraussetzen.
Das langfristige Ziel bleibt:
Der Wissensbestand gehört dem Benutzer und kann lokal bleiben.
Externe Infrastruktur kann später optional verwendet werden, darf aber keine Grundvoraussetzung sein.

---

## Cloud-Relay
Falls später ein Relay-Dienst für Erreichbarkeit verwendet wird, darf dieser nicht automatisch Zugriff auf den Klartext des Wissens erhalten.
Ein Relay soll möglichst nur verschlüsselte Kommunikation transportieren.

---

## VPN und vergleichbare Lösungen
Für den entfernten Zugriff können zukünftig beispielsweise sichere Tunnel- oder VPN-Techniken verwendet werden.
Die Alpha-Spezifikation schreibt keine konkrete Technologie fest.
Sie schreibt lediglich die Sicherheitsanforderungen fest.

---

## Privacy- und Anonymisierungsschicht
Die konfigurierte Privacy-/Anonymisierungsschicht erfüllt innerhalb ATHENAs primär die Aufgabe, externe Kommunikation gemäß den Sicherheitsregeln zu schützen.
Sie ist nicht automatisch die vorgesehene Architektur für den mobilen Zugriff auf den eigenen ATHENA Core.
Die konkrete Technik für externe Anonymisierung und sicheren Remote-Zugriff wird in Beta getrennt festgelegt. Beide Netzwerkfunktionen müssen logisch getrennt bleiben.

---

## Eingehende und ausgehende Verbindungen
ATHENA unterscheidet deshalb grundsätzlich:

```text
ATHENA → Internet
         geschützte externe Recherche

Benutzergerät → ATHENA
                authentifizierter Remote-Zugriff
```

Diese beiden Kommunikationsrichtungen besitzen unterschiedliche Sicherheitsziele.

---

## Kein direkter Internet-Fallback
Die bestehende Regel für externe ATHENA-Recherche bleibt unverändert:
Ist die vorgeschriebene Anonymisierung nicht verfügbar, darf ATHENA nicht heimlich direkt auf das Internet zugreifen.
Mobiler Remote-Zugriff ändert diese Regel nicht.

---

## Benachrichtigungen
Ein zukünftiger mobiler Client kann Benachrichtigungen anzeigen.
Beispiele:
- Hintergrundjob abgeschlossen,
- wichtiger Fehler,
- Backup fehlgeschlagen,
- Speicherproblem,
- ausdrücklich konfigurierte Erinnerung.
Benachrichtigungen dürfen keine sensiblen Inhalte auf einem gesperrten Bildschirm offenlegen.

---

## Push-Dienste
Falls Betriebssystem-Pushdienste verwendet werden, dürfen darüber möglichst keine vertraulichen Wissensinhalte übertragen werden.
Eine Benachrichtigung kann beispielsweise lediglich mitteilen:
ATHENA hat eine neue Benachrichtigung.
Der eigentliche Inhalt wird erst nach authentifiziertem Zugriff geladen.

---

## Sprachinteraktion
Ein zukünftiger mobiler Client kann Spracheingabe unterstützen.
Beispielsweise:
```text
Mikrofon

↓

lokale oder kontrollierte Speech-to-Text-Verarbeitung

↓

ATHENA Core

↓

Primärmodell

↓

Antwort
```
Die Verwendung externer Sprachdienste darf nicht unbemerkt erfolgen.

---

## Bilder und Dokumente
Der Benutzer kann später möglicherweise:
- Foto aufnehmen,
- PDF teilen,
- Screenshot senden,
- Datei auswählen
und diese direkt an ATHENA übergeben.
Die Datei durchläuft anschließend dieselbe Import- und Provenienzlogik wie eine Desktop-Datei.

---

## Herkunft mobiler Inhalte
Mobile Eingaben erhalten ebenfalls Provenienz.
Beispielsweise:
Quelle:
mobile Aufnahme

Gerät:
autorisiertes Gerät 03

Zeitpunkt:
08.08.2026 14:32
Geräteinformationen werden nur soweit gespeichert, wie sie für Nachvollziehbarkeit und Sicherheit sinnvoll sind.

---

## Mehrere Desktop-Geräte
Die Architektur soll langfristig nicht ausschließlich Smartphones berücksichtigen.
Später können beispielsweise existieren:
- Haupt-PC,
- Notebook,
- Tablet,
- Smartphone.
Alle greifen auf denselben logischen Wissensraum zu.

---

## Keine unkontrollierte Multi-Master-Architektur
Mehrere Geräte dürfen nicht unabhängig dieselben kanonischen Datenbanken verändern.
Änderungen müssen über kontrollierte ATHENA-Schnittstellen erfolgen.
Dadurch werden Synchronisationskonflikte reduziert.

---

## Zentraler Core als Ausgangspunkt
Für die erste Mehrgerätearchitektur gilt deshalb:
Ein Core entscheidet über kanonische Änderungen. Mehrere Clients dürfen ihn benutzen.
Dies ist einfacher, sicherer und konsistenter als mehrere vollständig unabhängige ATHENA-Instanzen.

---

## Spätere verteilte Architektur
Sollte langfristig eine echte Multi-Core- oder Multi-Server-Architektur notwendig werden, kann sie später entwickelt werden.
Sie ist ausdrücklich nicht Bestandteil von ATHENA_ALPHA v2.0.1.
Die Verwendung stabiler IDs und klarer Synchronisationsregeln hält diese Möglichkeit offen.

---

## Desktop offline
Ist der zentrale ATHENA-Rechner ausgeschaltet, kann der mobile Client keine vollständige Anfrage an das lokale Primärmodell stellen.
Er kann jedoch – sofern implementiert – Eingaben sicher zwischenspeichern.
Der Benutzer muss klar erkennen können:
ATHENA momentan nicht erreichbar.

Deine Eingabe wurde lokal gespeichert und wird später übertragen.

---

## Späterer Always-On-Server
ATHENA könnte zukünftig optional auf einem stromsparenden Heimserver oder einer leistungsfähigeren zentralen Maschine betrieben werden.
Dies ist eine mögliche Weiterentwicklung.
Die Architektur darf jedoch nicht voraussetzen, dass der Benutzer bereits zu Beginn einen Server besitzt.

---

## Modellhardware
Ein mobiler Client muss das große Primärmodell nicht lokal ausführen.
Dadurch bleibt ATHENA auch mit Modellen nutzbar, die erheblich mehr Ressourcen benötigen als ein Smartphone bereitstellen kann.

---

## Benutzererlebnis
Der Benutzer soll langfristig nicht darüber nachdenken müssen, wo ATHENA technisch läuft.
Die Interaktion soll möglichst ähnlich sein:

```text
Desktop    → ATHENA
Smartphone → ATHENA
Tablet     → ATHENA
```

Der zugrunde liegende Wissensbestand bleibt derselbe.

---

## Audit
Remote-Zugriffe werden sicherheitsrelevant protokolliert.
Mindestens:
- Zeitpunkt,
- Gerät,
- erfolgreiche oder fehlgeschlagene Authentifizierung,
- relevante administrative Aktionen.
Der Audit-Eintrag darf keine unnötigen Kopien vertraulicher Inhalte erzeugen.

---

## Geräteverlust
Bei Verlust eines autorisierten Geräts muss der Benutzer dessen Berechtigung widerrufen können.
Ein widerrufenes Gerät darf anschließend keine neue Verbindung zum ATHENA Core aufbauen.

---

## Schlüsselwechsel
Die Architektur muss später ermöglichen, kompromittierte Geräte- oder Verbindungsschlüssel zu ersetzen, ohne den Wissensbestand neu verschlüsseln oder neu erstellen zu müssen.

---

## Portabilität
Auch die Remote- und Geräteverwaltung darf nicht an den ursprünglichen Haupt-PC gebunden sein.
Nach einer vollständigen Wiederherstellung von ATHENA auf neuer Hardware müssen autorisierte Geräte kontrolliert neu verbunden oder entsprechend sicher migriert werden können.

---

## Keine Erweiterung des Vertrauensbereichs
Die Einführung mobiler Clients darf nicht dazu führen, dass externe Dienste automatisch Teil des vertrauenswürdigen ATHENA-Kerns werden.
Der Vertrauensbereich soll möglichst klein bleiben:
```text
Benutzer

↓

autorisierte Clients

↓

ATHENA Core

↓

lokaler Wissensbestand
```
Externe Transportinfrastruktur bleibt außerhalb dieses Vertrauensbereichs, soweit technisch möglich.

---

## Datenschutz
Mehrgerätezugriff ändert nicht die grundlegende Datenschutzphilosophie.
Es gilt weiterhin:
- lokale Datenhoheit,
- minimale externe Abhängigkeiten,
- keine verpflichtende Cloud,
- nachvollziehbare Verbindungen,
- Benutzerkontrolle.

---

## Alpha-Abgrenzung
ATHENA_ALPHA v2.0.1 definiert für Mobile und Mehrgerätezugriff ausschließlich die architektonischen Voraussetzungen.
Die erste Implementierung muss noch keinen mobilen Client enthalten.
Sie darf jedoch keine Architekturentscheidung treffen, die einen späteren sicheren mobilen Client unnötig verhindert.

---

## Ziel
ATHENA soll zunächst als robuste lokale Desktop-Anwendung entstehen.
Langfristig soll daraus jedoch ein persönliches Wissenssystem werden können, das der Benutzer sicher von mehreren eigenen Geräten erreicht.
Die Geräte wechseln.
Die Benutzeroberflächen wechseln.
Das Primärmodell kann wechseln.
Der Wissenskern bleibt derselbe.

---

## Leitregel
Viele Geräte dürfen mit ATHENA sprechen. Es gibt trotzdem nur ein gemeinsames Langzeitgedächtnis.

---

## Abschluss des Kapitels
Die Mehrgerätearchitektur erweitert ATHENA perspektivisch über den einzelnen Desktop hinaus, ohne den lokalen Charakter des Systems aufzugeben.
Ein zentraler ATHENA Core, sichere Geräteauthentifizierung, minimale lokale Datenhaltung auf Clients und ein gemeinsamer Wissensbestand verhindern die Entstehung konkurrierender Gedächtnisse.
Damit bleibt ATHENA zunächst einfach implementierbar und gleichzeitig offen für einen späteren sicheren Zugriff von Smartphone, Tablet, Notebook oder anderen persönlichen Geräten.
