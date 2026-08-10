# Kapitel 24 – Performance, Skalierbarkeit und Ressourcenmanagement

---

## Einleitung
ATHENA ist nicht für einen Wissensbestand von wenigen Monaten ausgelegt.
Die Architektur muss davon ausgehen, dass das System über zehn, zwanzig oder mehr Jahre genutzt werden kann.
Dabei können sehr große Mengen entstehen aus:
- Chats,
- Dokumenten,
- Wissenseinheiten,
- Nachrichten,
- Medien,
- Versionen,
- Beziehungen,
- Auditinformationen.
Wachstum darf nicht dazu führen, dass ATHENA zunehmend unbenutzbar wird.
Performance und Skalierbarkeit sind deshalb grundlegende Architekturziele.

---

## Grundprinzip
Die Größe des Langzeitgedächtnisses darf nicht die Größe des Arbeitskontexts bestimmen.
ATHENA arbeitet grundsätzlich mit relevanten Ausschnitten des Wissensbestands.
Nicht mit dem gesamten Bestand.

---

## Langfristige Größenordnung
Die Architektur soll nicht auf eine kleine oder feste Anzahl von Wissenseinträgen optimiert werden.
Sie muss mindestens darauf vorbereitet sein, langfristig:
- Millionen Wissenseinheiten,
- sehr große Chatarchive,
- umfangreiche Dokumentensammlungen,
- jahrzehntelange Nachrichtenhistorien,
- große Mengen an Beziehungen
zu verwalten.
Eine konkrete Obergrenze wird nicht Bestandteil der Architektur.

---

## Speicherbedarf
Der tatsächliche Speicherbedarf hängt stark davon ab, welche Inhalte ATHENA langfristig erhält.
Reiner Text benötigt vergleichsweise wenig Speicher.
Große Datenmengen entstehen hauptsächlich durch:
- Bilder,
- Audio,
- Video,
- umfangreiche PDFs,
- Webseiten-Snapshots,
- Backups.
Die Architektur muss deshalb zwischen Wissensmenge und physischer Datenmenge unterscheiden.

---

## Textwissen
Selbst sehr umfangreiche Textarchive können über viele Jahre vergleichsweise kompakt bleiben.
ATHENA darf deshalb nicht versuchen, textbasiertes Langzeitwissen aggressiv zu löschen, nur um geringe Mengen Speicherplatz einzusparen.

---

## Medien
Große Mediendateien werden anders behandelt als atomare Wissenseinheiten.
ATHENA kann beispielsweise:
- Originalmedium archivieren,
- Transkript erzeugen,
- Metadaten extrahieren,
- relevante Wissenseinheiten erzeugen.
Das Original bleibt entsprechend der Aufbewahrungsregeln erhalten.

---

## Speicherüberwachung
ATHENA überwacht:
- freien Speicherplatz,
- Wachstum des Wissensbestands,
- Backup-Größe,
- Cache-Größe,
- Archiv-Größe.
Bei absehbaren Engpässen wird der Benutzer frühzeitig informiert.

---

## Speicherprognose
ATHENA darf aus dem bisherigen Wachstum eine grobe langfristige Speicherprognose ableiten.
Beispielsweise:
Aktueller Wissensbestand:
184 GB

Durchschnittliches Wachstum:
6,4 GB pro Monat

Geschätzter Speicherbedarf in 12 Monaten:
ca. 261 GB
Eine solche Prognose dient ausschließlich der Planung.

---

## Speichererweiterung
Wird der vorhandene Speicher zu klein, muss ATHENA vollständig auf einen größeren Datenträger migrierbar sein.
Dies darf keine Neuorganisation des Wissens erfordern.
Beispiel:
```text
2-TB-Festplatte

↓

8-TB-Festplatte

↓

ATHENA-Speicherort ändern

↓

Integrität prüfen

↓

Weiterarbeiten
```

---

