# Kapitel 23 – Wissensqualität, Konsistenz und Selbstwartung

---

## Einleitung
Ein Wissensbestand wird nicht automatisch besser, nur weil er größer wird.
Nach vielen Jahren können sich:
- Duplikate,
- veraltete Informationen,
- widersprüchliche Aussagen,
- schwache Verknüpfungen,
- fehlerhafte Interpretationen
ansammeln.
ATHENA benötigt deshalb Mechanismen zur kontinuierlichen Qualitätssicherung.
Diese dürfen jedoch niemals dazu führen, dass historisches Wissen unkontrolliert verändert oder gelöscht wird.

---

## Grundprinzip
ATHENA darf Wissen verbessern. ATHENA darf Geschichte nicht umschreiben.
Qualitätsverbesserung bedeutet:
- ergänzen,
- verknüpfen,
- kennzeichnen,
- neu interpretieren.
Nicht:
- stillschweigend überschreiben,
- automatisch löschen,
- ursprüngliche Aussagen verändern.

---

## Wissensqualität
Die Qualität einer Wissenseinheit wird anhand mehrerer Faktoren beurteilt.
Dazu gehören:
- Qualität der Quelle,
- Anzahl unabhängiger Quellen,
- Aktualität,
- Konsistenz,
- Provenienz,
- Vertrauensniveau,
- Relevanz.
Die genaue technische Gewichtung wird später definiert.

---

## Qualitätsstatus
Wissenseinheiten können unterschiedliche Zustände besitzen.
Beispielsweise:
- bestätigt,
- wahrscheinlich,
- unsicher,
- widersprochen,
- veraltet,
- historisch,
- persönliche Aussage,
- Interpretation,
- Fiktion.
Der Status gehört zur Wissenseinheit.
Er verändert nicht die Originalquelle.

---

## Fakten und Interpretationen
ATHENA trennt dauerhaft:
```text
Originalquelle

↓

extrahierte Aussage

↓

Interpretation

↓

Vertrauensbewertung
```
Diese Ebenen dürfen nicht miteinander verschmelzen.

---

## Duplikate
ATHENA erkennt möglichst automatisch, wenn mehrere Wissenseinheiten denselben Sachverhalt beschreiben.
Sie darf solche Einheiten logisch zusammenführen.
Die ursprünglichen Quellen und Provenienzketten bleiben jedoch erhalten.

---

## Kein aggressives Merging
Ähnlichkeit bedeutet nicht automatisch Identität.
ATHENA darf zwei Wissenseinheiten nicht allein deshalb zusammenführen, weil ihre Embeddings ähnlich sind.
Semantische Zusammenführung benötigt eine inhaltliche Entscheidung durch den Benutzer oder – bei automatisierter Verarbeitung – durch das aktive Primärmodell.

---

## Widersprüche
Widersprüchliche Informationen werden nicht automatisch aufgelöst.
Beispiel:
Quelle A
"X gilt."

Quelle B
"X gilt nicht."
ATHENA speichert:
- beide Aussagen,
- beide Quellen,
- zeitlichen Kontext,
- Vertrauensniveau,
- bekannte Erklärungen für den Widerspruch.

---

## Neue Erkenntnisse
Spätere Informationen können frühere Aussagen widerlegen.
ATHENA markiert die ältere Information entsprechend.
Sie wird jedoch nicht gelöscht.
Dadurch bleibt nachvollziehbar, wie sich Wissen entwickelt hat.

---

## Veraltetes Wissen
Eine Information kann korrekt gewesen sein und später veralten.
Beispiel:
Softwareversion X unterstützt Funktion Y.
Später:
Softwareversion Z unterstützt Funktion Y nicht mehr.
Beide Aussagen können historisch korrekt sein.
ATHENA berücksichtigt deshalb immer den Zeitbezug.

---

## Zeitliche Gültigkeit
Wissenseinheiten können, sofern relevant, einen Gültigkeitszeitraum besitzen.
Beispielsweise:
gültig ab

gültig bis

Stand der Information
Dadurch können aktuelle und historische Fragen unterschiedlich beantwortet werden.

---

## Selbstwartung
ATHENA darf regelmäßig Hintergrundaufgaben zur Wissensqualität durchführen.
Dazu gehören beispielsweise:
- Duplikaterkennung,
- Prüfung fehlender Verknüpfungen,
- Erkennung veralteter Informationen,
- Prüfung beschädigter Referenzen,
- Qualitätsprüfung von Metadaten,
- Erkennung unvollständiger Provenienz.
Diese Prozesse laufen bevorzugt im Hintergrund.

