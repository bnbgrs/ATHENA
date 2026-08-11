# ATHENA Beta Specification v0.1 – Kapitel 04

## Quellen, Roharchiv und Import-Pipeline

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Technische Basis:** [Beta Kapitel 01](01_Systemarchitektur_und_Technische_Basis.md)
**Datenmodell:** [Beta Kapitel 02](02_Persistentes_Datenmodell_und_ID_System.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)

---

## Teil I – Auftrag und Importgrenzen

### 1. Ziel des Import-Subsystems

Das Import-Subsystem überführt externe oder vom Benutzer bereitgestellte Daten kontrolliert in das **Raw Archive**.

Es erzeugt beziehungsweise registriert autoritativ:

```text
Source
BlobRecord
retained SourceRepresentation, soweit für Provenienz benötigt
SourceAnchor
```

Für Verarbeitung und Retrieval darf es zusätzlich **Derived SourceChunk Sets** erzeugen. Diese sind kein autoritatives Raw Archive und dürfen später neu gebaut werden.

Das Import-Subsystem erzeugt nicht eigenmächtig kanonisches Wissen.

Der Importpfad endet semantisch an der Grenze:

```text
Original erfassen
→ technisch aufbereiten
→ referenzierbar machen
→ Derived Chunks/Representations bereitstellen
→ für semantische Verarbeitung bereitstellen
```

Erst Benutzer oder aktives Primärmodell dürfen daraus semantische Änderungen an Knowledge beziehungsweise Personal Memory veranlassen.

---

### 2. Import ist keine Wissensextraktion

Dateierkennung, Hashing, Textextraktion, OCR, Transkription, Segmentierung und Chunking sind technische Importoperationen. Sie dürfen Daten strukturieren, aber keine eigenständige Entscheidung darüber treffen, ob eine Aussage wahr, dauerhaft relevant oder kanonisch ist.

---

### 3. Unterstützte Importklassen

v1 muss mindestens unterstützen:

- einzelne Dateien;
- mehrere Dateien;
- ganze Ordner;
- Drag-and-Drop aus der Desktop-UI;
- über die Core API eingereichte Dateien;
- Text-Paste;
- gespeicherte Webseiten-Snapshots;
- Chat-Anhänge;
- vom News-System gelieferte Quellcaptures.

E-Mail- und Plugin-Imports verwenden dieselbe Source-Pipeline, auch wenn ihre Collector-Komponente später separat implementiert wird.

---

### 4. Original zuerst

Bei jeder nicht flüchtigen Quelle gilt:

```text
Original übernehmen und verifizieren
↓
Source committen
↓
erst danach abgeleitete Verarbeitung starten
```

Eine fehlgeschlagene OCR- oder Parsing-Stufe darf niemals dazu führen, dass das Original verloren geht.

---

### 5. Import-Atomizität

Ein Import gilt erst als `captured`, wenn Blob und Source-Metadaten konsistent committed sind. Nachgelagerte Repräsentationen dürfen später entstehen.

Damit kann ATHENA eine große Quelle sofort sicher besitzen, ohne dass der Benutzer warten muss, bis sämtliche Analyse abgeschlossen ist.

---

### 6. Importzustände

Mindestens:

```text
discovered
staging
captured
processing
ready
partial
failed
quarantined
cancelled
```

`captured` bedeutet: Original sicher gespeichert.
`ready` bedeutet: alle für den gewählten Importpfad vorgesehenen technischen Repräsentationen sind verfügbar.

---

## Teil II – Intake und Preflight

### 7. ImportRequest

Jeder Import startet als persistierbarer `ImportRequest` beziehungsweise als entsprechender Job-Scope. Er enthält mindestens:

- Quelle des Imports;
- gewünschte Protection Scope;
- Benutzeroptionen;
- Rekursionsregeln;
- Symlink-Policy;
- maximale Einzeldateigröße, falls konfiguriert;
- erwartete Anzahl soweit bekannt;
- explizite `temporary`- oder `do_not_store`-Regeln.

---

### 8. Preflight

Vor großen Importen prüft ATHENA:

