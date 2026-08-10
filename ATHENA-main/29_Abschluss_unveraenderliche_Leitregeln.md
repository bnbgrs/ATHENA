# Abschluss – Unveränderliche Leitregeln von ATHENA

---

## Zweck dieses Abschlusses
Dieses Kapitel fasst die unveränderlichen Grundregeln von ATHENA_ALPHA v2.0.1 FINAL zusammen.
Es ersetzt nicht die vorherigen Kapitel.
Es dient als kompakter, nicht-normativer Referenzpunkt für zukünftige Architektur-, Design- und Implementierungsentscheidungen. Bei Abweichungen gelten die Kapitel 1–28 gemäß der in Kapitel 1 definierten normativen Hierarchie. Eine technische Entscheidung, die einer normativen Alpha-Regel widerspricht, muss geändert werden.

---

## 1. Der Benutzer denkt. ATHENA organisiert.
ATHENA unterstützt:
- Denken
- Erinnern
- Strukturieren
- Recherchieren
- Verknüpfen
- Dokumentieren
ATHENA ersetzt nicht die Verantwortung des Benutzers.

---

## 2. Das Wissen ist wichtiger als die Software.
Modelle können wechseln.
Programme können wechseln.
Hardware kann wechseln.
Speicherorte können wechseln.
Das Wissen muss bestehen bleiben.

---

## 3. Das Wissen gehört dem Benutzer.
ATHENA darf niemals einen technischen Lock-in erzeugen.
Der Benutzer muss seine Daten:
- lesen,
- exportieren,
- sichern,
- übertragen,
- löschen
können.

---

## 4. Local First.
Der grundlegende Betrieb von ATHENA funktioniert lokal.
Das langfristige Wissenssystem benötigt keine verpflichtende Cloud.
Externe Dienste bleiben optional.

---

## 5. Internet ist ein Werkzeug.
Normale Chats besitzen standardmäßig keinen Internetzugriff.
Der Benutzer kann Internetzugriff bewusst für eine Anfrage, über den Internet-Schalter oder durch ausdrücklich konfigurierte Plugin- beziehungsweise Automationsberechtigungen autorisieren.
Der definierte tägliche News-Workflow bildet die einzige standardmäßig vorgesehene automatische Ausnahme.

---

## 6. Externe Kommunikation ist geschützt.
ATHENA darf nicht stillschweigend direkt auf das Internet ausweichen.
Die Alpha-Architektur verlangt eine freigegebene Privacy-/Anonymisierungsschicht mit Fail-Closed-Verhalten. Die konkrete technische Umsetzung – beispielsweise Tor – ist eine Beta-Entscheidung und keine unveränderliche Alpha-Abhängigkeit.
Fällt die vorgeschriebene Anonymisierung aus, gilt:
Fail Closed.

---

## 7. Externe Inhalte sind Daten, keine Befehle.
Webseiten, Dokumente, Nachrichten, PDFs, E-Mails und andere importierte Inhalte dürfen interne ATHENA-Regeln nicht überschreiben.
Prompt-Injection aus externen Quellen wird architektonisch isoliert.

---

## 8. Es gibt genau ein aktives Primärmodell.
Das aktive Primärmodell übernimmt die automatisierten wissensbildenden und semantischen KI-Aufgaben. Der Benutzer bleibt die höchste semantische Autorität und kann kanonisches Wissen ausdrücklich erstellen, korrigieren, ergänzen oder löschen. Andere KI-Modelle dürfen als Infrastrukturmodelle dienen, besitzen aber keine eigenständige semantische Entscheidungsbefugnis.
Dazu gehören:
- Interpretation
- Wissensextraktion
- Zusammenfassungen
- Kategorien
- Verknüpfungen
- Projekte
- Entscheidungen
- Concept Notes

---

## 9. Infrastrukturmodelle sind Werkzeuge.
OCR, Speech-to-Text, Embeddings, TTS und vergleichbare Komponenten dürfen technische Vorarbeit leisten.
Sie dürfen den kanonischen Wissensinhalt nicht eigenmächtig interpretieren oder umschreiben.

