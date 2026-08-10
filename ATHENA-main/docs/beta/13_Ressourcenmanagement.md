# ATHENA Beta Specification v0.1 – Kapitel 13

## Ressourcenmanagement

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Jobs:** [Beta Kapitel 12](12_Job-System_Queue_und_Scheduler.md)
**Storage:** [Beta Kapitel 03](03_Storage_Datenbanken_und_Migrationen.md)
**Modelle:** [Beta Kapitel 08](08_Primaermodell_und_Provider-System.md)

---

## Teil I – Ziele

### 1. Ziel

Der Resource Manager verhindert, dass ATHENA den Computer monopolisiert oder durch RAM-, VRAM-, Disk- oder I/O-Überlastung instabil wird.

---

### 2. User first

Direkte Benutzerinteraktion hat grundsätzlich Vorrang vor nichtkritischer Hintergrundarbeit.

---

### 3. Safety first

Datensicherheitskritische Writes, Rollbacks und Recovery dürfen trotzdem Ressourcen reservieren, wenn Aufschub Datenverlust riskieren würde.

---

### 4. Resource Types

Mindestens:

```text
CPU
RAM
GPU utilization
VRAM
disk free
disk IO
network
model availability
battery/power state optional
user activity
```

---

## Teil II – Resource Snapshot

### 5. Snapshot

Resource Manager erzeugt periodische RuntimeSnapshots.

---

### 6. Provider

Hardwaremessung läuft über austauschbare `ResourceProbe`-Adapter. Fehlende GPU-Metriken dürfen den Core nicht unbenutzbar machen.

---

### 7. Freshness

Jeder Messwert besitzt Timestamp. Alte Werte werden nicht als aktuell behandelt.

---

### 8. Smoothing

Kurzzeitspitzen können geglättet werden; Admission für kritische Limits nutzt trotzdem sichere Worst-Case-/Peakinformationen.

---

## Teil III – Job Resource Profile

### 9. Profile

Jeder Jobtyp beschreibt geschätzte:

- CPU-Klasse;
- RAM;
- GPU;
- VRAM;
- Disk IO;
- Network;
- Storage Root.

---

### 10. Measured Learning

ATHENA darf reale Peakwerte lokaler Jobs messen und zukünftige Estimates verbessern. Diese Performanceprofile sind Configuration/Operational Metadata.

---

### 11. Unknown Estimate

Ist Ressourcenbedarf unbekannt, verwendet ATHENA konservative Defaults.

---

### 12. Hard and Soft

Profile unterscheiden harte Mindestanforderungen und weiche Präferenzen.

---

## Teil IV – Admission Control

### 13. Admission

Vor Jobstart:

```text
Job profile
+
current resources
+
priority
+
concurrency limits
↓
admit / wait
```

---

### 14. RAM Safety

Schwere Jobs starten nicht, wenn dadurch erwartbar Paging/Out-of-Memory-Risiko entsteht.

---

### 15. VRAM Safety

Primärmodelljobs starten nicht, wenn bekannter VRAM-Bedarf offensichtlich nicht verfügbar ist.

---

### 16. Disk Safety

Kapitel-03-Diskzustände werden als harte Admission-Signale genutzt.

---

### 17. IO Contention

Mehrere große Archive-/Backupjobs auf demselben Datenträger werden begrenzt.

---

## Teil V – GPU und Primärmodell

### 18. GPU Detection

Resource Manager versucht GPU/VRAM-Metriken über geeignete lokale Adapter zu lesen. Ohne zuverlässige Metrik bleibt manuelle Policy möglich.

---

### 19. External GPU Use

Hohe GPU-Auslastung durch andere Anwendungen kann Modell-Autoload und Background Inference blockieren.

---

### 20. Manual Override

Benutzer kann ausdrücklich einen Job/Modellload starten. ATHENA zeigt gegebenenfalls Ressourcerisiko, blockiert aber nur bei klaren Sicherheitsgrenzen.

---

### 21. Model Unload

Ein von ATHENA geladenes Idle-Modell kann zur Freigabe von VRAM entladen werden.

---

### 22. No Thrashing

Load/Unload-Hysterese verhindert, dass das Modell im Minutentakt zwischen Jobs ständig geladen und entladen wird.

---

## Teil VI – CPU und RAM

### 23. CPU Budget

Backgroundjobs erhalten ein konfigurierbares CPU-Budget beziehungsweise Workerlimit.

---

### 24. Process Priority

Workerprozesse dürfen niedrige OS-Priorität für nichtkritische Backgroundarbeit verwenden, sofern dies portabel und sicher umgesetzt wird.

---

### 25. RAM Headroom

