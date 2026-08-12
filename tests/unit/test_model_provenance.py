import json

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.model.domain import ModelInfo
from athena.model.provenance import ModelRunRepository
from athena.storage.database import SQLiteDatabase


def _model() -> ModelInfo:
    return ModelInfo(
        provider="lm_studio",
        backend_model_id="example/model",
        display_name="Example Model",
        model_type="llm",
        context_capacity=32768,
        quantization="Q4_K_M",
        loaded=True,
        vision=False,
        trained_for_tool_use=False,
    )


def test_model_signature_is_reused_for_identical_configuration(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    repository = ModelRunRepository(database)

    first = repository.get_or_create_signature(
        model=_model(),
        generation_parameters={"temperature": 0.0, "stream": False},
        context_configuration={"task": "knowledge_extraction"},
    )
    second = repository.get_or_create_signature(
        model=_model(),
        generation_parameters={"stream": False, "temperature": 0.0},
        context_configuration={"task": "knowledge_extraction"},
    )

    assert first.model_signature_id == second.model_signature_id
    assert first.signature_hash == second.signature_hash
    assert first.quantization == "Q4_K_M"
    database.stop()


def test_processing_run_records_snapshot_and_final_status(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    actor_id = chat.ensure_local_user()
    repository = ModelRunRepository(database)
    signature = repository.get_or_create_signature(
        model=_model(),
        generation_parameters={"temperature": 0.0},
    )

    running = repository.start_run(
        run_type="knowledge_extraction",
        trigger_actor_id=actor_id,
        pipeline_version="test/1",
        input_snapshot={"chat_id": "chat", "messages": [1, 2]},
        configuration={"schema_id": "test_schema"},
        model_signature_id=signature.model_signature_id,
        prompt_template_id="test.prompt",
        prompt_template_version="1",
    )

    assert running.status == "running"
    assert running.finished_at_us is None
    assert json.loads(running.input_snapshot_json)["messages"] == [1, 2]

    finished = repository.finish_run(running.processing_run_id, status="succeeded")
    assert finished.status == "succeeded"
    assert finished.finished_at_us is not None
    assert finished.model_signature_id == signature.model_signature_id
    database.stop()
