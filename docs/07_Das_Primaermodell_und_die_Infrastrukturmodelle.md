# Kapitel 7 – Primärmodell und Infrastrukturmodelle

---

## 1. Zweck dieses Kapitels

Dieses Kapitel definiert die Rollen, Grenzen und Verantwortlichkeiten der in ATHENA verwendeten KI-Modelle.

ATHENA unterscheidet strikt zwischen:

- aktivem Primärmodell
- Infrastrukturmodellen
- Benutzer
- technischen Algorithmen
- externen Quellen

Diese Trennung ist notwendig, damit ATHENA langfristig konsistent, nachvollziehbar und modellunabhängig bleibt.

---

## 2. Grundprinzip

ATHENA besitzt genau **ein aktives Primärmodell**.

Dieses Modell ist die einzige KI-Komponente mit semantischer Entscheidungsbefugnis über den kanonischen Wissensbestand.

Dabei gilt:

> **Nur der Benutzer und das aktive Primärmodell dürfen semantische Änderungen am kanonischen Wissen veranlassen.**

Der Benutzer besitzt die höchste Autorität.

Infrastrukturmodelle dürfen keine eigenständigen semantischen Wissensentscheidungen treffen.

---

## 3. Das Primärmodell ist nicht ATHENA

ATHENA darf nicht mit dem aktuell verwendeten Sprachmodell gleichgesetzt werden.

```text
ATHENA
≠
Primärmodell
```

ATHENA besteht aus:

- Core
- Wissenssystem
- Roharchiv
- Suche
- Sicherheitsregeln
- Provenienz
- Scheduler
- Benutzeroberflächen
- weiteren Systemkomponenten

Das Primärmodell ist eine austauschbare semantische Verarbeitungskomponente innerhalb dieser Architektur.

---

## 4. Das Primärmodell besitzt kein dauerhaftes Gedächtnis

Das Primärmodell speichert ATHENAs Wissen nicht dauerhaft in seinem Kontextfenster.

Langfristiges Wissen befindet sich außerhalb des Modells.

Der Ablauf lautet grundsätzlich:

```text
ATHENA Wissenssystem
↓
relevanter Kontext
↓
Primärmodell
↓
Antwort oder Interpretation
```

Nach Ende eines Modellaufrufs bleibt das langfristige Wissen im ATHENA-System erhalten.

---

## 5. Verantwortungsbereich des Primärmodells

Das aktive Primärmodell darf im Rahmen der Benutzerregeln semantische Aufgaben übernehmen.

Hierzu gehören insbesondere:

- Verstehen von Benutzeranfragen
- Analyse von Quellen
- Wissensextraktion
- Zusammenfassungen
- Relationserkennung
- Concept Notes
- Projektzuordnung
- Interpretation von Widersprüchen
- Bewertung von Relevanz
- semantische Klassifikation
- Formulierung von Antworten
- Neuinterpretation vorhandener Quellen

---

## 6. Benutzer als semantische Autorität

Der Benutzer darf kanonisches Wissen direkt:

- erstellen
- korrigieren
- ergänzen
- bearbeiten
- zusammenführen
- archivieren
- löschen

Eine manuelle Benutzeränderung ist ein regulärer Wissensvorgang.

Sie muss über dieselben Mechanismen für:

- Provenienz
- Versionierung
- Audit

nachvollziehbar bleiben.

---

## 7. Vorrang ausdrücklicher Benutzerentscheidungen

Eine explizite Benutzerkorrektur darf nicht durch eine spätere Modellinterpretation stillschweigend überschrieben werden.

Beispiel:

```text
Primärmodell:
Aussage X

↓

Benutzer:
Aussage X ist falsch. Korrekt ist Y.

↓

ATHENA:
Y als Benutzerkorrektur speichern
+
frühere Interpretation historisch erhalten
```

Eine spätere Neubewertung ist möglich.

Sie muss jedoch transparent erfolgen und neue Evidenz oder eine bewusste Reinterpretation berücksichtigen.

---

## 8. Kein direkter Schreibzugriff des Modells

Das Primärmodell schreibt nicht direkt in die kanonische Datenbank oder in Wissensdateien.

Der technische Ablauf lautet:

```text
Primärmodell
↓
strukturierter Vorschlag
↓
ATHENA Core
↓
Validierung
↓
Provenienz
↓
Versionierung
↓
kanonischer Speicher
```

Dadurch bleibt der Core die Kontrollinstanz.

---

## 9. Ein aktives Primärmodell

