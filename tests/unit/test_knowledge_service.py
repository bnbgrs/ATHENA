import pytest

from athena.chat.repository import ChatRepository
from athena.chat.service import ChatService
from athena.knowledge.models import KnowledgeKind
from athena.knowledge.repository import KnowledgeRepository
from athena.knowledge.service import ChatMessageSequenceError, KnowledgeService
from athena.storage.database import SQLiteDatabase


def test_promotion_uses_exact_message_text_without_model_rewrite(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    knowledge = KnowledgeService(KnowledgeRepository(database), chat)
    chat_id = chat.create_chat()
    exact = "  Message content is normalized only by the Knowledge draft boundary.  "
    chat.add_user_message(chat_id=chat_id, content=exact)

    created = knowledge.promote_chat_message(
        chat_id=chat_id,
        sequence_no=1,
        knowledge_kind=KnowledgeKind.OTHER,
    )

    assert created.payload.body == exact.strip()
    database.stop()


def test_missing_chat_sequence_is_rejected_before_knowledge_write(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()
    chat = ChatService(ChatRepository(database))
    repository = KnowledgeRepository(database)
    knowledge = KnowledgeService(repository, chat)
    chat_id = chat.create_chat()

    with pytest.raises(ChatMessageSequenceError):
        knowledge.promote_chat_message(
            chat_id=chat_id,
            sequence_no=2,
            knowledge_kind=KnowledgeKind.FACT,
        )

    count = database.connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
    assert count == 0
    database.stop()