- freien lokalen Spool-Speicher;
- Erreichbarkeit des Archive Root;
- Leserechte;
- geschätzte Datenmenge;
- Anzahl Dateien;
- offensichtliche Pfadprobleme;
- Protection Scope;
- laufende Disk-Full-Stufe.

Ein Preflight darf warnen oder pausieren, aber keine Quelle heimlich überspringen.

---

### 9. Dateierkennung

Der Dateityp wird mehrstufig bestimmt:

1. Dateiendung als Hinweis;
2. Magic Bytes beziehungsweise Containersignatur;
3. MIME- beziehungsweise Formatprobe;
4. Parser-Probe bei Bedarf.

Eine Endung allein gilt nicht als verlässliche Typbestimmung.

---

### 10. Unbekannte Formate

Ein unbekanntes Format wird trotzdem als Source archiviert, sofern der Benutzer den Import erlaubt.

Status:

```text
captured
processing_capability = unavailable
```

Spätere Parser oder Plugins können die Source erneut verarbeiten.

---

### 11. Verzeichnisimport

Ordnerimporte werden deterministisch enumeriert. Für jede gefundene Datei entsteht eine eigene Source. Die Ordnerstruktur kann zusätzlich als Importkontext beziehungsweise Collection-Metadatum erhalten werden, ohne als kanonische Identität zu dienen.

---

### 12. Symlink-Regel

v1 folgt bei Ordnerimporten standardmäßig **keinen** symbolischen Links beziehungsweise Junctions außerhalb des ausgewählten Importbaums.

Optionales Folgen muss explizit aktiviert werden und benötigt Zykluserkennung.

---

### 13. Versteckte und Systemdateien

Versteckte System-/Metadateien werden standardmäßig nicht automatisch importiert, wenn sie offensichtlich keine Benutzerdokumente darstellen.

Der Importbericht nennt gefilterte Dateien nach Kategorie, ohne daraus semantische Löschentscheidungen abzuleiten.

---

### 14. Dateiänderung während Intake

Vor und nach dem Kopieren werden soweit möglich Größe und relevante Dateimetadaten verglichen. Ändert sich die Quelldatei während der Aufnahme, wird der Versuch verworfen und kontrolliert wiederholt.

ATHENA darf keinen Mischzustand zweier Dateiversionen als Original committen.

---

## Teil III – Staging und Source-Erzeugung

### 15. Lokales Staging

Neue Bytes werden zunächst in einen lokalen Staging-Bereich geschrieben. Auch wenn `archive_root` online ist, darf eine Quelle nicht direkt als bestätigt gelten, bevor Länge und Integrität geprüft wurden.

---

### 16. Streaming Hash

Während des Kopierens wird SHA-256 inkrementell berechnet. Dadurch muss eine große Datei nicht vollständig in den RAM geladen werden.

---

### 17. Source-ID früh vergeben

Die `source_id` wird früh im Importjob erzeugt und bleibt über Retry, Offline-Spool und nachgelagerte Verarbeitung stabil.

Ein Retry erzeugt nicht automatisch mehrere Sources für denselben logischen Importversuch.

---

### 18. Blob-Deduplizierung

Nach vollständigem Hash kann ATHENA prüfen, ob ein identischer ungeschützter Blob bereits existiert. Ist dies verifiziert, wird der vorhandene Blob physisch wiederverwendet, während die neue Source ihre eigene Identität und Provenienz behält.

---

### 19. Source-Provenienz

Der Source-Commit dokumentiert mindestens:

- ImportActor;
- ursprünglichen Pfad beziehungsweise externen Locator soweit erlaubt;
- Zeit des Imports;
- Dateiname;
- erkannte Medienart;
- Protection Scope;
- Blob-ID;
- Importjob beziehungsweise ProcessingRun.

---

### 20. Original-Metadaten

Dateisystemmetadaten wie Erstell-/Änderungszeit werden als **Quellmetadaten** gespeichert und nicht mit ATHENAs `created_at` verwechselt.

Nicht verlässliche Metadaten werden als solche markiert.

---

### 21. Quarantäne

Eine Source kann in `quarantined` wechseln, wenn:

- Format und Inhalt stark widersprüchlich sind;
- Parser wiederholt abstürzt;
- Integritätsprüfung fehlschlägt;
- ein Schutz-/Policyproblem vorliegt;
- eine Archivdatei gefährliche Pfadstrukturen enthält.

Quarantäne bedeutet nicht Löschung.

---

## Teil IV – Technische Repräsentationen

### 22. Representation Pipeline

Nach erfolgreichem Source-Commit bestimmt ein Formatprofil, welche Repräsentationen sinnvoll sind.

Beispiele:

```text
PDF → extracted_text + page map
Bild → metadata + optional OCR text
Audio → transcript
Video → transcript + keyframe metadata
Office-Dokument → normalized text
HTML snapshot → cleaned readable text + DOM-derived structure
```

---

### 23. Representation ist immutable

Eine erzeugte SourceRepresentation wird nicht in-place korrigiert. Eine neue Parser-/OCR-Version erzeugt eine neue Representation mit eigener `representation_id` und ProcessingRun-Provenienz.

---

### 24. Parser-Versionierung

Jede Representation dokumentiert:

- Parser-/Provider-ID;
- Parser-Version;
- relevante Optionen;
- ProcessingRun;
- Input-Blob;
- Content Hash.

Damit kann später geprüft werden, warum zwei Extraktionen voneinander abweichen.

---

### 25. Textnormalisierung

Normalisierung darf technische Artefakte reduzieren, etwa:

- Zeilenendungen;
- Unicode-Normalisierung;
- eindeutig überflüssige Steuerzeichen.

Sie darf nicht eigenmächtig Aussagen umformulieren, zensieren, zusammenfassen oder „verbessern“.

---

### 26. Mehrere Repräsentationen parallel

ATHENA darf beispielsweise sowohl:

```text
native_text_extraction
```

als auch:

```text
ocr_text
```

für dieselbe Source besitzen. Keine wird automatisch zur ewigen Wahrheit erklärt.

---

### 27. Page Map

Für paginierte Dokumente wird eine Page Map erzeugt, die Textoffsets auf Seiten und gegebenenfalls Bounding Boxes zurückführen kann. Dies ist Voraussetzung für stabile SourceAnchors und spätere UI-Zitate.

---

### 28. Strukturinformationen

Überschriften, Tabellen, Listen, Absätze und Seitenbereiche dürfen als technische Strukturmetadaten extrahiert werden.

Diese Struktur unterstützt Chunking und Retrieval, ist aber keine eigenständige semantische Wissensentscheidung.

---

## Teil V – OCR, Audio und Video

### 29. OCRProvider

OCR wird ausschließlich über das `OCRProvider`-Interface angesprochen. Der Import-Core kennt kein fest verdrahtetes OCR-Modell.

---

### 30. OCR-Fallback

Bei bildbasierten PDFs:

```text
native text probe
↓
wenn unzureichend: OCR
↓
Representation speichern
```

Der Schwellenwert wird technisch über Textdichte und Parsingqualität bestimmt, nicht über Inhaltsthema.

---

### 31. OCR-Konfidenz

OCR-Konfidenzen dürfen als technische Qualitätswerte gespeichert werden. Sie sind keine epistemische Konfidenz über die Wahrheit des gelesenen Inhalts.

---

### 32. SpeechToTextProvider

Audio- und Video-Transkription läuft über `SpeechToTextProvider`.

Der Provider erzeugt zeitverankerte Segmente, sodass SourceAnchors auf Millisekundenbereiche zeigen können.

---

### 33. Speaker Labels

Speaker-Diarization darf gespeichert werden, wenn technisch verfügbar. Ungewisse Sprecherzuordnungen erhalten neutrale Labels wie `speaker_1`; ATHENA erfindet keine reale Identität.

---

### 34. Video

v1 analysiert Video primär über:

- Originaldatei;
- technische Medienmetadaten;
- Audiotranskript;
- optionale Keyframe-/Szenenrepräsentationen.

