# Kapitel 20 – Datenlebenszyklus, Aufbewahrung, Archivierung und Löschung

---

## Einleitung
ATHENA ist auf einen Nutzungszeitraum von vielen Jahren oder Jahrzehnten ausgelegt.
Damit entsteht zwangsläufig ein sehr großer Bestand aus:
- Chats
- Dokumenten
- Quellen
- Wissenseinheiten
- Nachrichten
- Medien
- Projekten
- Versionen
- Auditinformationen
Nicht alle Informationen müssen dauerhaft dieselbe Priorität besitzen.
ATHENA benötigt deshalb einen klar definierten Datenlebenszyklus.
Dieser darf jedoch niemals mit automatischem Vergessen verwechselt werden.

---

## Grundprinzip
ATHENA organisiert Alterung. ATHENA löscht nicht eigenmächtig.
Informationen können mit der Zeit weniger aktiv werden.
Sie bleiben jedoch erhalten, solange der Benutzer keine Löschung verlangt oder eine ausdrücklich konfigurierte technische Aufbewahrungsregel etwas anderes vorsieht.

---

## Lebenszyklus einer Information
Eine typische Information kann folgende Zustände durchlaufen:
```text
Neu

↓

Aktiv

↓

Langzeitwissen

↓

Archiviert

↓

optional: vom Benutzer gelöscht
```
Nicht jede Information muss alle Stufen durchlaufen.

---

## Neue Informationen
Neu importierte Informationen werden zunächst verarbeitet.
Dabei unterscheidet ATHENA zwischen:
- Originalquelle
- extrahiertem Wissen
- temporären technischen Daten
Diese Kategorien besitzen unterschiedliche Lebenszyklen.

---

## Aktives Wissen
Aktives Wissen umfasst Informationen, die momentan häufig oder unmittelbar relevant sind.
Beispiele:
- laufende Projekte
- aktuelle Entscheidungen
- häufig genutzte Concept Notes
- wiederkehrende Themen
- offene Fragen
Aktives Wissen erhält bei der Suche eine hohe Priorität.

---

## Langzeitwissen
Informationen, die weiterhin relevant sind, aber nicht regelmäßig benötigt werden, wechseln in den langfristigen Wissensbereich.
Sie bleiben vollständig:
- durchsuchbar
- verknüpft
- referenzierbar
- in Antworten verwendbar
Der Übergang verändert nicht den Inhalt.
Nur seine Abrufpriorität.

---

## Archiv
Sehr selten benötigte Informationen können archiviert werden.
Archivierung bedeutet:
- geringere Suchpriorität,
- weniger aktive Hintergrundverarbeitung,
- mögliche Auslagerung auf langsameren Speicher.
Archivierung bedeutet ausdrücklich nicht:
- Löschen,
- Vergessen,
- Entfernen von Beziehungen.

---

## Automatische Archivierung
ATHENA darf Inhalte anhand definierter Regeln zur Archivierung vorschlagen oder in dafür freigegebenen Bereichen automatisch archivieren.
Mögliche Kriterien:
- lange nicht verwendet,
- Projekt abgeschlossen,
- durch neuere Informationen ersetzt,
- historischer Zustand.
Die konkrete Archivierungslogik bleibt konfigurierbar.

---

## Reaktivierung
Archiviertes Wissen kann jederzeit wieder aktiv werden.
Beispiel:
```text
Archivierte Wissenseinheit

↓

Neue Benutzerfrage

↓

Treffer erkannt

↓

Wissen geladen

↓

bei erneuter Relevanz reaktiviert
```
Der Benutzer muss archivierte Informationen nicht manuell suchen.

---

## Roharchiv
Originalquellen werden gemäß den geltenden Aufbewahrungsregeln grundsätzlich langfristig erhalten.
Sie bilden die historische Quellengrundlage für daraus abgeleitetes Wissen.
Ein Chat kann deshalb längst aus dem aktiven Kontext verschwunden sein und trotzdem Jahre später erneut durchsucht werden.

---

## Chat-Aufbewahrung
Bei aktivierter Chat-Archivierung werden Chats mit mehr als einer sehr kurzen Interaktion grundsätzlich vollständig archiviert.
Damit können auch Informationen, die bei der ursprünglichen Wissensextraktion nicht als langfristig relevant erkannt wurden, später wiedergefunden werden.
Dies ist besonders wichtig, wenn sich die Bedeutung eines Gesprächs erst Wochen, Monate oder Jahre später zeigt.

