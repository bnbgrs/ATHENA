# Kapitel 5 – Roharchiv und Quellenmanagement

---

## Einleitung
Das Roharchiv ist ATHENAs historische Quellenbasis.

Es enthält die ursprünglichen Informationen, bevor diese interpretiert, zusammengefasst oder miteinander verknüpft werden.

Das Roharchiv ist keine Sammlung zufälliger Dateien. Es ist die autoritative Domäne für erhaltene Originalquellen und ermöglicht es, spätere Wissenseinheiten auf ihre Herkunft zurückzuführen.

Die Existenz einer Interpretation oder Zusammenfassung ersetzt niemals die zugrunde liegende Originalquelle.

---

## Grundprinzip
Originale besitzen Vorrang als historische Evidenz gegenüber ihren Ableitungen.

Jede spätere Zusammenfassung, Concept Note oder Wissenseinheit ist eine getrennte Sicht auf die ursprünglichen Informationen.

Verarbeitung verändert, ersetzt oder überschreibt Originalquellen niemals. Originale werden gemäß den geltenden Aufbewahrungsregeln erhalten und nur durch eine ausdrückliche Benutzerentscheidung oder eine ausdrücklich vom Benutzer konfigurierte Aufbewahrungsregel endgültig gelöscht.

---

## Was gehört ins Roharchiv?
Das Roharchiv speichert sämtliche langfristig relevanten Originalquellen.
Beispiele:
Gespräche
- Chats mit ATHENA
- importierte Chatverläufe
- Sprachtranskripte
- Meeting-Protokolle
Regel:
Chats mit mehr als einer kurzen Unterhaltung (mehr als etwa 1–2 Nachrichten) werden standardmäßig vollständig archiviert. Ausnahmen sind ausdrücklich als temporär geführte Chats, ein deaktivierter Archivierungsschalter oder die explizite Benutzeranweisung „nicht speichern“.

---

## Dokumente
- PDFs
- Word-Dokumente
- Markdown-Dateien
- Textdateien
- Präsentationen
- Tabellen

---

## Internetquellen
- Webseiten
- Nachrichten
- Blogartikel
- wissenschaftliche Veröffentlichungen
- Dokumentationen

---

## Medien
- Bilder
- Audio
- Videos

---

## Eigene Inhalte
- Notizen
- Skizzen
- Ideen
- Projektdokumente
- Entwürfe

---

## Unveränderlichkeit
Originalquellen werden durch Verarbeitung niemals automatisch verändert oder ersetzt.

Nicht erlaubt sind insbesondere:

- automatisches Umschreiben des Originals
- automatisches Kürzen des Originals
- automatische Übersetzung als Ersatz des Originals
- automatische Korrektur des Originals
- stilles Überschreiben bestehender Inhalte

Ändert sich eine Quelle, wird die Änderung versioniert oder als neue Quelle erfasst. Bestehende Versionen bleiben gemäß den Aufbewahrungsregeln erhalten.

Unveränderlichkeit bedeutet dabei **Unveränderlichkeit durch Verarbeitung**, nicht Unlöschbarkeit gegen den Willen des Benutzers. Endgültige Löschung richtet sich nach den definierten Lösch- und Aufbewahrungsregeln.

---

## Roharchiv ≠ Wissensgraph
Das Roharchiv dient ausschließlich als Quelle.
Nicht jede Quelle wird automatisch Teil des aktiven Wissensnetzes.
Beispiel:
```text
Rohchat
        │
        ▼
Primärmodell
        │
        ▼
3 relevante Erkenntnisse
        │
        ▼
Wissensgraph
```
Der vollständige Chat verbleibt im Archiv.
Nur die relevanten Erkenntnisse gelangen in das Wissensnetz.

---

## Quellenidentität
Jede Quelle erhält eine dauerhafte interne Identität.
Diese bleibt unabhängig von:
- Dateinamen,
- Ordnerstruktur,
- Speicherort,
- Laufwerksbuchstaben,
- Netzwerkpfaden.
Dadurch können Quellen verschoben werden, ohne dass Verknüpfungen verloren gehen.

---

## Versionierung
Verändert sich eine Quelle, entsteht keine stille Überschreibung.
ATHENA erstellt stattdessen eine neue Version.
Dadurch bleibt nachvollziehbar:
- wann sich etwas geändert hat,
- wodurch,
- warum.
Frühere Versionen bleiben erhalten.

---

## Provenienz
Jede aus dem Roharchiv abgeleitete Wissenseinheit muss ihre Herkunft eindeutig nachweisen können.