## Keine absoluten Pfadabhängigkeiten
Skalierbarkeit und Portabilität hängen zusammen.
Wissenseinheiten referenzieren keine fest eingebrannten Laufwerksbuchstaben oder absoluten Pfade.
Dadurch können Daten auch später:
- verschoben,
- verteilt,
- auf größere Speicher übertragen
werden.

---

## Storage Tiers
ATHENA darf langfristig unterschiedliche Speicherklassen verwenden.
Beispielsweise:
```text
Schneller Speicher
│
├── aktives Wissen
├── aktuelle Indizes
└── Cache

Langzeitspeicher
│
├── Roharchiv
├── ältere Dokumente
└── Medien

Backup-Speicher
│
└── Sicherungen
```
Für den Benutzer bleibt dies ein gemeinsamer Wissensbestand.

---

## Transparente Speicherverteilung
Die physische Verteilung darf nicht bestimmen, wie der Benutzer Wissen sucht.
Eine zehn Jahre alte Datei auf langsamem Archivspeicher bleibt über dieselbe ATHENA-Suche erreichbar wie eine aktuelle Wissenseinheit.

---

## Suchskalierung
ATHENA darf bei einer normalen Frage nicht sämtliche Wissenseinheiten vollständig an das Primärmodell senden.
Stattdessen erfolgt mehrstufiges Retrieval.
```text
Anfrage

↓

Suchraum eingrenzen

↓

Kandidaten finden

↓

Kandidaten bewerten

↓

relevanten Kontext auswählen

↓

Primärmodell
```

---

## Mehrstufige Suche
Je nach Anfrage können mehrere Ebenen kombiniert werden:
1. aktiver Gesprächskontext,
2. aktiver Wissensgraph,
3. Volltextindex,
4. semantischer Index,
5. Graphbeziehungen,
6. Langzeitwissen,
7. Roharchiv.
Nur notwendige Ebenen werden verwendet.

---

## Indizes
Suchindizes dienen ausschließlich der Performance.
Sie dürfen:
- optimiert,
- gelöscht,
- neu aufgebaut,
- durch neue Technologien ersetzt
werden.
Das kanonische Wissen bleibt davon unabhängig.

---

## Embeddings
Dasselbe gilt für Embeddings.
Ein zukünftiges besseres Embedding-Modell kann sämtliche Embeddings neu erzeugen.
Dafür muss kein kanonisches Wissen verändert werden.

---

## Partitionierung
Sehr große Datenbestände dürfen intern partitioniert werden.
Mögliche Kriterien:
- Zeitraum,
- Wissensart,
- Projekt,
- Speicherklasse.
Die konkrete technische Strategie gehört in die Beta-Spezifikation.
Für den Benutzer bleibt der Wissensraum einheitlich.

---

## Lazy Loading
ATHENA lädt große Daten nur dann vollständig, wenn sie tatsächlich benötigt werden.
Beispielsweise muss ein 500-seitiges PDF nicht vollständig in den Arbeitsspeicher geladen werden, wenn nur eine bestimmte Passage relevant ist.

---

## Inkrementelle Verarbeitung
Neue Informationen sollen bevorzugt inkrementell verarbeitet werden.
Nicht:

```text
Neue Wissenseinheit
↓
gesamten Wissensbestand neu analysieren
```
Sondern:
```text
Neue Wissenseinheit

↓

relevante Nachbarschaft bestimmen

↓

betroffene Beziehungen aktualisieren
```
Dies wird mit wachsendem Wissensbestand zunehmend wichtig.

---

## Hintergrundverarbeitung
Aufwendige Wartungsarbeiten werden in kleine, fortsetzbare Aufgaben zerlegt.
Dadurch kann ATHENA:
- pausieren,
- fortsetzen,
- Ressourcen freigeben,
- Benutzerinteraktionen priorisieren.

---

