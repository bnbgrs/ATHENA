"""Child-only pypdf execution for resource-bounded PDF parsing."""

from __future__ import annotations

import importlib
import os
import struct
import sys
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Protocol, cast

_REQUEST_MAGIC = b"ATHPDF2Q"
_SUCCESS_MAGIC = b"ATHPDF2S"
_ERROR_MAGIC = b"ATHPDF2E"

_MODE_PATH = 1
_MODE_BYTES = 2

_ERROR_ENCRYPTED = 1
_ERROR_NATIVE_TEXT = 2
_ERROR_RESOURCE = 3
_ERROR_REPRESENTATION = 4
_ERROR_ISOLATION = 5

_SEPARATOR = b"\n\n"


class _Page(Protocol):
    def extract_text(
        self,
    ) -> str | None: ...


class _Reader(Protocol):
    @property
    def is_encrypted(
        self,
    ) -> bool: ...

    @property
    def pages(
        self,
    ) -> Sequence[_Page]: ...


class _ResourceModule(Protocol):
    RLIMIT_AS: int

    def getrlimit(
        self,
        resource: int,
    ) -> tuple[int, int]: ...

    def setrlimit(
        self,
        resource: int,
        limits: tuple[int, int],
    ) -> None: ...


class _Failure(RuntimeError):
    def __init__(
        self,
        code: int,
        message: str,
    ) -> None:
        super().__init__(
            message
        )
        self.code = code


def main() -> int:
    try:
        if len(sys.argv) != 5:
            raise _Failure(
                _ERROR_ISOLATION,
                "Invalid PDF parser worker arguments.",
            )

        (
            max_input,
            max_pages,
            max_output,
            memory_limit,
        ) = (
            int(value)
            for value
            in sys.argv[1:5]
        )

        if min(
            max_input,
            max_pages,
            max_output,
            memory_limit,
        ) <= 0:
            raise _Failure(
                _ERROR_ISOLATION,
                "Invalid PDF parser worker limits.",
            )

        if os.name != "nt":
            _limit_posix_memory(
                memory_limit
            )

        request = (
            sys.stdin.buffer.read()
        )

        result = _handle(
            request,
            max_input=max_input,
            max_pages=max_pages,
            max_output=max_output,
        )

        sys.stdout.buffer.write(
            result
        )
        sys.stdout.buffer.flush()

        return 0

    except _Failure as exc:
        sys.stdout.buffer.write(
            _error(
                exc.code,
                str(exc),
            )
        )
        sys.stdout.buffer.flush()

        return exc.code

    except MemoryError:
        sys.stdout.buffer.write(
            _error(
                _ERROR_RESOURCE,
                "PDF parser exceeded its "
                "process memory limit.",
            )
        )
        sys.stdout.buffer.flush()

        return _ERROR_RESOURCE

    except Exception as exc:
        sys.stdout.buffer.write(
            _error(
                _ERROR_REPRESENTATION,
                "PDF parser failed closed "
                f"({type(exc).__name__}).",
            )
        )
        sys.stdout.buffer.flush()

        return _ERROR_REPRESENTATION


def _handle(
    request: bytes,
    *,
    max_input: int,
    max_pages: int,
    max_output: int,
) -> bytes:
    if (
        not request.startswith(
            _REQUEST_MAGIC
        )
        or len(request)
        <= len(_REQUEST_MAGIC)
    ):
        raise _Failure(
            _ERROR_ISOLATION,
            "Invalid PDF parser request.",
        )

    offset = len(
        _REQUEST_MAGIC
    )

    mode = request[
        offset
    ]

    offset += 1

    (
        payload,
        offset,
    ) = _read_blob(
        request,
        offset,
        max_input,
    )

    if offset != len(request):
        raise _Failure(
            _ERROR_ISOLATION,
            "PDF parser request "
            "has trailing bytes.",
        )

    if mode == _MODE_PATH:
        try:
            path = Path(
                os.fsdecode(
                    payload
                )
            )

        except (
            TypeError,
            UnicodeError,
        ) as exc:
            raise _Failure(
                _ERROR_ISOLATION,
                "PDF parser path is invalid.",
            ) from exc

        try:
            if (
                path.stat().st_size
                > max_input
            ):
                raise _Failure(
                    _ERROR_RESOURCE,
                    "PDF input exceeds the "
                    "configured parser byte limit.",
                )

        except OSError as exc:
            raise _Failure(
                _ERROR_REPRESENTATION,
                "Cannot inspect PDF source bytes.",
            ) from exc

        return _parse_path(
            path,
            max_pages=max_pages,
            max_output=max_output,
        )

    if mode == _MODE_BYTES:
        return _parse_bytes(
            payload,
            max_pages=max_pages,
            max_output=max_output,
        )

    raise _Failure(
        _ERROR_ISOLATION,
        "Unsupported PDF parser request mode.",
    )


def _parse_path(
    path: Path,
    *,
    max_pages: int,
    max_output: int,
) -> bytes:
    try:
        from pypdf import PdfReader
        from pypdf.errors import (
            PdfReadError,
        )

        reader = PdfReader(
            str(path),
            strict=True,
        )

        return _extract(
            cast(
                _Reader,
                reader,
            ),
            max_pages=max_pages,
            max_output=max_output,
        )

    except PdfReadError as exc:
        raise _Failure(
            _ERROR_REPRESENTATION,
            "Cannot parse PDF source bytes.",
        ) from exc

    except (
        OSError,
        ValueError,
    ) as exc:
        raise _Failure(
            _ERROR_REPRESENTATION,
            "Cannot parse PDF source bytes.",
        ) from exc


