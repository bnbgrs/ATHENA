"""Crash-durable filesystem publication primitives.

Canonical and recovery-critical ATHENA files are written and fsynced before
publication. Publication itself must also reach stable filesystem metadata
before the caller is allowed to treat the path as durable.

POSIX uses rename/replace followed by fsync of every directory whose entries
changed. Windows uses MoveFileExW with MOVEFILE_WRITE_THROUGH because Python's
os.replace() does not expose that durability flag.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

_MOVEFILE_REPLACE_EXISTING = 0x00000001
_MOVEFILE_WRITE_THROUGH = 0x00000008


def durable_replace(
    source: Path,
    destination: Path,
) -> None:
    """Atomically publish *source* at *destination* and flush rename metadata.

    The source and destination must be on the same filesystem, matching the
    atomic-replace contract already required by ATHENA's publication paths.

    On POSIX both directory entries are fsynced when a move crosses directory
    boundaries. On Windows MoveFileExW WRITE_THROUGH provides the publication
    barrier directly.

    Directory callers must publish to an absent destination. ATHENA's backup
    and restore paths already enforce that invariant before calling here.
    """

    source_path = Path(source)
    destination_path = Path(destination)

    source_parent = source_path.parent
    destination_parent = destination_path.parent

    if _is_windows():
        _windows_replace_write_through(
            source_path,
            destination_path,
        )
        return

    os.replace(
        source_path,
        destination_path,
    )

    # The destination name must survive power loss.
    fsync_directory(
        destination_parent
    )

    # A cross-directory rename also removes the source name from another
    # directory. Persist that metadata change as well.
    if source_parent != destination_parent:
        fsync_directory(
            source_parent
        )



def durable_mkdir(
    path: Path,
    *,
    parents: bool = False,
    exist_ok: bool = False,
) -> None:
    """Create a directory and durably publish every newly created entry.

    Existing real directories are accepted only when exist_ok permits them.
    Symlinks are never treated as an acceptable directory boundary.

    With parents=True, missing components are created from the nearest
    existing ancestor outward so that every child is published into an
    already-existing parent.
    """

    directory = Path(path)

    if directory.is_symlink():
        raise FileExistsError(
            f"Durable directory path is a symlink: {directory}"
        )

    if directory.exists():
        if not directory.is_dir():
            raise FileExistsError(
                f"Durable directory path is not a directory: {directory}"
            )

        if exist_ok:
            return

        raise FileExistsError(
            f"Durable directory already exists: {directory}"
        )

    if not parents:
        _durable_create_one_directory(
            directory,
            exist_ok=exist_ok,
        )
        return

    missing: list[Path] = []
    cursor = directory

    while not cursor.exists():
        if cursor.is_symlink():
            raise FileExistsError(
                f"Durable directory ancestor is a symlink: {cursor}"
            )

        missing.append(cursor)

        parent = cursor.parent

        if parent == cursor:
            raise FileNotFoundError(
                f"No existing ancestor for durable directory: {directory}"
            )

        cursor = parent

    if cursor.is_symlink() or not cursor.is_dir():
        raise NotADirectoryError(
            f"Durable directory ancestor is unsafe: {cursor}"
        )

    for item in reversed(missing):
        _durable_create_one_directory(
            item,
            exist_ok=(
                exist_ok
                if item == directory
                else True
            ),
        )


def _durable_create_one_directory(
    directory: Path,
    *,
    exist_ok: bool,
) -> None:
    parent = directory.parent

    if not parent.is_dir() or parent.is_symlink():
        raise NotADirectoryError(
            f"Durable directory parent is unsafe: {parent}"
        )

    if _is_windows():
        _windows_durable_create_directory(
            directory,
            exist_ok=exist_ok,
        )
        return

    try:
        directory.mkdir(
            parents=False,
            exist_ok=False,
        )
    except FileExistsError:
        if (
            exist_ok
            and directory.is_dir()
            and not directory.is_symlink()
        ):
            return
        raise

    # mkdir creates an entry in the parent directory. Persist that
    # entry before allowing callers to publish data below it.
    fsync_directory(
        parent
    )


def _windows_durable_create_directory(
    directory: Path,
    *,
    exist_ok: bool,
) -> None:
    """Publish one new Windows directory using a write-through move."""

    staging = directory.with_name(
        f".{directory.name}."
        f"{secrets.token_hex(8)}.mkdir-partial"
    )

    staging.mkdir(
        parents=False,
        exist_ok=False,
    )

    try:
        try:
            # Directory sources intentionally omit
            # MOVEFILE_REPLACE_EXISTING.
            _windows_replace_write_through(
                staging,
                directory,
            )
        except OSError:
            if (
                exist_ok
                and directory.is_dir()
                and not directory.is_symlink()
            ):
                return
            raise
    finally:
        try:
            staging.rmdir()
        except FileNotFoundError:
            pass

def fsync_directory(path: Path) -> None:
    """Synchronize one directory entry set on POSIX.

    Windows publication uses MoveFileExW WRITE_THROUGH instead. Python does
    not expose a portable directory-fsync contract there.
    """

    if _is_windows():
        return

    flags = os.O_RDONLY
    directory_flag = getattr(
        os,
        "O_DIRECTORY",
        0,
    )
    flags |= directory_flag

    descriptor = os.open(
        path,
        flags,
    )
    try:
        os.fsync(
            descriptor
        )
    finally:
        os.close(
            descriptor
        )


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_api_path(path: Path) -> str:
    """Return an absolute Win32 extended-length path without resolving links."""

    value = str(path.absolute())

    if value.startswith("\\\\?\\"):
        return value

    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]

    return "\\\\?\\" + value


def _windows_replace_write_through(
    source: Path,
    destination: Path,
) -> None:
    """Publish with the Win32 write-through rename primitive."""

    import ctypes
    from ctypes import wintypes

    # These ctypes symbols exist only on Windows. Resolve them dynamically so
    # non-Windows type checking does not require Windows-only ctypes stubs.
    win_dll = vars(ctypes)["WinDLL"]
    get_last_error = vars(ctypes)["get_last_error"]

    # MOVEFILE_REPLACE_EXISTING cannot replace an existing directory.
    # ATHENA directory publications already require an absent destination.
    source_is_directory = source.is_dir()

    if source_is_directory and destination.exists():
        raise FileExistsError(
            f"Durable directory destination already exists: {destination}"
        )

    kernel32 = win_dll(
        "kernel32",
        use_last_error=True,
    )

    move_file_ex = kernel32.MoveFileExW
    move_file_ex.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
    )
    move_file_ex.restype = wintypes.BOOL

    flags = _MOVEFILE_WRITE_THROUGH

    if not source_is_directory:
        flags |= _MOVEFILE_REPLACE_EXISTING

    succeeded = move_file_ex(
        _windows_api_path(source),
        _windows_api_path(destination),
        flags,
    )

    if succeeded:
        return

    error = get_last_error()

    raise OSError(
        error,
        f"MoveFileExW durable publication failed "
        f"with Windows error {error}.",
        str(destination),
    )
