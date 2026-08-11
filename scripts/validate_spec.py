#!/usr/bin/env python3
from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[1]
ALPHA = ROOT / 'docs' / 'alpha'
BETA = ROOT / 'docs' / 'beta'

checks=[]
def check(name, ok, detail=''):
    checks.append((name,bool(ok),detail))

all_files=[p for p in ROOT.rglob('*') if p.is_file()]
md=list(ROOT.rglob('*.md'))

check('No non-ASCII repository filenames', all(all(ord(c)<128 for c in p.name) for p in all_files), ', '.join(str(p.relative_to(ROOT)) for p in all_files if any(ord(c)>=128 for c in p.name)))
check('No extensionless duplicate files in docs/beta', not any(p.is_file() and '.' not in p.name for p in BETA.iterdir()))
check('No stale package metadata', not (ROOT/'docs/README_PACKAGE.md').exists() and not (ROOT/'docs/SHA256SUMS.txt').exists())
check('.gitignore exists', (ROOT/'.gitignore').exists())
check('.gitattributes exists', (ROOT/'.gitattributes').exists())
check('No .gitkeep remains', not any(p.name=='.gitkeep' for p in all_files))
check('No literal #U00 filename artifacts', not any('#U00' in str(p.relative_to(ROOT)) for p in all_files))
bad_u_links=[]
for p in md:
    txt=p.read_text(encoding='utf-8', errors='ignore')
    for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', txt):
        if '#U00' in target:
            bad_u_links.append(f'{p.relative_to(ROOT)} -> {target}')
check('No literal #U00 link targets', not bad_u_links, '; '.join(bad_u_links))

# file count / numbering
alpha_ch=sorted(ALPHA.glob('[0-9][0-9]_*.md'))
beta_ch=sorted(BETA.glob('[0-9][0-9]_*.md'))
check('29 Alpha chapters', len(alpha_ch)==29, str(len(alpha_ch)))
check('Alpha filenames 01-29', [int(p.name[:2]) for p in alpha_ch]==list(range(1,30)), str([p.name for p in alpha_ch]))
check('27 Beta chapters', len(beta_ch)==27, str(len(beta_ch)))
check('Beta filenames 01-27', [int(p.name[:2]) for p in beta_ch]==list(range(1,28)), str([p.name for p in beta_ch]))

# Markdown structure
bad_h1=[]; bad_fence=[]; trailing=[]; dup_sep=[]
for p in md:
    t=p.read_text(encoding='utf-8')
    if sum(1 for l in t.splitlines() if l.startswith('# ')) != 1: bad_h1.append(str(p.relative_to(ROOT)))
    if sum(1 for l in t.splitlines() if l.strip().startswith('```')) % 2: bad_fence.append(str(p.relative_to(ROOT)))
    if any(l.rstrip()!=l for l in t.splitlines()): trailing.append(str(p.relative_to(ROOT)))
    if re.search(r'(?m)^---\s*$\n\s*\n^---\s*$',t): dup_sep.append(str(p.relative_to(ROOT)))
check('Exactly one H1 per Markdown file', not bad_h1, ', '.join(bad_h1))
check('Balanced code fences', not bad_fence, ', '.join(bad_fence))
check('No trailing whitespace', not trailing, ', '.join(trailing))
check('No duplicate horizontal rules', not dup_sep, ', '.join(dup_sep))

# numbered beta section sequences (ignore unnumbered h3)
bad_nums=[]
for p in beta_ch:
    t=p.read_text(encoding='utf-8')
    nums=[int(x) for x in re.findall(r'(?m)^### (\d+)\.',t)]
    if nums and nums != list(range(1,max(nums)+1)):
        bad_nums.append(f'{p.name}:{nums[:10]}...{nums[-10:]}')
check('Beta numbered sections are contiguous', not bad_nums, '; '.join(bad_nums))

# links
broken=[]
link_re=re.compile(r'\[[^\]]*\]\(([^)]+)\)')
for p in md:
    t=p.read_text(encoding='utf-8')
    for target in link_re.findall(t):
        target=target.strip()
        if not target or target.startswith(('http://','https://','mailto:','#')): continue
        pathpart=target.split('#',1)[0]
        if not pathpart: continue
        # ignore code-like URLs without scheme only if clearly not relative file
        q=(p.parent/pathpart).resolve()
        if not q.exists(): broken.append(f'{p.relative_to(ROOT)} -> {target}')
