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

    backup = commands.add_parser("backup", help="Verified backup and isolated restore.")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser("create", help="Create and verify a backup.")
    backup_create.add_argument("--target", type=Path)
    backup_list = backup_commands.add_parser("list", help="List backup snapshots.")
    backup_list.add_argument("--limit", type=int, default=50)
    backup_verify = backup_commands.add_parser("verify", help="Verify one backup snapshot.")
    backup_verify.add_argument("snapshot_id", type=uuid.UUID)
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


def run_operational_command(app: AthenaApplication, args: argparse.Namespace) -> int:
    try:
        if args.command == "research":
            return _run_research(app, args)
        if args.command == "external":
            return _run_external(app, args)
        if args.command == "resource":
            return _run_resource(app, args)
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


def _run_backup(app: AthenaApplication, args: argparse.Namespace) -> int:
    if args.backup_command == "create":
        snapshot = app.backup.create_snapshot(target_root=args.target)
        _print_backup(snapshot)
        return 0
    if args.backup_command == "list":
        for snapshot in app.backup.list_snapshots(limit=args.limit):
            _print_backup(snapshot)
        return 0
    if args.backup_command == "verify":
        snapshot = app.backup.verify(args.snapshot_id)
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
        print("Restore used only the completed backup path, not live snapshot metadata.")
        return 0
    raise OperationalCommandError(
        f"Unsupported backup command: {args.backup_command!r}"
    )


def _print_backup(snapshot: Any) -> None:
    print(
        f"{snapshot.snapshot_id} state={snapshot.state} "
        f"verify={snapshot.verification_status} "
        f"commit={snapshot.snapshot_commit_seq} "
        f"objects={snapshot.object_count} path={snapshot.relative_path}"
    )
