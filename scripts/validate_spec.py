#!/usr/bin/env python3
"""Validate structural and cross-specification ATHENA invariants."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALPHA = ROOT / "docs" / "alpha"
BETA = ROOT / "docs" / "beta"
UTF8 = "utf-8"
IGNORED_SCAN_ROOTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "build",
        "dist",
    }
)

CheckResult = tuple[str, bool, str]
checks: list[CheckResult] = []


def read_text(path: Path) -> str:
    """Read repository text deterministically on every operating system."""
    return path.read_text(encoding=UTF8)


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))


def contains_all(text: str, values: Iterable[str]) -> bool:
    return all(value in text for value in values)


def included_in_repository_scan(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return not relative.parts or relative.parts[0] not in IGNORED_SCAN_ROOTS


all_files = [
    path
    for path in ROOT.rglob("*")
    if path.is_file() and included_in_repository_scan(path)
]
markdown_files = [
    path for path in ROOT.rglob("*.md") if included_in_repository_scan(path)
]

non_ascii_files = [
    str(path.relative_to(ROOT))
    for path in all_files
    if any(ord(character) >= 128 for character in path.name)
]
check(
    "No non-ASCII repository filenames",
    not non_ascii_files,
    ", ".join(non_ascii_files),
)
check(
    "No extensionless duplicate files in docs/beta",
    not any(path.is_file() and "." not in path.name for path in BETA.iterdir()),
)
check(
    "No stale package metadata",
    not (ROOT / "docs/README_PACKAGE.md").exists()
    and not (ROOT / "docs/SHA256SUMS.txt").exists(),
)
check(".gitignore exists", (ROOT / ".gitignore").exists())
check(".gitattributes exists", (ROOT / ".gitattributes").exists())
check("No .gitkeep remains", not any(path.name == ".gitkeep" for path in all_files))
check(
    "No literal #U00 filename artifacts",
    not any("#U00" in str(path.relative_to(ROOT)) for path in all_files),
)

bad_unicode_links: list[str] = []
for path in markdown_files:
    text = read_text(path)
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        if "#U00" in target:
            bad_unicode_links.append(f"{path.relative_to(ROOT)} -> {target}")
check(
    "No literal #U00 link targets",
    not bad_unicode_links,
    "; ".join(bad_unicode_links),
)

# File count / numbering.
alpha_chapters = sorted(ALPHA.glob("[0-9][0-9]_*.md"))
beta_chapters = sorted(BETA.glob("[0-9][0-9]_*.md"))
check("29 Alpha chapters", len(alpha_chapters) == 29, str(len(alpha_chapters)))
check(
    "Alpha filenames 01-29",
    [int(path.name[:2]) for path in alpha_chapters] == list(range(1, 30)),
    str([path.name for path in alpha_chapters]),
)
check("27 Beta chapters", len(beta_chapters) == 27, str(len(beta_chapters)))
check(
    "Beta filenames 01-27",
    [int(path.name[:2]) for path in beta_chapters] == list(range(1, 28)),
    str([path.name for path in beta_chapters]),
)

# Markdown structure.
bad_h1: list[str] = []
bad_fence: list[str] = []
trailing_whitespace: list[str] = []
duplicate_separators: list[str] = []
for path in markdown_files:
    text = read_text(path)
    lines = text.splitlines()
    relative = str(path.relative_to(ROOT))

    if sum(line.startswith("# ") for line in lines) != 1:
        bad_h1.append(relative)
    if sum(line.strip().startswith("```") for line in lines) % 2:
        bad_fence.append(relative)
    if any(line.rstrip() != line for line in lines):
        trailing_whitespace.append(relative)
    if re.search(r"(?m)^---\s*$\n\s*\n^---\s*$", text):
        duplicate_separators.append(relative)

check("Exactly one H1 per Markdown file", not bad_h1, ", ".join(bad_h1))
check("Balanced code fences", not bad_fence, ", ".join(bad_fence))
check(
    "No trailing whitespace",
    not trailing_whitespace,
    ", ".join(trailing_whitespace),
)
check(
    "No duplicate horizontal rules",
    not duplicate_separators,
    ", ".join(duplicate_separators),
)

# Numbered Beta section sequences (ignore unnumbered h3 headings).
bad_numbers: list[str] = []
for path in beta_chapters:
    text = read_text(path)
    numbers = [int(value) for value in re.findall(r"(?m)^### (\d+)\.", text)]
    if numbers and numbers != list(range(1, max(numbers) + 1)):
        bad_numbers.append(f"{path.name}:{numbers[:10]}...{numbers[-10:]}")
check(
    "Beta numbered sections are contiguous",
    not bad_numbers,
    "; ".join(bad_numbers),
)

# Relative Markdown links.
broken_links: list[str] = []
link_pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
for path in markdown_files:
    text = read_text(path)
    for raw_target in link_pattern.findall(text):
        target = raw_target.strip()
        if not target or target.startswith(("http://", "https://", "mailto:", "#")):
            continue

        path_part = target.split("#", 1)[0]
        if not path_part:
            continue

        destination = (path.parent / path_part).resolve()
        if not destination.exists():
            broken_links.append(f"{path.relative_to(ROOT)} -> {target}")
check(
    "All relative Markdown links resolve",
    not broken_links,
    "; ".join(broken_links[:30]),
)

# Indexes link every chapter.
for label, index, chapters in (
    ("Alpha", ALPHA / "INDEX.md", alpha_chapters),
    ("Beta", BETA / "INDEX.md", beta_chapters),
):
    text = read_text(index)
    missing = [path.name for path in chapters if path.name not in text]
    check(f"{label} INDEX links every chapter", not missing, ", ".join(missing))

all_text = "\n".join(read_text(path) for path in markdown_files)
alpha_text = "\n".join(
    read_text(path)
    for path in ALPHA.glob("*.md")
    if path.name != "CHANGES_ALPHA_v2.0.md"
)
beta_text = "\n".join(read_text(path) for path in BETA.glob("*.md"))

alpha_index = read_text(ALPHA / "INDEX.md")
beta_index = read_text(BETA / "INDEX.md")
alpha_05 = read_text(ALPHA / "05_Roharchiv_und_Quellenmanagement.md")
alpha_06 = read_text(ALPHA / "06_Wissensextraktion_und_Wissensgraph.md")
alpha_22 = read_text(ALPHA / "22_Kontextmanagement,_Gespraeche_und_Kontinuitaet.md")
beta_01 = read_text(BETA / "01_Systemarchitektur_und_Technische_Basis.md")
beta_02 = read_text(BETA / "02_Persistentes_Datenmodell_und_ID_System.md")
beta_03 = read_text(BETA / "03_Storage_Datenbanken_und_Migrationen.md")
beta_04 = read_text(BETA / "04_Quellen_Roharchiv_und_Import-Pipeline.md")
beta_10 = read_text(BETA / "10_Retrieval_und_Suche.md")
beta_16 = read_text(BETA / "16_Sicherheitsarchitektur_und_Protected_Content.md")
beta_17 = read_text(BETA / "17_Plugin-System_und_Berechtigungen.md")
beta_21 = read_text(BETA / "21_Backup_und_Restore.md")
beta_22 = read_text(BETA / "22_Recovery_Mode_und_Selbstdiagnose.md")

# Version/state consistency.
check("Current Alpha is v2.0.1", "ATHENA_ALPHA v2.0.1 FINAL" in alpha_index)
check("Beta basis is Alpha v2.0.1", "ATHENA Alpha v2.0.1 Final" in beta_index)
check(
    "No stale Alpha v2.0 normative refs",
    not re.search(
        r"ATHENA_ALPHA v2\.0(?!\.1)|ATHENA Alpha v2\.0(?!\.1)",
        alpha_text + "\n" + beta_text,
    ),
)

# Known audit blockers/regressions.
check(
    "Alpha source-derived provenance qualified",
    "Alle **aus Quellen abgeleiteten** Interpretationen" in alpha_05,
)
check(
    "Alpha direct-user semantic path explicit",
    "Direkte Benutzererstellung und Benutzerkorrektur benötigen weder eine künstliche "
    "Originalquelle" in alpha_06,
)
check(
    "Long-term replication architecture specified",
    contains_all(
        beta_text,
        (
            "long_term_root",
            "replication_pending",
            "long_term_confirmed_commit_seq",
            "CanonicalCommitBundle",
        ),
    ),
)
check(
    "Live network SQLite explicitly prohibited",
    "Keine live SQLite-Datenbank auf Netzwerkfreigaben" in beta_03,
)
check(
    "SourceChunk explicitly Derived State",
    "`SourceChunk` ist eine **reproduzierbare Derived-State-Verarbeitungseinheit**"
    in beta_02,
)
check(
    "SourceChunk absent from Raw Archive inventory",
    not re.search(r"### Raw Archive\s+```text[\s\S]{0,300}?SourceChunk", beta_02),
)
check(
    "Visual semantic authority remains user/primary model",
    "ausschließlich durch den Benutzer oder das aktive Primärmodell" in beta_04,
)
check(
    "Protected source metadata schema exists",
    "protected_metadata_payload_id" in beta_03,
)
check(
    "Protected content hash rule covers all content hashes",
    contains_all(
        beta_03,
        (
            "revisions.payload_hash",
            "source_representations.content_hash",
            "source_anchors.quoted_hash",
            "embedding_records.content_hash",
        ),
    ),
)
check(
    "Persistent key hierarchy fully represented",
    contains_all(
        beta_text,
        (
            "key_slots",
            "protection_scope_keys",
            "protected_blob_envelopes",
            "wrapped_root_key",
            "wrapped_scope_key",
            "wrapped_dek",
        ),
    ),
)
check(
    "Protected Durable Operational State specified",
    contains_all(
        beta_03,
        (
            "jobs",
            "checkpoints",
            "research_scopes",
            "protection_scope_id BLOB(16) NULL",
            "protected_payload_id BLOB(16) NULL",
        ),
    ),
)
check("Protection transition job specified", "ProtectionTransitionJob" in beta_16)
check(
    "Plugin trust boundary honest",
    "Ein aktiviertes Drittplugin ist ausdrücklich vom Benutzer vertrauter lokaler "
    "Erweiterungscode." in beta_17,
)
check("Backup-GC pin specified", "backup_snapshot_pin" in beta_text)
check(
    "Entity state history specified",
    "entity_state_history" in beta_text and "valid_from_commit_seq" in beta_text,
)
check(
    "SQLite application_id is integer",
    "PRAGMA application_id = 1096042574;" in beta_03,
)
check(
    "Config NULL uniqueness fixed with partial indexes",
    contains_all(
        beta_03,
        (
            "uq_configuration_global",
            "WHERE scope_entity_id IS NULL",
            "uq_configuration_scoped",
        ),
    ),
)
check(
    "Disk thresholds use max",
    "free < max(10 GiB, 5 % der Volume-Größe)" in beta_03
    and "free < min(" not in beta_text,
)
check("temporary and do_not_store distinct", "`do_not_store` ist strenger" in beta_02)
check(
    "Permanent deletion uses NULL restore block",
    "restore_blocking_until = NULL" in beta_02,
)
check(
    "Runtime lock state not persisted",
    "`locked` und `unlocked` sind **keine persistenten Scope-Zustände**" in beta_03,
)

# Additional cross-system regression checks.
root_readme = read_text(ROOT / "README.md")
check(
    "Root README links Alpha and Beta indexes",
    contains_all(root_readme, ("docs/alpha/INDEX.md", "docs/beta/INDEX.md")),
)
check(
    "Beta INDEX chapter statuses match consolidated state",
    "**Status:** Vollständiger erster Entwurf" not in beta_index,
)
check(
    "SourceChunk URI is derived, not archive",
    "derived://chunk/<chunk_id>" in beta_02
    and "archive://chunk/<chunk_id>" not in beta_text,
)
check(
    "Beta01 also classifies chunks as Derived State",
    "reproduzierbare Derived-State-Verarbeitungseinheiten" in beta_01,
)
check("As-of retrieval uses entity_state_history", "entity_state_history" in beta_10)
check(
    "Recovery always starts protected scopes runtime-locked",
    "runtime-locked" in beta_22,
)
check(
    "Key wrapping primitive concrete for v1",
    contains_all(beta_03, ("wrap_algorithm = AES-256-GCM", "96 Bit", "AAD")),
)
check(
    "Security chapter matches AES-GCM wrapping",
    "Wrapping-Schritte konkret **AES-256-GCM**" in beta_16,
)
check("Backup has explicit GC race test", "Backup-GC-Race-Test" in beta_21)
check(
    "Alpha distinguishes temporary from not-store",
    "„Nicht speichern“ ist strenger als ein temporärer Chat" in alpha_22,
)

gitignore = read_text(ROOT / ".gitignore")
check(
    "Repository ignores runtime DB/secrets",
    contains_all(
        gitignore,
        ("*.db", "*.db-wal", ".env", "/secrets/", "/archive/", "/backups/"),
    ),
)
check(
    "Runtime directory ignores are root-anchored",
    all(
        f"\n/{name}/" in f"\n{gitignore}"
        for name in (
            "state",
            "data",
            "runtime",
            "archive",
            "backups",
            "logs",
            "cache",
            "derived",
            "spool",
            "recovery",
            "projections",
        )
    ),
)
check(
    "Source module names are not globally ignored",
    all(f"\n{name}/" not in f"\n{gitignore}" for name in ("archive", "recovery")),
)
check(
    "Synthetic migration DB fixtures can be explicitly included",
    "!tests/migration/fixtures/**/*.db" in gitignore,
)

# Old contradictory wording guards.
guards = (
    "Der gesamte Prozess folgt immer derselben Reihenfolge",
    "Das Roharchiv ist die historische Wahrheit von ATHENA",
    "Alle späteren Wissenseinheiten bauen auf dieser Grundlage auf",
    "Eine vollständige visuelle semantische Interpretation wird nur über dafür "
    "freigegebene Infrastruktur- oder Primärmodellprozesse ergänzt",
    "free < min(10 GiB, 5 % der Volume-Größe)",
)
for guard in guards:
    check(f"Old wording absent: {guard[:45]}", guard not in all_text)

failed = [result for result in checks if not result[1]]
for name, ok, detail in checks:
    suffix = f" — {detail}" if detail and not ok else ""
    print(f"{'PASS' if ok else 'FAIL'}: {name}{suffix}")

print(f"\nTOTAL {len(checks) - len(failed)}/{len(checks)} PASS")
if failed:
    sys.exit(1)