check('All relative Markdown links resolve', not broken, '; '.join(broken[:30]))

# indexes link every chapter
for label,idx,chapters in [('Alpha',ALPHA/'INDEX.md',alpha_ch),('Beta',BETA/'INDEX.md',beta_ch)]:
    t=idx.read_text(encoding='utf-8')
    missing=[p.name for p in chapters if p.name not in t]
    check(f'{label} INDEX links every chapter', not missing, ', '.join(missing))

alltext='\n'.join(p.read_text(encoding='utf-8') for p in md)
alpha_text='\n'.join(p.read_text(encoding='utf-8') for p in ALPHA.glob('*.md') if p.name!='CHANGES_ALPHA_v2.0.md')
beta_text='\n'.join(p.read_text(encoding='utf-8') for p in BETA.glob('*.md'))

# version/state consistency
check('Current Alpha is v2.0.1', 'ATHENA_ALPHA v2.0.1 FINAL' in (ALPHA/'INDEX.md').read_text(encoding='utf-8'))
check('Beta basis is Alpha v2.0.1', 'ATHENA Alpha v2.0.1 Final' in (BETA/'INDEX.md').read_text(encoding='utf-8'))
check('No stale Alpha v2.0 normative refs', not re.search(r'ATHENA_ALPHA v2\.0(?!\.1)|ATHENA Alpha v2\.0(?!\.1)', alpha_text+'\n'+beta_text))

# known audit blockers/regressions
check('Alpha source-derived provenance qualified', 'Alle **aus Quellen abgeleiteten** Interpretationen' in (ALPHA/'05_Roharchiv_und_Quellenmanagement.md').read_text())
check('Alpha direct-user semantic path explicit', 'Direkte Benutzererstellung und Benutzerkorrektur benötigen weder eine künstliche Originalquelle' in (ALPHA/'06_Wissensextraktion_und_Wissensgraph.md').read_text())
check('Long-term replication architecture specified', all(x in beta_text for x in ['long_term_root','replication_pending','long_term_confirmed_commit_seq','CanonicalCommitBundle']))
check('Live network SQLite explicitly prohibited', 'Keine live SQLite-Datenbank auf Netzwerkfreigaben' in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text())
check('SourceChunk explicitly Derived State', '`SourceChunk` ist eine **reproduzierbare Derived-State-Verarbeitungseinheit**' in (BETA/'02_Persistentes_Datenmodell_und_ID_System.md').read_text())
check('SourceChunk absent from Raw Archive inventory', not re.search(r'### Raw Archive\s+```text[\s\S]{0,300}?SourceChunk', (BETA/'02_Persistentes_Datenmodell_und_ID_System.md').read_text()))
check('Visual semantic authority remains user/primary model', 'ausschließlich durch den Benutzer oder das aktive Primärmodell' in (BETA/'04_Quellen_Roharchiv_und_Import-Pipeline.md').read_text())
check('Protected source metadata schema exists', 'protected_metadata_payload_id' in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text())
check('Protected content hash rule covers all content hashes', all(x in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text() for x in ['revisions.payload_hash','source_representations.content_hash','source_anchors.quoted_hash','embedding_records.content_hash']))
check('Persistent key hierarchy fully represented', all(x in beta_text for x in ['key_slots','protection_scope_keys','protected_blob_envelopes','wrapped_root_key','wrapped_scope_key','wrapped_dek']))
check('Protected Durable Operational State specified', all(x in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text() for x in ['jobs','checkpoints','research_scopes','protection_scope_id BLOB(16) NULL','protected_payload_id BLOB(16) NULL']))
check('Protection transition job specified', 'ProtectionTransitionJob' in (BETA/'16_Sicherheitsarchitektur_und_Protected_Content.md').read_text())
check('Plugin trust boundary honest', 'Ein aktiviertes Drittplugin ist ausdrücklich vom Benutzer vertrauter lokaler Erweiterungscode.' in (BETA/'17_Plugin-System_und_Berechtigungen.md').read_text())
check('Backup-GC pin specified', 'backup_snapshot_pin' in beta_text)
check('Entity state history specified', 'entity_state_history' in beta_text and 'valid_from_commit_seq' in beta_text)
check('SQLite application_id is integer', 'PRAGMA application_id = 1096042574;' in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text())
check('Config NULL uniqueness fixed with partial indexes', all(x in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text() for x in ['uq_configuration_global','WHERE scope_entity_id IS NULL','uq_configuration_scoped']))
check('Disk thresholds use max', 'free < max(10 GiB, 5 % der Volume-Größe)' in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text() and 'free < min(' not in beta_text)
check('temporary and do_not_store distinct', '`do_not_store` ist strenger' in (BETA/'02_Persistentes_Datenmodell_und_ID_System.md').read_text())
check('Permanent deletion uses NULL restore block', 'restore_blocking_until = NULL' in (BETA/'02_Persistentes_Datenmodell_und_ID_System.md').read_text())
check('Runtime lock state not persisted', '`locked` und `unlocked` sind **keine persistenten Scope-Zustände**' in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text())