---

## Selbstwartung verändert keine Originale
Keine Wartungsaufgabe darf:
- Originalquellen verändern,
- historische Aussagen überschreiben,
- Wissenseinheiten endgültig löschen.
Automatische Wartung erzeugt ausschließlich kontrollierte Änderungen an abgeleiteten Strukturen oder neue Bewertungen.

---

## Wartungsvorschläge
Bei weitreichenden Änderungen kann ATHENA zunächst einen Vorschlag erzeugen.
Beispiel:
ATHENA hat 14 vermutlich doppelte Wissenseinheiten erkannt.

12 können sicher logisch zusammengeführt werden.

2 sind nicht eindeutig.

[Details anzeigen]
Der Grad notwendiger Benutzerbestätigung wird später technisch festgelegt.

---

## Automatische sichere Wartung
Rein technische, rekonstruierbare Aufgaben dürfen automatisch erfolgen.
Beispiele:
- Suchindex neu aufbauen,
- Cache bereinigen,
- Embeddings neu erzeugen,
- beschädigte Vorschaudaten neu erstellen.
Diese Vorgänge verändern kein kanonisches Wissen.

---

## Unsichere Wartung
Semantische Veränderungen benötigen höhere Vorsicht.
Beispiele:
- zwei Wissenseinheiten zusammenführen,
- Aussage als widerlegt markieren,
- Projektzuordnung verändern,
- Concept Note wesentlich umstrukturieren.
Solche Änderungen müssen auditierbar und reversibel sein.

---

## Reinterpretation
Mit neuen Primärmodellen kann ATHENA ältere Quellen erneut analysieren.
Dies kann beispielsweise sinnvoll sein, wenn:
- ein neues Modell deutlich leistungsfähiger ist,
- alte Extraktionen unvollständig waren,
- neue Fragestellungen entstanden sind.
Eine Neuinterpretation ist jedoch keine stille Migration.

---

## Mehrere Interpretationen
ATHENA kann mehrere Interpretationen derselben Quelle erhalten.
Beispiel:
```text
Quelle

├── Interpretation 2026
│
├── Interpretation 2029
│
└── Interpretation 2034
```
Dadurch bleibt sichtbar, wie sich die Modellleistung und Wissenseinordnung entwickelt haben.

---

## Reinterpretationskampagnen
Der Benutzer kann gezielt eine Neuinterpretation bestimmter Bereiche anstoßen.
Beispielsweise:
- Projekt ATHENA neu analysieren,
- wissenschaftliche Sammlung neu auswerten,
- alte Chats mit neuem Modell erneut prüfen.
ATHENA verarbeitet solche Aufgaben über die persistente Queue.

---

## Keine automatische globale Neuinterpretation
Ein Modellupdate löst niemals automatisch eine vollständige Neuinterpretation des gesamten Wissensbestands aus.
Bei zehn oder mehr Jahren Daten wäre dies:
- ressourcenintensiv,
- unnötig,
- potenziell störend.
Neuinterpretation erfolgt gezielt.

---

## Wissensgesundheit
ATHENA kann einen allgemeinen Zustand des Wissenssystems anzeigen.
Beispielsweise:
Wissensbestand

Integrität: OK
Provenienz: 99,8 %
Suchindex: OK
Offene Widersprüche: 47
Unvollständig verarbeitete Quellen: 12
Warteschlange Reinterpretation: 3
Diese Anzeige dient der Orientierung.
Sie darf keine scheinbare wissenschaftliche Genauigkeit vortäuschen.

---

## Offene Fragen
ATHENA darf erkennen, wenn ein Wissensbereich offene Fragen enthält.
Diese können im Wissensgraphen explizit gespeichert werden.
Beispielsweise:
Thema X

Bekannt:
...

Unklar:
...

Widersprüchlich:
...

Noch zu recherchieren:
...
Dadurch wird nicht nur vorhandenes Wissen organisiert.
Auch Wissenslücken werden sichtbar.

---

## Wissenslücken
ATHENA darf Wissenslücken vorschlagen.
Es startet jedoch keine externe Recherche allein aufgrund einer erkannten Wissenslücke, sofern dies nicht durch eine ausdrücklich konfigurierte Hintergrundfunktion erlaubt wurde.
Die Internetregeln bleiben bestehen.

---

