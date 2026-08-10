# ATHENA Beta Specification v0.1 – Kapitel 14

## Nachrichten- und Ereignissystem

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Import:** [Beta Kapitel 04](04_Quellen_Roharchiv_und_Import-Pipeline.md)
**Knowledge:** [Beta Kapitel 05](05_Wissenseinheiten_Claims_und_Wissensgraph.md)
**Jobs:** [Beta Kapitel 12](12_Job-System_Queue_und_Scheduler.md)

---

## Teil I – Auftrag

### 1. Ziel

Das Nachrichten- und Ereignissystem sammelt nach Benutzerregeln externe Nachrichtenquellen, gruppiert Artikel zu Ereignissen und integriert Entwicklungen nachvollziehbar in ATHENAs Knowledge-System.

---

### 2. News ist externe Information

Ein Artikel ist zunächst eine Source. Er wird nicht allein durch Veröffentlichung zu kanonischer Wahrheit.

---

### 3. Ereignis versus Meinung

Berichtete Ereignisse, Quellenclaims, Kommentare und Bewertungen werden getrennt modelliert. Meinungen dürfen als attribuierte Claims erhalten bleiben.

---

### 4. Daily Job

Daily News ist die in Alpha definierte automatische Standardausnahme für externen Internetzugriff, sofern vom Benutzer nicht deaktiviert.

---

## Teil II – News Configuration

### 5. News Profile

Konfiguration umfasst:

- aktiviert/deaktiviert;
- lokale Tageszeit;
- Zeitzone;
- Quellenprofile;
- Regionen/Themengewichtung;
- Sprache;
- Backfill-Limit;
- maximale tägliche Datenmenge;
- Protected/Privacy-Regeln.

---

### 6. Global Coverage

Defaultziel ist ein breiter Überblick über wichtige weltweite Ereignisse, nicht ein ausschließlich personalisierter Filterbubble-Feed.

---

### 7. Personal Interests

Persönliche Themen dürfen zusätzlich gewichtet werden, ohne globale relevante Entwicklungen vollständig auszublenden.

---

### 8. Source Diversity

Quellenprofile sollen nach Region, Sprache und redaktioneller Perspektive diversifizierbar sein.

---

## Teil III – Collector

### 9. Collector Boundary

News Collector benutzt ausschließlich den ExternalAccessGateway.

---

### 10. No Direct Requests

News-Code öffnet keine direkten Internetverbindungen an der Privacy-/Audit-Schicht vorbei.

---

### 11. Source Capture

Relevante Artikel werden als Web Snapshot/Source aufgenommen mit URL, Retrievalzeit und Inhaltsrepräsentation.

---

### 12. Feed Discovery

RSS/Atom, strukturierte Feeds oder indexierbare Newsseiten dürfen als Discovery-Mechanismen dienen. Discoveryresultat ist noch keine Source, bis ein relevanter Capture erfolgt.

---

### 13. Rate Limits

Collector respektiert technische Rate Limits und nutzt Backoff/Caching.

---

## Teil IV – Daily Workflow

### 14. Phase 1 Discovery

Breite Quellenabfrage sammelt Kandidaten.

---

### 15. Phase 2 Capture

Ausgewählte Kandidaten werden als Sources gesichert.

---

### 16. Phase 3 Extraction

Primärmodell extrahiert Claims, Orte, Akteure, Zeiten und Ereigniskandidaten.

---

### 17. Phase 4 Clustering

Mehrere Artikel werden zu Event-Kandidaten geclustert.

---

### 18. Phase 5 Comparison

Claims unterschiedlicher Quellen werden auf Übereinstimmung/Widerspruch verglichen.

---

### 19. Phase 6 Digest

Daily Digest synthetisiert Top Events mit Quellen, Unsicherheit und Entwicklungen.

---

### 20. Phase 7 Knowledge