---

## Chat-Speicherung steuerbar
Für normale Chats ist die automatische Archivierung standardmäßig aktiviert. Der Benutzer kann sie über die Benutzeroberfläche deaktivieren oder einen einzelnen Chat ausdrücklich als temporär beziehungsweise „nicht speichern“ markieren.

Ein **temporärer** Chat darf innerhalb eines klar begrenzten temporären Lebenszyklus technisch persistiert werden, wird danach aber nicht Bestandteil des langfristigen Raw Archive.

„**Nicht speichern**“ ist strenger: Der vollständige Chat-Payload soll soweit technisch möglich überhaupt nicht persistent geschrieben werden. Lediglich ausdrücklich daraus gespeichertes Knowledge oder Personal Memory darf mit Benutzeraktions-Provenienz fortbestehen.

---

## Explizite Speicherung
Unabhängig von der automatischen Einstellung kann der Benutzer jederzeit anweisen:
- diesen Chat speichern,
- diesen Chat nicht speichern,
- diese Information merken,
- diese Information nicht übernehmen.
Explizite Benutzeranweisungen besitzen Vorrang.

---

## Bereits gespeicherte Chats
Das spätere Deaktivieren der Chat-Archivierung löscht keine bereits gespeicherten Gespräche.
Bestehende Inhalte werden nur nach den vom Benutzer festgelegten Lösch- und Aufbewahrungsregeln entfernt; das bloße Deaktivieren der zukünftigen Archivierung löscht sie nicht.

---

## Nachrichten
Das Nachrichtensystem besitzt einen eigenen Lebenszyklus.
Einzelne Rohartikel können langfristig weniger relevant werden.
Die daraus entstandenen Ereignisse und historischen Entwicklungen bleiben jedoch Bestandteil des Wissenssystems.

---

## Temporäre Daten
Nicht alle Daten müssen dauerhaft erhalten bleiben.
Temporäre technische Daten können automatisch entfernt werden.
Beispiele:
- Cache
- rekonstruierbare temporäre Downloads
- Vorschaudateien
- rekonstruierbare Embeddings
- rein technische temporäre Logs ohne Audit- oder Provenienzfunktion
- rekonstruierbare Zwischenverarbeitung
Voraussetzung:
Die Daten müssen vollständig rekonstruierbar sein.

---

## Kein Wissen ausschließlich im Cache
Temporäre Daten dürfen niemals die einzige Kopie einer langfristig relevanten Information enthalten.
Bevor temporäre Daten entfernt werden, muss die kanonische Information sicher gespeichert sein.

---

## Deduplizierung
ATHENA soll identische Originaldaten nicht unnötig mehrfach physisch speichern.
Deduplizierung darf verwendet werden, solange:
- alle logischen Referenzen erhalten bleiben,
- Provenienz erhalten bleibt,
- keine Quelle scheinbar verschwindet.

---

## Versionen
Mehrere Versionen derselben Quelle oder Wissenseinheit werden nicht als unnötige Duplikate behandelt.
Versionierung dient der historischen Nachvollziehbarkeit.

---

## Löschung
ATHENA darf langfristiges Wissen nicht aufgrund eigener Heuristiken eigenmächtig endgültig löschen.

Eine endgültige Löschung erfolgt nur durch eine ausdrückliche Benutzerentscheidung oder aufgrund einer ausdrücklich vom Benutzer konfigurierten Aufbewahrungs-, Lebenszyklus- beziehungsweise Löschregel.

Solche Regeln gelten als vorab erteilte Benutzerentscheidung innerhalb ihres klar definierten Geltungsbereichs. Sie müssen einsehbar, änderbar und nachvollziehbar sein.

---

## Löschumfang
Der Benutzer kann unterschiedliche Ebenen löschen.
Beispielsweise:
- einzelne Wissenseinheit
- Originalquelle
- Chat
- Projekt
- persönlicher Gedächtniseintrag
- geschützter Bereich
ATHENA muss vor der Löschung feststellen, welche Abhängigkeiten betroffen sind.

---

## Abhängigkeiten
Vor einer Löschung prüft ATHENA:
- welche Wissenseinheiten auf die Quelle verweisen,
- welche Concept Notes betroffen sind,
- welche Projekte betroffen sind,
- welche Beziehungen betroffen sind.
Der Benutzer wird über relevante Folgen informiert.

---

