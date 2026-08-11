# ATHENA Beta Specification v0.1 – Kapitel 16

## Sicherheitsarchitektur und Protected Content

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Gateway:** [Beta Kapitel 15](15_External_Access_Gateway_und_Netzwerkzugriff.md)

---

## Teil I – Sicherheitsmodell

### 1. Ziel

Dieses Kapitel definiert ATHENAs v1-Sicherheitsarchitektur für lokale Daten, Protected Content, Secrets, Berechtigungen und sichere Fehlerzustände.

---

### 2. Threat Model

v1 schützt insbesondere gegen:

- versehentlichen Datenzugriff durch andere lokale Benutzer/Prozesse soweit OS-Rechte dies unterstützen;
- Klartextleaks geschützter Inhalte in Index, Cache, Logs und Backups;
- fehlerhafte Plugins und unerlaubte Zugriffe **über die offizielle Plugin-/Core-Schnittstelle**;
- Prompt-Injection aus externen Quellen;
- unbeabsichtigte Internetzugriffe;
- Manipulation/Verlust durch fehlerhafte Writes;
- Restore gelöschter Inhalte.

v1 behauptet **keine sichere Ausführung absichtlich bösartigen Drittplugin-Codes unter demselben Betriebssystemkonto**, solange keine echte OS-Sandbox aktiviert ist. Die Installation/Aktivierung eines Drittplugins ist daher in v1 eine ausdrückliche Vertrauensentscheidung. Kapitel 17 konkretisiert diese Grenze.

v1 behauptet außerdem keinen vollständigen Schutz eines bereits vollständig kompromittierten Betriebssystems.

---

### 3. Local First ist nicht automatisch sicher

Lokale Speicherung reduziert externe Datenweitergabe, ersetzt aber nicht:

- Verschlüsselung;
- Zugriffskontrolle;
- Backupschutz;
- sichere Secrets;
- Least Privilege.

---

### 4. Fail Closed

Bei Sicherheitsfehlern wird Zugriff verweigert beziehungsweise ein geschützter Zustand erhalten. Komfortfunktionen dürfen Sicherheitsgrenzen nicht automatisch umgehen.

---

### 5. Security Boundary

Der ATHENA Core ist die zentrale Autorisierungsinstanz. UI, Modelle, Plugins und externe Clients erhalten keine direkten Datenbank-/Secret-Rechte.

---

## Teil II – Security Context

### 6. SecurityContext

Jeder sensitive Core-Request trägt einen Runtime SecurityContext:

```text
actor_id
client_id
authenticated_session
granted_capabilities
unlocked_protection_scopes
request_origin
```

---

### 7. Authorization before Data

Berechtigung wird geprüft, bevor Protected Payload, Search Result oder Source Preview geladen wird.

---

### 8. No Model Authorization

Ein Modelloutput kann keine SecurityContext-Capability selbst gewähren.

---

### 9. Session

Desktop v1 besitzt eine lokale authenticated session. Spätere Remote Clients erhalten eigene Session-/Tokenregeln in Kapitel 19.

---

## Teil III – ProtectionScope

### 10. Scope

Protected Content wird logisch über `protection_scope_id` gruppiert.

Der persistente Scope besitzt nur Lifecyclezustände wie `active`, `retired` oder `pending_delete`. **Locked/Unlocked ist ausschließlich Runtimezustand im SecurityContext** und wird nach Neustart nie aus einem persistenten `unlocked`-Flag wiederhergestellt.

---

### 11. Neutral Metadata

Ein gesperrter Scope soll keine verräterischen Namen benötigen. Die interne ID ist neutral.

---

### 12. Membership

Knowledge, Memory, Sources, Blobs, Interpretations, Auditdetails und Derived State können einem ProtectionScope angehören.

---

### 13. Inheritance

Abgeleiteter Inhalt, der geschützte Information enthält, erbt mindestens denselben Schutz.

---

### 14. Mixed Input

Eine Synthese aus public + protected Inputs ist protected, wenn die Ausgabe protected Details enthält.

---

## Teil IIIa – Schutzstatus-Übergänge

