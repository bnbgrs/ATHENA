from __future__ import annotations

from pathlib import Path

from athena.config.settings import AthenaSettings
from athena.core.application import AthenaApplication
from athena.jobs.source_processing import _failure_reason

_SECRET = "ATHENA_P1_04_SECRET_CANARY_52D771FE"


class _SyntheticSecretError(RuntimeError):
    pass


def test_processing_run_error_detail_never_persists_exception_message(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        AthenaSettings(
            local_root=tmp_path / "runtime",
        )
    )
    app.start(
        run_startup_maintenance=False,
    )

    try:
        actor_id = app.chat.ensure_local_user()

        run = app.model_runs.start_run(
            run_type="error-safety-test",
            trigger_actor_id=actor_id,
            pipeline_version="test-v1",
            input_snapshot={"test": True},
            configuration={"test": True},
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )

        finished = app.model_runs.finish_run(
            run.processing_run_id,
            status="failed",
            error_detail=(
                "_SyntheticSecretError: "
                + _SECRET
            ),
        )

        assert finished.error_detail == "_SyntheticSecretError"
        assert _SECRET not in (finished.error_detail or "")

    finally:
        app.stop()


def test_processing_run_free_text_is_reduced_to_generic_code(
    tmp_path: Path,
) -> None:
    app = AthenaApplication(
        AthenaSettings(
            local_root=tmp_path / "runtime",
        )
    )
    app.start(
        run_startup_maintenance=False,
    )

    try:
        actor_id = app.chat.ensure_local_user()

        run = app.model_runs.start_run(
            run_type="error-safety-fallback-test",
            trigger_actor_id=actor_id,
            pipeline_version="test-v1",
            input_snapshot={"test": True},
            configuration={"test": True},
            model_signature_id=None,
            prompt_template_id=None,
            prompt_template_version=None,
        )

        finished = app.model_runs.finish_run(
            run.processing_run_id,
            status="failed",
            error_detail=(
                "free text containing "
                + _SECRET
            ),
        )

        assert finished.error_detail == "OperationalError"
        assert _SECRET not in (finished.error_detail or "")

    finally:
        app.stop()


def test_source_processing_failure_reason_is_opaque() -> None:
    error = _SyntheticSecretError(
        _SECRET
    )

    detail = _failure_reason(
        error
    )

    assert detail == "_SyntheticSecretError"
    assert _SECRET not in detail
