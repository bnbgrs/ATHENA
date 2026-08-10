# Kapitel 21 – Modellfreiheit, Inhaltsneutralität und robuste Wissensverarbeitung

---

## Einleitung
ATHENA ist als persönliches Wissenssystem konzipiert.
Das System darf deshalb nicht davon abhängig sein, welche inhaltlichen Grenzen, Moderationsregeln oder Verhaltensweisen ein bestimmtes Sprachmodell besitzt.
Modelle sind austauschbare Verarbeitungskomponenten.
Sie definieren weder den zulässigen Wissensbestand noch die Identität von ATHENA.
Dies gilt unabhängig davon, ob der Benutzer ein frei konfigurierbares, lokal angepasstes, sogenanntes Heretic- oder ein anderes kompatibles Modell als Primärmodell verwendet.

---

## Grundprinzip
Bei automatisierter KI-Verarbeitung bestimmt das aktive Primärmodell die inhaltliche Interpretation. Der Benutzer kann Interpretationen ausdrücklich selbst veranlassen oder korrigieren. Infrastrukturmodelle dürfen diese semantischen Entscheidungen nicht eigenständig umschreiben.
Damit wird verhindert, dass ein vom Primärmodell erzeugter Inhalt durch nachgelagerte Hilfsmodelle unbeabsichtigt verändert, abgeschwächt oder neu interpretiert wird.

---

## Frei wählbares Primärmodell
ATHENA muss die Verwendung kompatibler, vom Benutzer gewählter Primärmodelle unterstützen. Dazu können auch frei konfigurierte oder sogenannte Heretic-Modelle gehören. Ein kompatibles Modell kann als dauerhaftes Primärmodell konfiguriert werden.
Für ATHENA gelten dabei dieselben Architekturregeln wie für jedes andere Primärmodell.
Das Modell bleibt austauschbar.
Der Wissensbestand bleibt modellunabhängig.

---

## Ein Primärmodell für wissensbildende Aufgaben
Das jeweils aktive Primärmodell übernimmt sämtliche inhaltlich interpretierenden KI-Aufgaben.
Hierzu gehören insbesondere:
- Benutzerkommunikation
- Analyse
- Zusammenfassung
- Wissensextraktion
- Kategorisierung
- Concept Notes
- Beziehungen
- Projektzuordnung
- Bewertung von Widersprüchen
- Neuinterpretation von Quellen
Dadurch bleibt die inhaltliche Verarbeitung konsistent.

---

## Infrastrukturmodelle bleiben zulässig
Es ist weder notwendig noch sinnvoll, sämtliche technischen Aufgaben vom Primärmodell ausführen zu lassen.
Infrastrukturmodelle können weiterhin verwendet werden für:
- Embeddings
- OCR
- Speech-to-Text
- Text-to-Speech
- Bildvorverarbeitung
- technische Klassifikation
- Formatkonvertierung
Diese Modelle dürfen auch andere Modellfamilien oder andere Trainingscharakteristika besitzen.
Entscheidend ist ihre Rolle.

---

## Semantische Firewall
Zwischen Primärmodell und Infrastrukturmodellen gilt eine verbindliche semantische Grenze.
Infrastrukturmodelle dürfen Inhalte:
- transportieren,
- indexieren,
- transkribieren,
- technisch klassifizieren,
- konvertieren.
Sie dürfen Inhalte nicht:
- umformulieren,
- abschwächen,
- moralisieren,
- zensieren,
- inhaltlich korrigieren,
- durch eine eigene Zusammenfassung ersetzen,
- aufgrund des Themas verwerfen.

---

## Beispiel
Das Primärmodell erzeugt eine Wissenseinheit.
```text
aktives Primärmodell

↓

kanonischer Text

↓

Embedding-Modell

↓

Vektor
```
Das Embedding-Modell erzeugt lediglich eine mathematische Repräsentation für die Suche.
Der ursprüngliche Text bleibt unverändert.

---

## NSFW- und andere sensible Inhalte
ATHENA behandelt NSFW-Inhalte technisch nach denselben Grundprinzipien wie andere zulässige Inhalte des persönlichen Wissensbestands.
Ein Infrastrukturmodell darf einen bereits vom Primärmodell erzeugten Inhalt nicht deshalb verändern, weil dieser beispielsweise:
- sexuell explizit,
- kontrovers,
- politisch,
- gewaltdarstellend,
- ungewöhnlich,
- philosophisch,
- religiös,
- gesellschaftlich umstritten
ist.
Die Aufgabe der Infrastruktur besteht nicht darin, den Wissensbestand inhaltlich neu zu bewerten.

