# ATHENA Alpha v2.0 – Konsolidierungsänderungen

**Historischer Stand:** durch [Alpha v2.0.1](CHANGES_ALPHA_v2.0.1.md) als aktueller finaler Alpha-Stand ersetzt. Dieses Dokument bleibt als unverändertes Konsolidierungsprotokoll erhalten.

Dieses Dokument protokolliert die letzte Konsolidierung vor dem geplanten Freeze `alpha-v2.0-final`. Es ist kein Ersatz für die normativen Kapitel.

## Inhaltliche Konsolidierung

- Benutzer und aktives Primärmodell sind die einzigen Instanzen, die semantische Änderungen am kanonischen Wissen veranlassen dürfen; der Benutzer besitzt die höchste Autorität.
- Automatisierte semantische Wissensextraktion liegt beim aktiven Primärmodell; direkte Benutzererstellung und Benutzerkorrektur sind gleichwertig vorgesehene Wissensvorgänge.
- Infrastrukturmodelle dürfen technische Klassifikationen erzeugen, aber keine eigenständigen semantischen Wissensentscheidungen treffen.
- `ATHENA Persistent Data` trennt die autoritativen Domänen Knowledge, Personal Memory, Raw Archive, Audit and Provenance sowie Configuration.
- Durable Operational State wurde von Derived State unterschieden: Pending Writes, Queue-Zustände, Checkpoints, Journale und noch nicht bestätigte Synchronisationspuffer dürfen nicht wie rekonstruierbarer Cache behandelt werden.
- Knowledge ist autoritativ für kanonisches semantisches Wissen; Raw Archive, Personal Memory, Audit/Provenance und Configuration besitzen jeweils eigene autoritative Zuständigkeiten.
- Personal Knowledge und Personal Memory wurden endgültig getrennt. Projekte, Entscheidungen, Ziele, Ideen und Erfahrungen gehören zu Knowledge; Arbeits-, Modell- und Antwortpräferenzen gehören zu Personal Memory.
- Personal Memory wurde ausdrücklich als getrennte Context Source in den Context Builder aufgenommen.
- Provenienz unterstützt Benutzeränderungen ohne erfundene Modellsignatur. Modellmetadaten sind nur verpflichtend, wenn tatsächlich ein Modell beteiligt war.
- Originalquellen sind gegen destruktive Verarbeitung geschützt, aber nicht gegen ausdrückliche Benutzerlöschung oder ausdrücklich konfigurierte Aufbewahrungsregeln.
- Raw Archive ist eine parallele Quellen-Domäne und keine letzte Stufe der Knowledge-Lebenszyklushierarchie.
- Graceful Degradation wurde auf nichtkritische/optionale Fehler präzisiert. Kritische Integritäts- oder Sicherheitsfehler dürfen Read-Only- oder Recovery-Zustände auslösen.
- Internetberechtigungen wurden vereinheitlicht: Offline ist Standard; ausdrückliche Web-Anfragen, der Internet-Schalter und ausdrücklich konfigurierte Plugins/Automationen können gültige Autorisierungen darstellen. Daily News bleibt die einzige standardmäßig vorgesehene automatische Ausnahme.
- Local First wurde als Datenschutz-, Robustheits- und Effizienzprinzip präzisiert und nicht als starre Pflicht zur vollständigen lokalen Suche vor jeder bereits autorisierten Web-Recherche.
- Externe Aktionen benötigen eine gültige Benutzerautorisierung; diese kann einzeln oder vorab durch ausdrücklich konfigurierte Regeln, Automationen oder Plugin-Berechtigungen erteilt werden.
- Konkrete Bindungen an ein bestimmtes Modellbackend wurden aus Alpha entfernt und durch generische Backend-Begriffe ersetzt. Die konkrete Referenzimplementierung gehört in Beta.
- Die Privacy-/Anonymisierungsschicht ist das normative Alpha-Prinzip. Tor wird ausschließlich als nicht-normative geplante v1-Option genannt; die verbindliche technische Auswahl und Integration gehört in Beta.
- Der Begriff Heretic wurde außerhalb des inhaltsneutralen Modellfreiheitskontexts aus Recovery entfernt.
- „objektive externe Fakten“ wurde durch „extern überprüfbare Sachverhalte“ ersetzt.
- Kapitel 29 verweist nun korrekt auf die normative Hierarchie der Kapitel 1–28.
- Sensible Informationen: Personal-Memory-Regeln und Raw-Archive-Regeln sind ausdrücklich voneinander getrennt.
- Kapitel 3 bezeichnet den gemeinsamen persistenten Speicher konsistent als Datenspeicher und trennt Core-Koordination von Benutzerautorität.
- Modellgestützte Interpretation und Modellsignatur wurden auch in den zusammenfassenden Regeln ausdrücklich von direkter Benutzerprovenienz getrennt.
- Aussagen zum dauerhaften Erhalt von Originalen wurden auf die geltenden Aufbewahrungs- und Löschregeln abgestimmt.

## Formale Konsolidierung

- Markdown-Listen wurden auf `-` normalisiert.
- fehlerhafte H2-Überschriften in Kapitel 12 wurden in normale Fehlerbeispiele zurückgeführt.
- Escaping-Artefakte in Kapitel 27 wurden entfernt.
- die drei Kategorien in Kapitel 8 besitzen konsistente Unterüberschriften.
- ASCII-Abläufe und Diagramme werden soweit möglich in `text`-Codeblöcken dargestellt.
- bekannte Tipp- und Grammatikfehler wurden korrigiert.
- `INDEX.md` beschreibt den konsolidierten Freeze-Kandidaten und die normative Hierarchie.
- Root-`README.md` wurde als knapper Projekteinstieg ergänzt.

## Normative Hierarchie

1. Kapitel 1–2: oberste Prinzipien.
2. Kapitel 3–27: normative Detailarchitektur.
3. Kapitel 28: normativer Scope, Entwicklungsgrenzen und Übergang zur Beta-Spezifikation.
4. Kapitel 29: nicht-normative Zusammenfassung.

Bei Konflikten gilt die spezifischere normative Regel aus Kapitel 3–28, sofern sie Kapitel 1–2 nicht widerspricht. Kapitel 29 kann keine normative Detailregel überschreiben.

## Nicht geändert

Es wurden keine neuen Produktfunktionen eingeführt. Die Konsolidierung beseitigt Widersprüche, präzisiert bestehende Grenzen und normalisiert die Dokumentation für den Alpha-Freeze.