ATHENA verwendet zu einem Zeitpunkt genau ein aktives Primärmodell für wissensbildende semantische Entscheidungen.

Dadurch werden konkurrierende semantische Entscheidungsinstanzen vermieden.

Mehrere Modelle dürfen technisch installiert sein.

Es bleibt jedoch eindeutig definiert, welches Modell aktuell die Rolle des Primärmodells besitzt.

---

## 10. Modellwechsel

Der Benutzer kann das aktive Primärmodell wechseln.

Ein Modellwechsel verändert bestehendes Wissen nicht automatisch.

Er verändert insbesondere nicht:

- Originalquellen
- bestehende Wissenseinheiten
- Provenienz
- Projekte
- Beziehungen
- Audit-Historie
- persönliche Benutzeränderungen

Neue wissensbildende Operationen erhalten die Signatur des neu aktiven Primärmodells.

---

## 11. Keine automatische globale Neuinterpretation

Der Wechsel auf ein neueres oder leistungsfähigeres Modell löst niemals automatisch eine globale Neuinterpretation des gesamten Wissensbestands aus.

Eine Reinterpretation erfolgt:

- gezielt
- nachvollziehbar
- versioniert
- bewusst ausgelöst

---

## 12. Mehrere Interpretationen

Eine Originalquelle kann im Laufe der Zeit mehrere Interpretationen besitzen.

Beispiel:

```text
Originalquelle
│
├── Interpretation Modell A
│
├── Interpretation Modell B
│
└── Benutzerkorrektur
```

Die Interpretationen bleiben voneinander unterscheidbar.

Das Original bleibt unverändert.

---

## 13. Modellsignatur

Jede semantische Modelloperation, die langfristiges Wissen beeinflusst, erhält eine Modellsignatur.

Mindestens soweit verfügbar:

- Provider
- Modellname
- Modell-Identifier
- Modellversion
- Quantisierung
- relevante Generationseinstellungen
- Zeitpunkt

Fehlende Metadaten werden als unbekannt gespeichert.

ATHENA erfindet keine Modellinformationen.

---

## 14. Modellunabhängigkeit

ATHENA darf nicht dauerhaft von einer bestimmten Modellfamilie abhängig werden.

Heute kann ein bestimmtes lokales Modell verwendet werden.

Später kann ein anderes kompatibles Modell dieselbe Rolle übernehmen.

Die Architektur bleibt bestehen.

---

## 15. Lokale Modellhoheit

ATHENA ist so konzipiert, dass das Primärmodell lokal betrieben werden kann.

Der grundlegende Wissenszugriff darf nicht von der Verfügbarkeit eines externen KI-Anbieters abhängen.

Optionale externe Modelle können später unterstützt werden.

Sie dürfen jedoch nicht zum notwendigen Bestandteil des ATHENA-Gedächtnisses werden.

---

## 16. Infrastrukturmodelle

Neben dem Primärmodell darf ATHENA spezialisierte Infrastrukturmodelle verwenden.

Beispiele:

- OCR
- Embeddings
- Speech-to-Text
- Text-to-Speech
- technische Bildanalyse
- Dateivorverarbeitung

Diese Modelle erfüllen technische Aufgaben.

---

## 17. Keine semantische Autorität für Infrastrukturmodelle

Für Infrastrukturmodelle gilt:

> **Infrastrukturmodelle dürfen keine eigenständigen semantischen Wissensentscheidungen treffen.**

Sie dürfen beispielsweise:

```text
Bild
↓
OCR
↓
Text
```

oder:

```text
Text
↓
Embedding-Modell
↓
Vektor
```

erzeugen.

Sie dürfen jedoch nicht eigenständig entscheiden:

- welche Aussage wahr ist
- welche Information gelöscht wird
- welche Information dauerhaft relevant ist
- welche Benutzerkorrektur ignoriert wird
- welche Concept Note kanonisch sein soll

---

## 18. Semantische Firewall

Zwischen Infrastrukturmodellen und kanonischem Wissen existiert eine klare semantische Grenze.

Ein Infrastrukturmodell darf Daten:

- extrahieren
- transkribieren
- indexieren
- technisch klassifizieren
- konvertieren

Es darf kanonische Inhalte nicht eigenmächtig:

- umschreiben
- abschwächen
- korrigieren
- löschen
- neu interpretieren

---

## 19. Technische Klassifikatoren

Auch technische Klassifikatoren besitzen keine autonome semantische Autorität.

Ein Klassifikator kann beispielsweise erkennen:

```text
Dateityp: PDF
```

oder:

```text
Sprache: Deutsch
```

Er darf jedoch nicht allein entscheiden:

```text
Diese Quelle ist unwichtig und kann gelöscht werden.
```

Eine solche Entscheidung gehört in den Verantwortungsbereich des Benutzers beziehungsweise des Primärmodells innerhalb der ATHENA-Regeln.

---

## 20. Infrastrukturmodell-Ausfall

Der Ausfall eines Infrastrukturmodells darf keinen Datenverlust verursachen.

Beispiel OCR:

```text
Dokument
↓
OCR fehlgeschlagen
↓
Original speichern
↓
Verarbeitung vormerken
↓
später erneut versuchen
```

---

## 21. Embedding-Ausfall

Fällt das Embedding-Modell aus:

- bleibt das kanonische Wissen erhalten
- bleibt Volltextsuche möglich
- bleiben direkte Beziehungen verfügbar
- können Embeddings später neu erzeugt werden

Embeddings sind abgeleitete Daten.

---

## 22. Speech-to-Text-Ausfall

Kann eine Audiodatei nicht transkribiert werden:

- bleibt die Originaldatei erhalten
- wird der fehlgeschlagene Verarbeitungsschritt dokumentiert
- kann später ein anderes kompatibles Infrastrukturmodell verwendet werden

---

## 23. Refusal-Failsafe des Primärmodells

Kann oder will das Primärmodell einen Inhalt nicht interpretieren, darf daraus kein Datenverlust entstehen.

Der Ablauf lautet:

```text
Originalquelle
↓
Primärmodell verweigert oder scheitert
↓
Original bleibt gespeichert
↓
Status dokumentieren
↓
spätere Reinterpretation ermöglichen
```

Ein Refusal ist kein Löschsignal.

---

## 24. Refusal-Failsafe von Infrastrukturmodellen

Dasselbe gilt für Infrastrukturmodelle.

Wenn ein technisches Hilfsmodell eine Quelle nicht verarbeitet, bleibt diese erhalten.

ATHENA kann später:

- dasselbe Modell erneut versuchen
- ein anderes Modell verwenden
- den Verarbeitungsschritt überspringen

---

## 25. Keine Moderationskette

ATHENA verwendet standardmäßig kein zweites Sprachmodell, dessen Aufgabe darin besteht, die Antwort des Primärmodells nachträglich semantisch umzuschreiben.

Die Antwort des aktiven Primärmodells bleibt dessen Antwort.

Technische Nachbearbeitung darf erfolgen, solange sie die Semantik nicht eigenmächtig verändert.

---

## 26. Benutzerkontrollierte Modellwahl

Der Benutzer entscheidet, welches kompatible Modell die Rolle des Primärmodells übernimmt.

ATHENA darf:

- Modelle erkennen
- Empfehlungen anzeigen
- technische Kompatibilität prüfen

ATHENA darf jedoch nicht heimlich aufgrund des Inhalts einer Anfrage auf ein anderes Primärmodell wechseln.

---

## 27. Automatischer Modellwechsel

Ein automatischer Wechsel ist nur zulässig, wenn der Benutzer diese Funktion ausdrücklich aktiviert.

Jeder automatische Wechsel muss:

- sichtbar
- protokolliert
- der jeweiligen Wissensoperation zugeordnet

sein.

---

## 28. Modellprofile

ATHENA darf technische Modellprofile verwalten.

Ein Modellprofil kann enthalten:

- Provider
- Kontextgröße
- VRAM-Bedarf
- Quantisierung
- unterstützte Fähigkeiten
- Performanceinformationen
- bekannte technische Einschränkungen

Modellprofile sind Konfiguration.

Sie sind kein kanonisches Wissen über den Benutzer.

---

## 29. Laden und Entladen

ATHENA darf Modelle automatisiert laden oder entladen, wenn die entsprechenden Ressourcenregeln dies erlauben.

Manuelle Benutzerentscheidungen besitzen Vorrang.

Ein Modell, das der Benutzer bewusst geladen hält, darf nicht ohne definierte Regel entladen werden.

---

## 30. Hintergrundverarbeitung

Hintergrundjobs dürfen das Primärmodell verwenden, wenn:

- die Aufgabe dies tatsächlich benötigt
- ausreichend Ressourcen vorhanden sind
- keine höher priorisierte Benutzerinteraktion beeinträchtigt wird

Die Modellnutzung bleibt über Job- und Modellsignaturen nachvollziehbar.

---

## 31. Modellwechsel während langer Jobs

Ein langlaufender Job darf nicht unbemerkt teilweise mit unterschiedlichen Primärmodellen verarbeitet werden.

