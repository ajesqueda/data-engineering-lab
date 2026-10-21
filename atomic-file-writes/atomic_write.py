"""Crash-safe file writes with the POSIX file API: temp file + fsync + rename.

A pipeline that overwrites `output.csv` in place has a window where the file
is half old, half new, or empty. If the job dies in that window, the next
reader (a dashboard, a downstream task) sees garbage.

The fix that databases, Spark output committers and most file-based tools
rely on:

    1. write the new content to a temp file in the *same directory*
    2. fsync the temp file          -> the bytes are on disk, not just in RAM
    3. rename temp -> target        -> POSIX makes this atomic within one filesystem
    4. fsync the directory          -> the rename itself survives a power cut

Readers then see either the complete old file or the complete new file, never
a mix. This module uses `os.open`/`os.write`/`os.fsync` directly so each
system call is visible.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from pathlib import Path

# Called after each chunk is written. Tests use it to simulate a crash halfway.
ChunkHook = Callable[[int], None]


def _write_chunks(fd: int, chunks: Iterable[bytes], on_chunk: ChunkHook | None) -> None:
    for i, chunk in enumerate(chunks):
        view = memoryview(chunk)
        # os.write may write fewer bytes than asked (a "short write"), so loop.
        while view:
            written = os.write(fd, view)
            view = view[written:]
        if on_chunk:
            on_chunk(i)


def naive_write(path: Path, chunks: Iterable[bytes], on_chunk: ChunkHook | None = None) -> None:
    """Overwrite `path` in place. O_TRUNC empties the old file *immediately*."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        _write_chunks(fd, chunks, on_chunk)
    finally:
        os.close(fd)


def atomic_write(path: Path, chunks: Iterable[bytes], on_chunk: ChunkHook | None = None) -> None:
    """Replace `path` so readers see either the old or the new content, nothing in between."""
    path = Path(path)
    # Same directory as the target: rename is only atomic within one
    # filesystem, and /tmp is often a different one.
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    # O_EXCL: fail rather than clobber a temp file another writer owns.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        try:
            _write_chunks(fd, chunks, on_chunk)
            # Without fsync the data may still be in the OS page cache. A
            # power cut after the rename could leave a renamed but empty file.
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)  # rename(2): atomic swap of the directory entry
    except BaseException:
        # Leave no half-written temp files behind for the next run to trip on.
        tmp.unlink(missing_ok=True)
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    # A rename changes the *directory*, which is itself a file of
    # name -> inode entries. Syncing it makes the new entry durable.
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "daily_totals.csv"
        old = [b"date,total\n", b"2026-10-20,100\n"]
        new = [b"date,total\n", b"2026-10-20,100\n", b"2026-10-21,250\n"]

        def crash_after_first_chunk(i: int) -> None:
            if i == 0:
                raise RuntimeError("simulated crash")

        for name, writer in (("naive", naive_write), ("atomic", atomic_write)):
            atomic_write(target, old)
            try:
                writer(target, new, on_chunk=crash_after_first_chunk)
            except RuntimeError:
                pass
            print(f"{name:>6} write crashed mid-way; file now holds: {target.read_bytes()!r}")


if __name__ == "__main__":
    main()