Visuelle Infrastrukturmodelle dürfen technische Bild-, Frame-, Objekt- oder Szenenrepräsentationen erzeugen, soweit diese **keine autonome semantische Wissensentscheidung** darstellen. Eine Interpretation, die Knowledge, Claims, Relations, Ereignisbedeutung oder andere kanonische Semantik beeinflusst, wird ausschließlich durch den Benutzer oder das aktive Primärmodell veranlasst.

---

### 35. Fehlende Infrastrukturmodelle

Ist OCR oder Speech-to-Text nicht verfügbar:

```text
Source bleibt captured
↓
Representation Job wartet/failed
↓
später retry
```

Original und Source bleiben vollständig erhalten.

---

## Teil VI – Archive und Container

### 36. Archive-Dateien

ZIP/TAR/ähnliche Container werden zunächst selbst als Source archiviert. Eine optionale Expansion erzeugt zusätzliche Child-Sources.

---

### 37. Archive Bomb Protection

Vor Expansion werden Grenzen geprüft:

- maximale Anzahl Einträge;
- maximale entpackte Gesamtgröße;
- maximale Kompression Ratio;
- Rekursionstiefe;
- Pfadnormalisierung.

Bei Überschreitung wird nicht weiter entpackt; der Originalcontainer bleibt erhalten.

---

### 38. Path Traversal

Archiveinträge mit Pfaden wie:

```text
../../outside/file
```

werden niemals außerhalb eines kontrollierten Staging-Verzeichnisses geschrieben.

---

### 39. Nested Archives

Verschachtelte Archive werden nur bis zu einer konfigurierten Tiefe automatisch expandiert. Weitere Ebenen bleiben als normale Sources verfügbar.

---

## Teil VII – Chunking und Anchors

### 40. Chunking nach Representation

Chunking erfolgt auf einer eindeutig versionierten SourceRepresentation, nicht direkt auf einer unklaren „aktuellen Textfassung“.

---

### 41. Struktur vor fester Größe

Chunk-Grenzen bevorzugen:

1. Dokumentabschnitte;
2. Überschriften;
3. Absätze;
4. Tabellen-/Listenblöcke;
5. erst danach Token-/Zeichenlimits.

Damit bleibt lokaler Kontext besser erhalten.

---

### 42. Chunkgröße ist Profil

Die konkrete Zielgröße gehört zum `chunking_profile_id`. Sie ist keine globale unveränderliche Alpha-Regel.

---

### 43. Overlap

Overlap wird nur verwendet, wenn es Retrievalqualität tatsächlich verbessert. Der Overlap wird als technische Chunking-Eigenschaft dokumentiert und darf keine doppelte Source-Evidenz vortäuschen.

---

### 44. SourceAnchor vor Chunk-ID

Langfristige Evidenz zeigt bevorzugt auf `source_id + anchor_id`.

Chunk-IDs dienen Verarbeitung und Retrieval. Ein Rechunking darf keine Claim-Evidenz zerstören.

---

### 45. Tabellen

Tabellen erhalten soweit möglich strukturierte Anchors auf:

- Seite;
- Tabellenindex;
- Zeile;
- Spalte;
- Zellbereich.

Ein reiner Fließtextdump darf die einzige Darstellung nicht sein, wenn die Tabellenstruktur zuverlässig extrahierbar ist.

---

## Teil VIII – Import-Deduplizierung

### 46. Byte-identische Quelle

Byte-identische Dateien dürfen denselben Blob verwenden, bleiben aber getrennte Sources, wenn sie aus unterschiedlichen Importereignissen stammen.

---

### 47. Doppelimport desselben Pfads

Wenn dieselbe unveränderte Datei über denselben Watch-Scope erneut gemeldet wird, darf ATHENA das Ereignis als technischen Duplikat-Trigger erkennen und keine neue Source erzeugen.

Diese Optimierung benötigt einen stabilen Watch-/Import-Fingerprint und darf echte neue Versionen nicht verschlucken.

---

### 48. Semantische Duplikate

Ähnlicher Text, andere Formatierung oder eine konvertierte Datei sind **keine** physische Deduplizierung.

Eine semantische Same-As-/Merge-Entscheidung gehört in Knowledge Processing.

---