## Löschung aus Backups
Eine besondere Herausforderung besteht darin, dass gelöschte Informationen noch in älteren Backups vorhanden sein können.
ATHENA muss deshalb langfristig ein Verfahren besitzen, mit dem endgültige Löschanforderungen auch bei späteren Wiederherstellungen berücksichtigt werden.
Die konkrete technische Umsetzung wird in der Beta-Spezifikation definiert.

---

## Restore und gelöschte Daten
Eine Wiederherstellung eines älteren Backups darf nicht unbemerkt dauerhaft gelöschte Inhalte wieder in den aktiven Wissensbestand zurückbringen.
ATHENA muss entsprechende Löschinformationen bei der Wiederherstellung berücksichtigen.

---

## Audit nach Löschung
Das Audit Log darf nach einer endgültigen Löschung keine versteckte Kopie des gelöschten Inhalts enthalten.
Es darf lediglich technisch notwendige Informationen behalten, beispielsweise:
Objekt ID 82741

endgültig gelöscht

08.08.2026
Nicht jedoch den eigentlichen gelöschten Inhalt.

---

## Geschützte Inhalte
Für geschützte Inhalte gelten dieselben Lebenszyklusregeln.
Archivierte geschützte Inhalte bleiben verschlüsselt.
Backups behalten denselben Schutz.

---

## Speicheroptimierung
Mit wachsendem Wissensbestand darf ATHENA automatische Speicheroptimierungen durchführen.
Zulässig sind beispielsweise:
- Kompression
- Deduplizierung
- Archivierung
- Rekonstruktion abgeleiteter Daten
- Rotation technischer Logs
Nicht zulässig ist die automatische Löschung kanonischen Wissens allein zur Speicherplatzersparnis.

---

## Speicherwarnungen
Wird Speicherplatz knapp, informiert ATHENA den Benutzer frühzeitig.
Das System kann geeignete Maßnahmen vorschlagen, beispielsweise:
- Cache bereinigen
- alte rekonstruierbare Indizes entfernen
- Archiv auf größeren Datenträger verschieben
- Backup-Rotation prüfen
Langfristiges Wissen wird nicht automatisch geopfert.

---

## Langfristige Skalierung
Der Lebenszyklus ist so ausgelegt, dass ATHENA auch nach zehn oder mehr Jahren nicht den gesamten Wissensbestand permanent im aktiven Arbeitsbereich halten muss.
Stattdessen entsteht eine Hierarchie:
Die Knowledge-Domäne besitzt eine interne Prioritäts- und Lebenszyklushierarchie:

```text
Aktives Wissen
      ↓
Langzeitwissen
      ↓
archiviertes Wissen
```

Parallel dazu bleibt das **Raw Archive** eine getrennte Quellen-Domäne. Es ist keine letzte Stufe des Wissenslebenszyklus, sondern hält gemäß den Aufbewahrungsregeln Originalquellen und deren Provenienzverknüpfungen vor. Beide Domänen bleiben durchsuchbar, ohne miteinander zu verschmelzen.

---

## Benutzerkontrolle
Der Benutzer kann jederzeit sehen:
- welche Informationen aktiv sind,
- welche archiviert sind,
- welche Daten viel Speicher benötigen,
- welche temporären Daten gelöscht werden können.
Die technische Organisation darf weitgehend automatisch erfolgen.
Endgültige Entscheidungen über langfristiges Wissen verbleiben beim Benutzer.

---

## Ziel
ATHENA soll auch nach Jahrzehnten nicht an seinem eigenen Wissensbestand ersticken.
Gleichzeitig darf langfristige Skalierung nicht durch aggressives Löschen erreicht werden.
Das System organisiert Informationen nach Relevanz und Nutzung, während die historische Wissensbasis erhalten bleibt.

---

## Leitregel
Weniger relevant bedeutet weiter entfernt – nicht vergessen.

---

## Abschluss des Kapitels
Der Datenlebenszyklus ermöglicht ATHENA, über Jahrzehnte zu wachsen, ohne dass alle Informationen permanent dieselbe Priorität besitzen.
Aktives Wissen, Langzeitwissen und archiviertes Wissen bilden innerhalb der Knowledge-Domäne eine skalierbare Wissenshierarchie. Das Raw Archive bleibt parallel dazu die getrennte Quellen-Domäne für erhaltene Originale.
Der Benutzer behält dabei jederzeit die endgültige Kontrolle darüber, was dauerhaft erhalten bleibt und was tatsächlich gelöscht wird.