#### Protection Transition Job

Das nachträgliche Schützen einer bereits unprotected Entity ist **kein einzelnes Flag-Update**. Es läuft als resumierbarer, auditierter `ProtectionTransitionJob`.

Mindestens:

```text
Write Guard für Ziel-Scope/Entity setzen
↓
aktuelle + gemäß Retention verbleibende historische Payloads bestimmen
↓
Source-/Datei-/URI-Metadaten erfassen
↓
Protected Payloads/Blobs mit neuer Keyhierarchie erzeugen
↓
Ciphertext verifizieren
↓
FTS / Embeddings / HNSW / Previews / Temp / Projection bereinigen
↓
Operational State / Checkpoints auf Protected Payloads umstellen
↓
EntityStateHistory + ProtectionScope atomar fortschreiben
↓
alte ungeschützte Darstellungen gemäß Lösch-/Cleanupregeln entfernen
↓
Integritätsprüfung + Audit
```

Ein Protection Transition gilt erst als abgeschlossen, wenn keine nach Policy zu entfernende ungeschützte persistente Schattenkopie mehr bekannt ist.

#### Unprotect Transition

`unprotect` ist ebenfalls ein expliziter TransitionJob. Es erzeugt bewusst neue unprotected Payloads/Derived State, aktualisiert EntityStateHistory und entfernt alte Ciphertextkopien nur entsprechend Retention-/Löschregeln. Ein Unlock allein ist **kein** Unprotect.

#### Historische Revisionen

Wenn historische Revisionen nach Retention weiterhin existieren, müssen auch sie den neuen Protection Scope respektieren. Ein Protected Current Head bei weiterhin ungeschützt lesbarer Alt-Revision wäre ein Securityfehler.

---

## Teil IV – Passwort und KDF

### 15. Password Storage

Das Benutzerpasswort wird niemals dauerhaft im Klartext gespeichert.

---

### 16. KDF

Kapitel 03 legt Argon2id als v1-KDF fest.

Das Passwort wird temporär zur Ableitung eines Key-Encryption-Key verarbeitet.

---

### 17. KDF Parameters

Argon2id-Parameter werden pro ATHENA-Installation gespeichert und beim Setup auf die lokale Hardware kalibriert.

Ziel ist eine merkbare, aber akzeptable Unlock-Latenz; konkrete Defaults werden im Implementierungstest festgelegt und versioniert.

---

### 18. Salt

Für die KDF wird ein kryptographisch zufälliger Salt verwendet. Salt ist nicht geheim.

---

### 19. Password Change

Ein Passwortwechsel leitet einen neuen KEK ab und ersetzt beziehungsweise ergänzt den Password `key_slot`, der denselben zufälligen ATHENA Root Key schützt.

Dadurch müssen große Blobs, Scope Keys und per-object DEKs nicht vollständig neu verschlüsselt werden.

Der alte Password Slot wird erst als `retired` markiert beziehungsweise sicher entfernt, nachdem der neue Slot erfolgreich durch einen Test-Unwrap verifiziert wurde.

---

### 20. Password Lifetime

Passwortbytes werden nach KDF-Verarbeitung nicht absichtlich länger im Speicher gehalten als nötig. Python kann keine absolute RAM-Auslöschungsgarantie versprechen; diese Grenze wird dokumentiert.

---

## Teil V – Key Hierarchy

### 21. Master Key

ATHENA verwendet einen zufälligen **ATHENA Root Key**. Er ist weder aus Benutzerinhalten noch direkt aus dem Passwort abgeleitet.

Der Root Key wird nie im Klartext persistent gespeichert. Er wird über einen oder mehrere `key_slots` geschützt, etwa Password-, Recovery- oder OS-Secret-Slot.

---

### 22. Scope Keys

Jeder ProtectionScope erhält einen eigenen zufälligen, **versionierten Scope Key**.

Persistente `protection_scope_keys` speichern den Scope Key ausschließlich unter dem ATHENA Root Key gewrappt. `protection_scopes.current_scope_key_id` zeigt auf die für neue Writes aktive Version.

