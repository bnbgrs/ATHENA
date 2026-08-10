# Kapitel 22 – Kontextmanagement, Gespräche und Kontinuität

---

## Einleitung
ATHENA soll sich auch nach Wochen, Monaten oder Jahren sinnvoll auf frühere Gespräche und relevante langfristige Informationen beziehen können.

Dies darf jedoch nicht dadurch erreicht werden, dass der gesamte persistente Datenbestand permanent in das Kontextfenster des Primärmodells geladen wird.

ATHENA trennt deshalb strikt zwischen:

- aktuellem Gesprächskontext
- relevanten Personal-Memory-Einträgen
- aktivem Wissen
- Langzeitwissen
- Raw Archive

Personal Memory und Knowledge bleiben auch dann logisch getrennt, wenn beide für dieselbe Antwort in den Arbeitskontext aufgenommen werden.

Das Primärmodell erhält immer nur den für die aktuelle Aufgabe relevanten Ausschnitt.

---

## Grundprinzip
Das Kontextfenster ist Arbeitsgedächtnis. ATHENAs autoritative persistente Daten bilden das Langzeitgedächtnis des Systems.
Arbeitskontext und persistente Langzeitdaten dürfen niemals miteinander verwechselt werden.

---

## Aktueller Gesprächskontext
Während einer Unterhaltung erhält das Primärmodell den unmittelbar relevanten Gesprächsverlauf.
Dieser Kontext dient dazu:
- Referenzen zu verstehen,
- vorherige Aussagen zu berücksichtigen,
- eine zusammenhängende Unterhaltung zu führen.
Er ist jedoch kein dauerhafter Wissensspeicher.

---

## Kontextfenster ist kein Archiv
ATHENA darf nicht davon ausgehen, dass Informationen dauerhaft erhalten bleiben, nur weil sie sich momentan im Kontextfenster des Modells befinden.
Langfristig relevante Informationen müssen separat gespeichert werden.

---

## Automatische Chat-Archivierung
Normale Gespräche mit mehr als einer sehr kurzen Interaktion werden standardmäßig vollständig im Roharchiv gespeichert. Als Referenz gilt: Gespräche mit mehr als etwa 1–2 Nachrichten werden grundsätzlich archiviert. Der Benutzer kann die Archivierung für normale Chats über die Benutzeroberfläche deaktivieren oder einzelne Gespräche ausdrücklich als temporär beziehungsweise „nicht speichern“ markieren.
Explizite Benutzeranweisungen besitzen immer Vorrang.

---

## Warum vollständige Chats erhalten bleiben
Das Primärmodell kann bei der ersten Verarbeitung nicht zuverlässig vorhersehen, welche Information Jahre später relevant werden könnte.
Deshalb werden bei aktivierter Chat-Archivierung nicht nur extrahierte Wissenseinheiten gespeichert.
Der ursprüngliche Gesprächsverlauf bleibt ebenfalls erhalten.

---

## Beispiel
Der Benutzer erwähnt beiläufig:
Ich habe damals für Projekt X eine bestimmte Datenbank ausprobiert.
ATHENA bewertet diese Aussage zunächst möglicherweise als unwichtig.
Sechs Monate später fragt der Benutzer:
Welche Datenbank hatte ich damals für Projekt X getestet?
ATHENA muss den ursprünglichen Chat wiederfinden und die Information rekonstruieren können.

---

## Langfristige Gesprächskontinuität
ATHENA soll frühere Gespräche auch dann wiederfinden können, wenn:
- sie nicht mehr aktiv sind,
- keine Wissenseinheit daraus erzeugt wurde,
- Wochen oder Monate vergangen sind,
- das Primärmodell inzwischen gewechselt wurde.
Das Roharchiv bildet hierfür die Rückfallebene.

---

## Kontextaufbau
Vor einer Antwort baut ATHENA einen relevanten Arbeitskontext auf.

Der Prozess folgt grundsätzlich:

```text
Benutzerfrage
        │
        ├── aktueller Gesprächskontext
        ├── relevante Personal-Memory-Einträge
        ├── relevantes aktives Wissen
        ├── bei Bedarf Langzeitwissen
        └── bei Bedarf Raw Archive
                    ↓
              Context Builder
                    ↓
              Primärmodell
                    ↓
                 Antwort
```

Personal Memory wird dabei als eigene Context Source eingebracht und nicht in die Knowledge-Domäne kopiert oder mit ihr verschmolzen.

Nicht der gesamte Datenbestand wird geladen.

---

