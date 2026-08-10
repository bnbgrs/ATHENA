# ATHENA Beta Specification v0.1 – Kapitel 25

## Repository- und Code-Struktur

**Status:** Vollständiger erster technischer Entwurf – konsolidiert, noch nicht eingefroren
**Normative Basis:** [ATHENA Alpha v2.0.1](../alpha/INDEX.md)
**Architektur:** [Beta Kapitel 01](01_Systemarchitektur_und_Technische_Basis.md)
**Updates:** [Beta Kapitel 23](23_Updates_Migrationen_und_Kompatibilitaet.md)

---

## Teil I – Ziele

### 1. Ziel

Die Repositorystruktur soll modular, für AI-gestützte Entwicklung gut navigierbar und für einen lokalen Monolithen nicht unnötig komplex sein.

---

### 2. Git Scope

Git ist Source of Truth für:

- Code;
- Spezifikationen;
- Schemas;
- Migrationen;
- Tests;
- Buildkonfiguration.

Persönliche ATHENA-Daten gehören nicht ins Development-Repository.

---

### 3. One Repository

v1 verwendet ein Monorepo für Core, Desktop UI, Tests und Spezifikation.

---

### 4. No Microservice Repo Split

Die logischen Module aus Kapitel 01 werden nicht in separate Repositories zerlegt.

---

## Teil II – Root Layout

### 5. Layout

Empfohlene Struktur:

```text
ATHENA/
├── docs/
│   ├── alpha/
│   ├── beta/
│   └── architecture/
├── src/
│   └── athena/
├── ui/
├── tests/
├── schemas/
├── migrations/
├── scripts/
├── packaging/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
├── .gitattributes
└── .gitignore
```

---

### 6. docs/alpha

Gefrorene Alpha-Spezifikation.

---

### 7. docs/beta

Technische Beta-Spezifikation.

---

### 8. docs/architecture

Spätere ADRs, Diagramme und implementierungsspezifische Architekturhinweise, die nicht Teil der normativen Beta-Kapitel sein müssen.

---

## Teil III – Python Package

### 9. src layout

Python verwendet `src`-Layout:

```text
src/athena/
```

Dadurch werden zufällige Imports aus Repositoryroot vermieden.

---

### 10. Package Root

`athena` enthält nur produktiven Corecode.

---

### 11. No Business Logic in scripts

`scripts/` enthält Development-/Maintenance-Hilfen, keine versteckte Produktionslogik.

---

## Teil IV – Core Module Tree

### 12. Proposed Tree

```text
src/athena/
├── core/
├── api/
├── model/
├── knowledge/
├── memory/
├── archive/
├── search/
├── context/
├── research/
├── jobs/
├── news/
├── network/
├── security/
├── storage/
├── backup/
├── recovery/
├── plugins/
├── observability/
├── config/
└── common/
```

---

### 13. core

Application lifecycle, dependency wiring, command coordination, actor/security context.

---

### 14. api

Core API contracts, transport adapters, event streams.

---

### 15. model

Primary-/InfrastructureProvider Interfaces und konkrete Adapter.

---

### 16. knowledge

KnowledgeUnits, Claims, Relations, Projects, Concept Notes und semantische Workflows.

---

### 17. memory

Personal Memory Domainservice.

---

### 18. archive

Sources, import, representations, anchors, blobs.

---

### 19. search

FTS, Embeddings, Vector, Hybrid Retrieval.

---

### 20. context

Context Builder und Token Budget.

---

### 21. research

Exhaustive Research.

---

### 22. jobs

Queue, Scheduler, Worker Contracts, Checkpoints.

---

### 23. news

Collectors, Event Processing, Digests.

---

### 24. network

ExternalAccessGateway und Privacy Routes.

---

### 25. security

Authorization, Protected Content, Secrets, Crypto adapter.

---

### 26. storage

SQLAlchemy repositories, schema metadata, BlobStore.

---

### 27. backup

Backup Repository und Restore.

---