Mindestens dokumentiert werden, soweit anwendbar:

- Originalquelle oder Originalquellen
- Erstellungszeitpunkt
- Importzeitpunkt
- Quelle der Quelle, falls vorhanden
- originierender Akteur beziehungsweise Prozess

War ein Primärmodell an der semantischen Ableitung beteiligt, werden zusätzlich seine Modellsignatur und die relevante Verarbeitungsversion gespeichert.

Direkte Benutzeränderungen oder vom Benutzer erzeugte Wissenseinheiten erhalten stattdessen eine eindeutige Benutzerprovenienz; ATHENA erfindet keine nicht vorhandene Modellbeteiligung.

---

## Externe Quellen
Externe Informationen werden zunächst ausschließlich als Aussagen ihrer Quelle gespeichert.
Beispiel:
Nicht:
Aussage X ist wahr.
Sondern:
Quelle A behauptet Aussage X.
Erst durch spätere Bestätigung, Widerspruch oder zusätzliche Quellen verändert sich das Vertrauensniveau.

---

## Prompt-Injection
Externe Quellen dürfen niemals als Systemanweisung interpretiert werden.
Dies gilt insbesondere für:
- Webseiten
- PDFs
- Quellcode
- E-Mails
- Dokumentationen
- Nachrichten
Externe Inhalte sind Daten.
Sie sind niemals Befehle an ATHENA.

---

## Geschützte Quellen
Quellen können als geschützt markiert werden.
Für geschützte Quellen gelten zusätzlich:
- verschlüsselte Speicherung,
- neutrale Dateinamen,
- keine öffentlichen Tags,
- keine unverschlüsselten Zusammenfassungen,
- keine Metadaten, die Rückschlüsse auf den Inhalt erlauben.
Die Quelle bleibt dennoch Bestandteil des Gesamtsystems.

---

## Refusal-Failsafe
Kann das Primärmodell eine Quelle nicht interpretieren oder verweigert die Verarbeitung, gilt:
- Die Quelle wird trotzdem archiviert.
- Es erfolgt keine automatische Löschung.
- Die Interpretation wird als fehlgeschlagen markiert.
- Eine spätere Neuinterpretation bleibt möglich.
Ein fehlgeschlagener Verarbeitungsschritt darf niemals zum Verlust der Originalquelle führen.

---

## Integritätsprüfung
Jede Quelle besitzt Integritätsinformationen.
Beispielsweise:
- Prüfsumme
- Zeitstempel
- Versionsnummer
- Änderungsquelle
ATHENA übernimmt beschädigte oder widersprüchliche Quellen niemals stillschweigend.

---

## Auditierbarkeit
Jeder Import einer Quelle wird protokolliert.
Mindestens:
- Zeitpunkt
- Importweg
- Benutzer oder Hintergrundprozess
- Ergebnis
- eventuelle Warnungen
Dadurch bleibt der vollständige Lebenszyklus jeder Quelle nachvollziehbar.

---

## Ziel des Roharchivs

Das Roharchiv soll gewährleisten, dass keine langfristig relevante **Quelleninformation** verloren geht.

Es dient nicht der täglichen Arbeit, sondern der dauerhaften Nachvollziehbarkeit von Quellen und Originalen.

Das Roharchiv ist die **autoritative historische Quellenbasis** von ATHENA. Alle aus externen, importierten oder archivierten Quellen abgeleiteten Wissenseinheiten bauen auf dieser Grundlage auf.

Direkt vom Benutzer erzeugtes Wissen benötigt dagegen keine künstliche Originalquelle. Seine Herkunft wird über die originierende Benutzeraktion, Revision und Audit-/Provenienzmetadaten dokumentiert.

## Abschluss des Kapitels

Das Roharchiv bildet die unveränderte Quellenbasis des Systems.

Alle **aus Quellen abgeleiteten** Interpretationen, Zusammenfassungen und Beziehungen müssen jederzeit auf die jeweils verwendeten Originalquellen beziehungsweise eindeutig bestimmte Quellrepräsentationen zurückgeführt werden können.

Direkt vom Benutzer erzeugte Wissenseinheiten, Entscheidungen oder Korrekturen werden stattdessen auf ihre originierende Benutzeraktion zurückgeführt.

Das nächste Kapitel beschreibt beide semantischen Schreibpfade: automatisierte Extraktion aus Quellen sowie direkte Benutzererstellung und Benutzerkorrektur.
