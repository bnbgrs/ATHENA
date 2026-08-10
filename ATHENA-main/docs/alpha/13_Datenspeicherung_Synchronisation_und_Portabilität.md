# Kapitel 13 – Datenspeicherung, Synchronisation und Portabilität

---

## Einleitung

Das Wissen ist der wertvollste Bestandteil von ATHENA.

Deshalb darf es niemals von einer bestimmten Festplatte, einem bestimmten Computer oder einer bestimmten Softwareinstallation abhängig sein.

Dieses Kapitel definiert die Regeln für Speicherung, Synchronisation und langfristige Portabilität des Wissensbestands.

Die Architektur geht davon aus, dass Hardware im Laufe der Jahre mehrfach ersetzt wird.

Der Wissensbestand bleibt dabei unverändert erhalten.

---

## Grundprinzip

Das Wissen ist ortsunabhängig.

Der physische Speicherort darf sich ändern.

Die logische Struktur des Wissens darf sich dadurch niemals ändern.

---

## Single Source of Truth
Die autoritativen Domänen von **ATHENA Persistent Data** bilden gemeinsam den maßgeblichen langfristigen Systemzustand.

Dazu gehören:

- Knowledge
- Raw Archive
- Personal Memory
- Audit and Provenance
- Configuration

Jede Domäne ist für ihren jeweiligen Inhalt autoritativ; keine abgeleitete technische Struktur darf eine konkurrierende Quelle derselben Information werden.

Davon zu unterscheiden sind zwei technische Zustandsklassen:

**Durable Operational State**

- persistente Queue-Einträge
- Checkpoints
- Transaktionsjournale
- lokale Offline- und Synchronisationspuffer
- noch nicht bestätigte Writes

Dieser Zustand ist nicht die kanonische Quelle für bereits bestätigt persistiertes Wissen. Solange darin jedoch noch nicht anderweitig bestätigte Daten liegen, ist er **nicht rekonstruierbar** und muss gegen Verlust geschützt werden.

**Derived State**

- Suchindex
- Cache
- Embeddings
- Vorschaudaten
- rein abgeleitete temporäre Dateien

Derived State ist aus den autoritativen Daten rekonstruierbar und darf keine Information enthalten, die ausschließlich dort existiert.

---

## Speicherstruktur
ATHENA unterscheidet logisch zwischen:

### Autoritativen persistenten Domänen

- Raw Archive
- Knowledge / Wissensgraph
- Personal Memory
- Audit and Provenance
- Configuration

### Durable Operational State

- persistente Queue
- Checkpoints
- Transaktionsjournal
- noch nicht bestätigte lokale Puffer

### Derived State

- Suchindizes
- Embeddings
- Caches
- Vorschaudaten
- sonstige rekonstruierbare technische Daten

### Backups

Backups sind unabhängige Sicherungskopien der dafür vorgesehenen Zustände und niemals die laufende Primärinstanz.

Diese Bereiche bleiben logisch voneinander getrennt, auch wenn die konkrete Implementierung sie teilweise auf demselben physischen Datenträger ablegt.

---

## Netzwerkfestplatte

Der langfristige Wissensbestand kann auf einer lokalen Festplatte,

einem NAS,

oder einer über das Netzwerk angebundenen externen Festplatte gespeichert werden.

Der Speicherort ist frei austauschbar.

---

## Offlinefähigkeit
Ist ein für autoritative Daten vorgesehener Langzeitspeicher vorübergehend nicht erreichbar, darf ATHENA soweit sicher möglich lokal weiterarbeiten.

Neue oder geänderte Informationen werden dann in **Durable Operational State** lokal gepuffert.

Dieser Puffer kann vorübergehend die einzige Kopie noch nicht synchronisierter Informationen enthalten. Er wird deshalb wie nicht rekonstruierbarer Zustand geschützt und darf nicht als gewöhnlicher Cache behandelt oder automatisch bereinigt werden.

Ist eine sichere lokale Persistierung nicht möglich, muss ATHENA den betroffenen Schreibvorgang stoppen, statt Datenverlust zu riskieren.

---

## Synchronisation
Sobald der vorgesehene Langzeitspeicher wieder erreichbar ist, kann ATHENA die Synchronisation automatisch fortsetzen.

