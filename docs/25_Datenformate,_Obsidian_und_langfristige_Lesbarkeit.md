# Kapitel 25 – Datenformate, Obsidian und langfristige Lesbarkeit

---

## Einleitung
ATHENA soll Wissen über Jahrzehnte erhalten.
Damit reicht es nicht aus, Daten lediglich zuverlässig zu speichern.
Sie müssen auch dann noch verständlich und rekonstruierbar sein, wenn sich:
- ATHENA,
- Obsidian,
- Datenbanken,
- Betriebssysteme,
- Modelle,
- Speicherhardware
grundlegend verändert haben.
Der langfristige Wissensbestand darf deshalb nicht ausschließlich in einem proprietären oder undokumentierten Format existieren.

---

## Grundprinzip
ATHENA muss verschwinden können, ohne dass das Wissen mit ihr verschwindet.
Der Benutzer muss seinen Wissensbestand grundsätzlich auch außerhalb einer funktionierenden ATHENA-Installation verstehen, sichern und migrieren können.

---

## Kanonische Daten und Arbeitsdarstellungen
ATHENA unterscheidet zwischen:
- kanonischen Daten,
- menschenlesbaren Darstellungen,
- rekonstruierbaren technischen Daten.
Diese Ebenen erfüllen unterschiedliche Aufgaben.

---

## Kanonische Daten
Die kanonische Ebene enthält die verbindliche strukturierte Repräsentation des Wissens.
Sie muss alle Informationen enthalten, die für eine vollständige Rekonstruktion erforderlich sind.
Hierzu gehören unter anderem:
- stabile IDs,
- Wissenseinheiten,
- Beziehungen,
- Provenienz,
- Versionen,
- Zeitinformationen,
- Sicherheitszuordnungen,
- notwendige Metadaten.
Das konkrete technische Format wird in der Beta-Spezifikation festgelegt.

---

## Menschenlesbare Ebene
Wesentliche Wissensinhalte sollen zusätzlich in offenen, dokumentierten und möglichst menschenlesbaren Formaten verfügbar sein.
Markdown besitzt hierfür eine zentrale Rolle.
Insbesondere geeignet sind:
- .md
- .txt
- offene Medienformate
- dokumentierte strukturierte Exportformate
Dadurch bleibt der Wissensbestand unabhängig von einer einzelnen Anwendung zugänglich.

---

## Markdown
Markdown ist das bevorzugte Format für menschenlesbare Wissensdarstellungen.
Es eignet sich insbesondere für:
- Concept Notes,
- Projektübersichten,
- Zusammenfassungen,
- Dokumentation,
- exportierte Wissenseinheiten.
Markdown ist jedoch nicht zwingend die alleinige interne Datenbank von ATHENA.
Komplexe Beziehungen und technische Metadaten können eine zusätzliche strukturierte Repräsentation benötigen.

---

## Obsidian
Obsidian dient als langfristig nützliche zusätzliche Oberfläche auf Markdown-basiertes Wissen.
Der Benutzer kann damit beispielsweise:
- Notizen lesen,
- Verknüpfungen erkunden,
- Inhalte manuell bearbeiten,
- Wissensstrukturen durchsuchen.
Obsidian ist jedoch nicht ATHENA.

---

## Keine Obsidian-Abhängigkeit
ATHENA darf nicht davon abhängig sein, dass Obsidian installiert ist.
Falls Obsidian:
- entfernt,
- nicht mehr weiterentwickelt,
- inkompatibel,
- oder durch eine andere Anwendung ersetzt
wird, bleibt der Wissensbestand vollständig nutzbar.

---

## Obsidian-Updates
Automatische Obsidian-Updates dürfen ATHENA nicht beschädigen.
Insbesondere darf ATHENA nicht von:
- einer bestimmten Obsidian-Version,
- einem Theme,
- einem einzelnen Community-Plugin
abhängig sein.

---

## Obsidian als Ansicht
Die bevorzugte Architektur behandelt Obsidian primär als Ansicht beziehungsweise Editor einer menschenlesbaren Wissensebene.
Der ATHENA Core bleibt für:
- Integrität,
- stabile Identitäten,
- Provenienz,
- Sicherheitsregeln,
- Wissenslogik
verantwortlich.

---

## Manuelle Änderungen
Der Benutzer darf menschenlesbare Wissensdateien auch außerhalb von ATHENA bearbeiten.
ATHENA muss solche Änderungen kontrolliert erkennen und verarbeiten können, sofern der betreffende Bereich dafür vorgesehen ist.
Externe Änderungen dürfen nicht stillschweigend kanonische Daten beschädigen.

---

## Konflikte durch externe Bearbeitung
Entsteht durch eine externe Bearbeitung ein Konflikt, gilt:
- keine stille Überschreibung,
- beide Zustände sichern,
- Unterschied erkennen,
- Konflikt nachvollziehbar behandeln.
Die genaue Synchronisationslogik wird technisch spezifiziert.

---