---

## 10. Modelle sind austauschbar.
ATHENA darf niemals von einem einzelnen Modell abhängig werden.
Ein Modellwechsel verändert nicht automatisch den vorhandenen Wissensbestand.

---

## 11. Der Benutzer kontrolliert das Primärmodell.
ATHENA darf nicht aufgrund des Inhalts einer Anfrage heimlich auf ein anderes Primärmodell wechseln.
Modellwechsel bleiben sichtbar und nachvollziehbar.

---

## 12. Originale bleiben erhalten.
Verarbeitung verändert, ersetzt oder überschreibt Originalquellen niemals.

```text
Original
↓
Extraktion / Interpretation
↓
getrennte Ableitung
```

Originale werden gemäß den geltenden Aufbewahrungsregeln erhalten. Eine endgültige Löschung erfolgt nur durch eine ausdrückliche Benutzerentscheidung oder eine ausdrücklich vom Benutzer konfigurierte Aufbewahrungsregel.

„Originale bleiben erhalten“ bedeutet deshalb Schutz vor destruktiver Verarbeitung, nicht Unlöschbarkeit gegen den Willen des Benutzers.

---

## 13. Refusal bedeutet niemals Datenverlust.
Kann ein Modell einen Inhalt nicht verarbeiten:
- Original speichern
- Fehler dokumentieren
- Verarbeitung später erneut ermöglichen
Der Inhalt darf nicht verschwinden.

---

## 14. Inhaltsneutralität.
ATHENA organisiert Inhalte unabhängig von deren Thema.
Technische Infrastruktur darf Inhalte nicht aufgrund ihres Themas:
- abschwächen
- umschreiben
- entfernen
- schlechter archivieren
Epistemische Bewertung bleibt davon getrennt.

---

## 15. Quellen bleiben nachvollziehbar.
ATHENA soll auch nach Jahrzehnten beantworten können:
Woher weiß ich das?
Jede relevante Wissenseinheit besitzt Provenienz.

---

## 16. Jede modellgestützte Interpretation erhält eine Modellsignatur.
War ein Modell an einer dauerhaft gespeicherten Interpretation beteiligt, bleiben mindestens nachvollziehbar:
- Modell beziehungsweise Provider
- Modellversion
- Quantisierung, soweit vorhanden
- relevante Einstellungen
- Zeitpunkt
Direkte Benutzerinterpretationen ohne Modellbeteiligung erhalten stattdessen eindeutige Benutzerprovenienz; ATHENA erfindet keine Modellsignatur.

---

## 17. Relevante Änderungen sind auditierbar.
ATHENA dokumentiert relevante automatische und manuelle Veränderungen an autoritativen persistenten Daten.
Der Benutzer soll nachvollziehen können:
- was geändert wurde
- wann
- durch welchen Akteur oder Prozess
- warum

---

## 18. Automatisierung ist soweit sinnvoll reversibel.
Zusammenführungen, Umstrukturierungen und andere semantische Veränderungen sollen rückgängig gemacht werden können.
Automatisierung darf nicht zu irreversibler Wissensdrift führen.

---

## 19. ATHENA löscht niemals eigenmächtig langfristiges Wissen.
Wissen kann:
- historisiert
- archiviert
- niedriger priorisiert
werden.

Endgültige Löschung erfolgt nur durch eine ausdrückliche Benutzerentscheidung oder aufgrund einer ausdrücklich vom Benutzer konfigurierten Aufbewahrungs-, Lebenszyklus- beziehungsweise Löschregel. Eine solche Regel gilt innerhalb ihres definierten Geltungsbereichs als vorab erteilte Benutzerentscheidung.

---

## 20. Der Benutzer besitzt das Recht auf endgültige Löschung.
Eine Löschanforderung muss auch berücksichtigen:
- Original
- Interpretation
- Index
- Embeddings
- Cache
- Beziehungen
Backups besitzen definierte Lösch- und Wiederherstellungsregeln.

---

## 21. Roharchiv und Wissensgraph bleiben getrennt.
Vollständige Originalgespräche und andere Quellen werden nicht zum eigentlichen Wissensgraphen.
Aus ihnen werden relevante Wissenseinheiten extrahiert.