Der Ablauf lautet grundsätzlich:

```text
Durable lokaler Puffer
        ↓
Integritätsprüfung
        ↓
Übertragung / Synchronisation
        ↓
Commit und Erfolgsprüfung
        ↓
Verifikation am Ziel
        ↓
Lokalen Puffer erst danach freigeben oder bereinigen
```

Eine lokale Kopie wird erst entfernt, wenn die erfolgreiche, konsistente Übertragung bestätigt und soweit vorgesehen verifiziert wurde.

Ein bloß gestarteter oder „gesendeter“ Transfer gilt nicht als bestätigter Commit.

---

## Konfliktbehandlung

Treten widersprüchliche Änderungen auf,

überschreibt ATHENA niemals stillschweigend Daten.

Stattdessen:

Konflikt erkennen,

beide Versionen erhalten,

Konflikt dokumentieren,

Benutzer informieren.

---

## Portabilität

Der gesamte Wissensbestand muss auf einen neuen Speicherort umziehbar sein.

Beispiele:

neue externe Festplatte

neues NAS

neuer Laufwerksbuchstabe

neuer Netzwerkpfad

neuer Computer

Die interne Struktur bleibt unverändert.

---

## Keine festen Pfade

Interne Beziehungen dürfen niemals auf absoluten Dateipfaden beruhen.

Stattdessen verwendet ATHENA:

stabile interne IDs,

relative Referenzen,

portable Metadaten.

Dadurch bleibt das Wissen unabhängig vom Speicherort.

---

## Integrität

Der Wissensbestand wird regelmäßig geprüft.

Hierzu gehören unter anderem:

Vollständigkeit

Prüfsummen

Struktur

interne Beziehungen

beschädigte Dateien

fehlende Komponenten

Beschädigungen werden dokumentiert und – soweit möglich – automatisch behoben.

---

## Versionierung

Der Wissensbestand entwickelt sich über viele Jahre.

ATHENA dokumentiert Änderungen nachvollziehbar.

Hierzu gehören:

neue Wissenseinheiten

Änderungen

Archivierungen

Löschungen

Wiederherstellungen

Die Historie bleibt nachvollziehbar.

---

## Backup

Vor kritischen Änderungen erstellt ATHENA automatisch Sicherungen.

Die Backup-Strategie wird im folgenden Kapitel detailliert beschrieben.

---

## Speicherwachstum

Die Architektur geht von einem langfristig wachsenden Wissensbestand aus.

ATHENA darf keine Größenbeschränkungen voraussetzen.

Auch sehr große Wissensbestände sollen ohne strukturelle Änderungen verwaltet werden können.

---

## Performance

Mit zunehmender Größe darf die Bedienung nicht spürbar schlechter werden.

Hierzu dürfen unter anderem verwendet werden:

Cache

Suchindex

Embeddings

Hintergrundoptimierungen

Diese dienen ausschließlich der Beschleunigung.

Sie sind niemals Bestandteil des eigentlichen Wissens.

---

## Graceful Degradation

Ist der langfristige Speicher vorübergehend nicht erreichbar,

arbeitet ATHENA mit lokalen Daten weiter.

Synchronisation erfolgt automatisch,

sobald der Speicher wieder verfügbar ist.

Dadurch bleibt das System auch bei Netzwerkproblemen nutzbar.

---

## Zukunftssicherheit

Neue Speichertechnologien dürfen jederzeit verwendet werden.

Die Architektur schreibt kein bestimmtes Dateisystem,

keinen bestimmten Datenträger,

und keinen bestimmten Netzwerkstandard vor.

Entscheidend ist ausschließlich,

dass die Architekturprinzipien dieses Kapitels eingehalten werden.

---

## Leitregel

Der Speicherort darf sich ändern. Das Wissen darf sich dadurch nicht ändern.

---

## Abschluss des Kapitels

Die Speicherarchitektur stellt sicher,

dass ATHENA ihren Wissensbestand über viele Jahre hinweg zuverlässig bewahren kann.

Hardwarewechsel,

Netzwerkänderungen,

neue Computer

oder neue Speicherlösungen dürfen niemals zum Verlust oder zur Beschädigung des Wissens führen.

Dieses Kapitel bildet damit die Grundlage für die langfristige Lebensdauer des gesamten Systems.