## Stabile Identitäten
Dateinamen sind keine Identitäten.
Ordner sind keine Identitäten.
Eine Wissenseinheit besitzt eine stabile interne ID.
Dadurch kann eine Datei umbenannt oder verschoben werden, ohne dass Beziehungen verloren gehen.

---

## Dateinamen
Menschenlesbare Dateinamen sollen verständlich sein.
Die technische Identität wird jedoch separat verwaltet.
Dadurch können Titel geändert werden, ohne interne Referenzen zu zerstören.

---

## Ordner
Ordner dienen der menschlichen Orientierung und physischen Organisation.
Sie bilden nicht die primäre Wissensstruktur.
Ein Wissenselement kann logisch mit vielen Bereichen verbunden sein, obwohl es physisch nur an einem Ort gespeichert wird.

---

## Links
Wissensbeziehungen dürfen nicht ausschließlich von fragilen Dateipfaden abhängen.
ATHENA verwaltet Beziehungen über stabile Identitäten.
Menschenlesbare Links können zusätzlich erzeugt werden.

---

## Frontmatter und Metadaten
Markdown-Dateien können strukturierte Metadaten enthalten.
Diese dürfen zur Portabilität beitragen.
Kritische Systeminformationen dürfen jedoch nicht ausschließlich von einem Formatdetail abhängen, das eine externe Anwendung unbemerkt entfernen könnte.

---

## Originaldateien
Importierte Originale bleiben während ihrer Aufbewahrung grundsätzlich in ihrem ursprünglichen Format erhalten.
Beispiele:

```text
PDF  → PDF bleibt erhalten
JPEG → JPEG bleibt erhalten
MP3  → MP3 bleibt erhalten
DOCX → DOCX bleibt erhalten
```

Zusätzliche Extraktionen werden separat gespeichert.

---

## Extraktion ist kein Ersatz
Beispiel:
```text
PDF

├── Original
├── extrahierter Text
├── OCR-Ergebnis
└── Wissenseinheiten
```
Der extrahierte Text ersetzt niemals das Original-PDF.

---

## Formatmigration
Manche Dateiformate können langfristig veralten.
ATHENA darf deshalb zusätzliche modernere Kopien erzeugen.
Beispielsweise:
```text
altes Format

├── unverändertes Original
└── migrierte lesbare Version
```
Das Original bleibt gemäß den geltenden Aufbewahrungsregeln erhalten.

---

## Keine destruktive Formatmigration
Eine Formatmigration darf niemals nach dem Muster erfolgen:
```text
altes Format

↓

konvertieren

↓

Original löschen
```
Stattdessen bleibt die historische Quelle bestehen.

---

## Export
ATHENA muss einen vollständigen Export des persönlichen Wissensbestands ermöglichen.
Der Export soll soweit möglich aus offenen und dokumentierten Formaten bestehen.
Er muss unabhängig von einer laufenden ATHENA-Instanz gesichert werden können.

---

## Vollständiger Export
Ein vollständiger Export umfasst mindestens:
- Originalquellen,
- menschenlesbares Wissen,
- Projekte,
- Concept Notes,
- Beziehungen,
- notwendige Provenienz,
- relevante Metadaten.
Geschützte Inhalte werden entsprechend ihrer Sicherheitsregeln behandelt.

---

## Strukturierter Export
Zusätzlich zu menschenlesbaren Dateien soll ATHENA eine maschinenlesbare Darstellung der Beziehungen und Metadaten exportieren können.
Dadurch kann ein zukünftiges System den Wissensbestand rekonstruieren.
Das konkrete Format wird später festgelegt.

---

## Exportdokumentation
Ein vollständiger Export soll eine Dokumentation enthalten, die erklärt:
- Verzeichnisstruktur,
- Datenformate,
- IDs,
- Beziehungen,
- Versionierung,
- Provenienz.
Dadurch bleibt der Export auch ohne ATHENA verständlich.

---

## Notfall-Lesbarkeit
Ein wesentliches Ziel lautet:
Wenn ATHENA eines Tages nicht mehr startet, soll der Benutzer trotzdem einen großen Teil seines Wissens mit normalen Werkzeugen öffnen können.
Beispielsweise:
- Texteditor,
- Markdown-Editor,
- PDF-Reader,
- Bildbetrachter,
- Mediaplayer.

---

## Kein Vendor Lock-in
ATHENA darf den Benutzer nicht technisch zwingen, ATHENA dauerhaft zu verwenden, um an seine eigenen Daten zu gelangen.
Dies gilt auch dann, wenn ATHENA selbst die komfortabelste Möglichkeit zur Nutzung des Wissens bleibt.

---

## Datenbank
Eine interne Datenbank darf für:
- Performance,
- Transaktionen,
- Beziehungen,
- Indizes
verwendet werden.
Sie darf jedoch nicht die einzige langfristig interpretierbare Repräsentation des Wissens darstellen.

---