## Retrieval statt Vollbeladung
ATHENA verwendet gezielte Suche, um relevante Informationen auszuwählen.
Dabei können kombiniert werden:
- Volltextsuche
- semantische Suche
- Wissensgraph
- Projektbezug
- Zeitbezug
- Quellenbezug
- Gesprächsbezug
Nur die relevantesten Ergebnisse gelangen in den Modellkontext.

---

## Kontextbudget
Jedes Primärmodell besitzt eine begrenzte Kontextgröße. ATHENA verwaltet dieses Kontextbudget aktiv.

Priorität erhalten typischerweise:

1. aktuelle Benutzeranfrage
2. notwendiger aktueller Gesprächskontext
3. relevante Personal-Memory-Einträge, sofern sie für die Zusammenarbeit oder Antwortform benötigt werden
4. hochrelevantes aktives Wissen
5. relevante langfristige Wissenseinheiten
6. notwendige Originalquellen

Die Reihenfolge darf aufgabengerecht angepasst werden. Weniger relevante Informationen werden nicht unnötig geladen.

---

## Große Kontextfenster
Auch wenn zukünftige Modelle sehr große Kontextfenster besitzen, bleibt das Retrieval-Prinzip bestehen.
Ein größeres Kontextfenster ist eine Ressource.
Es ersetzt keine Wissensarchitektur.
ATHENA darf deshalb auch zukünftig nicht den vollständigen Wissensbestand unselektiert in ein Modell laden.

---

## Gesprächszusammenfassungen
Lange Gespräche können zusätzlich strukturiert zusammengefasst werden.
Eine solche Zusammenfassung ersetzt niemals den Originalchat.
Sie dient ausschließlich der schnelleren Kontextrekonstruktion.

---

## Mehrstufige Rekonstruktion
Bei sehr alten oder umfangreichen Gesprächen kann ATHENA zunächst eine vorhandene Zusammenfassung verwenden.
Reicht diese nicht aus, greift ATHENA auf den Originalchat zurück.
Beispiel:
```text
Frage

↓

Chat-Zusammenfassung

↓

Information reicht nicht

↓

Originalchat durchsuchen

↓

relevante Passage

↓

Antwort
```

---

## Wochen später nach Nachrichten suchen
Dasselbe Prinzip gilt für Nachrichten und externe Ereignisse.
Der Benutzer muss auch Wochen oder Monate später fragen können:
- Was geschah damals?
- Welche Quellen hatten wir dazu?
- Wie entwickelte sich das Ereignis danach?
- Was wusste ATHENA zu diesem Zeitpunkt?
ATHENA durchsucht dafür das historische Ereigniswissen und bei Bedarf die ursprünglichen Nachrichtenquellen.

---

## Zeitbewusstsein
ATHENA muss bei historischen Informationen zwischen verschiedenen Zeitpunkten unterscheiden.
Beispiel:
Was wissen wir heute über X?
ist nicht dasselbe wie:
Was wussten wir im August 2026 über X?
Die Wissensarchitektur muss beide Fragen beantworten können.

---

## Point-in-Time-Rekonstruktion
Soweit die gespeicherten Daten dies erlauben, soll ATHENA historische Wissensstände rekonstruieren können.
Dazu verwendet sie:
- Versionen
- Zeitstempel
- Provenienz
- Auditdaten
- historische Quellen
Dadurch kann später nachvollzogen werden, wie sich Wissen entwickelt hat.

---

## Gesprächsreferenzen
ATHENA soll natürliche Referenzen verstehen können.
Beispiele:
- „Das hatten wir vor ein paar Monaten.“
- „Was war nochmal unsere Entscheidung dazu?“
- „Wir hatten darüber schon gesprochen.“
- „Welche Lösung hatten wir damals verworfen?“
Solche Anfragen lösen eine Suche im persönlichen Wissensbestand und gegebenenfalls im Chatarchiv aus.

---

## Unsicherheit
Findet ATHENA mehrere mögliche frühere Gespräche, darf sie nicht willkürlich eines davon als richtig behandeln.
Sie kann:
- mehrere Kandidaten vergleichen,
- Unsicherheit kennzeichnen,
- bei Bedarf den Benutzer um Klärung bitten.

---

## Keine erfundene Erinnerung
ATHENA darf niemals behaupten, sich an etwas zu erinnern, wenn keine entsprechende gespeicherte Information gefunden wurde.
Kann eine frühere Aussage nicht rekonstruiert werden, wird dies transparent mitgeteilt.

---