---

## Inhaltsneutralität bedeutet nicht Vertrauensneutralität
ATHENA darf eine Information selbstverständlich weiterhin als:
- unbelegt,
- widersprochen,
- unsicher,
- fiktional,
- persönliche Meinung,
- externe Behauptung
klassifizieren.
Das ist keine Inhaltszensur.
Es ist Wissensorganisation.
ATHENA unterscheidet deshalb strikt zwischen:
Inhalt bewahren
und
epistemischen Status bestimmen.

---

## Originaltreue
Ein gespeicherter Originalinhalt bleibt während seiner Aufbewahrung unverändert; Verarbeitung überschreibt ihn niemals.
Auch das Primärmodell darf das Original nicht überschreiben.
Interpretationen werden separat gespeichert.
Damit existieren mindestens zwei getrennte Ebenen:
```text
Original
↓
Interpretation
```
Optional können später weitere Interpretationen hinzukommen.

---

## Kein stilles Umschreiben
Kein nachgelagerter Verarbeitungsschritt darf einen bereits erzeugten kanonischen Inhalt stillschweigend ersetzen.
Falls eine Transformation erforderlich ist, entsteht eine neue abgeleitete Darstellung.
Die ursprüngliche Darstellung bleibt erhalten.

---

## Refusal-Isolation
Die Verweigerung eines einzelnen Modells darf nicht auf andere Systemkomponenten übertragen werden.
Beispiel:
```text
OCR erfolgreich

↓

Primärmodell verweigert Interpretation

↓

Original + OCR-Text bleiben gespeichert

↓

Interpretationsjob erhält Status "nicht verarbeitet"
```
ATHENA löscht den Inhalt nicht.

---

## Infrastruktur-Refusal
Verweigert ein Infrastrukturmodell einen technischen Verarbeitungsschritt, gilt dasselbe Prinzip.
Beispielsweise:
```text
Bild

↓

Bildanalysemodell verweigert

↓

Originalbild bleibt erhalten

↓

anderes kompatibles Modell kann später verwendet werden
```
Ein Refusal ist ein Komponentenfehler oder eine Komponentenbegrenzung.
Nicht eine Eigenschaft des Wissens.

---

## Capability Routing
ATHENA darf für technische Aufgaben unterschiedliche Modelle verwenden.
Dabei entscheidet der Core anhand der benötigten Fähigkeit.
Beispiel:
```text
Audio
  ↓
Speech-to-Text

Bild
  ↓
OCR

Wissensinterpretation
  ↓
Primärmodell

Suche
  ↓
Embedding-Modell
```
Die Rollen bleiben strikt getrennt.

---

## Modellprofile
ATHENA darf für Modelle technische Profile verwalten.
Ein Profil kann beispielsweise beschreiben:
- unterstützte Aufgaben
- Kontextgröße
- VRAM-Bedarf
- Geschwindigkeit
- Quantisierung
- bekannte Einschränkungen
- Kompatibilität
Dadurch kann ATHENA geeignete Modelle auswählen, ohne ihre Rollen zu vermischen.

---

## Austausch problematischer Hilfsmodelle
Falls ein Infrastrukturmodell bestimmte Inhalte technisch nicht zuverlässig verarbeitet, soll dieses Modell austauschbar sein.
Der Benutzer muss dafür weder den Wissensbestand ändern noch sein Primärmodell ersetzen.
Beispiel:
```text
Embedding-Modell A ungeeignet

↓

Embedding-Modell B auswählen

↓

Embeddings neu erzeugen
```
Der kanonische Text bleibt identisch.

---

## Keine Moderationskette
ATHENA besitzt keine zusätzliche Modellkette, deren Aufgabe darin besteht, Antworten des Primärmodells nachträglich inhaltlich umzuschreiben.
Insbesondere soll kein zweites Sprachmodell standardmäßig zwischen Primärmodell und Benutzer geschaltet werden, um dessen Antworten erneut zu interpretieren.
Die Antwort des aktiven Primärmodells bleibt dessen Antwort.

---

