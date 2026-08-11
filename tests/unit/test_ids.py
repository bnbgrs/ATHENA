import uuid

from athena.common.ids import new_uuid7, uuid_from_blob, uuid_to_blob


def test_uuid7_has_standard_version_and_variant() -> None:
    value = new_uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    assert len(value.bytes) == 16


def test_uuid_blob_roundtrip() -> None:
    value = new_uuid7()

    assert uuid_from_blob(uuid_to_blob(value)) == value