## Vertrauensänderungen
Das Vertrauensniveau einer Wissenseinheit kann sich verändern.
Beispiel:
```text
2026: unsicher

2027: mehrere unabhängige Bestätigungen
↓
hohes Vertrauen
```
Die Änderung wird historisiert.

---

## Benutzerkorrekturen
Benutzerkorrekturen besitzen besondere Bedeutung.
Sagt der Benutzer beispielsweise:
Das ist falsch.
darf ATHENA dies nicht ignorieren.
Die Korrektur wird dokumentiert und in die Wissensbewertung aufgenommen.
Bei extern überprüfbaren Sachverhalten bleibt dennoch die Trennung zwischen persönlicher Aussage und externen Quellen erhalten.

---

## Schutz vor Wissensdrift
Wiederholte Zusammenfassungen können Informationen mit der Zeit verändern.
ATHENA vermeidet deshalb Ketten wie:
```text
Original

↓

Zusammenfassung

↓

Zusammenfassung der Zusammenfassung

↓

Zusammenfassung der Zusammenfassung der Zusammenfassung
```
Stattdessen werden wichtige Neuinterpretationen möglichst wieder gegen:
- Originalquelle,
- atomare Wissenseinheiten
geprüft.

---

## Original-Rückbindung
Concept Notes und Zusammenfassungen behalten Verweise auf ihre zugrunde liegenden Wissenseinheiten und Quellen.
Dadurch kann ATHENA bei Unsicherheit jederzeit zum Original zurückkehren.

---

## Halluzinationsschutz
Eine vom Primärmodell erzeugte Aussage wird nicht allein deshalb zu einem bestätigten Fakt, weil sie überzeugend formuliert wurde.
ATHENA berücksichtigt:
- Quellen,
- Provenienz,
- Vertrauensniveau.
Fehlt eine Quelle, wird dies kenntlich gemacht.

---

## Fehlerhafte Wissensextraktion
Wird später festgestellt, dass das Primärmodell eine Quelle falsch interpretiert hat:
1. Original bleibt unverändert.
2. fehlerhafte Interpretation wird historisiert oder als fehlerhaft markiert.
3. korrigierte Interpretation wird ergänzt.
4. abhängige Concept Notes können aktualisiert werden.
5. Änderung wird auditierbar dokumentiert.

---

## Konsistenzprüfung
ATHENA darf regelmäßig prüfen:
- existieren verwaiste Beziehungen?
- fehlen Quellen?
- verweisen Einträge auf nicht mehr existierende Objekte?
- sind Zeitangaben widersprüchlich?
- fehlen notwendige Metadaten?
Technische Probleme werden soweit möglich automatisch repariert.

---

## Keine zentrale “Wahrheits-KI”
ATHENA besitzt kein separates Modell, das entscheidet, welche Aussage endgültig wahr ist.
Stattdessen entsteht Wissensqualität aus:
- Quellen,
- Provenienz,
- zeitlicher Entwicklung,
- Widersprüchen,
- Vertrauensbewertung,
- Benutzerkontext.
Das Primärmodell unterstützt diese Einordnung.
Es ersetzt nicht die Quellenlage.

---

## Performance der Wartung
Selbstwartung darf die aktive Nutzung nicht beeinträchtigen.
Aufwendige Aufgaben werden:
- priorisiert,
- in Teilaufgaben zerlegt,
- über die Queue verarbeitet,
- bei Ressourcenbedarf pausiert.

---

## Langfristige Skalierung
Mit wachsendem Wissensbestand wird nicht regelmäßig alles vollständig neu analysiert.
ATHENA arbeitet bevorzugt inkrementell.
Neue Informationen lösen nur dort Prüfungen aus, wo relevante Beziehungen bestehen.

---

## Ziel
Nach zehn oder zwanzig Jahren soll ATHENA nicht nur sehr viel wissen.
Der Wissensbestand soll weiterhin:
- nachvollziehbar,
- konsistent,
- wartbar,
- durchsuchbar,
- historisch verständlich
sein.

---

## Leitregel
Wissensqualität entsteht nicht durch Überschreiben, sondern durch Quellen, Kontext, Versionierung und nachvollziehbare Korrektur.

---

## Abschluss des Kapitels
ATHENA behandelt Wissensqualität als kontinuierlichen Prozess.
Neue Informationen können alte ergänzen, korrigieren oder widerlegen.
Die historische Entwicklung bleibt dabei erhalten.
Durch regelmäßige, kontrollierte Selbstwartung kann der Wissensbestand über Jahrzehnte wachsen, ohne seine Nachvollziehbarkeit oder innere Struktur zu verlieren.
