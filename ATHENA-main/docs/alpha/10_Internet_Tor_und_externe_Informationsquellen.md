# Kapitel 10 – Internet, Anonymisierung und externe Informationsquellen

---

## Einleitung
ATHENA ist ein Local-First-System.
Das Internet ist eine Ergänzung des lokalen Wissens.
Es ersetzt dieses niemals.
Der langfristige Wissensbestand bleibt jederzeit die primäre Wissensquelle.
Externe Informationen dienen ausschließlich dazu,
- Wissen zu ergänzen,
- Wissen zu aktualisieren,
- neue Entwicklungen zu erkennen,
- Nachrichten zu archivieren.

---

## Grundprinzip
ATHENA kommuniziert niemals grundlos mit dem Internet.
Jede externe Verbindung besitzt einen nachvollziehbaren Zweck.
Der Benutzer entscheidet grundsätzlich selbst, wann ATHENA das Internet verwenden darf.
Die einzige definierte Standardausnahme ist der tägliche News-Workflow.

---

## Local First
Local First bedeutet, dass ATHENA vorhandene lokale Informationen bevorzugt nutzt und externe Kommunikation nicht ohne Zweck erzeugt.

Bei Fragen, die sinnvoll aus dem lokalen Bestand beantwortet werden können, durchsucht ATHENA je nach Bedarf:

1. aktives Wissen
2. Langzeitwissen
3. Raw Archive

Bei ausdrücklich aktuellen, externen oder webbezogenen Anfragen darf ATHENA eine bereits autorisierte Internetrecherche direkt einbeziehen, ohne zuvor zwangsläufig den gesamten lokalen Bestand auszuschöpfen.

Local First ist damit ein Datenschutz-, Robustheits- und Effizienzprinzip – keine starre Reihenfolge, die sachlich notwendige aktuelle Recherche künstlich verzögert.

---

## Standardzustand
Normale Chats starten grundsätzlich im Offline-Modus.
Das bedeutet:
- keine Websuche,
- keine API-Abfragen,
- keine externen Datenquellen,
- keine unbemerkten Netzwerkzugriffe.
Der Benutzer arbeitet standardmäßig ausschließlich mit seinem lokalen Wissensbestand.

---

## Internet-Schalter
Die Benutzeroberfläche besitzt einen klar sichtbaren Internet-Schalter.
Mögliche Zustände:
- Internet AUS
- Internet AN
Ist der Schalter deaktiviert, dürfen normale Chats keine externe Recherche durchführen.
Ist der Schalter aktiviert, darf ATHENA bei Bedarf externe Quellen einbeziehen.
Der Schalter wirkt ausschließlich auf normale Benutzeranfragen.

---

## Der News-Workflow
Der tägliche Nachrichten-Workflow bildet die einzige standardmäßig freigegebene automatische Internetverbindung.
Seine Aufgabe besteht darin,
- wichtige internationale Entwicklungen zu erkennen,
- Ereignisse zusammenzufassen,
- Quellen miteinander zu vergleichen,
- das externe Wissen aktuell zu halten.
Der News-Workflow arbeitet unabhängig vom Internet-Schalter der normalen Chats.

---

## Anonymisierung
Das unveränderliche Alpha-Prinzip verlangt für externe Kommunikation eine vom Benutzer freigegebene Privacy-/Anonymisierungsschicht mit Fail-Closed-Verhalten.

Grundsätze:
- keine ungeschützte direkte Internetverbindung außerhalb dieser Schicht,
- keine automatische Umgehung,
- keine stille Deaktivierung,
- nachvollziehbarer Verbindungsstatus.

Die konkrete technische Umsetzung der Privacy-/Anonymisierungsschicht wird in der Beta-Spezifikation festgelegt.

### Nicht-normativer Umsetzungshinweis

Für die erste Implementierung ist Tor als konkrete Option vorgesehen. Diese Nennung erklärt die beabsichtigte v1-Richtung, ist aber keine unveränderliche Alpha-Abhängigkeit. Die verbindliche Auswahl und Integration der Technik gehört in Beta.