ATHENA muss Modell- und Verarbeitungskonfigurationen für solche Jobs festhalten.

Wenn sich das aktive Modell während einer Unterbrechung ändert, muss ATHENA dies erkennen.

Die technische Behandlung wird in der Beta-Spezifikation konkretisiert.

---

## 32. Benutzerinhalte und Modellgrenzen

Die Grenzen eines bestimmten Modells sind Eigenschaften dieses Modells.

Sie definieren nicht automatisch die Grenzen des ATHENA-Wissenssystems.

Kann ein Modell eine gespeicherte Quelle nicht bearbeiten, bleibt die Quelle trotzdem Bestandteil des Systems.

---

## 33. Inhaltsneutralität der Infrastruktur

Infrastrukturmodelle dürfen einen Inhalt nicht allein aufgrund seines Themas schlechter archivieren oder technisch verwerfen.

Dies gilt beispielsweise für:

- politische Inhalte
- kontroverse Inhalte
- NSFW-Inhalte
- fiktionale Inhalte
- wissenschaftliche Hypothesen
- ungewöhnliche persönliche Notizen

Die jeweilige rechtliche und technische Zulässigkeit bleibt davon unberührt.

---

## 34. Epistemische Bewertung bleibt zulässig

Inhaltsneutralität bedeutet nicht, dass jede Aussage denselben epistemischen Status erhält.

Das Primärmodell darf innerhalb des Wissenssystems unterscheiden zwischen:

- belegt
- unbelegt
- widersprüchlich
- fiktional
- Meinung
- Interpretation
- persönliche Aussage

Diese Bewertung ist Wissensorganisation, nicht technische Zensur.

---

## 35. Benutzerkorrektur versus externe Evidenz

Eine Benutzerkorrektur besitzt höchste Kontrollautorität über den eigenen Wissensbestand.

Bei Aussagen über externe Sachverhalte darf ATHENA dennoch festhalten, dass externe Quellen eine andere Aussage stützen.

Beispiel:

```text
Benutzer:
Ich halte Aussage X für falsch.

Quelle A:
behauptet X.

Quelle B:
bestätigt X.
```

ATHENA darf diese Ebenen getrennt speichern, anstatt eine davon zu löschen.

---

## 36. Primärmodell als semantischer Prozessor

Das Primärmodell soll nicht als alleinige Wahrheitsinstanz verstanden werden.

Es analysiert:

- Quellen
- Benutzerinformationen
- bestehendes Wissen
- Widersprüche
- Kontext

und erzeugt daraus strukturierte semantische Vorschläge.

Die kanonische Persistierung bleibt unter Kontrolle des ATHENA Core.

---

## 37. Zukunftssicherheit

Neue Modellgenerationen dürfen integriert werden, ohne die Architektur zu verändern.

Dies gilt unabhängig von:

- Modellgröße
- Quantisierung
- Modellarchitektur
- Kontextlänge
- Backend
- Hardware

Die Rolle bleibt dieselbe:

```text
Primärmodell
=
aktive semantische KI-Instanz
```

---

## 38. Autoritätshierarchie

Innerhalb des ATHENA-Systems gilt für semantische Kontrollentscheidungen grundsätzlich:

```text
Benutzer
↓
ATHENA Core und verbindliche Benutzerregeln
↓
aktives Primärmodell
↓
Infrastrukturmodelle und technische Algorithmen
↓
externe Quellen
```

Diese Hierarchie beschreibt die Kontrollautorität innerhalb ATHENAs.

Sie bedeutet nicht, dass eine persönliche Aussage automatisch faktisch wahrer ist als hochwertige externe Evidenz.

---

## 39. Leitregel

> **Der Benutzer besitzt die höchste Autorität über ATHENAs Wissensbestand. Das aktive Primärmodell ist die einzige KI-Komponente mit semantischer Entscheidungsbefugnis. Infrastrukturmodelle unterstützen technisch, dürfen aber keine eigenständigen semantischen Wissensentscheidungen treffen.**

---

## 40. Abschluss des Kapitels

Das Primärmodell ist ATHENAs zentrale semantische Verarbeitungskomponente.

Es ist jedoch weder das Gedächtnis noch die Identität von ATHENA.

Der Benutzer bleibt die höchste Autorität.

Der ATHENA Core kontrolliert die Persistierung.

Infrastrukturmodelle bleiben technische Werkzeuge.

Diese Trennung ermöglicht es, Modelle langfristig auszutauschen, ohne dass Wissen, Benutzerkontrolle oder Systemidentität verloren gehen.
