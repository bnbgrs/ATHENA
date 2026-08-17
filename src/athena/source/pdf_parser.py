"""Supervise resource-bounded PDF parsing in a disposable child process."""

from __future__ import annotations

import ctypes
import os
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

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

_ERROR_MESSAGE_LIMIT = 4096
_RESULT_FIXED_OVERHEAD = 32
_PAGE_OVERHEAD = 12

_JOB_EXTENDED_LIMITS = 9
_JOB_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_LIMIT_KILL_ON_CLOSE = 0x00002000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


class PdfRepresentationError(RuntimeError):
    """Base error for native PDF text extraction."""


class EncryptedPdfUnsupportedError(PdfRepresentationError):
    """Raised for encrypted PDFs, which ATHENA does not parse."""


class PdfNativeTextUnavailableError(PdfRepresentationError):
    """Raised when a PDF has no usable native text."""


class PdfResourceLimitError(PdfRepresentationError):
    """Raised when a PDF crosses a configured resource boundary."""


class PdfParserTimeoutError(PdfResourceLimitError):
    """Raised when the parser child exceeds its wall-clock budget."""


class PdfParserIsolationError(PdfRepresentationError):
    """Raised when parser containment or IPC cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PdfParserPolicy:
    """Operational limits; accepted-document text semantics remain unchanged."""

    max_input_bytes: int = 128 * 1024 * 1024
    max_pages: int = 4_000
    max_output_bytes: int = 64 * 1024 * 1024
    timeout_seconds: float = 90.0
    max_process_memory_bytes: int = 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        values = (
            self.max_input_bytes,
            self.max_pages,
            self.max_output_bytes,
            self.timeout_seconds,
            self.max_process_memory_bytes,
        )
        if any(value <= 0 for value in values):
            raise ValueError(
                "All PDF parser policy limits must be positive."
            )


DEFAULT_PDF_PARSER_POLICY = PdfParserPolicy()


@dataclass(frozen=True, slots=True)
class PdfParsedPage:
    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class PdfParseResult:
    page_count: int
    pages: tuple[PdfParsedPage, ...]
    byte_length: int

    def text(self) -> str:
        return "\n\n".join(
            page.text
            for page in self.pages
        )


class IsolatedPdfTextParser:
    """Parse PDF text outside the ATHENA process with OS containment."""

    def __init__(
        self,
        policy: PdfParserPolicy = DEFAULT_PDF_PARSER_POLICY,
    ) -> None:
        self.policy = policy

    def parse_path(
        self,
        source_path: Path,
    ) -> PdfParseResult:
        try:
            byte_length = source_path.stat().st_size
        except OSError as exc:
            raise PdfRepresentationError(
                "Cannot inspect PDF source bytes."
            ) from exc

        self._require_input_size(
            byte_length
        )

        encoded_path = os.fsencode(
            source_path.resolve()
        )

        request = (
            _REQUEST_MAGIC
            + bytes((_MODE_PATH,))
            + _pack_blob(encoded_path)
        )

        return self._run(
            request
        )

    def parse_bytes(
        self,
        payload: bytes,
    ) -> PdfParseResult:
        self._require_input_size(
            len(payload)
        )

        request = (
            _REQUEST_MAGIC
            + bytes((_MODE_BYTES,))
            + _pack_blob(payload)
        )

        return self._run(
            request
        )

    def _require_input_size(
        self,
        byte_length: int,
    ) -> None:
        if (
            byte_length
            > self.policy.max_input_bytes
        ):
            raise PdfResourceLimitError(
                "PDF input exceeds the configured parser byte limit "
                f"({byte_length} > {self.policy.max_input_bytes})."
            )

    def _run(
        self,
        request: bytes,
    ) -> PdfParseResult:
        worker_path = (
            Path(__file__)
            .resolve()
            .with_name(
                "pdf_parser_worker.py"
            )
        )

        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    str(
                        worker_path
                    ),
                    str(
                        self.policy.max_input_bytes
                    ),
                    str(
                        self.policy.max_pages
                    ),
                    str(
                        self.policy.max_output_bytes
                    ),
                    str(
                        self.policy.max_process_memory_bytes
                    ),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise PdfParserIsolationError(
                "Cannot start isolated PDF parser child."
            ) from exc

        job: _WindowsMemoryJob | None = None

        try:
            if os.name == "nt":
                job = (
                    _WindowsMemoryJob.attach(
                        process.pid,
                        (
                            self.policy
                            .max_process_memory_bytes
                        ),
                    )
                )

            try:
                stdout, _stderr = (
                    process.communicate(
                        input=request,
                        timeout=(
                            self.policy
                            .timeout_seconds
                        ),
                    )
                )

            except subprocess.TimeoutExpired as exc:
                process.kill()
                process.communicate()

                raise PdfParserTimeoutError(
                    "PDF parser exceeded its "
                    "wall-clock timeout."
                ) from exc

        except PdfRepresentationError:
            if process.poll() is None:
                process.kill()
                process.communicate()

            raise

        finally:
            if job is not None:
                job.close()

        if (
            process.returncode != 0
            and not stdout.startswith(
                _ERROR_MAGIC
            )
        ):
            raise PdfParserIsolationError(
                "PDF parser child exited "
                "unexpectedly with code "
                f"{process.returncode}."
            )

        return self._decode_result(
            stdout
        )

    def _decode_result(
        self,
        payload: bytes,
    ) -> PdfParseResult:
        maximum = (
            self.policy.max_output_bytes
            + _RESULT_FIXED_OVERHEAD
            + (
                self.policy.max_pages
                * _PAGE_OVERHEAD
            )
        )

        if len(payload) > maximum:
            raise PdfParserIsolationError(
                "PDF parser returned an "
                "oversized IPC result."
            )

        if payload.startswith(
            _ERROR_MAGIC
        ):
            _raise_encoded_error(
                payload
            )

        if not payload.startswith(
            _SUCCESS_MAGIC
        ):
            raise PdfParserIsolationError(
                "PDF parser returned an "
                "invalid result header."
            )

        offset = len(
            _SUCCESS_MAGIC
        )

        (
            page_count,
            offset,
        ) = _read_u32(
            payload,
            offset,
        )

        (
            byte_length,
            offset,
        ) = _read_u64(
            payload,
            offset,
        )

        if (
            page_count
            > self.policy.max_pages
            or byte_length
            > self.policy.max_output_bytes
        ):
            raise PdfParserIsolationError(
                "PDF parser result metadata "
                "exceeds policy."
            )

        pages: list[
            PdfParsedPage
        ] = []

        measured = 0

        for expected_page in range(
            1,
            page_count + 1,
        ):
            (
                page_number,
                offset,
            ) = _read_u32(
                payload,
                offset,
            )

            (
                text_length,
                offset,
            ) = _read_u64(
                payload,
                offset,
            )

            if (
                page_number
                != expected_page
                or text_length
                > self.policy.max_output_bytes
            ):
                raise PdfParserIsolationError(
                    "PDF parser page metadata "
                    "is invalid."
                )

            end = (
                offset
                + text_length
            )

            if end > len(payload):
                raise PdfParserIsolationError(
                    "PDF parser result is truncated."
                )

            encoded = payload[
                offset:end
            ]

            offset = end

            try:
                text = encoded.decode(
                    "utf-8",
                    errors="strict",
                )

            except UnicodeDecodeError as exc:
                raise PdfParserIsolationError(
                    "PDF parser returned "
                    "invalid UTF-8."
                ) from exc

            measured += len(
                encoded
            )

            if expected_page > 1:
                measured += 2

            if (
                measured
                > self.policy.max_output_bytes
            ):
                raise PdfResourceLimitError(
                    "PDF extracted text exceeds "
                    "the configured output byte limit."
                )

            pages.append(
                PdfParsedPage(
                    page_number=page_number,
                    text=text,
                )
            )

        if (
            offset != len(payload)
            or measured != byte_length
        ):
            raise PdfParserIsolationError(
                "PDF parser result length "
                "is inconsistent."
            )

        return PdfParseResult(
            page_count=page_count,
            pages=tuple(
                pages
            ),
            byte_length=byte_length,
        )


class _WindowsMemoryJob:
    def __init__(
        self,
        handle: int,
    ) -> None:
        self.handle = handle

    @classmethod
    def attach(
        cls,
        pid: int,
        memory_limit: int,
    ) -> _WindowsMemoryJob:
        if os.name != "nt":
            raise PdfParserIsolationError(
                "Windows Job Object requested "
                "on non-Windows."
            )

        try:
            from ctypes import wintypes

            # These ctypes symbols exist only on Windows. Resolve them
            # dynamically so Linux/macOS type checking remains valid while
            # preserving the native Windows Job Object implementation.
            win_dll = vars(ctypes)["WinDLL"]
            win_error = vars(ctypes)["WinError"]
            get_last_error = vars(ctypes)["get_last_error"]

            kernel32 = win_dll(
                "kernel32",
                use_last_error=True,
            )

            class Basic(
                ctypes.Structure
            ):
                _fields_ = [
                    (
                        "PerProcessUserTimeLimit",
                        ctypes.c_longlong,
                    ),
                    (
                        "PerJobUserTimeLimit",
                        ctypes.c_longlong,
                    ),
                    (
                        "LimitFlags",
                        wintypes.DWORD,
                    ),
                    (
                        "MinimumWorkingSetSize",
                        ctypes.c_size_t,
                    ),
                    (
                        "MaximumWorkingSetSize",
                        ctypes.c_size_t,
                    ),
                    (
                        "ActiveProcessLimit",
                        wintypes.DWORD,
                    ),
                    (
                        "Affinity",
                        ctypes.c_size_t,
                    ),
                    (
                        "PriorityClass",
                        wintypes.DWORD,
                    ),
                    (
                        "SchedulingClass",
                        wintypes.DWORD,
                    ),
                ]

            class Io(
                ctypes.Structure
            ):
                _fields_ = [
                    (
                        "ReadOperationCount",
                        ctypes.c_ulonglong,
                    ),
                    (
                        "WriteOperationCount",
                        ctypes.c_ulonglong,
                    ),
                    (
                        "OtherOperationCount",
                        ctypes.c_ulonglong,
                    ),
                    (
                        "ReadTransferCount",
                        ctypes.c_ulonglong,
                    ),
                    (
                        "WriteTransferCount",
                        ctypes.c_ulonglong,
                    ),
                    (
                        "OtherTransferCount",
                        ctypes.c_ulonglong,
                    ),
                ]

            class Extended(
                ctypes.Structure
            ):
                _fields_ = [
                    (
                        "BasicLimitInformation",
                        Basic,
                    ),
                    (
                        "IoInfo",
                        Io,
                    ),
                    (
                        "ProcessMemoryLimit",
                        ctypes.c_size_t,
                    ),
                    (
                        "JobMemoryLimit",
                        ctypes.c_size_t,
                    ),
                    (
                        "PeakProcessMemoryUsed",
                        ctypes.c_size_t,
                    ),
                    (
                        "PeakJobMemoryUsed",
                        ctypes.c_size_t,
                    ),
                ]

            kernel32.CreateJobObjectW.argtypes = [
                ctypes.c_void_p,
                wintypes.LPCWSTR,
            ]

            kernel32.CreateJobObjectW.restype = (
                wintypes.HANDLE
            )

            (
                kernel32
                .SetInformationJobObject
                .argtypes
            ) = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]

            (
                kernel32
                .SetInformationJobObject
                .restype
            ) = wintypes.BOOL

            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]

            kernel32.OpenProcess.restype = (
                wintypes.HANDLE
            )

            (
                kernel32
                .AssignProcessToJobObject
                .argtypes
            ) = [
                wintypes.HANDLE,
                wintypes.HANDLE,
            ]

            (
                kernel32
                .AssignProcessToJobObject
                .restype
            ) = wintypes.BOOL

            kernel32.CloseHandle.argtypes = [
                wintypes.HANDLE
            ]

            kernel32.CloseHandle.restype = (
                wintypes.BOOL
            )

            job = (
                kernel32.CreateJobObjectW(
                    None,
                    None,
                )
            )

            if not job:
                raise win_error(
                    get_last_error()
                )

            process_handle = None

            try:
                limits = Extended()

                (
                    limits
                    .BasicLimitInformation
                    .LimitFlags
                ) = (
                    _JOB_LIMIT_PROCESS_MEMORY
                    | _JOB_LIMIT_KILL_ON_CLOSE
                )

                limits.ProcessMemoryLimit = (
                    memory_limit
                )

                if not (
                    kernel32
                    .SetInformationJobObject(
                        job,
                        _JOB_EXTENDED_LIMITS,
                        ctypes.byref(
                            limits
                        ),
                        ctypes.sizeof(
                            limits
                        ),
                    )
                ):
                    raise win_error(
                        get_last_error()
                    )

                process_handle = (
                    kernel32.OpenProcess(
                        (
                            _PROCESS_SET_QUOTA
                            | _PROCESS_TERMINATE
                        ),
                        False,
                        pid,
                    )
                )

                if not process_handle:
                    raise win_error(
                        get_last_error()
                    )

                if not (
                    kernel32
                    .AssignProcessToJobObject(
                        job,
                        process_handle,
                    )
                ):
                    raise win_error(
                        get_last_error()
                    )

            except OSError:
                kernel32.CloseHandle(
                    job
                )
                raise

            finally:
                if process_handle:
                    kernel32.CloseHandle(
                        process_handle
                    )

            return cls(
                cast(
                    int,
                    job,
                )
            )

        except OSError as exc:
            raise PdfParserIsolationError(
                "Cannot enforce Windows PDF "
                "parser process memory isolation."
            ) from exc

    def close(
        self,
    ) -> None:
        if not self.handle:
            return

        from ctypes import wintypes

        win_dll = vars(ctypes)["WinDLL"]

        kernel32 = win_dll(
            "kernel32",
            use_last_error=True,
        )

        kernel32.CloseHandle.argtypes = [
            wintypes.HANDLE
        ]

        kernel32.CloseHandle.restype = (
            wintypes.BOOL
        )

        kernel32.CloseHandle(
            self.handle
        )

        self.handle = 0


def _pack_blob(
    payload: bytes,
) -> bytes:
    return (
        struct.pack(
            ">Q",
            len(payload),
        )
        + payload
    )


def _read_u32(
    payload: bytes,
    offset: int,
) -> tuple[int, int]:
    end = offset + 4

    if end > len(payload):
        raise PdfParserIsolationError(
            "PDF parser result is truncated."
        )

    return (
        struct.unpack(
            ">I",
            payload[offset:end],
        )[0],
        end,
    )


def _read_u64(
    payload: bytes,
    offset: int,
) -> tuple[int, int]:
    end = offset + 8

    if end > len(payload):
        raise PdfParserIsolationError(
            "PDF parser result is truncated."
        )

    return (
        struct.unpack(
            ">Q",
            payload[offset:end],
        )[0],
        end,
    )


def _raise_encoded_error(
    payload: bytes,
) -> None:
    offset = len(
        _ERROR_MAGIC
    )

    if offset >= len(payload):
        raise PdfParserIsolationError(
            "PDF parser error result is truncated."
        )

    code = payload[
        offset
    ]

    offset += 1

    (
        length,
        offset,
    ) = _read_u32(
        payload,
        offset,
    )

    if (
        length
        > _ERROR_MESSAGE_LIMIT
        or offset + length
        != len(payload)
    ):
        raise PdfParserIsolationError(
            "PDF parser error result is invalid."
        )

    try:
        message = payload[
            offset:
        ].decode(
            "utf-8",
            errors="strict",
        )

    except UnicodeDecodeError as exc:
        raise PdfParserIsolationError(
            "PDF parser error message is invalid."
        ) from exc

    errors: dict[
        int,
        type[PdfRepresentationError],
    ] = {
        _ERROR_ENCRYPTED: (
            EncryptedPdfUnsupportedError
        ),
        _ERROR_NATIVE_TEXT: (
            PdfNativeTextUnavailableError
        ),
        _ERROR_RESOURCE: (
            PdfResourceLimitError
        ),
        _ERROR_REPRESENTATION: (
            PdfRepresentationError
        ),
        _ERROR_ISOLATION: (
            PdfParserIsolationError
        ),
    }

    error_type = errors.get(
        code
    )

    if error_type is None:
        raise PdfParserIsolationError(
            "PDF parser returned "
            "an unknown error code."
        )

    raise error_type(
        message
    )