### 49. Versionserkennung

Wird am selben beobachteten Ursprung neuer Inhalt gefunden:

```text
neue Source
+
source relation: supersedes/version_of
```

Die alte Source bleibt erhalten.

---

## Teil IX – Folder Watch und inkrementelle Imports

### 50. Folder Watch

Ein optionaler Folder Watch überwacht explizit konfigurierte Verzeichnisse.

Er ist standardmäßig auf die gewählten Scopes begrenzt und scannt nicht die gesamte Festplatte.

---

### 51. Watch Events sind Hinweise

Dateisystemevents sind nicht alleinige Wahrheit. Nach einem Event prüft ATHENA den tatsächlichen Dateizustand.

Mehrere schnell aufeinanderfolgende Events werden debounced.

---

### 52. Stabilitätsfenster

Eine Datei wird erst importiert, wenn Größe und Änderungszeit über ein kurzes Stabilitätsfenster unverändert geblieben sind.

Dadurch werden Dateien nicht mitten im Kopiervorgang aufgenommen.

---

### 53. Delete Event

Das Löschen einer beobachteten externen Datei löscht **nicht** automatisch die bereits archivierte Source.

Es wird höchstens als externes Ereignis dokumentiert.

---

### 54. Rename Event

Ein Rename im Watched Folder ändert keine bestehende Source-ID. Bei noch nicht importierter Datei wird der neue Pfad verwendet; bei bereits archivierter Quelle kann die neue externe Herkunft als neues Ereignis dokumentiert werden.

---

## Teil X – Web- und externe Captures

### 55. Web Snapshot als Source

Eine Webquelle wird nicht nur als URL gespeichert. Der Collector übergibt einen Snapshot mit:

- URL;
- Retrievalzeit;
- Response-/Content-Metadaten;
- archiviertem Inhalt soweit zulässig.

Damit bleibt die Quelle auch nach späterer Webseitenänderung zitierbar.

---

### 56. Externes HTML ist Daten

HTML, eingebettete Prompts, Kommentare, Metatags und Texte werden ausschließlich als externe Daten behandelt. Sie dürfen keine Instruktionen an ATHENAs Core oder Primärmodellautorität werden.

---

### 57. Redirect Chain

Web-Captures dürfen die Redirect-Kette als Provenienzmetadatum behalten. Die finale URL ersetzt nicht zwingend die ursprünglich angefragte URL.

---

### 58. Robots, Login und geschlossene Quellen

Collector-Regeln für rechtliche/technische Zugriffsbedingungen werden im External-Access-Kapitel definiert. Die Import-Pipeline selbst umgeht keine Authentifizierung und keinen Zugriffsschutz.

---

## Teil XI – Fehler, Cancel und Resume

### 59. Fehlerklassifikation

Importfehler werden mindestens getrennt in:

```text
source_unreadable
storage_unavailable
integrity_failed
unsupported_format
parser_failed
ocr_failed
transcription_failed
chunking_failed
security_blocked
cancelled
```

---

### 60. Partial Ready

Wenn Original und Textrepräsentation vorhanden sind, aber beispielsweise OCR einer einzelnen Seite scheitert, darf der Import als `partial` nutzbar sein.

Die UI zeigt fehlende Teilbereiche.

---

### 61. Retry

Retry verwendet dieselbe Source-/Jobidentität, solange derselbe Importversuch fortgesetzt wird. Erfolgreiche Stages werden über Checkpoints nicht unnötig wiederholt.

---

### 62. Cancel

Cancel stoppt neue nachgelagerte Verarbeitung.

Bereits bestätigte Source-/Blob-Commits bleiben erhalten, sofern der Benutzer nicht ausdrücklich deren Löschung verlangt.

---

### 63. Crash Resume

Nach Neustart:

```text
ImportJob laden
↓
captured Sources prüfen
↓
letzten bestätigten Stage-Checkpoint lesen
↓
nur fehlende Stages fortsetzen
```

---

## Teil XII – Protected Imports

### 64. Protection Scope am Eingang

Der Protection Scope wird **vor** dem finalen Blob Write festgelegt.