def _parse_bytes(
    payload: bytes,
    *,
    max_pages: int,
    max_output: int,
) -> bytes:
    try:
        from pypdf import PdfReader
        from pypdf.errors import (
            PdfReadError,
        )

        with BytesIO(
            payload
        ) as stream:
            reader = PdfReader(
                stream,
                strict=True,
            )

            return _extract(
                cast(
                    _Reader,
                    reader,
                ),
                max_pages=max_pages,
                max_output=max_output,
            )

    except PdfReadError as exc:
        raise _Failure(
            _ERROR_REPRESENTATION,
            "Cannot parse PDF source bytes.",
        ) from exc

    except (
        OSError,
        ValueError,
    ) as exc:
        raise _Failure(
            _ERROR_REPRESENTATION,
            "Cannot parse PDF source bytes.",
        ) from exc


def _extract(
    reader: _Reader,
    *,
    max_pages: int,
    max_output: int,
) -> bytes:
    if reader.is_encrypted:
        raise _Failure(
            _ERROR_ENCRYPTED,
            "VS6 Step 1 does not process "
            "encrypted PDFs; retain the original "
            "and retry after an explicit "
            "decryption workflow is available.",
        )

    pages = reader.pages
    page_count = len(
        pages
    )

    if page_count > max_pages:
        raise _Failure(
            _ERROR_RESOURCE,
            "PDF page count exceeds the "
            "configured parser limit.",
        )

    result = bytearray(
        _SUCCESS_MAGIC
    )

    result.extend(
        struct.pack(
            ">IQ",
            page_count,
            0,
        )
    )

    total = 0
    saw_text = False

    for (
        index,
        page,
    ) in enumerate(
        pages
    ):
        try:
            text = (
                page.extract_text()
                or ""
            )

            text = (
                text.replace(
                    "\r\n",
                    "\n",
                )
                .replace(
                    "\r",
                    "\n",
                )
            )

        except Exception as exc:
            raise _Failure(
                _ERROR_REPRESENTATION,
                "Native PDF text extraction "
                f"failed on page {index + 1}.",
            ) from exc

        encoded = text.encode(
            "utf-8"
        )

        total += len(
            encoded
        )

        if index:
            total += len(
                _SEPARATOR
            )

        if total > max_output:
            raise _Failure(
                _ERROR_RESOURCE,
                "PDF extracted text exceeds "
                "the configured output byte limit.",
            )

        saw_text = (
            saw_text
            or bool(
                text.strip()
            )
        )

        result.extend(
            struct.pack(
                ">IQ",
                index + 1,
                len(encoded),
            )
        )

        result.extend(
            encoded
        )

    if not saw_text:
        raise _Failure(
            _ERROR_NATIVE_TEXT,
            "PDF has no usable native text. "
            "OCR fallback is intentionally "
            "deferred beyond VS6 Step 1.",
        )

    struct.pack_into(
        ">Q",
        result,
        len(_SUCCESS_MAGIC) + 4,
        total,
    )

    return bytes(
        result
    )


def _read_blob(
    payload: bytes,
    offset: int,
    maximum: int,
) -> tuple[bytes, int]:
    end = (
        offset
        + 8
    )

    if end > len(payload):
        raise _Failure(
            _ERROR_ISOLATION,
            "PDF parser request is truncated.",
        )

    length = struct.unpack(
        ">Q",
        payload[
            offset:end
        ],
    )[0]

    if length > maximum:
        raise _Failure(
            _ERROR_RESOURCE,
            "PDF input exceeds the "
            "configured parser byte limit.",
        )

    data_end = (
        end
        + length
    )

    if data_end > len(payload):
        raise _Failure(
            _ERROR_ISOLATION,
            "PDF parser request is truncated.",
        )

    return (
        payload[
            end:data_end
        ],
        data_end,
    )


def _error(
    code: int,
    message: str,
) -> bytes:
    encoded = (
        message
        .encode(
            "utf-8"
        )[:4096]
    )

    return (
        _ERROR_MAGIC
        + bytes(
            (code,)
        )
        + struct.pack(
            ">I",
            len(encoded),
        )
        + encoded
    )


def _limit_posix_memory(
    memory_limit: int,
) -> None:
    try:
        resource_module = cast(
            _ResourceModule,
            importlib.import_module(
                "resource"
            ),
        )

        (
            _soft,
            hard,
        ) = resource_module.getrlimit(
            resource_module.RLIMIT_AS
        )

        effective_hard = (
            memory_limit
            if hard < 0
            else min(
                memory_limit,
                hard,
            )
        )

        resource_module.setrlimit(
            resource_module.RLIMIT_AS,
            (
                min(
                    memory_limit,
                    effective_hard,
                ),
                effective_hard,
            ),
        )

    except (
        AttributeError,
        ImportError,
        OSError,
        ValueError,
    ) as exc:
        raise _Failure(
            _ERROR_ISOLATION,
            "Cannot enforce POSIX PDF "
            "parser process memory isolation.",
        ) from exc


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