ATHENA hält einen konfigurierbaren RAM-Headroom für UI/Core und andere Anwendungen frei.

---

### 26. Memory Pressure

Bei Memory Pressure:

- neue schwere Jobs stoppen;
- Batchgrößen reduzieren;
- Caches bereinigen;
- Modelljobs gegebenenfalls warten.

---

## Teil VII – Disk und IO

### 27. Disk Root Awareness

Disk-Free und I/O werden pro Storage Root/Volume betrachtet, nicht nur global.

---

### 28. Sequential Work

Große Blobkopien werden nach Möglichkeit sequentiell gestreamt und begrenzt parallelisiert.

---

### 29. Derived Cleanup

Bei Platzdruck dürfen nur sicher rekonstruierbare Daten automatisch entfernt werden.

---

### 30. Emergency Reserve

Kapitel 03 definiert die Emergency Reserve. Resource Manager behandelt deren Freigabe als EMERGENCY-Operation.

---

## Teil VIII – User Activity

### 31. Idle Detection

Optional kann ATHENA erkennen, ob der Benutzer aktiv mit Maus/Tastatur beziehungsweise foreground Anwendungen arbeitet.

---

### 32. Idle Jobs

Sehr schwere Maintenance kann bevorzugt in Idle-Phasen laufen.

---

### 33. Privacy

User-Activity-Erkennung speichert keine unnötigen detaillierten Verhaltensprofile.

---

### 34. No Surprise

Ein plötzlich startender schwerer GPU-Job während aktiver Nutzung wird vermieden.

---

## Teil IX – Profiles

### 35. Modes

v1 bietet verständliche Resource Modes:

```text
Balanced
Quiet
Performance
Pause Background
```

---

### 36. Balanced

Standard: direkte Interaktion schnell, Background moderat.

---

### 37. Quiet

Reduzierte CPU/GPU/I/O-Last, geeignet während anderer Arbeit.

---

### 38. Performance

Mehr Parallelität und aggressive Nutzung freier Ressourcen.

---

### 39. Pause Background

Keine nichtkritischen Backgroundjobs. Datensicherheits-/Recoveryarbeit darf separat sichtbar bleiben.

---

## Teil X – Thermal/Power

### 40. Temperature optional

Temperaturdaten dürfen berücksichtigt werden, wenn zuverlässig verfügbar. ATHENA implementiert keine eigene Hardware-Schutzlogik anstelle der Gerätefirmware.

---

### 41. Laptop Battery

Spätere mobile/Notebookprofile können schwere Backups/Inference bei Akkubetrieb verzögern.

---

### 42. Power Loss Risk

Kritische Persistenz bleibt transaktional; Resource Policy ersetzt keine Crash Safety.

---

## Teil XI – UI

### 43. Resource Status

UI/Tray zeigt kompakt:

- Primary Model loaded;
- VRAM soweit verfügbar;
- Background paused/running;
- Storage Warning;
- Queue count.

---

### 44. Advanced View

Diagnoseansicht zeigt detaillierte CPU/RAM/GPU/Diskwerte und aktuelle Jobreservierungen.

---

### 45. Explain Waiting

Jobstatus erklärt:

```text
wartet auf VRAM
wartet auf NAS
wartet auf freien Speicher
```

statt generischem `queued`.

---

## Teil XII – Tests

### 46. GPU Contention Test

Externen GPU-Load simulieren. Background Modelljob muss warten; User Override bleibt möglich.

---

### 47. RAM Pressure Test

RAM künstlich knapp. Batchgrößen reduzieren und schwere Jobs nicht starten.

---

### 48. Disk Critical Test

Derived Jobs pausieren; keine automatische Knowledge-/Blob-Löschung.

---

### 49. User Priority Test

Background Research läuft. Userchat muss innerhalb definierter Preemptiongrenze Ressourcen erhalten.

---

### 50. No Thrash Test

Viele kleine Modelljobs: Load/Unload-Hysterese verhindert unnötige Modellwechsel.

---

### 51. Missing Metrics Test

GPU-Probe nicht verfügbar. Core funktioniert weiter mit degraded Resource Info.

---

### 52. Mode Test

Quiet/Balanced/Performance verändern nur Resource Scheduling, nicht Knowledge Semantik.

---

### 53. Abschluss

Ressourcenmanagement ist bestanden, wenn ATHENA auf einem normalen Desktop über lange Zeit im Hintergrund laufen kann, ohne Benutzerarbeit unnötig zu stören oder Datensicherheit gegen Performance einzutauschen.

---

## Nächster Schritt

**Beta Kapitel 14 – Nachrichten- und Ereignissystem**.