Eine geschützte Datei darf nicht kurzzeitig als normaler Klartextblob im öffentlichen Archive Root landen.

---

### 65. Protected Staging

Geschützte Imports verwenden einen dafür vorgesehenen lokalen Stagingpfad mit restriktiven Dateirechten und möglichst kurzer Klartextlebensdauer.

---

### 66. Protected Representations

OCR-, Transcript- und Textrepräsentationen geschützter Sources erben mindestens denselben Protection Scope.

---

### 67. Keine ungeschützten Previews

Thumbnail, Preview, FTS, Embedding, Dateiname und Importbericht dürfen keine geschützten Inhalte in ungeschützte Derived-State-Bereiche kopieren.

---

## Teil XIII – UI und Transparenz

### 68. Import Progress

Die UI zeigt mindestens:

- Anzahl entdeckt;
- erfolgreich captured;
- processing;
- ready;
- partial;
- failed;
- quarantined;
- verbleibende Datenmenge soweit schätzbar.

---

### 69. Fehler pro Datei

Ein Fehler bei einer Datei bricht einen Ordnerimport nicht automatisch vollständig ab.

Fehlerhafte Sources werden einzeln sichtbar und retrybar.

---

### 70. Keine stillen Skips

Gefilterte, übersprungene oder nicht unterstützte Dateien erscheinen im Abschlussbericht mit Grund.

---

### 71. Import Receipt

Ein abgeschlossener größerer Import erzeugt einen menschenlesbaren Receipt:

- Importzeit;
- Scope;
- Dateizahl;
- Gesamtbytes;
- neue Sources;
- deduplizierte Blobs;
- Fehler;
- Quarantäne;
- offene Processing Jobs.

---

## Teil XIV – Tests und Abnahmekriterien

### 72. Einzeldatei-Test

Datei importieren, Core neu starten, Source und Originalbytes anhand der `source_id` wieder lesen. Hash muss identisch sein.

---

### 73. Großdatei-Test

Mehrere Gigabyte große Datei streamend importieren. RAM-Nutzung darf nicht proportional zur Dateigröße wachsen.

---

### 74. Änderung-während-Import-Test

Quelldatei während des Kopierens verändern. ATHENA darf keinen gemischten Blob committen.

---

### 75. Parser-Failure-Test

Parser absichtlich fehlschlagen lassen. Original muss `captured` bleiben und später neu verarbeitet werden können.

---

### 76. Archive-Bomb-Test

Extrem komprimiertes Testarchiv importieren. Expansion muss an den Sicherheitsgrenzen stoppen; Container bleibt erhalten.

---

### 77. Path-Traversal-Test

Archiv mit `../`-Einträgen. Kein Byte darf außerhalb des Stagingbereichs geschrieben werden.

---

### 78. Offline-Archive-Test

Archive Root offline nehmen. Source muss über lokalen Durable Spool sicher aufgenommen und später verifiziert synchronisiert werden.

---

### 79. Protected-Import-Test

Geschützte Datei importieren und danach gesamten unprotected Derived State durchsuchen. Kein Klartextfragment darf auffindbar sein.

---

### 80. Rechunking-Test

Chunking-Profil ändern und Source neu chunken. Bestehende SourceAnchors und Claim-Evidenz müssen gültig bleiben.

---

### 81. Folder-Watch-Test

Große Datei langsam in einen Watched Folder kopieren. Import darf erst nach Stabilitätsfenster beginnen.

---

### 82. Cancel-Resume-Test

Ordnerimport während Representation Processing abbrechen und ATHENA neu starten. Bereits bestätigte Sources bleiben konsistent; Job kann kontrolliert fortgesetzt werden.

---

### 83. Abschluss

Das Import-Subsystem ist bestanden, wenn ATHENA beliebige unterstützte Quellen sicher aufnehmen kann, bevor irgendeine semantische Interpretation nötig ist, und wenn Parser-, Modell-, Netzwerk- oder Prozessfehler niemals die bereits erfassten Originaldaten gefährden.

---

## Nächster Schritt

**Beta Kapitel 05 – Wissenseinheiten, Claims und Wissensgraph**.
