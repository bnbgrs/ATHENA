"""Persistent model signatures and concrete processing runs."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob
from athena.common.time import utc_now_us
from athena.model.domain import ModelInfo
from athena.storage.database import SQLiteDatabase


class ProcessingRunNotFoundError(LookupError):
    """Raised when a requested processing run does not exist."""


@dataclass(frozen=True, slots=True)
class ModelSignature:
    model_signature_id: uuid.UUID
    provider: str
    model_identifier: str
    model_revision: str | None
    quantization: str | None
    generation_parameters_json: str
    context_configuration_json: str | None
    signature_hash: bytes
    created_at_us: int


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    processing_run_id: uuid.UUID
    run_type: str
    started_at_us: int
    finished_at_us: int | None
    status: str
    trigger_actor_id: uuid.UUID
    pipeline_version: str
    input_snapshot_json: str
    configuration_hash: bytes
    model_signature_id: uuid.UUID | None
    prompt_template_id: str | None
    prompt_template_version: str | None
    error_detail: str | None


class ModelRunRepository:
    """Store reproducibility metadata for semantic model work."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_or_create_signature(
        self,
        *,
        model: ModelInfo,
        generation_parameters: Mapping[str, Any],
        context_configuration: Mapping[str, Any] | None = None,
    ) -> ModelSignature:
        generation_json = _canonical_json(generation_parameters)
        context_json = (
            _canonical_json(context_configuration)
            if context_configuration is not None
            else None
        )
        normalized = {
            "provider": model.provider,
            "model_identifier": model.backend_model_id,
            "model_revision": None,
            "quantization": model.quantization,
            "generation_parameters": json.loads(generation_json),
            "context_configuration": (
                json.loads(context_json) if context_json is not None else None
            ),
        }
        signature_hash = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).digest()

        with self.database.write_transaction() as connection:
            existing = connection.execute(
                """
                SELECT *
                FROM model_signatures
                WHERE signature_hash = ?
                """,
                (signature_hash,),
            ).fetchone()
            if existing is not None:
                return _signature_from_row(existing)

            model_signature_id = new_uuid7()
            created_at_us = utc_now_us()
            connection.execute(
                """
                INSERT INTO model_signatures (
                    model_signature_id,
                    provider,
                    model_identifier,
                    model_revision,
                    quantization,
                    generation_parameters_json,
                    context_configuration_json,
                    signature_hash,
                    created_at_us
                ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_blob(model_signature_id),
                    model.provider,
                    model.backend_model_id,
                    model.quantization,
                    generation_json,
                    context_json,
                    signature_hash,
                    created_at_us,
                ),
            )

        return ModelSignature(
            model_signature_id=model_signature_id,
            provider=model.provider,
            model_identifier=model.backend_model_id,
            model_revision=None,
            quantization=model.quantization,
            generation_parameters_json=generation_json,
            context_configuration_json=context_json,
            signature_hash=signature_hash,
            created_at_us=created_at_us,
        )

    def start_run(
        self,
        *,
        run_type: str,
        trigger_actor_id: uuid.UUID,
        pipeline_version: str,
        input_snapshot: Mapping[str, Any],
        configuration: Mapping[str, Any],
        model_signature_id: uuid.UUID | None,
        prompt_template_id: str | None,
        prompt_template_version: str | None,
    ) -> ProcessingRun:
        processing_run_id = new_uuid7()
        started_at_us = utc_now_us()
        input_snapshot_json = _canonical_json(input_snapshot)
        configuration_hash = hashlib.sha256(
            _canonical_json(configuration).encode("utf-8")
        ).digest()

        with self.database.write_transaction() as connection:
            actor = connection.execute(
                "SELECT active FROM actors WHERE actor_id = ?",
                (uuid_to_blob(trigger_actor_id),),
            ).fetchone()
            if actor is None or int(actor["active"]) != 1:
                raise ValueError("ProcessingRun trigger actor is missing or inactive.")
            if model_signature_id is not None:
                signature = connection.execute(
                    "SELECT 1 FROM model_signatures WHERE model_signature_id = ?",
                    (uuid_to_blob(model_signature_id),),
                ).fetchone()
                if signature is None:
                    raise ValueError("ProcessingRun references an unknown ModelSignature.")

            connection.execute(
                """
                INSERT INTO processing_runs (
                    processing_run_id,
                    run_type,
                    started_at_us,
                    finished_at_us,
                    status,
                    trigger_actor_id,
                    pipeline_version,
                    input_snapshot_json,
                    configuration_hash,
                    model_signature_id,
                    prompt_template_id,
                    prompt_template_version,
                    error_detail
                ) VALUES (?, ?, ?, NULL, 'running', ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    uuid_to_blob(processing_run_id),
                    _required_text(run_type, "run_type"),
                    started_at_us,
                    uuid_to_blob(trigger_actor_id),
                    _required_text(pipeline_version, "pipeline_version"),
                    input_snapshot_json,
                    configuration_hash,
                    uuid_to_blob(model_signature_id)
                    if model_signature_id is not None
                    else None,
                    _optional_text(prompt_template_id),
                    _optional_text(prompt_template_version),
                ),
            )

        return ProcessingRun(
            processing_run_id=processing_run_id,
            run_type=run_type.strip(),
            started_at_us=started_at_us,
            finished_at_us=None,
            status="running",
            trigger_actor_id=trigger_actor_id,
            pipeline_version=pipeline_version.strip(),
            input_snapshot_json=input_snapshot_json,
            configuration_hash=configuration_hash,
            model_signature_id=model_signature_id,
            prompt_template_id=_optional_text(prompt_template_id),
            prompt_template_version=_optional_text(prompt_template_version),
            error_detail=None,
        )

    def finish_run(
        self,
        processing_run_id: uuid.UUID,
        *,
        status: str,
        error_detail: str | None = None,
    ) -> ProcessingRun:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("ProcessingRun final status is invalid.")
        finished_at_us = utc_now_us()
        normalized_error = _persisted_error_detail(error_detail)

        with self.database.write_transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE processing_runs
                SET finished_at_us = ?, status = ?, error_detail = ?
                WHERE processing_run_id = ? AND status = 'running'
                """,
                (
                    finished_at_us,
                    status,
                    normalized_error,
                    uuid_to_blob(processing_run_id),
                ),
            )
            if cursor.rowcount != 1:
                raise ProcessingRunNotFoundError(
                    "ProcessingRun does not exist or is already finished."
                )

        return self.load_run(processing_run_id)

    def load_run(self, processing_run_id: uuid.UUID) -> ProcessingRun:
        row = self.database.connection.execute(
            "SELECT * FROM processing_runs WHERE processing_run_id = ?",
            (uuid_to_blob(processing_run_id),),
        ).fetchone()
        if row is None:
            raise ProcessingRunNotFoundError(f"ProcessingRun {processing_run_id} not found.")
        return _run_from_row(row)

    def load_signature(self, model_signature_id: uuid.UUID) -> ModelSignature:
        row = self.database.connection.execute(
            "SELECT * FROM model_signatures WHERE model_signature_id = ?",
            (uuid_to_blob(model_signature_id),),
        ).fetchone()
        if row is None:
            raise LookupError(f"ModelSignature {model_signature_id} not found.")
        return _signature_from_row(row)


_SAFE_ERROR_DETAIL_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_.-]{0,127}\Z",
    re.ASCII,
)


def _persisted_error_detail(
    value: str | None,
) -> str | None:
    """Reduce durable error detail to an opaque machine-safe identifier."""
    normalized = _optional_text(value)

    if normalized is None:
        return None

    candidate = normalized.split(
        ":",
        1,
    )[0].strip()

    if (
        _SAFE_ERROR_DETAIL_RE.fullmatch(
            candidate
        )
        is None
    ):
        return "OperationalError"

    return candidate


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty.")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _signature_from_row(row: Any) -> ModelSignature:
    return ModelSignature(
        model_signature_id=uuid_from_blob(row["model_signature_id"]),
        provider=str(row["provider"]),
        model_identifier=str(row["model_identifier"]),
        model_revision=(
            str(row["model_revision"]) if row["model_revision"] is not None else None
        ),
        quantization=(
            str(row["quantization"]) if row["quantization"] is not None else None
        ),
        generation_parameters_json=str(row["generation_parameters_json"]),
        context_configuration_json=(
            str(row["context_configuration_json"])
            if row["context_configuration_json"] is not None
            else None
        ),
        signature_hash=bytes(row["signature_hash"]),
        created_at_us=int(row["created_at_us"]),
    )


def _run_from_row(row: Any) -> ProcessingRun:
    return ProcessingRun(
        processing_run_id=uuid_from_blob(row["processing_run_id"]),
        run_type=str(row["run_type"]),
        started_at_us=int(row["started_at_us"]),
        finished_at_us=(
            int(row["finished_at_us"]) if row["finished_at_us"] is not None else None
        ),
        status=str(row["status"]),
        trigger_actor_id=uuid_from_blob(row["trigger_actor_id"]),
        pipeline_version=str(row["pipeline_version"]),
        input_snapshot_json=str(row["input_snapshot_json"]),
        configuration_hash=bytes(row["configuration_hash"]),
        model_signature_id=(
            uuid_from_blob(row["model_signature_id"])
            if row["model_signature_id"] is not None
            else None
        ),
        prompt_template_id=(
            str(row["prompt_template_id"]) if row["prompt_template_id"] is not None else None
        ),
        prompt_template_version=(
            str(row["prompt_template_version"])
            if row["prompt_template_version"] is not None
            else None
        ),
        error_detail=(
            str(row["error_detail"]) if row["error_detail"] is not None else None
        ),
    )