Nur relevante längerfristige Event-/Claim-Strukturen werden als Knowledge persistiert. Rohartikel bleiben im Raw Archive nach Retentionregeln.

---

## Teil V – Event Entity

### 21. Event

News Events werden in v1 als KnowledgeUnit `event` plus spezialisierte Claims/Relations modelliert, nicht als separate unverbundene Wahrheitsschicht.

---

### 22. Event Identity

Event Merge basiert auf:

- Zeit;
- Ort;
- Akteuren;
- Kernhandlung;
- Sourcecluster.

Semantischer Merge wird vom Primärmodell beziehungsweise Benutzer veranlasst.

---

### 23. Event Time

Ereigniszeit wird getrennt von Artikelpublikations- und Retrievalzeit gespeichert.

---

### 24. Event Evolution

Ein Event kann über Tage neue Claims/Phasen erhalten, ohne jeden Artikel als neues unabhängiges Event darzustellen.

---

### 25. Related Events

Mehrere Ereignisse können als `part_of`, `caused_by`, `followed_by` oder neutral `related_to` verknüpft werden, sofern semantisch begründet.

---

## Teil VI – Source Comparison

### 26. Independent Reporting

Wenn erkennbar, dass mehrere Artikel auf dieselbe Agentur/Quelle zurückgehen, wird dies im Sourcecluster berücksichtigt.

---

### 27. Agreement

Übereinstimmende Claims aus mehreren Quellen können `supported` werden, ohne absolute Wahrheit zu behaupten.

---

### 28. Disagreement

Abweichende Zahlen, Ursachen oder Bewertungen bleiben sichtbar.

---

### 29. Corrections

Spätere Korrekturen einer Nachrichtenquelle erzeugen neue Source-Captures/Claims und können alte Claims `retracted`/`superseded` markieren.

---

## Teil VII – Ranking

### 30. Importance

News Importance kann Signale kombinieren:

- globale Auswirkung;
- Zahl/Vielfalt unabhängiger Quellen;
- Neuigkeit;
- direkte Relevanz zu bestehenden Projekten;
- Fortsetzung bereits wichtiger Events.

Es gibt keine alleinige Klickpopularitätsmetrik.

---

### 31. Diversity Constraint

Ein einzelnes Großereignis darf den gesamten Digest dominieren, wenn dies sachlich angemessen ist, aber kleinere relevante Regionen/Themen sollen nicht algorithmisch unsichtbar werden.

---

### 32. User Customization

Der Benutzer kann Themen höher/niedriger gewichten. Harte Ausschlüsse sind explizite Konfiguration.

---

## Teil VIII – Backfill

### 33. Offline Detection

Scheduler erkennt verpasste Daily-News-Zeiträume.

---

### 34. Historical Window

Backfill-Jobs behalten den historischen Zieltag/-zeitraum, statt nur aktuelle Artikel zu sammeln.

---

### 35. Source Limits

Historische Rekonstruktion ist abhängig davon, welche Quellen alte Inhalte noch anbieten.

---

### 36. Backfill Status

Ein Tag wird markiert:

```text
complete
partial
unreconstructable
```

Keine erfundenen Artikel bei Lücken.

---

### 37. Bounded Work

Viele verpasste Tage werden in Batches und mit Backpressure verarbeitet.

---

## Teil IX – Digests

### 38. Daily Digest

Enthält:

- wichtigste Events;
- kurze Entwicklung;
- Quellen;
- bekannte Konflikte;
- Unsicherheit;
- Links zu Event/Source Details.

---

### 39. Weekly Digest

Synthese der Evententwicklung über die Woche, nicht nur Aneinanderreihung von sieben Daily Digests.

---

### 40. Monthly Digest

Hebt längerfristige Trends und wichtige Veränderungen hervor.

---

### 41. Digest Provenance

Jede Zusammenfassung verweist auf Event-/Claim-/Source-Revisionen.

---

### 42. Digest Revision

