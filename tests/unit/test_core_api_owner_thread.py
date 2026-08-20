from __future__ import annotations

import threading
from pathlib import Path

from athena.api.client import CoreApiClient
from athena.api.process import CoreApiProcess
from athena.config.settings import AthenaSettings


def _process(tmp_path: Path) -> CoreApiProcess:
    return CoreApiProcess(
        settings=AthenaSettings(
            local_root=(tmp_path / "runtime").resolve()
        )
    )


def test_core_api_sqlite_work_runs_on_domain_owner_thread(
    tmp_path: Path,
) -> None:
    process = _process(tmp_path)
    caller_thread = threading.get_ident()

    process.start()
    try:
        owner_thread = process.executor.thread_id
        assert owner_thread is not None
        assert owner_thread != caller_thread

        client = CoreApiClient(
            process.runtime_root,
            timeout_seconds=2.0,
        )

        created = client.create_chat()
        loaded = client.load_chat(created.chat_id)
        chats = client.list_chats(limit=10)

        assert loaded.chat_id == created.chat_id
        assert any(
            chat.chat_id == created.chat_id
            for chat in chats
        )
        assert process.executor.thread_id == owner_thread
    finally:
        process.stop()