### 28. recovery

Health/Recovery services.

---

### 29. plugins

Plugin manifest, host, capabilities.

---

### 30. observability

Logging/Metrics/Health.

---

### 31. config

Versioned configuration service.

---

### 32. common

Kleine wirklich domänenübergreifende Types. Kein „misc“-Ablageplatz.

---

## Teil V – Module Layers

### 33. Domain

Jedes Modul trennt soweit sinnvoll:

```text
domain/
application/
ports/
adapters/
```

ohne dogmatisch vier Verzeichnisse für triviale Module zu erzwingen.

---

### 34. Ports

Provider-/Repositoryinterfaces liegen nahe an der Domain, die sie benötigt.

---

### 35. Adapters

SQLite, HTTP, LM backend, filesystem, Qt etc. sind Adapter.

---

### 36. Dependency Direction

Domaincode importiert keine Qt-/SQLite-/HTTP-Details.

---

## Teil VI – Storage Code

### 37. storage/db

```text
storage/
├── db/
│   ├── engine.py
│   ├── schema.py
│   ├── types.py
│   └── repositories/
├── blob/
├── migration/
└── roots/
```

---

### 38. Migrations

Alembicmigrationen liegen top-level unter `migrations/`, weil sie releaseweit relevant sind.

---

### 39. No SQL in UI

UI importiert keine Storage-Repositories.

---

## Teil VII – API Schemas

### 40. schemas

Versionierte externe Schemas liegen unter:

```text
schemas/api/v1/
schemas/plugin/v1/
schemas/export/v1/
schemas/projection/v1/
```

---

### 41. Generated Code

Generierte Client-/Schemaartefakte werden klar gekennzeichnet und möglichst reproduzierbar erstellt.

---

## Teil VIII – UI Layout

### 42. ui

```text
ui/
└── desktop/
    ├── app/
    ├── views/
    ├── viewmodels/
    ├── widgets/
    ├── resources/
    └── tests/
```

---

### 43. No Domain Duplication

UI ViewModels dürfen Domainzustand darstellen, aber keine zweite Knowledge-/Permissionlogik implementieren.

---

## Teil IX – Tests Layout

### 44. Tests

```text
tests/
├── unit/
├── integration/
├── contract/
├── e2e/
├── recovery/
├── migration/
├── security/
├── performance/
└── fixtures/
```

---

### 45. Module Tests

Tests können zusätzlich spiegelbildlich nach Modul organisiert werden.

---

## Teil X – Dependency Management

### 46. pyproject

Pythonprojekt wird über `pyproject.toml` konfiguriert.

---

### 47. Dependency Groups

Trennen:

- runtime;
- desktop;
- dev/test;
- optional integrations.

---

### 48. Pins

Releases verwenden reproduzierbare Lock-/Pinstrategie. Die Spezifikation schreibt keine dauerhaft eingefrorenen Bibliotheksversionen fest.

---

### 49. Minimal Core

Optional UI-/ML-/Pluginabhängigkeiten werden nicht unnötig in minimalen Recovery Core importiert.

---

## Teil XI – Code Quality

### 50. Formatter/Linter

v1 verwendet automatisierte Format-/Lintchecks für Python.

---

### 51. Type Checking

Öffentliche Coreports und Datenverträge werden statisch typisiert.

---

### 52. No Generated Giant Files

Produktionscode wird nicht als ein einzelnes tausende Zeilen langes Modul erzeugt.

---

### 53. Complexity

Große Funktionen werden an klaren Domain-/Servicegrenzen zerlegt.

---

## Teil XII – Architecture Decision Records

### 54. ADR

Wichtige spätere technische Änderungen erhalten kurze ADRs unter:

```text
docs/architecture/adr/
```

---

### 55. When

ADR bei Entscheidungen wie:

- Vector Provider wechseln;
- Remote DB;
- neue Encryption;
- UI Frameworkwechsel;
- Syncmodell.

---

### 56. No Duplicate Spec