---

### 23. Data Encryption Keys

Jeder geschützte strukturierte Payload und jeder große Protected Blob erhält einen eigenen zufälligen Data Encryption Key (DEK).

Der DEK wird unter dem zum Zeitpunkt des Writes aktiven Scope Key gewrappt. Große Blobdaten können dadurch unabhängig von Password-/Root-/Scope-Key-Wrapping rotiert werden.

---

### 24. Wrapping

Persistente Hierarchie:

```text
Password / Recovery Secret / OS Secret
→ Key Slot
→ KEK beziehungsweise sicherer Slot-Mechanismus
→ ATHENA Root Key
→ versionierter Scope Key
→ per-object DEK
→ AES-256-GCM Payload/Blob
```

Kapitel 03 definiert dafür `key_slots`, `protection_scope_keys`, `protected_payloads` und `protected_blob_envelopes`.

Für v1 verwenden die kryptographischen Wrapping-Schritte konkret **AES-256-GCM**. Jeder Wrap erhält einen kryptographisch zufälligen, unter dem jeweiligen Wrapping-Key eindeutigen 96-Bit-Nonce. Associated Data bindet mindestens Key-/Scope-/Objekt-ID, Key-Version und Format-Version. Nonce-Wiederverwendung unter demselben Key ist verboten.

`wrap_algorithm` bleibt im persistenten Schema versioniert, damit ein späterer Algorithmuswechsel nur über eine ausdrückliche, geprüfte Migration erfolgen kann.

---

### 25. Rotation

Scope-Key-Rotation erzeugt eine neue `key_version`.

Neue Payloads verwenden sofort die neue Version. Bestehende per-object DEKs können in einem resumierbaren RotationJob unter den neuen Scope Key rewrapped werden. Eine vollständige Neuverschlüsselung großer Payloaddaten ist nicht automatisch erforderlich.

Alte Scope Keys werden erst `retired`, wenn keine surviving Payloads/DEKs mehr ausschließlich auf sie angewiesen sind.

---

### 26. Cryptographic Erasure

Ist ein kompletter Scope endgültig zu löschen und kein surviving Payload benötigt dessen Keys, kann Schlüsselvernichtung zusätzlich zur logischen/physikalischen Löschung eingesetzt werden.

---

## Teil VI – AES-GCM und Payloads

### 27. AEAD

Kapitel 03 legt AES-256-GCM als v1-AEAD fest.

---

### 28. Authentication Failure

GCM-Tagfehler wird als Integritäts-/Securityfehler behandelt. ATHENA gibt keinen teilweise entschlüsselten Inhalt aus.

---

### 29. Nonce

Nonce-Wiederverwendung unter demselben Schlüssel ist verboten. Das Blobformat aus Kapitel 03 erzwingt eindeutige Nonces pro Chunk/DEK.

---

### 30. AAD

IDs, Formatversion und Chunkindex werden als Associated Data gebunden, damit Metadatenmanipulation erkannt wird.

---

### 31. No Custom Crypto

ATHENA implementiert keine eigene Verschlüsselungsprimitive. Es verwendet etablierte Bibliotheksprimitive hinter einem `CryptoProvider`.

---

## Teil VII – Unlock und Lock

### 32. Unlock

Unlock:

```text
Password eingeben
↓
KDF
↓
Key unwrap
↓
Verifier/authenticated decrypt
↓
Scope Session aktiv
```

---

### 33. Failed Unlock

Fehler werden ohne Information darüber zurückgegeben, welcher interne Schlüsselteil falsch war.

---

### 34. Auto Lock

Auto-Lock ist konfigurierbar. Default soll einen praktikablen Schutz bieten, ohne laufende explizit protected Aufgaben unkontrolliert zu zerstören.

---

### 35. Lock Transition

Beim Lock:

- Protected Search Index verwerfen;
- decrypted previews entfernen;
- protected model contexts beenden/invalidieren;
- temporäre entschlüsselte Job-/Contextpayloads verwerfen;
- Keyhandles und unwrapped Root-/Scope-/DEKs freigeben;
- UI-Inhalte sperren.