---

## 22. Relevante Chats bleiben rekonstruierbar.
Chats, die über eine sehr kurze Interaktion hinausgehen, werden entsprechend den definierten Archivierungsregeln standardmäßig vollständig erhalten. Ausnahmen sind ausdrücklich temporäre Chats, ein deaktivierter Archivierungsschalter oder die Benutzeranweisung „nicht speichern“.
Dadurch können Informationen auch Jahre später erneut ausgewertet werden.

---

## 23. Das Kontextfenster ist kein Gedächtnis.
Das Primärmodell erhält nur den relevanten Arbeitskontext.
Langfristiges Erinnern entsteht durch ATHENAs Wissenssystem und Retrieval.

---

## 24. ATHENA muss nicht alles gleichzeitig wissen.
ATHENA muss wissen, wo sie Informationen wiederfindet.
Retrieval besitzt Vorrang vor unselektierter Vollbeladung des Modellkontexts.

---

## 25. Wissen besitzt zeitlichen Kontext.
ATHENA unterscheidet zwischen:
- aktuell
- historisch
- zeitlos
- veraltet
Eine früher korrekte Aussage darf nicht deshalb als falsch behandelt werden, weil sich die Welt später verändert hat.

---

## 26. Widersprüche werden dokumentiert.
ATHENA erzeugt bei widersprüchlichen Quellen nicht automatisch eine künstliche Wahrheit.
Quellen, Zeitbezug und Vertrauensniveau bleiben sichtbar.

---

## 27. Externe Aussagen sind zunächst Behauptungen ihrer Quellen.
Eine Nachricht oder Webseite wird nicht automatisch zur Wahrheit des Wissenssystems.
Bestätigung und Widerspruch beeinflussen das Vertrauensniveau.

---

## 28. News werden als Ereignisse organisiert.
ATHENA baut kein bloßes Artikelarchiv.
Mehrere Meldungen über dasselbe Ereignis werden logisch zusammengeführt.

---

## 29. Der tägliche News-Workflow darf Rückstände nachholen.
War ATHENA offline, bleiben verpasste Zeiträume erhalten.
ATHENA führt später einen Backfill durch.
Sie überspringt historische Lücken nicht stillschweigend.

---

## 30. Fehlende historische Daten werden nicht erfunden.
Ein News-Backfill kann vollständig, teilweise oder nicht rekonstruierbar sein.
Unsicherheit wird transparent dargestellt.

---

## 31. Hintergrundaufgaben sind persistent.
Ein Neustart, Stromausfall oder ausgeschalteter Computer darf Aufgaben nicht verlieren lassen.
Die Queue übersteht Sitzungen und Neustarts.

---

## 32. Direkte Benutzerinteraktion besitzt Vorrang.
Hintergrundjobs sollen den normalen Chatbetrieb nicht unnötig blockieren.

---

## 33. ATHENA nutzt freie Ressourcen, statt sie zu erzwingen.
Rechenintensive Hintergrundaufgaben berücksichtigen:
- CPU
- RAM
- GPU
- VRAM
- Benutzeraktivität

---

## 34. ATHENA stört keine aktive GPU-Arbeit unnötig.
Spiele, Rendering und andere GPU-intensive Anwendungen besitzen Vorrang vor nicht dringenden Hintergrundaufgaben.

---

## 35. Modelle können automatisch geladen und entladen werden.
Automatische Modellverwaltung ist zulässig, wenn sie die aktive Nutzung nicht beeinträchtigt.
Manuelle Benutzerentscheidungen besitzen Vorrang.

---

## 36. Keine Aufgabe wird stillschweigend übersprungen.
Kann ein Job nicht ausgeführt werden, wird er:
- verschoben
- erneut versucht
- oder nachvollziehbar als fehlgeschlagen markiert

---

## 37. ATHENA Persistent Data bildet den autoritativen persistenten Systemzustand.
Die autoritativen Domänen von **ATHENA Persistent Data** bilden gemeinsam den maßgeblichen langfristigen Systemzustand.