## Benutzerinteraktion besitzt Vorrang
Eine laufende Wartungsaufgabe darf eine direkte Benutzeranfrage nicht unnötig verzögern.
Bei Bedarf werden Hintergrundaufgaben:
- gedrosselt,
- pausiert,
- oder später fortgesetzt.

---

## Ressourcenüberwachung
ATHENA überwacht mindestens:
- CPU-Auslastung,
- RAM,
- GPU-Auslastung,
- VRAM,
- Datenträgerbelegung,
- Datenträgeraktivität.
Netzwerkressourcen können ebenfalls berücksichtigt werden.

---

## GPU und VRAM
Das Primärmodell kann erhebliche GPU-Ressourcen benötigen.
ATHENA muss deshalb erkennen können:
- ob das Modell geladen ist,
- wie viel VRAM verwendet wird,
- ob genügend VRAM für eine Aufgabe verfügbar ist.

---

## Manuelle Modellkontrolle
Der Benutzer kann das Primärmodell jederzeit über die Oberfläche:
- laden,
- entladen,
- wechseln.
Dadurch können GPU-Ressourcen bewusst für andere Anwendungen freigegeben werden.

---

## Hintergrundmodell und aktive GPU-Nutzung
ATHENA soll vermeiden, ein großes Primärmodell automatisch zu laden, wenn die GPU offensichtlich stark durch eine andere Anwendung verwendet wird.
Eine Hintergrundaufgabe kann stattdessen warten.

---

## Ressourcenlimits
Der Benutzer soll später Grenzwerte konfigurieren können.
Beispielsweise:
Hintergrundaufgaben:

max. CPU: 30 %
max. RAM: 8 GB
GPU nur bei Idle
Die konkrete UI und technische Umsetzung werden in der Beta-Spezifikation definiert.

---

## Hardwareprofile
ATHENA kann die vorhandene Hardware erkennen und daraus sinnvolle Standardwerte ableiten.
Dazu gehören:
- CPU,
- RAM,
- GPU,
- VRAM,
- Speichermedien.
Manuelle Einstellungen bleiben möglich.

---

## Hardwarewechsel
Ein neuer Computer kann erheblich leistungsfähiger sein als der ursprüngliche Rechner.
ATHENA darf deshalb keine alten Performanceannahmen dauerhaft im Wissensbestand verankern.
Ressourcenprofile gehören zur Systemkonfiguration.
Nicht zum Wissen.

---

## Modellskalierung
Mit zukünftiger Hardware können größere Modelle eingesetzt werden.
Der Wechsel von einem kleineren zu einem größeren Primärmodell erfordert keine Änderung der Wissensarchitektur.

---

## Queue und Ressourcen
Der Scheduler berücksichtigt Ressourcenbedarf bereits vor dem Start einer Aufgabe.
Beispiel:
```text
Job benötigt Primärmodell

↓

VRAM nicht verfügbar

↓

Job wartet

↓

VRAM wird frei

↓

Modell laden

↓

Job ausführen
```

---

## Priorisierung
Direkte Benutzerinteraktion besitzt grundsätzlich Vorrang vor:
- Reindexierung,
- Reembedding,
- News-Backfill,
- Reinterpretation,
- Wissenswartung.
Datensicherheitskritische Vorgänge können eine höhere Priorität erhalten, wenn ein Aufschub Datenverlust verursachen könnte.

---

## Cache
ATHENA darf Caches verwenden, um häufig benötigte Informationen schneller bereitzustellen.
Cache-Daten müssen vollständig rekonstruierbar sein.
Sie sind niemals die einzige Kopie einer Information.

---

## Cache-Bereinigung
ATHENA kann Cache automatisch begrenzen und bereinigen.
Dies gehört zu den sicheren automatischen Wartungsaufgaben.

---

## Startzeit
Ein sehr großer Wissensbestand darf nicht bedeuten, dass ATHENA beim Start zunächst sämtliche Daten laden muss.
ATHENA soll schnell betriebsbereit werden.
Notwendige Komponenten werden priorisiert geladen.
Andere Strukturen können anschließend im Hintergrund geprüft werden.