ADR erklärt Entscheidung/Tradeoff, ersetzt nicht die normative Beta-Spezifikation.

---

## Teil XIII – Git Workflow

### 57. main

`main` bleibt stabiler gemeinsamer Entwicklungsstand.

---

### 58. Feature Branches

Bei Codeentwicklung:

```text
feature/storage
feature/chat
feature/search
fix/...
```

sind sinnvoll, aber kein komplexes Gitflow erforderlich.

---

### 59. Small Commits

Commits sollen jeweils eine nachvollziehbare Änderung enthalten.

---

### 60. Specs with Code

Wenn Code eine Beta-Entscheidung bewusst ändert, wird die zugehörige Spezifikation im selben oder eng gekoppelten Change aktualisiert.

---

## Teil XIV – Tags

### 61. Alpha Tag

`alpha-v2.0.1-final` markiert gefrorenen Alpha-Stand.

---

### 62. Beta Tags

Spätere Meilensteine können:

```text
beta-spec-v0.1
beta-v0.1.0
```

getrennt markieren.

---

### 63. Release

App-Releases und Spec-Tags werden nicht verwechselt.

---

## Teil XV – .gitignore

### 64. Personal Data

Mindestens ausgeschlossen:

- lokale `state_root`;
- `athena.db`;
- archive blobs;
- protected data;
- backups;
- user config/secrets;
- runtime logs;
- generated caches.

---

### 65. Environment

Auch:

- `.venv`;
- Python caches;
- IDE local state;
- build artifacts.

---

### 66. No Secret Commit

Tests nutzen Dummysecrets. Echte API Keys gelangen nicht ins Repo.

---

## Teil XVI – Sample Data

### 67. Fixtures

Testfixtures enthalten künstliche oder lizenzrechtlich geeignete Daten.

---

### 68. No User Archive

Entwicklungsfixtures werden nicht aus dem realen persönlichen ATHENA-Archiv kopiert.

---

### 69. Protected Fixtures

Securitytests verwenden synthetische eindeutig erkennbare Teststrings.

---

## Teil XVII – Build/Packaging

### 70. Packaging

`packaging/` enthält Installer-/Bundlekonfiguration.

---

### 71. Reproducibility

Buildprozess soll aus Gitcommit + Dependency Lock reproduzierbar sein.

---

### 72. Version Injection

Build erhält Appversion und Gitcommit in technische Metadaten.

---

## Teil XVIII – AI Coding Support

### 73. Repo Indexability

Klare Modulnamen, kleine Files und stabile Interfaces erleichtern AI-gestützte Navigation.

---

### 74. Spec References

Kritische Module können in Docstrings/README auf relevante Beta-Kapitel verweisen.

---

### 75. No Full Repo Prompt Requirement

Entwicklung soll durch symbolische Suche, Tests und gezieltes Retrieval möglich sein; kein Agent muss das gesamte Repo in einem Kontextfenster halten.

---

## Teil XIX – Tests

### 76. Import Boundary Test

Domainmodule dürfen nicht Qt/SQLite direkt importieren, wo Ports vorgesehen sind.

---

### 77. Secret Scan

CI prüft auf bekannte Secretmuster.

---

### 78. Gitignore Test

Testlauf darf keine Runtime-DB/Archivefiles als untracked Produktionsartefakte im Repo erzeugen.

---

### 79. Architecture Smoke

Corepackage muss ohne Desktop UI importierbar/startbar sein.

---

### 80. Recovery Dependency Test

Minimal Recovery darf ohne Modell-/Obsidian-/Pluginpakete starten.

---

### 81. Packaging Test

Clean checkout → dependency install → tests → build.

---

### 82. Abschluss

Die Repositorystruktur ist bestanden, wenn ein Entwickler oder Coding-Agent schnell den zuständigen Modulbereich findet, während persönliche Daten, UI, Domain und technische Adapter sauber getrennt bleiben.

---

## Nächster Schritt

**Beta Kapitel 26 – Teststrategie**.