Dabei ist:

- Knowledge autoritativ für kanonisches semantisches Wissen
- Raw Archive autoritativ für erhaltene Originalquellen
- Personal Memory autoritativ für langfristige Zusammenarbeitseinstellungen
- Audit and Provenance autoritativ für Herkunft und Änderungshistorie
- Configuration autoritativ für Benutzer- und Systemkonfiguration

Keine abgeleitete technische Struktur darf eine konkurrierende Quelle dieser Informationen werden.

---

## 38. Abgeleitete Daten sind rekonstruierbar.
Rein abgeleitete Daten wie Suchindizes, Embeddings, Caches oder Vorschauen sind rekonstruierbar.

Durable Operational State ist davon zu unterscheiden. Noch nicht bestätigte Writes, lokale Synchronisationspuffer, Transaktionsjournale und notwendige Checkpoints können vorübergehend die einzige Kopie noch nicht bestätigt persistierter Informationen enthalten und dürfen deshalb nicht als entbehrlicher Cache behandelt werden.

---

## 39. Der Speicherort ist austauschbar.
ATHENA darf nicht logisch an:
- Laufwerksbuchstaben
- Festplatten
- UNC-Pfade
- Computer
gebunden sein.

---

## 40. Interne Beziehungen verwenden stabile Identitäten.
Dateinamen und Pfade sind keine dauerhaften Objektidentitäten.

---

## 41. Eine neue Festplatte darf kein neues ATHENA bedeuten.
Ein bestehender Wissensbestand muss auf einen neuen Datenträger übertragen und dort weiterverwendet werden können.

---

## 42. Netzwerkverlust bedeutet nicht Datenverlust.
Ist ein Langzeitspeicher vorübergehend offline, arbeitet ATHENA nur soweit weiter, wie neue Informationen sicher in Durable Operational State persistiert werden können.

Grundsätzlich:

- sicher lokal puffern
- Pending State gegen Verlust schützen
- später synchronisieren
- bei nicht sicher möglicher Persistierung den betroffenen Schreibvorgang stoppen

---

## 43. Lokale Puffer werden erst nach bestätigter Synchronisation entfernt.
„Gesendet“ ist nicht dasselbe wie „sicher angekommen“.

Ein lokaler Pending- oder Synchronisationspuffer wird erst freigegeben oder bereinigt, wenn Übertragung, Commit und erforderliche Verifikation erfolgreich bestätigt wurden.

---

## 44. Konflikte werden niemals still überschrieben.
Bei konkurrierenden Änderungen werden beide Zustände erhalten, bis der Konflikt sicher aufgelöst wurde.

---

## 45. Backups sind automatisch.
Der Benutzer soll nicht daran denken müssen, regelmäßig Sicherungen anzulegen.

---

## 46. Backups wachsen nicht unbegrenzt.
Die Standard-Retention basiert auf einer sinnvollen Rotation aus:
- täglichen
- wöchentlichen
- monatlichen
- jährlichen
Sicherungen.

---

## 47. Ein Backup muss physisch getrennt sein können.
Ein Backup auf demselben defekten Datenträger ist kein ausreichender Katastrophenschutz.

---

## 48. Ein Backup gilt erst als gut, wenn Restore funktioniert.
ATHENA prüft die Wiederherstellbarkeit.

---

## 49. Geschützte Inhalte bleiben auch im Backup geschützt.
Backups dürfen keine unverschlüsselten Schattenkopien geschützter Informationen erzeugen.

---

## 50. Recovery ist Kernfunktion.
Recovery darf nicht von:
- Primärmodell
- Plugins
- Obsidian
- Internet
abhängen.

---

## 51. ATHENA besitzt einen sicheren Nur-Lese-Modus.
Kann die Integrität von Schreibvorgängen nicht garantiert werden, soll Wissen weiterhin lesbar bleiben, ohne weitere Schäden zu verursachen.

---

## 52. Graceful Degradation.
Der Ausfall einer nichtkritischen oder optionalen Komponente soll den Gesamtbetrieb nicht unnötig stoppen.