## Datenbankverlust
Rekonstruierbare Strukturen sollen soweit möglich aus den kanonischen Daten und dokumentierten Exportinformationen wiederhergestellt werden können.
Die genaue Grenze zwischen kanonischer Datenbank und menschenlesbarer Repräsentation wird in der Beta-Spezifikation festgelegt.

---

## Schemas
Strukturierte Daten besitzen versionierte Schemas.
Dadurch weiß eine spätere ATHENA-Version, wie ältere Daten interpretiert werden müssen.

---

## Schema-Migration
Ändert sich ein Schema:
1. alte Version erkennen,
2. Backup erstellen,
3. Migration durchführen,
4. Ergebnis validieren,
5. neue Version markieren.
Originalquellen bleiben davon unberührt.

---

## Zeichencodierung
Textbasierte Formate verwenden standardisierte Unicode-Codierung.
Dadurch bleiben:
- verschiedene Sprachen,
- Sonderzeichen,
- wissenschaftliche Zeichen
langfristig erhalten.
Die konkrete technische Vorgabe wird in der Beta-Spezifikation festgelegt.

---

## Zeitinformationen
Zeitstempel müssen eindeutig gespeichert werden.
ATHENA muss zwischen:
- lokal angezeigter Zeit,
- Zeitzone,
- technisch eindeutiger Zeitreferenz
unterscheiden können.
Dies ist insbesondere für jahrzehntelange historische Rekonstruktionen relevant.

---

## Checksummen
Originalquellen und wichtige persistente Dateien können über Prüfsummen identifiziert und auf Integrität geprüft werden.
Dadurch kann ATHENA erkennen:
- beschädigte Dateien,
- identische Originale,
- unbeabsichtigte Veränderungen.

---

## Migration auf neue Festplatte
Der vollständige Wissensbestand kann auf einen neuen Datenträger übertragen werden.
Der Ablauf soll grundsätzlich möglich sein als:
```text
ATHENA-Daten exportieren oder kopieren

↓

neuer Datenträger

↓

neuen Speicherort auswählen

↓

Integritätsprüfung

↓

ATHENA arbeitet weiter
```
Der neue Pfad darf vollständig anders sein.

---

## Migration auf neuen Computer
Dasselbe Prinzip gilt für einen vollständigen Computerwechsel.
Der Wissensbestand gehört nicht zur Identität des ursprünglichen PCs.

---

## Zukunft ohne Obsidian
Sollte Obsidian irgendwann nicht mehr verwendet werden, kann eine andere Markdown-kompatible Anwendung oder ein zukünftiger ATHENA-eigener Wissenseditor dessen Rolle übernehmen.
Der Wissensbestand muss dafür nicht neu erstellt werden.

---

## Zukunft ohne das aktuelle Modellbackend
Dasselbe Prinzip gilt für das jeweils konfigurierte Modellbackend.

Ein Modellbackend führt Modelle aus, besitzt aber nicht den Wissensbestand.

Ein zukünftiges anderes kompatibles Backend kann diese Rolle übernehmen, ohne dass autoritative Daten neu erfunden oder migriert werden müssen, sofern die dokumentierten Schnittstellen eingehalten werden.

---

## Zukunft ohne ATHENA
Der strengste Portabilitätstest lautet:
Kann der Benutzer sein Wissen noch verstehen, wenn ATHENA selbst nicht mehr existiert?
Die Architektur soll diese Frage soweit praktisch möglich mit Ja beantworten.

---

## Git und Spezifikationen
Die ATHENA-Spezifikationen und der Quellcode werden getrennt vom persönlichen Wissensbestand versioniert.
Markdown eignet sich besonders für die Speicherung der Architekturtexte in Git.
Dadurch können:
- Änderungen verglichen,
- Versionen markiert,
- frühere Zustände wiederhergestellt
werden.

---

## Dokumentation als Teil der Portabilität
Eine langfristig stabile Datenstruktur ohne Dokumentation ist nicht ausreichend.
Deshalb gehört die Beschreibung der Datenformate selbst zu den langfristig zu erhaltenden Projektunterlagen.

---

## Ziel
ATHENA soll keinen digitalen Tresor bauen, dessen Schlüssel ausschließlich ATHENA selbst besitzt.
ATHENA soll ein Wissenssystem bauen, das komfortabel von ATHENA verwaltet wird, dessen Inhalte aber langfristig dem Benutzer gehören und technisch zugänglich bleiben.

---

## Leitregel
ATHENA darf das beste Werkzeug für den Wissensbestand sein. Sie darf niemals das einzige Werkzeug sein, das ihn noch verstehen kann.

---

## Abschluss des Kapitels
Offene Formate, stabile Identitäten, dokumentierte Schemas und die Trennung zwischen kanonischen Daten und rekonstruierbaren technischen Strukturen bilden die Grundlage für die langfristige Lesbarkeit von ATHENA.
Obsidian, Modellbackends, Datenbanken und selbst ATHENA können sich im Laufe der Jahre verändern oder vollständig ersetzt werden.
Der Wissensbestand bleibt.