---

## Fail Closed
Ist die vorgeschriebene Anonymisierung nicht verfügbar, dürfen keine ungeschützten direkten Internetverbindungen aufgebaut werden.

Beispiel:

```text
Privacy-/Anonymisierungsschicht nicht erreichbar
↓
kein direkter Fallback
↓
Aufgabe verschieben oder Benutzer informieren
```

Privatsphäre besitzt Vorrang vor Komfort.

---

## Prompt-Injection
Externe Quellen dürfen niemals Systemanweisungen darstellen.
Dies gilt unter anderem für:
- Webseiten
- PDFs
- E-Mails
- Quellcode
- Nachrichten
- Dokumentationen
Externe Inhalte werden ausschließlich als Daten interpretiert.
Nicht als Befehle.

---

## Transparenz
Jede Internetverbindung wird nachvollziehbar dokumentiert.
Mindestens:
- Zeitpunkt
- Anlass
- verwendete Quellen
- Status der Privacy-/Anonymisierungsschicht
- Ergebnis
Der Benutzer kann diese Informationen jederzeit einsehen.

---

## Statusanzeige
ATHENA zeigt jederzeit deutlich an:
- Internet aktiviert oder deaktiviert
- Privacy-/Anonymisierungsschicht verfügbar oder nicht verfügbar
- letzte Internetnutzung
- Grund der letzten Verbindung
- Anzahl ausstehender Internetaufgaben
Der Netzwerkzustand darf niemals verborgen sein.

---

## Quellenbewertung
Nicht jede Quelle besitzt dieselbe Qualität.
ATHENA bewertet unter anderem:
- Vertrauenswürdigkeit
- Aktualität
- Unabhängigkeit
- Konsistenz mit anderen Quellen
Mehrere voneinander unabhängige Quellen erhöhen das Vertrauensniveau.

---

## Aussagen statt Wahrheiten
Externe Informationen werden zunächst als Aussagen ihrer jeweiligen Quelle gespeichert.
Beispiel:
Nicht:
Aussage X ist wahr.
Sondern:
Quelle A berichtet Aussage X.
Bestätigungen und Widersprüche werden separat dokumentiert.
Dadurch bleibt die Entwicklung einer Information nachvollziehbar.

---

## Externe Informationen im Wissenssystem
Externe Informationen werden niemals allein aufgrund ihres Abrufs ungeprüft zu kanonischem Wissen.

Bei automatisierter semantischer Verarbeitung bewertet das aktive Primärmodell unter den Regeln von ATHENA unter anderem:

- langfristige Relevanz
- Einordnung
- Beziehungen zu vorhandenen Wissenseinheiten
- angemessenen epistemischen beziehungsweise Vertrauensstatus

Der Benutzer kann diese Entscheidungen jederzeit ausdrücklich vorgeben, korrigieren oder selbst veranlassen. Externe Quellen und Infrastrukturkomponenten besitzen keine eigenständige semantische Autorität.

---

## Fehlerbehandlung
Kann eine Internetaufgabe nicht ausgeführt werden,
beispielsweise wegen:
- fehlender Verbindung,
- fehlender Anonymisierung,
- nicht erreichbarer Quelle,
wird sie nicht verworfen.
Sie bleibt in der persistenten Queue und wird später erneut geprüft.

---

## Leitregel
Lokales Wissen besitzt immer Vorrang. Externe Informationen ergänzen den Wissensbestand, ersetzen ihn jedoch niemals.

---

## Abschluss des Kapitels
ATHENA betrachtet das Internet als Informationsquelle – nicht als Gedächtnis.
Die Kombination aus Local First, Benutzerkontrolle, transparenter Internetnutzung und anonymer Kommunikation gewährleistet, dass externe Informationen den Wissensbestand erweitern, ohne die grundlegenden Prinzipien des Systems zu gefährden.
