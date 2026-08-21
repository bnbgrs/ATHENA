"""Stable identifiers for durable chat send operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

_ASSISTANT_MESSAGE_NAMESPACE = uuid.UUID(
    "1db1d2a3-19d4-4b52-a70b-72fd254f0933"
)
_NEW_CHAT_NAMESPACE = uuid.UUID(
    "b10e5c18-84af-48d4-a5dc-f32f69ed91dc"
)


class SendOperationState(str, Enum):
    """Durable persistence state for one client send operation."""

    ABSENT = "absent"
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SendOperationStatus:
    """Stable persisted identity and state for one send operation."""

    chat_id: uuid.UUID
    operation_id: uuid.UUID
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    state: SendOperationState


class SendOperationStateError(RuntimeError):
    """Raised when a non-absent durable send is executed again."""

    def __init__(
        self,
        status: SendOperationStatus,
    ) -> None:
        self.status = status

        super().__init__(
            "Send operation "
            f"{status.operation_id} is {status.state.value}; "
            "only absent operations may execute."
        )


def user_message_id_for_operation(
    operation_id: uuid.UUID,
) -> uuid.UUID:
    """Use the client operation as the durable user-turn identity."""
    return operation_id


def assistant_message_id_for_operation(
    operation_id: uuid.UUID,
) -> uuid.UUID:
    """Derive the assistant-turn identity from the operation."""
    return uuid.uuid5(
        _ASSISTANT_MESSAGE_NAMESPACE,
        operation_id.hex,
    )


def chat_id_for_operation(
    operation_id: uuid.UUID,
) -> uuid.UUID:
    """Derive the future new-chat identity from the operation."""
    return uuid.uuid5(
        _NEW_CHAT_NAMESPACE,
        operation_id.hex,
    )