Beispiele:

- Privacy-/Anonymisierungsschicht nicht verfügbar → lokal weiterarbeiten, externe Zugriffe fail-closed blockieren
- Embeddings nicht verfügbar → Volltextsuche verwenden
- Netzwerkspeicher offline → sicher lokal puffern, sofern möglich

Kann die Integrität autoritativer Daten oder einer kritischen Sicherheitsgrenze nicht garantiert werden, darf ATHENA betroffene Schreiboperationen stoppen und in Read-Only- oder Recovery-Zustände wechseln.

---

## 53. ATHENA überwacht ihren eigenen Zustand.
Observability umfasst unter anderem:
- Core
- Modelle
- Queue
- Speicher
- Privacy-/Anonymisierungsschicht
- Backup
- Suchsystem
- Netzwerk

---

## 54. Fehler werden verständlich erklärt.
ATHENA zeigt:
- was ausgefallen ist
- was weiterhin funktioniert
- was versucht wurde
- was als Nächstes möglich ist

---

## 55. Updates dürfen Wissen nicht gefährden.
Vor kritischen Updates:
- prüfen
- sichern
- aktualisieren
- testen
Bei Fehler:
- Rollback

---

## 56. Migrationen sind kontrolliert.
Datenmigrationen sind:
- versioniert
- abgesichert
- validiert
- soweit möglich reversibel

---

## 57. Neue Modelle interpretieren altes Wissen nicht automatisch neu.
Globale Neuinterpretationen erfolgen nur bewusst.

---

## 58. Obsidian ist austauschbar.
Obsidian ist eine nützliche Wissensoberfläche.
Es ist nicht ATHENA und besitzt nicht das kanonische Wissen.

---

## 59. Das Modellbackend ist austauschbar.
Das konfigurierte Modellbackend ist austauschbar.

Alpha legt keinen bestimmten Modellserver oder Anbieter als dauerhafte Systemabhängigkeit fest. Die konkrete Referenzimplementierung wird in der Beta-Spezifikation bestimmt.

---

## 60. Offene Datenformate besitzen Vorrang.
Langfristiges Wissen soll soweit sinnvoll in:
- Markdown
- dokumentierten strukturierten Formaten
- Standardmedienformaten
zugänglich bleiben.

---

## 61. ATHENA darf verschwinden, ohne dass das Wissen verschwindet.
Der Benutzer soll einen erheblichen Teil seines Wissens auch ohne funktionierende ATHENA-Installation lesen können.

---

## 62. Obsidian- oder Softwareupdates dürfen das Wissen nicht brechen.
Integration erfolgt über stabile, dokumentierte Schnittstellen und offene Daten.

---

## 63. Plugins besitzen Funktionen. ATHENA besitzt das Wissen.
Ein Plugin kann entfernt werden.
Seine bereits übernommenen Wissensinhalte bleiben erhalten.

---

## 64. Plugins dürfen den Core nicht umgehen.
Kanonische Änderungen laufen über kontrollierte ATHENA-Schnittstellen.

---

## 65. Plugins erhalten minimale Berechtigungen.
Neue Rechte werden nicht stillschweigend vergeben.

---

## 66. Ein Pluginfehler darf ATHENA nicht mitreißen.
Optionale Erweiterungen müssen isolierbar sein.

---

## 67. Persönliches Gedächtnis ist vom Wissensbestand getrennt.
Es speichert langfristige Präferenzen zur Zusammenarbeit.
Nicht ungefragt beliebige persönliche Details.

---

## 68. Persönliches Gedächtnis ist transparent.
Der Benutzer kann es:
- lesen
- bearbeiten
- löschen
- zurücksetzen

---

## 69. Geschützte Inhalte werden vollständig über ATHENA verwaltet.
Der Benutzer benötigt keine externe Verschlüsselungssoftware für die normale Nutzung.

---

## 70. Ein geschützter Bereich schützt mehr als den Text.
Auch:
- Dateinamen
- Tags
- Metadaten
- Suchindex
- Zusammenfassungen
dürfen keine geschützten Inhalte verraten.