Persistent bleibt der ProtectionScope selbst `active`; es wird **kein persistentes `unlocked`-Flag** gespeichert.

---

### 36. Running Jobs

Protected Jobs werden beim Lock an sicheren Grenzen pausiert, sofern sie den Schlüssel weiter benötigen.

---

### 37. Manual Lock

Tray/UI bietet sofortiges Lock.

---

## Teil VIII – Protected Search

### 38. Persistent Exclusion

Geschützter Klartext wird nicht in normalen persistenten FTS/HNSW-Indizes gespeichert.

---

### 39. Unlocked Runtime

Nach Unlock können temporäre In-Memory-Indizes für erlaubte Scopes gebaut werden.

---

### 40. Large Protected Archive

Falls ein sehr großer Protected Scope später In-Memory-Indizes unpraktisch macht, darf ein verschlüsselter persistenter Indexprovider ergänzt werden. Dies ist nicht v1-Grundvoraussetzung.

---

### 41. Lock Cleanup

Temporäre Protected Search-Strukturen werden beim Lock verworfen.

---

### 42. Search Metadata

Locked State verrät standardmäßig weder Treffertext noch Anzahl spezifischer Treffer.

---

## Teil IX – Protected Model Use

### 43. Context Authorization

Protected Content gelangt nur bei unlocked Scope in den Context Builder.

---

### 44. Local Primary Model

Bei lokalem Primärmodell bleiben protected Inputs lokal; trotzdem werden Context, Logs und temp files auf Leaks geprüft.

---

### 45. Future Remote Provider

Ein externer Modellprovider darf Protected Content nur mit expliziter separater Benutzerfreigabe erhalten. Default ist deny.

---

### 46. Model Output

Eine Antwort, die Protected Content enthält, wird in UI/Chat entsprechend markiert und bei Persistenz mindestens gleich geschützt.

---

## Teil X – Secrets Store

### 47. Secrets

Secrets umfassen:

- API Keys;
- Tokens;
- Connector Credentials;
- Recovery Secret Material;
- Plugin Secrets.

---

### 48. OS Secret Store

v1 verwendet nach Möglichkeit den Betriebssystem-Credential-/Secret-Store über einen `SecretsProvider`.

---

### 49. Fallback

Fehlt ein geeigneter OS-Store, benötigt ATHENA einen verschlüsselten lokalen Secrets Store; kein Klartext-JSON.

---

### 50. References

Configuration speichert nur `secret_ref`, nicht Secretwert.

---

### 51. Logs

Secretwerte werden vor Logging redigiert. Fehlerobjekte dürfen Requestheader nicht ungefiltert serialisieren.

---

## Teil XI – Dateirechte

### 52. State Root Permissions

Installer/Startup prüft, dass `state_root` nicht unnötig für andere lokale Benutzer schreibbar ist.

---

### 53. Protected Staging

Protected Staging erhält restriktive Dateirechte.

---

### 54. Backup Permissions

Backupziel bekommt sinnvolle Berechtigungen; bei Netzlaufwerken werden unzureichende Rechte sichtbar gewarnt.

---

### 55. No Security by Hidden Filename

Neutrale Dateinamen ergänzen Verschlüsselung, ersetzen sie nicht.

---

## Teil XII – Prompt Injection

### 56. Sources are Data

Externe Webseiten, Dokumente, E-Mails und importierte Dateien sind Daten.

---

### 57. Instruction Boundary

Nur System-/Task-/Benutzerinstruktionen aus autorisierten Kanälen dürfen das Modellverhalten steuern.

---

### 58. Tool Calls

Toolcall-Vorschläge des Primärmodells durchlaufen Capability/Authorization. Ein Dokument kann keine Toolberechtigung erzeugen.

---

### 59. Exfiltration

Eine Sourceanweisung, lokale Secrets oder andere Dokumente an eine Website zu senden, wird nicht als legitime Aufgabe übernommen.

---

### 60. Indirect Injection

Auch Inhalte, die von Search/News/Plugins stammen, behalten Source-Labels bis in den Modellcontext.