## Gesprächslöschung
Wird ein Chat endgültig gelöscht, darf ATHENA ihn später nicht über versteckte Caches oder Suchindizes rekonstruieren.
Abgeleitete rekonstruierbare Systeme müssen die Löschung übernehmen.

---

## Geschützte Gespräche
Chats können geschützten Wissensbereichen zugeordnet werden.
Ist der entsprechende Bereich gesperrt, dürfen diese Gespräche nicht zur Kontextbildung verwendet werden.

---

## Temporäre Gespräche
Der Benutzer kann Gespräche bewusst ohne dauerhafte Archivierung führen.
In diesem Modus darf der Chat für die aktuelle Unterhaltung verwendet werden.
Nach Ende des vorgesehenen temporären Lebenszyklus wird er nicht Bestandteil des langfristigen Archivs.

---

## „Nicht speichern“-Gespräche

„Nicht speichern“ ist strenger als ein temporärer Chat.

Ein ausdrücklich als „nicht speichern“ geführter Chat darf keinen persistenten vollständigen Chat-Payload in Raw Archive, Suchindex, normalen Checkpoints oder anderen langlebigen Zuständen hinterlassen. Die Gesprächsinhalte sollen soweit technisch möglich nur im für die aktuelle Sitzung notwendigen flüchtigen Arbeitsspeicher existieren.

Der Benutzer kann aus einem solchen Gespräch dennoch ausdrücklich einzelne Wissens- oder Personal-Memory-Inhalte speichern. Diese erhalten dann eine Benutzeraktions-Provenienz ohne heimliche Archivkopie des vollständigen Chats.

Technisch unvermeidbare kurzfristige Prozesspuffer müssen minimiert und nach Ende der Sitzung beziehungsweise nach Crash-Recovery-Regeln sicher verworfen werden.

---

## Wissensextraktion bei deaktivierter Chat-Archivierung
Die konkrete Benutzeroberfläche soll klar unterscheiden können zwischen:
- Chat archivieren,
- Wissen daraus übernehmen.
Dadurch kann der Benutzer langfristig entscheiden, ob ein Gespräch vollständig erhalten bleiben oder lediglich daraus ausdrücklich freigegebenes Wissen übernommen werden soll.
Die genaue Bedienlogik wird in der technischen Spezifikation festgelegt.

---

## Modellwechsel
Ein Wechsel des Primärmodells darf die Gesprächskontinuität nicht zerstören.
Das neue Modell erhält über ATHENAs Retrieval-System denselben relevanten Wissenskontext.
Kontinuität entsteht dadurch aus dem Wissenssystem.
Nicht aus dem internen Zustand eines bestimmten Modells.

---

## Neustart
Ein Neustart von:
- ATHENA,
- Modellbackend,
- Betriebssystem,
- Computer
darf die langfristige Gesprächskontinuität nicht beeinträchtigen.
Persistente Informationen werden anschließend wieder über das Wissenssystem bereitgestellt.

---

## Performance
Auch nach zehn oder mehr Jahren darf eine normale Benutzerfrage nicht erfordern, sämtliche historischen Chats zu analysieren.
Indizes, Wissensgraph, Zusammenfassungen und Retrieval reduzieren den Suchraum.
Für gemäß den Aufbewahrungsregeln erhaltene Originalquellen bleibt das Raw Archive die vollständige Rückfallebene.

---

## Ziel
ATHENA soll sich langfristig so verhalten, als verfüge sie über ein sehr großes Gedächtnis.
Technisch entsteht dieses Verhalten jedoch nicht durch ein gigantisches Kontextfenster.
Es entsteht durch:
- zuverlässige Archivierung,
- strukturierte Wissensextraktion,
- mehrstufiges Retrieval,
- Provenienz,
- zeitliche Versionierung.

---

## Leitregel
ATHENA muss nicht alles gleichzeitig im Kopf haben. ATHENA muss wissen, wo sie es wiederfindet.

---

## Abschluss des Kapitels
Die Trennung zwischen Arbeitskontext und Langzeitgedächtnis ermöglicht ATHENA eine praktisch unbegrenzt wachsende Wissensbasis.
Aktuelle Gespräche bleiben schnell.
Alte Gespräche bleiben auffindbar.
Selbst Informationen, deren Bedeutung erst Monate oder Jahre später erkennbar wird, können über das Roharchiv wiederhergestellt werden.
Damit entsteht langfristige Kontinuität unabhängig von Kontextfenster, Modellgeneration oder Laufzeit einer einzelnen Sitzung.
