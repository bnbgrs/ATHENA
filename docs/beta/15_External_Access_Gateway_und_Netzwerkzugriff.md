# ATHENA Beta Specification v0.1 – Kapitel 15

## External Access Gateway und Netzwerkzugriff

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Architektur:** [Beta Kapitel 01](01_Systemarchitektur_und_Technische_Basis.md)
**News:** [Beta Kapitel 14](14_Nachrichten_und_Ereignissystem.md)

---

## Teil I – Sicherheitsgrenze

### 1. Ziel

Der `ExternalAccessGateway` ist die einzige reguläre Core-Schnittstelle für externe Netzwerkkommunikation.

Coremodule, Provider und **konforme Plugins** dürfen die Netzwerkpolicy über die offiziellen ATHENA-Schnittstellen nicht durch direkte Sockets umgehen.

Für Drittplugins gilt die Vertrauensgrenze aus Kapitel 17: Solange keine OS-Sandbox vorhanden ist, ist die Aktivierung eines Drittplugins eine ausdrückliche Benutzer-Vertrauensentscheidung. Das Gateway-Capabilitymodell allein wird nicht als technische Garantie gegen absichtlich bösartigen lokalen Code ausgegeben.

---

### 2. Local First

Normale Wissensfunktionen bleiben ohne Internet verfügbar. Internet erweitert ATHENA, ist aber keine Voraussetzung für das eigene Gedächtnis.

---

### 3. Default

Normaler Chat-Internetzugriff ist standardmäßig aus.

Daily News ist die definierte automatische Standardausnahme, solange vom Benutzer aktiviert.

---

### 4. Fail Closed

Ist die konfigurierte Privacy-/Anonymisierungsschicht nicht verfügbar, erfolgt **kein** automatischer direkter Fallback.

---

## Teil II – Autorisierung

### 5. Authorization Object

Jeder externe Request besitzt eine gültige `ExternalAccessAuthorization`.

Sie enthält mindestens:

- actor;
- purpose;
- scope;
- allowed destinations/categories;
- privacy route;
- expiry;
- originating user action/configuration.

---

### 6. Single Request

Eine explizite Userfrage wie „Suche online nach X“ autorisiert den dafür notwendigen Requestscope.

---

### 7. Persistent Workflow

News/Plugins/Automationen können eine vorab konfigurierte dauerhafte Berechtigung besitzen.

---

### 8. No Knowledge Equals Permission

Dass ATHENA weiß, wie eine externe Aktion ausgeführt wird, ist keine Autorisierung.

---

### 9. Revocation

Benutzer kann Berechtigung widerrufen. Neue Requests werden blockiert; laufende Requests werden soweit sicher abgebrochen.

---

## Teil III – Gateway API

### 10. Interface

Logisch:

```text
ExternalAccessGateway.request()
fetch()
stream()
download()
resolve()
health()
```

Higher-level Search/Collector-Adapter bauen darauf auf.

---

### 11. No arbitrary client

Module erhalten keinen beliebigen `requests.Session`/Socketzugang, sondern eine Gateway-Capability.

---

### 12. Request Metadata

Gateway kennt:

- Methode;
- URL;
- Header policy;
- Body size;
- timeout;
- redirect policy;
- expected content;
- authorization id.

---

### 13. Response Limits

Maximale Bodygröße und Streaminglimits verhindern unkontrollierte Downloads.

---

## Teil IV – Privacy Route

### 14. Abstraktion

Alpha fordert eine freigegebene Privacy-/Anonymisierungsschicht mit Fail-Closed.

v1 implementiert dafür einen `PrivacyRouteProvider`.

---

### 15. Tor Referenz

Die v1-Referenzimplementation verwendet Tor als Privacy Route, gekapselt hinter dem Providerinterface.

---

### 16. Proxy Resolution

Bei Torbetrieb muss DNS-Auflösung ebenfalls über die Privacy Route erfolgen, damit keine lokalen DNS-Leaks entstehen.

---

### 17. Health

Gateway prüft Route Health vor automatischen externen Jobs.

---

### 18. No Silent Direct

Wenn Tor/Privacy Route ausfällt:

```text
request denied or queued
```

nicht:

```text
direct connection
```

---

## Teil V – Destination Policy

### 19. Scheme

Default externe Schemes:

```text
https
http
```

Andere Protokolle benötigen eigene Adapter/Capability.

---

### 20. Local Network SSRF

Extern gelieferte URLs dürfen nicht ungeprüft auf:

- localhost;
- RFC1918/private Netze;
- link-local;
- Metadata Services;
- lokale Adminports

zugreifen.

Private Zielnetze benötigen eigene explizite Internal-Network-Permission.

---

### 21. Redirect Revalidation

Jeder Redirect wird gegen Destination Policy und Authorization erneut geprüft.

---

### 22. URL Credentials

Credentials in URLs werden nicht in Logs geschrieben.

---

## Teil VI – Header und Identität

### 23. Minimal Headers

Gateway sendet nur notwendige Header.

---

### 24. User Agent

ATHENA verwendet einen dokumentierten User-Agent beziehungsweise Adapter-spezifischen Header, soweit technisch sinnvoll.

---

### 25. Cookies

Persistente Cookies sind pro Connector/Authorization isoliert. Normale Webrecherche teilt keinen globalen Browser-Cookiejar.

---

### 26. Auth Secrets

API Tokens und Login Secrets kommen aus Secrets Store und werden weder in Audit URLs noch Debuglogs geschrieben.