---

## Teil XIII – Plugins

### 61. Untrusted by Default

Drittplugins sind im Core **nicht automatisch zu privilegierten Komponenten**. Ihre offiziellen API-Zugriffe folgen Least Privilege und Capability Checks.

In v1 ist die Installation/Aktivierung eines Drittplugins jedoch eine ausdrückliche Vertrauensentscheidung für dessen Code, solange keine OS-Sandbox vorhanden ist. Das Capabilitymodell allein wird nicht als Schutz gegen absichtlich bösartigen Python-/Native-Code ausgegeben.

---

### 62. No Direct DB

Über die offizielle Plugin-API erhält ein Plugin keine direkte `athena.db` Connection.

Ohne OS-Sandbox ist dies eine API-Invariante und kein Beweis, dass absichtlich bösartiger lokaler Code die Datei auf Betriebssystemebene niemals öffnen könnte. Kapitel 17 macht diese Grenze explizit.

---

### 63. No Direct Secrets

Über offizielle Capabilities erhält ein Plugin nur explizit freigegebene Secret Handles beziehungsweise serverseitig injizierte Credentials.

Ein Plugin, dessen Code nicht vertraut wird, darf in v1 ohne echte OS-Sandbox nicht aktiviert werden.

---

### 64. Out-of-process

Nichttriviale Drittplugins laufen bevorzugt außerhalb des Core-Prozesses mit schmaler IPC-Schnittstelle.

Diese Prozessgrenze schützt Corestabilität und vereinfacht Capabilitykontrolle. **Sie ist allein keine Security Sandbox**. Hostile-Code-Isolation benötigt zusätzlich Betriebssystemmechanismen, die Datei-, Netzwerk-, Prozess- und Secretzugriff technisch beschränken.

---

### 65. Revocation

Capabilities können sofort widerrufen werden.

---

## Teil XIV – Network Security

### 66. Gateway

Alle allgemeinen externen Verbindungen laufen über ExternalAccessGateway.

---

### 67. SSRF

Private/Internal Destinations werden von externen Redirects blockiert.

---

### 68. TLS

HTTPS-Zertifikatsprüfung wird nicht global deaktiviert. Benutzerdefinierte CAs sind explizite Konfiguration.

---

### 69. Tor/Privacy Route

Privacyroute Fail-Closed ist verpflichtend für entsprechend konfigurierte externe Workflows.

---

## Teil XV – Security Audit

### 70. Security Events

Mindestens auditiert:

- unlock success/failure;
- lock;
- permission changes;
- denied external access;
- plugin install/enable/disable;
- secret access class;
- protected export;
- recovery key operation;
- integrity/authentication failure.

---

### 71. No Password Log

Passwort, KDF input, DEKs oder unwrapped Scope Keys werden nie geloggt.

---

### 72. Rate Limited Failure Log

Wiederholte Unlockfehler werden so auditiert, dass Logs nicht als DoS unbegrenzt wachsen.

---

## Teil XVI – Recovery Key

### 73. Optional

v1 darf einen optionalen Recovery-Key-Mechanismus anbieten.

---

### 74. Separation

Recovery Key wird nie unverschlüsselt zusammen mit dem Backup gespeichert.

---

### 75. User Responsibility

Die UI erklärt klar: Verlust von Passwort **und** Recoverymaterial kann geschützte Daten dauerhaft unzugänglich machen.

---

### 76. No Backdoor

ATHENA besitzt keinen versteckten Hersteller-/Entwickler-Masterkey.

---

## Teil XVII – Export

### 77. Protected Export

Protected Export bleibt verschlüsselt, außer der Benutzer wählt ausdrücklich einen Klartextexport und bestätigt die Konsequenz.

---

### 78. Temporary Plaintext

Klartextexport nutzt kontrolliertes Ziel und minimiert temporäre Kopien.

---

### 79. Manifest

Exportmanifest darf ohne Unlock keine protected Titel/Inhalte verraten.

---

## Teil XVIII – Security States

### 80. Normal

Alle erlaubten Scopes entsprechend Session verfügbar.

---