Bei späterem Backfill/Korrektur kann ein Digest revisioniert werden. Alte Version bleibt nachvollziehbar.

---

## Teil X – Personalization Boundary

### 43. Personal Memory

Personal Memory kann Form/Schwerpunkte des Digests beeinflussen.

---

### 44. No Personalized Truth

Interessen des Benutzers verändern nicht die epistemische Bewertung eines Claims.

---

### 45. No Hidden Filter

Wesentliche automatische Themenfilter sind in Configuration sichtbar.

---

## Teil XI – Protected/Private

### 46. Private Projects

Wenn News mit geschützten Projekten verknüpft wird, dürfen diese Projektinformationen nicht als externe Suchquery gesendet werden, sofern der Benutzer dies nicht ausdrücklich erlaubt.

---

### 47. Query Minimization

External Discovery sendet nur notwendige Suchbegriffe und keine unnötigen lokalen Memory-/Knowledge-Daten.

---

### 48. Protected Event Links

Links zwischen öffentlichem Event und Protected Knowledge dürfen im gesperrten Zustand keine Protected Details leaken.

---

## Teil XII – Failure und Recovery

### 49. Collector Failure

Ein fehlerhafter Sourcecollector macht Daily Job `partial`, nicht automatisch komplett failed.

---

### 50. External Offline

Privacy Route oder Internet nicht verfügbar: Job wartet/Backfill später. Kein Direct-Fallback.

---

### 51. Model Failure

Artikel bleiben captured; Event Extraction kann später wiederholt werden.

---

### 52. Duplicate Job

Idempotency verhindert, dass derselbe Daily Scope doppelte Eventstrukturen erzeugt.

---

## Teil XIII – UI

### 53. News View

UI bietet:

- Today;
- Timeline;
- Event Detail;
- Source Comparison;
- Weekly/Monthly;
- Backfill Status.

---

### 54. Event Detail

Zeigt Quellenclaims getrennt von ATHENA-Synthese.

---

### 55. Source Access

Originalcapture/Anchor kann aus Event/Claim geöffnet werden.

---

### 56. Uncertainty

Uneinigkeit wird sichtbar formuliert, nicht hinter einem einheitlichen Summarytext versteckt.

---

## Teil XIV – Tests

### 57. Cluster Test

Fünf Artikel über dasselbe Ereignis dürfen nicht fünf unabhängige Events erzeugen.

---

### 58. Distinct Event Test

Ähnliche Akteure an unterschiedlichen Tagen/Orten dürfen nicht fälschlich gemerged werden.

---

### 59. Opinion Test

Kommentarartikel: Meinung muss attribuiert bleiben und darf nicht als Eventfakt gespeichert werden.

---

### 60. Correction Test

Quelle korrigiert Zahl. Neue Claimrevision/Source erfasst, alte Historie bleibt.

---

### 61. Backfill Test

PC zehn Tage offline. Historische Jobs werden mit ursprünglichen Datumsfenstern erzeugt.

---

### 62. Unreconstructable Test

Alte Quelle nicht mehr verfügbar. Tag wird partial/unreconstructable, nicht erfunden.

---

### 63. Privacy Test

Protected Projektbegriff darf nicht ohne Freigabe an externe Suche gesendet werden.

---

### 64. Gateway Failure Test

Privacy Route unavailable. Kein Direct Internet.

---

### 65. Digest Provenance Test

Jeder zentrale Digestpunkt muss auf Events/Claims/Sources rückführbar sein.

---

### 66. Abschluss

Das News-System ist bestanden, wenn ATHENA nicht bloß Artikel sammelt, sondern nachvollziehbar Ereignisverläufe dokumentiert und dabei Quellenunterschiede, historische Lücken und Datenschutzgrenzen sichtbar erhält.

---

## Nächster Schritt

**Beta Kapitel 15 – External Access Gateway und Netzwerkzugriff**.