## Keine semantische Abhängigkeit von Hilfsmodellen
Ein Infrastrukturmodell darf niemals zur einzigen Quelle einer semantischen Information werden, wenn diese für das langfristige Wissen relevant ist.
Beispielsweise darf ein technischer Klassifikator nicht allein entscheiden:
Diese Quelle ist irrelevant und kann gelöscht werden.
Eine solche Entscheidung gehört in den Verantwortungsbereich des Primärmodells beziehungsweise des Benutzers.

---

## Modellwechsel und Inhaltskontinuität
Wird später ein anderes Primärmodell eingesetzt, bleiben sämtliche bisherigen Inhalte erhalten.
Das neue Modell darf vorhandenes Wissen lesen, soweit der Benutzer und die Sicherheitsregeln dies erlauben.
Es darf jedoch ältere Inhalte nicht allein aufgrund eigener Modellpräferenzen automatisch umschreiben oder entfernen.

---

## Neuinterpretation
Falls ein neues Primärmodell bestimmte ältere Inhalte anders interpretiert, wird dies als neue Interpretation gespeichert.
Beispiel:
```text
Originalquelle
      │
      ├── Interpretation Modell A
      │
      └── Interpretation Modell B
```
Dadurch bleibt sichtbar, wie unterschiedliche Modellgenerationen denselben Inhalt bewertet haben.

---

## Modellbedingte Einschränkungen
ATHENA soll bekannte Einschränkungen eines Modells soweit möglich transparent machen.
Beispielsweise:
- bestimmte Formate nicht unterstützt,
- Kontext zu klein,
- wiederholte Refusals bei bestimmten Verarbeitungstypen,
- technische Inkompatibilität.
Diese Informationen helfen bei der Modellauswahl.
Sie verändern jedoch nicht den Wissensbestand.

---

## Benutzerhoheit über das Primärmodell
Der Benutzer entscheidet, welches kompatible Modell ATHENAs Primärmodell ist.
ATHENA darf Empfehlungen geben.
Sie darf das Primärmodell jedoch nicht heimlich aufgrund des Inhalts einer Anfrage wechseln.

---

## Automatischer Modellwechsel
Ein automatischer Wechsel des Primärmodells ist nur zulässig, wenn der Benutzer eine entsprechende Funktion ausdrücklich aktiviert hat.
Auch dann muss der Wechsel sichtbar und auditierbar sein.
Für wissensbildende Prozesse muss eindeutig gespeichert werden, welches Modell tatsächlich verwendet wurde.

---

## Lokale Modellhoheit
ATHENA ist darauf ausgelegt, das Primärmodell lokal betreiben zu können.
Der langfristige Wissensbestand darf nicht davon abhängig werden, dass ein bestimmter externer KI-Anbieter verfügbar bleibt.
Cloud-Modelle können zukünftig optional unterstützt werden.
Sie dürfen jedoch nicht zur Voraussetzung für den grundlegenden Betrieb werden.

---

## Zukunftssicherheit
Die Begriffe:
- Heretic-Modell
- unzensiertes Modell
- lokales Modell
- bestimmte Modellfamilie
beschreiben keine unveränderlichen Architekturkomponenten.
Entscheidend ist das zugrunde liegende Prinzip:
Der Benutzer kontrolliert die inhaltlich interpretierende Modellinstanz.
Damit bleibt ATHENA unabhängig von zukünftigen Modellgenerationen und deren jeweiligen Trainings- oder Moderationscharakteristika.

---

## Ziel
ATHENA soll unterschiedliche Modelle dort einsetzen können, wo sie technisch sinnvoll sind, ohne dass dadurch mehrere konkurrierende Instanzen über den Inhalt des Wissens entscheiden.
Das Primärmodell bleibt die zentrale automatisierte semantische KI-Instanz. Die höchste semantische Autorität verbleibt beim Benutzer.
Hilfsmodelle bleiben Werkzeuge.

---

## Leitregel
Ein Primärmodell interpretiert. Infrastrukturmodelle unterstützen. Kein Hilfsmodell darf den kanonischen Inhalt eigenmächtig neu schreiben.

---

## Abschluss des Kapitels
Die Trennung zwischen semantischer Interpretation und technischer Verarbeitung stellt sicher, dass ATHENA gleichzeitig leistungsfähig, modular und inhaltsneutral bleibt.
Das aktive Primärmodell kann die vollständige inhaltliche Verarbeitung übernehmen, während spezialisierte Hilfsmodelle weiterhin technische Aufgaben erledigen.
Damit bleibt die inhaltliche Konsistenz des Systems erhalten, ohne auf die Vorteile spezialisierter Modelle verzichten zu müssen.
