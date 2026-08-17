"""CLI parser/dispatch helpers for Research, external access, resources, and backup."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from athena.external.gateway import ExternalDirectApprovalRequired
from athena.resources.manager import ResourceMode

if TYPE_CHECKING:
    from athena.core.application import AthenaApplication


class OperationalCommandError(RuntimeError):
    """Normalized operational CLI error."""


def add_operational_parsers(commands: Any) -> None:
    research = commands.add_parser(
        "research",
        help="Exhaustive Research result, promotion, and external-source workflows.",
    )
    research_commands = research.add_subparsers(dest="research_command", required=True)

    enqueue = research_commands.add_parser("enqueue", help="Queue local Exhaustive Research.")
    enqueue.add_argument("query")
    enqueue.add_argument("--source", dest="source_ids", action="append", type=uuid.UUID, default=[])
    _add_research_model_args(enqueue)

    web = research_commands.add_parser(
        "web-enqueue",
        help="Capture explicit authorized URLs into Raw Archive, then queue Research.",
    )
    web.add_argument("query")
    web.add_argument("--authorization", type=uuid.UUID, required=True)
    web.add_argument("--url", dest="urls", action="append", required=True)
    _add_research_model_args(web)

    show = research_commands.add_parser(
        "show",
        help="Show one immutable ResearchResult by result/scope/job UUID.",
    )
    show.add_argument("identifier", type=uuid.UUID)

    propose = research_commands.add_parser(
        "propose",
        help="Freeze reviewable Knowledge/Claim proposals from one ResearchResult.",
    )
    propose.add_argument("result_id", type=uuid.UUID)

    proposals = research_commands.add_parser(
        "proposals",
        help="List frozen proposals for one ResearchResult.",
    )
    proposals.add_argument("result_id", type=uuid.UUID)

    accept = research_commands.add_parser(
        "accept",
        help="Explicitly accept one pending Research proposal.",
    )
    accept.add_argument("proposal_id", type=uuid.UUID)
    accept.add_argument(
        "--keep-separate-near-duplicates",
        action="store_true",
        help="Explicitly keep a surfaced canonical near-duplicate separate.",
    )

    reject = research_commands.add_parser(
        "reject",
        help="Reject/acknowledge one pending Research proposal.",
    )
    reject.add_argument("proposal_id", type=uuid.UUID)

    external = commands.add_parser(
        "external",
        help="Explicit fail-closed external access authorization and Source capture.",
    )
    external_commands = external.add_subparsers(dest="external_command", required=True)
    authorize = external_commands.add_parser("authorize", help="Create explicit user authorization.")
    authorize.add_argument("purpose")
    authorize.add_argument("--host", dest="hosts", action="append", required=True)
    authorize.add_argument(
        "--privacy-route",
        choices=("tor_preferred", "tor", "direct_explicit"),
        default="tor_preferred",
    )
    authorize.add_argument("--ttl-seconds", type=int, default=1800)
    approve_direct = external_commands.add_parser(
        "approve-direct",
        help="Create a separate short-lived Direct authorization from Tor Preferred.",
    )
    approve_direct.add_argument("authorization_id", type=uuid.UUID)
    approve_direct.add_argument("host")
    approve_direct.add_argument("--ttl-seconds", type=int, default=900)
    capture = external_commands.add_parser("capture", help="Capture one authorized URL.")
    capture.add_argument("authorization_id", type=uuid.UUID)
    capture.add_argument("url")
    revoke = external_commands.add_parser("revoke", help="Revoke an authorization.")
    revoke.add_argument("authorization_id", type=uuid.UUID)

    resource = commands.add_parser("resource", help="Resource status and scheduling mode.")
    resource_commands = resource.add_subparsers(dest="resource_command", required=True)
    resource_commands.add_parser("status", help="Show current resource snapshot/policy.")
    resource_mode = resource_commands.add_parser("mode", help="Set resource scheduling mode.")
    resource_mode.add_argument("mode", choices=tuple(item.value for item in ResourceMode))

    delete = commands.add_parser(
        "delete",
        help="Preview and execute explicit lifecycle deletion.",
    )
    delete_commands = delete.add_subparsers(
        dest="delete_command",
        required=True,
    )
    delete_preview = delete_commands.add_parser(
        "preview",
        help="Show payload-free deletion dependencies.",
    )
    delete_preview.add_argument(
        "entity_id",
        type=uuid.UUID,
    )
    delete_apply = delete_commands.add_parser(
        "apply",
        help="Apply a reviewed deletion preview.",
    )
    delete_apply.add_argument(
        "entity_id",
        type=uuid.UUID,
    )
    delete_apply.add_argument(
        "--preview-digest",
        required=True,
    )

    protected_scope_preview = delete_commands.add_parser(
        "protected-scope-preview",
        help="Preview destructive ProtectionScope crypto-erasure.",
    )
    protected_scope_preview.add_argument(
        "protection_scope_id",
        type=uuid.UUID,
    )

    protected_scope_apply = delete_commands.add_parser(
        "protected-scope-apply",
        help="Apply reviewed ProtectionScope crypto-erasure.",
    )
    protected_scope_apply.add_argument(
        "protection_scope_id",
        type=uuid.UUID,
    )
    protected_scope_apply.add_argument(
        "--preview-digest",
        required=True,
    )

    backup = commands.add_parser("backup", help="Verified backup and isolated restore.")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser(
        "create",
        help="Create and verify a backup.",
    )
    backup_create_target = backup_create.add_mutually_exclusive_group()
    backup_create_target.add_argument("--target", type=Path)
    backup_create_target.add_argument("--target-id", type=uuid.UUID)
    backup_list = backup_commands.add_parser("list", help="List backup snapshots.")
    backup_list.add_argument("--limit", type=int, default=50)
    backup_verify = backup_commands.add_parser("verify", help="Verify one backup snapshot.")
    backup_verify.add_argument("snapshot_id", type=uuid.UUID)
    backup_verify.add_argument(
        "--deep",
        action="store_true",
        help=(
            "Hash every backup object and "
            "perform an isolated restore smoke."
        ),
    )
    backup_restore = backup_commands.add_parser(
        "restore",
        help="Restore one snapshot into a new/empty isolated ATHENA root.",
    )
    backup_restore.add_argument("snapshot_id", type=uuid.UUID)
    backup_restore.add_argument("destination_root", type=Path)
    backup_restore_path = backup_commands.add_parser(
        "restore-path",
        help="Restore a completed backup path without relying on live backup metadata.",
    )
    backup_restore_path.add_argument("snapshot_root", type=Path)
    backup_restore_path.add_argument("destination_root", type=Path)

    backup_target = backup_commands.add_parser(
        "target",
        help="Manage durable backup targets.",
    )
    backup_target_commands = backup_target.add_subparsers(
        dest="backup_target_command",
        required=True,
    )
    backup_target_add = backup_target_commands.add_parser(
        "add",
        help="Register or reattach a backup target.",
    )
    backup_target_add.add_argument("root", type=Path)
    backup_target_commands.add_parser(
        "list",
        help="List registered backup targets.",
    )
    backup_target_status = backup_target_commands.add_parser(
        "status",
        help="Refresh one backup target status.",
    )
    backup_target_status.add_argument("target_id", type=uuid.UUID)

    backup_target_sync = backup_target_commands.add_parser(
        "sync",
        help="Synchronize pending deletion-ledger records.",
    )
    backup_target_sync.add_argument(
        "target_id",
        type=uuid.UUID,
    )
    backup_target_policy = backup_target_commands.add_parser(
        "policy",
        help="Set one target retention policy.",
    )
    backup_target_policy.add_argument("target_id", type=uuid.UUID)
    backup_target_policy.add_argument("--daily", type=int, required=True)
    backup_target_policy.add_argument("--weekly", type=int, required=True)
    backup_target_policy.add_argument("--monthly", type=int, required=True)
    backup_target_policy.add_argument("--yearly", type=int, required=True)

    backup_retention = backup_commands.add_parser(
        "retention",
        help="Preview or apply deterministic backup retention.",
    )
    backup_retention_commands = backup_retention.add_subparsers(
        dest="backup_retention_command",
        required=True,
    )
    backup_retention_plan = backup_retention_commands.add_parser(
        "plan",
        help="Preview retention without deleting anything.",
    )
    backup_retention_plan.add_argument("target_id", type=uuid.UUID)
    backup_retention_apply = backup_retention_commands.add_parser(
        "apply",
        help="Apply retention and safe backup-object GC.",
    )
    backup_retention_apply.add_argument("target_id", type=uuid.UUID)


def run_operational_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    try:
        if args.command == "research":
            return _run_research(app, args)
        if args.command == "external":
            return _run_external(app, args)
        if args.command == "resource":
            return _run_resource(app, args)
        if args.command == "delete":
            return _run_delete(app, args)
        if args.command == "backup":
            return _run_backup(app, args)
    except (ValueError, RuntimeError, OSError) as exc:
        raise OperationalCommandError(f"{type(exc).__name__}: {exc}") from exc
    raise OperationalCommandError(f"Unsupported operational command: {args.command!r}")


def _add_research_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", dest="model_id")
    parser.add_argument("--context-limit", type=int)
    parser.add_argument("--output-reserve", type=int)
    parser.add_argument("--safety-margin", type=int)


def _run_research(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.research_command == "enqueue":
        job = app.research.enqueue_local(
            query=args.query,
            explicit_source_ids=tuple(args.source_ids),
            requested_model_id=args.model_id,
            context_limit=args.context_limit,
            output_reserve=args.output_reserve,
            safety_margin=args.safety_margin,
        )
        print(f"Research job: {job.job_id}")
        print(f"URI: {job.uri}")
        return 0

    if args.research_command == "web-enqueue":
        job = app.external_research.enqueue(
            query=args.query,
            authorization_id=args.authorization,
            urls=tuple(args.urls),
            requested_model_id=args.model_id,
            context_limit=args.context_limit,
            output_reserve=args.output_reserve,
            safety_margin=args.safety_margin,
        )
        print(f"External Research job: {job.job_id}")
        print(f"URI: {job.uri}")
        return 0

    if args.research_command == "show":
        view = app.research_promotion.result_view(args.identifier)
        print(json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.research_command == "propose":
        proposal_set = app.research_promotion.create_proposals(args.result_id)
        print(f"Proposal set: {proposal_set.proposal_set_id}")
        print(f"Result: {proposal_set.result_id}")
        _print_proposals(
            app.research_promotion.list_proposals(proposal_set.proposal_set_id)
        )
        return 0

    if args.research_command == "proposals":
        proposals = app.research_promotion.proposals_for_result(args.result_id)
        _print_proposals(proposals)
        return 0

    if args.research_command == "accept":
        accepted = app.research_promotion.accept(
            args.proposal_id,
            keep_separate_near_duplicates=args.keep_separate_near_duplicates,
        )
        print(f"Accepted proposal: {accepted.proposal_id}")
        print(f"Entity: {accepted.entity_id}")
        print(f"Revision: {accepted.revision_id}")
        print(f"Commit: {accepted.commit_id}")
        return 0

    if args.research_command == "reject":
        rejected = app.research_promotion.reject(args.proposal_id)
        print(f"Rejected proposal: {rejected.proposal_id}")
        print(f"State: {rejected.state.value}")
        return 0

    raise OperationalCommandError(
        f"Unsupported research command: {args.research_command!r}"
    )


def _print_proposals(proposals: tuple[Any, ...]) -> None:
    if not proposals:
        print("No frozen Research proposals.")
        return
    for item in proposals:
        print(
            f"[{item.ordinal}] {item.proposal_id} "
            f"type={item.proposal_type.value} state={item.state.value} "
            f"evidence={item.evidence_kind}:{item.evidence_ordinal}"
        )
        print(f"    {item.payload_json}")


def _run_external(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.external_command == "authorize":
        authorization = app.external_access.authorize_explicit(
            purpose=args.purpose,
            allowed_hosts=tuple(args.hosts),
            privacy_route=args.privacy_route,
            ttl_seconds=args.ttl_seconds,
        )
        print(f"Authorization: {authorization.authorization_id}")
        print(f"Route: {authorization.privacy_route}")
        print(f"Expires at us: {authorization.expires_at_us}")
        if authorization.privacy_route == "tor_preferred":
            print(
                "Fallback policy: Tor first; direct access requires a separate "
                "explicit direct_explicit authorization."
            )
        return 0
    if args.external_command == "approve-direct":
        authorization = app.external_access.authorize_direct_fallback(
            args.authorization_id,
            host=args.host,
            ttl_seconds=args.ttl_seconds,
        )
        print(f"Direct authorization: {authorization.authorization_id}")
        print(f"Route: {authorization.privacy_route}")
        print(f"Expires at us: {authorization.expires_at_us}")
        print("This authorization is separate; Tor Preferred was not silently bypassed.")
        return 0
    if args.external_command == "capture":
        try:
            result = app.external_access.capture_url(args.authorization_id, args.url)
        except ExternalDirectApprovalRequired as exc:
            host = urlsplit(exc.url).hostname
            print("Tor could not fetch this source; direct access was NOT used.")
            if host is not None:
                print(
                    "To permit direct access explicitly, run: "
                    f"athena external approve-direct {args.authorization_id} {host}"
                )
            raise
        print(f"Captured Source: {result.source.source_id}")
        print(f"Type: {result.source.source_type.value}")
        print(f"SHA-256: {result.source.content_sha256.hex()}")
        return 0
    if args.external_command == "revoke":
        authorization = app.external_access.revoke(args.authorization_id)
        print(f"Revoked: {authorization.authorization_id}")
        print(f"Revoked at us: {authorization.revoked_at_us}")
        return 0
    raise OperationalCommandError(
        f"Unsupported external command: {args.external_command!r}"
    )


def _run_resource(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.resource_command == "status":
        policy = app.resources.policy()
        snapshot = app.resources.snapshot()
        print(f"Mode: {policy.mode.value}")
        print(f"RAM available: {snapshot.ram_available_bytes}")
        print(f"Disk free: {snapshot.disk_free_bytes}")
        print(f"CPU load: {snapshot.cpu_load_fraction}")
        print(f"GPU load: {snapshot.gpu_utilization_fraction}")
        print(f"VRAM available: {snapshot.vram_available_bytes}")
        print(f"Primary LLM loaded: {snapshot.model_loaded}")
        print(f"Degraded metrics: {','.join(snapshot.degraded_metrics) or '<none>'}")
        return 0
    if args.resource_command == "mode":
        policy = app.resources.set_mode(ResourceMode(args.mode))
        print(f"Resource mode: {policy.mode.value}")
        return 0
    raise OperationalCommandError(
        f"Unsupported resource command: {args.resource_command!r}"
    )


def _run_delete(
    app: AthenaApplication,
    args: argparse.Namespace,
) -> int:
    if args.delete_command == "preview":
        preview = app.lifecycle_deletion.preview(
            args.entity_id
        )

        print(
            f"Entity: {preview.entity_id}"
        )
        print(
            f"Type: {preview.entity_type}"
        )
        print(
            f"Lifecycle: {preview.lifecycle_state}"
        )
        print(
            f"Preview digest: {preview.preview_digest}"
        )
        print(
            "Dependencies: "
            f"{len(preview.dependencies)}"
        )

        for dependency in preview.dependencies:
            dependent_id = (
                str(
                    dependency.dependent_entity_id
                )
                if dependency.dependent_entity_id
                is not None
                else "<none>"
            )

            dependent_type = (
                dependency.dependent_entity_type
                or "<none>"
            )

            print(
                "  "
                f"{dependency.relation} "
                f"count={dependency.count} "
                f"entity={dependent_id} "
                f"type={dependent_type}"
            )

        return 0

    if args.delete_command == "apply":
        result = app.lifecycle_deletion.delete(
            args.entity_id,
            preview_digest=args.preview_digest,
        )

        print(
            f"Deleted entity: {result.entity_id}"
        )
        print(
            f"Type: {result.entity_type}"
        )
        print(
            f"Commit: {result.commit_id}"
        )
        print(
            "Logical entities deleted: "
            f"{len(result.deleted_entity_ids)}"
        )

        return 0

    if args.delete_command == "protected-scope-preview":
        protected_preview = app.protected_scope_purge.preview(
            args.protection_scope_id
        )
        print(
            f"Protection scope: {protected_preview.protection_scope_id}"
        )
        print(
            f"Lifecycle: {protected_preview.lifecycle_state}"
        )
        print(
            f"Sources: {protected_preview.source_count}"
        )
        print(
            "Protected payloads: "
            f"{protected_preview.protected_payload_count}"
        )
        print(
            "Protected blobs: "
            f"{protected_preview.protected_blob_count}"
        )
        print(
            f"Scope keys: {protected_preview.scope_key_count}"
        )
        print(
            f"Preview digest: {protected_preview.preview_digest}"
        )
        return 0

    if args.delete_command == "protected-scope-apply":
        protected_result = app.protected_scope_purge.delete(
            args.protection_scope_id,
            preview_digest=args.preview_digest,
        )
        print(
            "Protection scope deleted: "
            f"{protected_result.protection_scope_id}"
        )
        print(
            "Deleted Sources: "
            f"{len(protected_result.deleted_source_ids)}"
        )
        print(
            "Destroyed Scope Keys: "
            f"{protected_result.destroyed_scope_key_count}"
        )
        print(
            "Removed Protected Payloads: "
            f"{protected_result.removed_payload_count}"
        )
        print(
            "Removed Blob Envelopes: "
            f"{protected_result.removed_blob_envelope_count}"
        )
        print(
            "Deleted ciphertext replicas: "
            f"{protected_result.deleted_replica_count}"
        )
        print(
            f"Commit: {protected_result.commit_id}"
        )
        return 0

    raise OperationalCommandError(
        "Unsupported delete command: "
        f"{args.delete_command!r}"
    )


def _run_backup(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.backup_command == "create":
        snapshot = app.backup.create_snapshot(
            target_root=args.target,
            target_id=args.target_id,
        )
        _print_backup(snapshot)
        return 0
    if args.backup_command == "list":
        for snapshot in app.backup.list_snapshots(limit=args.limit):
            _print_backup(snapshot)
        return 0
    if args.backup_command == "verify":
        snapshot = (
            app.backup.verify_deep(args.snapshot_id)
            if getattr(args, "deep", False)
            else app.backup.verify_light(args.snapshot_id)
        )
        _print_backup(snapshot)
        return 0
    if args.backup_command == "restore":
        destination = app.backup.restore_to(
            args.snapshot_id,
            destination_root=args.destination_root,
        )
        print(f"Restored isolated ATHENA root: {destination}")
        print("Live ATHENA roots were not activated or overwritten.")
        return 0
    if args.backup_command == "restore-path":
        destination = app.backup.restore_path(
            args.snapshot_root,
            destination_root=args.destination_root,
        )
        print(f"Restored isolated ATHENA root: {destination}")
        print(
            "Restore used only the completed backup path, "
            "not live snapshot metadata."
        )
        return 0
    if args.backup_command == "target":
        return _run_backup_target(app, args)
    if args.backup_command == "retention":
        return _run_backup_retention(app, args)
    raise OperationalCommandError(
        f"Unsupported backup command: {args.backup_command!r}"
    )



def _run_backup_target(
    app: AthenaApplication,
    args: argparse.Namespace,
) -> int:
    if args.backup_target_command == "add":
        _print_backup_target(
            app.backup.register_target(
                args.root
            )
        )
        return 0

    if args.backup_target_command == "list":
        for target in app.backup.list_targets():
            _print_backup_target(target)
        return 0

    if args.backup_target_command == "status":
        _print_backup_target(
            app.backup.target_status(
                args.target_id
            )
        )
        return 0

    if args.backup_target_command == "sync":
        _print_backup_target(
            app.backup.sync_deletion_ledger(
                args.target_id
            )
        )
        return 0

    if args.backup_target_command == "policy":
        _print_backup_target(
            app.backup.set_retention_policy(
                args.target_id,
                daily=args.daily,
                weekly=args.weekly,
                monthly=args.monthly,
                yearly=args.yearly,
            )
        )
        return 0

    raise OperationalCommandError(
        "Unsupported backup target command: "
        f"{args.backup_target_command!r}"
    )


def _run_backup_retention(
    app: AthenaApplication,
    args: argparse.Namespace,
) -> int:
    if args.backup_retention_command == "plan":
        plan = app.backup.plan_retention(
            args.target_id
        )
        _print_retention_plan(plan)
        return 0

    if args.backup_retention_command == "apply":
        result = app.backup.apply_retention(
            args.target_id
        )
        _print_retention_plan(
            result.plan
        )
        print(
            "Pruned: "
            f"{len(result.pruned_snapshot_ids)}"
        )
        print(
            "Deleted backup objects: "
            f"{result.deleted_object_count}"
        )
        return 0

    raise OperationalCommandError(
        "Unsupported backup retention command: "
        f"{args.backup_retention_command!r}"
    )


def _print_backup_target(target: Any) -> None:
    print(
        f"{target.target_id} "
        f"status={target.status} "
        f"root={target.root_path}"
    )
    print(
        "Retention: "
        f"daily={target.policy.daily} "
        f"weekly={target.policy.weekly} "
        f"monthly={target.policy.monthly} "
        f"yearly={target.policy.yearly}"
    )
    print(
        "Last successful backup us: "
        f"{target.last_successful_backup_at_us}"
    )
    print(
        "Last verification us: "
        f"{target.last_verified_at_us}"
    )
    print(
        "Deletion ledger watermark: "
        f"{target.deletion_ledger_watermark}"
    )
    print(
        "Deletion sync pending: "
        f"{'yes' if target.deletion_sync_pending else 'no'}"
    )


def _print_retention_plan(plan: Any) -> None:
    print(
        f"Target: {plan.target_id}"
    )
    print(
        "Keep: "
        + (
            ",".join(
                str(item)
                for item in plan.keep_snapshot_ids
            )
            or "<none>"
        )
    )
    print(
        "Prune: "
        + (
            ",".join(
                str(item)
                for item in plan.prune_snapshot_ids
            )
            or "<none>"
        )
    )



def _print_backup(snapshot: Any) -> None:
    print(
        f"{snapshot.snapshot_id} state={snapshot.state} "
        f"verify={snapshot.verification_status} "
        f"commit={snapshot.snapshot_commit_seq} "
        f"objects={snapshot.object_count} path={snapshot.relative_path}"
    )
