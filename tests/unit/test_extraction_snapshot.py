from __future__ import annotations


def test_successful_extraction_snapshot_round_trips_without_model_call(tmp_path) -> None:
    from athena.knowledge.extraction_snapshot import ExtractionSnapshotRepository
    from athena.model.provenance import ModelRunRepository
    from tests.unit.test_proposal_acceptance import _extracted

    database, result, _knowledge, _claims, _acceptance = _extracted(tmp_path)
    try:
        snapshots = ExtractionSnapshotRepository(database, ModelRunRepository(database))
        snapshots.save(result)
        loaded = snapshots.load(result.processing_run.processing_run_id)
        assert loaded.chat_id == result.chat_id
        assert loaded.processing_run.processing_run_id == result.processing_run.processing_run_id
        assert loaded.model_signature.model_signature_id == result.model_signature.model_signature_id
        assert loaded.model.backend_model_id == result.model.backend_model_id
        assert loaded.proposals == result.proposals
    finally:
        database.stop()