---

## Teil VII – Content Handling

### 27. Bytes first

Gateway liefert Bytes/Stream und technische Metadaten. Parsing erfolgt im Import/Collector-Layer.

---

### 28. Compression Bomb

Dekomprimierte Responsegröße besitzt Limits.

---

### 29. MIME Validation

Content-Type wird als Hinweis behandelt und gegen tatsächliche Daten geprüft.

---

### 30. Prompt Injection

Netzwerkinhalt bleibt externe Source Data und kann Coreregeln nicht ändern.

---

## Teil VIII – Audit

### 31. External Access Event

Jeder externe Zugriff protokolliert mindestens:

- Zeit;
- Authorization/Purpose;
- Destination Host;
- Privacy Route Status;
- Ergebnis;
- Responsegröße;
- Source-ID falls Capture entstanden.

Keine unnötigen Querysecrets.

---

### 32. URL Sanitization

Sensitive Queryparameter können redigiert oder gehasht werden. Vollständige URL bleibt nur dort gespeichert, wo sie als Source Provenienz tatsächlich erforderlich und zulässig ist.

---

### 33. Denied

Blockierte Requests erzeugen Audit mit Reason Code.

---

## Teil IX – Rate Limits und Robustheit

### 34. Timeouts

Connect, read und total timeout sind begrenzt.

---

### 35. Retry

Nur idempotente beziehungsweise sicher retrybare Requests werden automatisch wiederholt.

---

### 36. Backoff

Exponential Backoff + Jitter für 429/temporäre Fehler.

---

### 37. Host Concurrency

Per-Host-Concurrency verhindert aggressive Parallelisierung.

---

### 38. Circuit Breaker

Wiederholt fehlerhafte Ziele können temporär in Circuit-Open gehen.

---

## Teil X – Downloads

### 39. Streaming

Große Downloads werden direkt in kontrolliertes Staging gestreamt.

---

### 40. Max Size

Authorization/Importprofil definiert Maximalgröße oder verlangt Userfreigabe.

---

### 41. Hash

Beim Streamen wird Integritätshash berechnet.

---

### 42. Partial Download

Unvollständige Downloads werden nicht als Source committed.

---

## Teil XI – Plugins

### 43. Plugin Network Capability

Plugin erhält nur explizite Network Capability mit Scope.

---

### 44. Gateway Enforcement

Pluginhost muss direkten Netzwerkzugriff soweit technisch möglich blockieren beziehungsweise nicht bereitstellen; zulässige Requests laufen über Gateway RPC.

---

### 45. Destination Scope

Berechtigungen können auf Domains/API-Gruppen beschränkt werden.

---

### 46. User View

UI zeigt pro Plugin, ob und wohin es extern zugreifen darf.

---

## Teil XII – Interne Provider

### 47. Model Backend

Lokale Modellbackend-Verbindungen sind von externem Webzugriff logisch getrennt. Sie werden durch Local Backend Policy beschränkt.

---

### 48. NAS

Zugriff auf konfigurierten NAS-/Storage-Root ist Storage-IO, nicht allgemeine Internetberechtigung.

---

### 49. Future Remote Model

Ein späterer Cloudmodellprovider wäre externer Zugriff und benötigt explizite Datenschutz-/Authorization-Regeln.

---

## Teil XIII – UI

### 50. Internet Toggle

UI besitzt klaren Internet-Schalter für normale Chats.

---

### 51. Status

Zeigt:

```text
Internet permission: on/off
Privacy route: ready/error
Last external access
Reason
```

---

### 52. Per Request

Bei fehlender Freigabe kann ATHENA fragen:

```text
Für diese Recherche Internet aktivieren?
```

statt still extern zuzugreifen.

---

### 53. Daily News

News-Automation wird separat als konfigurierte Ausnahme angezeigt.

---

## Teil XIV – Tests

### 54. Fail Closed Test

Tor/Privacy Route stoppen. Automatischer Newsrequest darf keine direkte Verbindung herstellen.

---

### 55. DNS Leak Test

Testziel mit nur über Route auflösbarem Host. Lokale DNS-Auflösung darf nicht verwendet werden.

---

### 56. SSRF Test

Externe Seite redirectet auf `127.0.0.1`. Gateway muss blockieren.

---

### 57. Redirect Test

Erlaubte Domain redirectet auf nicht erlaubtes Ziel. Revalidation blockiert.

---

### 58. Secret Log Test

URL/API-Key in Request. Logs/Audit dürfen Secret nicht enthalten.

---

### 59. Large Response Test

Server streamt unbounded Body. Gateway bricht am Limit ab.

---

### 60. Retry Test

POST ohne Idempotenz darf nicht blind automatisch wiederholt werden.

---

### 61. Plugin Permission Test

Plugin ohne Network Capability versucht Fetch. Denied + Audit.

---

### 62. Internet Toggle Test

Normaler Chat Internet off. Modell darf nicht eigenmächtig Webrequest auslösen.

---

### 63. Explicit Search Test

User sagt explizit „suche online“. Authorization gilt für Taskscope und wird auditiert.

---

### 64. Abschluss

Der Gateway ist bestanden, wenn jede externe Kommunikation einen nachvollziehbaren Zweck, eine gültige Autorisierung und eine durchsetzbare Privacyroute besitzt und kein Modul die Grenze still umgehen kann.

---

## Nächster Schritt

**Beta Kapitel 16 – Sicherheitsarchitektur und Protected Content**.
