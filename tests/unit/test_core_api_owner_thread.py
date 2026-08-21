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

        first = client.create_chat()
        second = client.create_chat()

        loaded = client.load_chat(
            first.chat_id
        )

        chats = client.list_chats(
            limit=10
        )
        offset_chats = client.list_chats(
            limit=10,
            offset=1,
        )

        assert loaded.chat_id == first.chat_id

        listed_ids = tuple(
            chat.chat_id
            for chat in chats
        )
        offset_ids = tuple(
            chat.chat_id
            for chat in offset_chats
        )

        assert first.chat_id in listed_ids
        assert second.chat_id in listed_ids
        assert offset_ids == listed_ids[1:]
        assert process.executor.thread_id == owner_thread
    finally:
        process.stop()