# additional cross-system regression checks
check('Root README links Alpha and Beta indexes', all(x in (ROOT/'README.md').read_text(encoding='utf-8') for x in ['docs/alpha/INDEX.md','docs/beta/INDEX.md']))
check('Beta INDEX chapter statuses match consolidated state', '**Status:** Vollständiger erster Entwurf' not in (BETA/'INDEX.md').read_text(encoding='utf-8'))
check('SourceChunk URI is derived, not archive', 'derived://chunk/<chunk_id>' in (BETA/'02_Persistentes_Datenmodell_und_ID_System.md').read_text() and 'archive://chunk/<chunk_id>' not in beta_text)
check('Beta01 also classifies chunks as Derived State', 'reproduzierbare Derived-State-Verarbeitungseinheiten' in (BETA/'01_Systemarchitektur_und_Technische_Basis.md').read_text())
check('As-of retrieval uses entity_state_history', 'entity_state_history' in (BETA/'10_Retrieval_und_Suche.md').read_text())
check('Recovery always starts protected scopes runtime-locked', 'runtime-locked' in (BETA/'22_Recovery_Mode_und_Selbstdiagnose.md').read_text())
check('Key wrapping primitive concrete for v1', all(x in (BETA/'03_Storage_Datenbanken_und_Migrationen.md').read_text() for x in ['wrap_algorithm = AES-256-GCM','96 Bit','AAD']))
check('Security chapter matches AES-GCM wrapping', 'Wrapping-Schritte konkret **AES-256-GCM**' in (BETA/'16_Sicherheitsarchitektur_und_Protected_Content.md').read_text())
check('Backup has explicit GC race test', 'Backup-GC-Race-Test' in (BETA/'21_Backup_und_Restore.md').read_text())
check('Alpha distinguishes temporary from not-store', '„Nicht speichern“ ist strenger als ein temporärer Chat' in (ALPHA/'22_Kontextmanagement,_Gespraeche_und_Kontinuitaet.md').read_text())
gitignore=(ROOT/'.gitignore').read_text(encoding='utf-8')
check('Repository ignores runtime DB/secrets', all(x in gitignore for x in ['*.db','*.db-wal','.env','/secrets/','/archive/','/backups/']))
check('Runtime directory ignores are root-anchored', all(('\n/'+name+'/') in ('\n'+gitignore) for name in ['state','data','runtime','archive','backups','logs','cache','derived','spool','recovery','projections']))
check('Source module names are not globally ignored', all(('\n'+name+'/') not in ('\n'+gitignore) for name in ['archive','recovery']))
check('Synthetic migration DB fixtures can be explicitly included', '!tests/migration/fixtures/**/*.db' in gitignore)

# old contradictory wording guards
guards=[
    'Der gesamte Prozess folgt immer derselben Reihenfolge',
    'Das Roharchiv ist die historische Wahrheit von ATHENA',
    'Alle späteren Wissenseinheiten bauen auf dieser Grundlage auf',
    'Eine vollständige visuelle semantische Interpretation wird nur über dafür freigegebene Infrastruktur- oder Primärmodellprozesse ergänzt',
    'free < min(10 GiB, 5 % der Volume-Größe)',
]
for g in guards:
    check(f'Old wording absent: {g[:45]}', g not in alltext)

failed=[c for c in checks if not c[1]]
for name,ok,detail in checks:
    print(('PASS' if ok else 'FAIL')+': '+name+((' — '+detail) if detail and not ok else ''))
print(f'\nTOTAL {len(checks)-len(failed)}/{len(checks)} PASS')
if failed:
    sys.exit(1)