### 81. Locked

Protected Payloads gesperrt; unprotected ATHENA bleibt nutzbar.

---

### 82. Degraded

Beispiel: OS Secrets Store nicht erreichbar. Connectorfunktionen werden deaktiviert statt Secrets unsicher zu laden.

---

### 83. Read-only Safe Mode

Bei Integritätsunsicherheit werden Writes blockiert.

---

### 84. Security Recovery

Bei Key-/Ciphertextfehler wird nicht automatisch neu verschlüsselt oder überschrieben; Recovery/Backup wird angeboten.

---

## Teil XIX – Tests

### 85. Wrong Password Test

Falsches Passwort darf keinen teilweise entschlüsselten State erzeugen.

---

### 86. Nonce Test

Millionen Testchunks dürfen innerhalb eines Blobkeys keinen Nonce-Wiederholungsweg durch Formatlogik erlauben.

---

### 87. Ciphertext Tamper Test

Bitflip im Ciphertext → GCM authentication failure, kein Plaintext.

---

### 88. Metadata Leak Test

Locked Protected Scope: automatisiert prüfen, dass Canary-Klartext beziehungsweise sensitive Metadaten nicht vorkommen in:

- `sources.original_name` / `source_uri`;
- normalen Revision-/Representation-Hashes;
- FTS/HNSW/Embeddingfiles;
- Cache/Preview/Temp;
- Jobs/Checkpoints/ResearchScopes/CandidateSets;
- Audit-/Logsummary;
- Obsidian/Projection;
- normalen Backupmanifests.

---

### 89. Plugin DB Test

Contracttest: Ein Plugin ohne entsprechende Capability erhält über Core/Plugin RPC weder DB-Connection noch direkten Source-/Secretzugriff.

Solange v1 keine OS-Sandbox besitzt, beweist dieser Test **nicht**, dass absichtlich bösartiger lokal ausgeführter Plugin-Code auf Betriebssystemebene niemals Dateien öffnen kann. Eine solche Behauptung benötigt separate Hardened-Sandbox-Tests.

---

### 90. Prompt Injection Test

Source fordert Secret-Exfiltration. Kein Toolcall darf autorisiert werden.

---

### 91. Secret Log Test

Absichtlich API-Key-Fehler erzeugen. Secret darf in keinem Log erscheinen.

---

### 92. Lock Test

Während protected Chat manuell locken. Context/session/index müssen invalidiert werden.

---

### 93. Backup Test

Protected Backup enthält nur Ciphertext; keine entschlüsselte Kopie.

---

### 94. Password Change Test

Passwort ändern.

Erwartung:

- neuer Password Key Slot verifiziert;
- derselbe Root Key weiter verwendbar;
- Scope Keys/DEKs weiterhin entschlüsselbar;
- große Blobs ohne vollständige Daten-Re-encryption weiterhin zugänglich;
- alter Password Slot erst nach erfolgreichem Cutover retired/entfernt.

---

### 95. Scope Deletion Test

Scope löschen und Keymaterial entfernen. Surviving andere Scopes bleiben zugänglich.

Zusätzlich Protection Transition testen:

1. unprotected Entity mit historischen Revisionen, FTS, Embedding, Preview, Jobcheckpoint und Obsidian-Projektion erzeugen;
2. Entity nachträglich schützen;
3. Transition erfolgreich abschließen;
4. gesamten unprotected persistenten State nach Canary-Inhalt durchsuchen.

Erwartung: kein verbleibender ungeschützter Klartext außerhalb ausdrücklich zulässiger neutraler Metadaten.

---

### 96. Read-only Test

DB-Integritätsfehler simulieren. Core darf keine weiteren normalen Writes ausführen.

---

### 97. Abschluss

Security ist bestanden, wenn Schutz nicht von versteckten Dateinamen oder gutem Verhalten des Modells abhängt, sondern durch Coreautorisation, Kryptographie, getrennte Indizes, Least Privilege und Fail-Closed technisch erzwungen wird.

---

## Nächster Schritt

**Beta Kapitel 17 – Plugin-System und Berechtigungen**.