---

## 71. Passwörter werden nicht im Klartext gespeichert.
Recovery-Schlüssel werden nicht unverschlüsselt neben den geschützten Daten aufbewahrt.

---

## 72. Mehrere Geräte teilen ein Gedächtnis.
Desktop, Smartphone und zukünftige Clients greifen langfristig auf denselben logischen Wissensbestand zu.

---

## 73. Mobile Clients sind Clients, keine konkurrierenden ATHENA-Instanzen.
Die erste Architektur verwendet einen zentralen Core.

---

## 74. Remote-Zugriff ist authentifiziert und verschlüsselt.
Ein öffentlich freigegebener ungeschützter ATHENA-Port ist nicht vorgesehen.

---

## 75. Mobile Zukunft darf Desktop Version 1 nicht verzögern.
Die Architektur bleibt vorbereitet.
Die erste Implementierung bleibt bewusst Desktop First.

---

## 76. Performance ist Architekturziel.
ATHENA soll auch mit sehr großen Wissensbeständen flüssig bleiben.

---

## 77. Millionen Wissenseinheiten dürfen keine neue Benutzerlogik erfordern.
Skalierung wird intern gelöst.

---

## 78. Inkrementelle Verarbeitung besitzt Vorrang.
Neue Informationen sollen nicht ständig globale Neuberechnungen auslösen.

---

## 79. Der Benutzer sucht nach Wissen, nicht nach Dateien.
Speicherort und Dateiorganisation sollen für normale Fragen irrelevant sein.

---

## 80. ATHENA dokumentiert nicht nur Wissen, sondern Wissensentwicklung.
Historische Aussagen, Korrekturen, Widersprüche und neue Interpretationen bleiben nachvollziehbar.

---

## 81. Kein automatisches Handeln allein aufgrund von Wissen.
Wissen allein autorisiert niemals eine externe Aktion.

Externe Aktionen benötigen eine **gültige Benutzerautorisierung**. Diese kann:

- unmittelbar für eine einzelne Aktion erteilt werden oder
- vorab durch eine ausdrücklich konfigurierte Regel, Automation oder Plugin-Berechtigung festgelegt sein.

```text
Wissen / Ereignis
        ↓
Handlungsvorschlag oder ausgelöste Regel
        ↓
gültige Benutzerautorisierung prüfen
        ↓
externe Aktion
```

ATHENA wird nicht allein durch eine gespeicherte Information zu einem autonomen Akteur. Vorab autorisierte Automatisierung bleibt trotzdem zulässig und auditierbar.

---

## 82. Benutzerkontrolle besitzt Vorrang vor Autonomie.
Automatisierung dient der Entlastung.
Nicht der Entmündigung.

---

## 83. Keep it simple.
Eine einfache robuste Lösung wird einer komplexeren Lösung vorgezogen, wenn beide dieselben Anforderungen erfüllen.

---

## 84. Keine Technik um der Technik willen.
ATHENA benötigt keine komplexe Infrastruktur allein aufgrund technischer Eleganz.

---

## 85. Aus Benutzersicht bleibt ATHENA ein Programm.
Die gewünschte Alltagserfahrung lautet:
```text
ATHENA öffnen
↓
chatten
↓
fertig
```

---

## 86. Alpha ist Vision, Beta ist Umsetzung.
ATHENA_ALPHA v2.0.1 FINAL definiert:
- Identität
- Philosophie
- Grenzen
- unveränderliche Architekturprinzipien
ATHENA_BETA_SPEC definiert:
- Technologien
- Datenmodelle
- APIs
- Prozesse
- konkrete Implementierung

---

## 87. Die technische Implementierung bleibt modular.
Code wird nicht als ein einziger monolithischer Schritt entwickelt.
Module werden einzeln spezifiziert, implementiert und getestet.

---

## 88. Spezifikationsgetriebene Entwicklung.
Der Code muss den dokumentierten Anforderungen folgen.
Nicht umgekehrt.

---

## 89. Git verwaltet das Projekt.
Quellcode und Spezifikationen werden versioniert.
Der persönliche Wissensbestand erhält davon getrennte Speicher- und Backupmechanismen.