---

## Graceful Startup
Beim Start kann ATHENA beispielsweise zunächst verfügbar machen:
Core: bereit

Lokale Suche: bereit

Primärmodell: lädt

News-System: wartet

Archivindex: wird geprüft
Der Benutzer muss nicht warten, bis sämtliche Hintergrundkomponenten vollständig initialisiert wurden.

---

## Graceful Shutdown
Beim Beenden müssen laufende Hintergrundaufgaben einen sicheren Zustand erreichen.
Sie werden entweder:
- abgeschlossen,
- kontrolliert pausiert,
- oder persistent für die Fortsetzung gespeichert.
Ein normales Beenden darf keine Aufgabe beschädigen.

---

## Stromausfall
Auch ein unerwarteter Abbruch darf keine inkonsistenten kanonischen Daten erzeugen.
Schreibvorgänge müssen so gestaltet werden, dass ATHENA nach einem Neustart erkennen kann:
- was vollständig gespeichert wurde,
- was unvollständig war,
- welche Aufgabe erneut ausgeführt werden muss.

---

## Performance-Monitoring
ATHENA darf langfristige Leistungsdaten sammeln, soweit sie für die lokale Diagnose notwendig sind.
Beispiele:
- durchschnittliche Suchzeit,
- Modellladezeit,
- Queue-Länge,
- Indexierungsdauer.
Diese Daten bleiben technische Telemetrie innerhalb des lokalen Systems.

---

## Keine verpflichtende externe Telemetrie
Der grundlegende Betrieb von ATHENA benötigt keine Übertragung von Nutzungs- oder Leistungsdaten an externe Anbieter.
Lokale Diagnose muss unabhängig davon funktionieren.

---

## Performance-Warnungen
ATHENA soll Probleme verständlich erklären.
Beispiel:
Die semantische Suche ist momentan langsamer als üblich.

Ursache:
Der Suchindex wird neu aufgebaut.

Lokale Volltextsuche bleibt verfügbar.

---

## Messbarkeit
Performanceoptimierungen sollen auf messbaren Engpässen beruhen.
ATHENA darf nicht unnötig komplexer werden, nur um theoretische Skalierungsprobleme zu lösen, die praktisch nicht auftreten.

---

## Zukunftssicherheit
Neue Technologien können später bestehende Performancekomponenten ersetzen.
Beispiele:
- neue Datenbanken,
- neue Suchverfahren,
- neue Embedding-Systeme,
- neue Speichertechnologien,
- neue Beschleunigerhardware.
Solange kanonisches Wissen und stabile Identitäten erhalten bleiben, darf die interne Performancearchitektur ausgetauscht werden.

---

## Ziel
ATHENA soll nach zehn Jahren nicht grundsätzlich anders bedient werden müssen als am ersten Tag.
Der Wissensbestand darf massiv wachsen.
Die sichtbare Interaktion bleibt:
```text
Frage

↓

kurze Suche

↓

relevanter Kontext

↓

Antwort
```
Die Komplexität des gewachsenen Systems bleibt hinter dieser einfachen Interaktion verborgen.

---

## Leitregel
ATHENA darf über Jahrzehnte wachsen, ohne dass der Benutzer die Größe des Wissensbestands bei jeder Interaktion spürt.

---

## Abschluss des Kapitels
Performance ist in ATHENA kein nachträgliches Optimierungsprojekt.
Sie entsteht aus der grundlegenden Trennung zwischen kanonischem Wissen, rekonstruierbaren Indizes, mehrstufigem Retrieval, Hintergrundverarbeitung und aktivem Arbeitskontext.
Dadurch kann der Wissensbestand langfristig sehr groß werden, während die tägliche Nutzung schnell und übersichtlich bleibt.