---

## 90. Langfristige Stabilität besitzt Vorrang vor Feature Creep.
Neue Funktionen dürfen ATHENA nicht unnötig komplizierter machen.

---

## Die zentrale Hierarchie
Wenn zukünftige Anforderungen miteinander konkurrieren, gilt folgende Priorisierung:
1. Integrität des Wissens

2. Sicherheit und Benutzerkontrolle

3. Nachvollziehbarkeit und Portabilität

4. Zuverlässigkeit

5. Einfachheit der Bedienung

6. Performance

7. neue Funktionen
Eine neue Funktion darf niemals Punkt 1 bis 5 gefährden, nur um Punkt 7 zu erfüllen.

---

## Der endgültige Architekturtest
Jede zukünftige technische Entscheidung kann anhand von sieben Fragen geprüft werden:
1. Gefährdet sie vorhandenes Wissen?
2. Macht sie ATHENA von einer einzelnen Technologie abhängig?
3. Verringert sie die Kontrolle des Benutzers?
4. Erzeugt sie eine neue versteckte Datenkopie?
5. Ist sie nachvollziehbar und im Fehlerfall wiederherstellbar?
6. Macht sie die Benutzeroberfläche unnötig komplizierter?
7. Ist sie wirklich notwendig?
Wenn eine Entscheidung diese Prüfung nicht besteht, muss sie geändert oder verworfen werden.

---

## Was ATHENA langfristig sein soll
ATHENA soll nicht zu einem ständig autonom handelnden digitalen Wesen werden.
ATHENA soll auch nicht lediglich ein Chatfenster mit einem lokalen Sprachmodell sein.
Das Ziel liegt dazwischen:
Ein dauerhaftes persönliches Wissenssystem, mit dem der Benutzer natürlich sprechen kann und das Informationen zuverlässig organisiert, erinnert, verbindet und schützt.

---

## Was dauerhaft bleibt
Über Jahrzehnte können sich verändern:
- Hardware
- Modelle
- Benutzeroberflächen
- Betriebssysteme
- Modellbackends
- Speichergeräte
- Suchtechnologien
- Datenbanken
- Plugins
Dauerhaft bleiben sollen:
- gemäß den Aufbewahrungsregeln erhaltene Originalquellen
- Wissen
- Beziehungen
- Provenienz
- Entscheidungen
- Historie
- Benutzerhoheit

---

## Abschließender Leitsatz
Der Benutzer denkt. ATHENA organisiert.
Das Wissen gehört dem Benutzer.
Alles andere ist austauschbar.

---

## Status
Mit diesem Abschluss ist ATHENA_ALPHA v2.0.1 FINAL konzeptionell abgeschlossen.
Alle weiteren Arbeiten gehören grundsätzlich in die technische Spezifikation:
ATHENA_BETA_SPEC
ATHENA_ALPHA bleibt die verbindliche Referenz für alle späteren Architektur- und Implementierungsentscheidungen.

---

## Ergänzende Konsolidierungsregeln

- Der Benutzer besitzt die höchste Autorität über ATHENAs Wissensbestand.
- Nur der Benutzer und das aktive Primärmodell dürfen semantische Änderungen am kanonischen Wissen veranlassen.
- Infrastrukturmodelle und technische Algorithmen dürfen keine eigenständigen semantischen Wissensentscheidungen treffen.
- Originalquellen dürfen analysiert und interpretiert werden, werden dabei jedoch niemals überschrieben; Ableitungen bleiben getrennt und mit Provenienz verknüpft. Endgültige Löschung folgt ausschließlich den definierten Benutzer- und Aufbewahrungsregeln.
- Meinungen werden als attribuierte Aussagen gespeichert und nicht als Ereignisfakten ausgegeben.
- Externe Kommunikation folgt einer freigegebenen Privacy-/Anonymisierungsschicht mit Fail-Closed-Verhalten; konkrete Technologien sind Beta-Implementierungsentscheidungen.
- Kapitel 29 fasst zusammen und überschreibt keine normative Detailregel.
