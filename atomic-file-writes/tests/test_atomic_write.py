import os
from pathlib import Path

import pytest
from atomic_write import atomic_write, naive_write

OLD = [b"id,value\n", b"1,old\n"]
NEW = [b"id,value\n", b"1,new\n", b"2,new\n"]


class SimulatedCrash(Exception):
    pass


def crash_after(n: int):
    def hook(i: int) -> None:
        if i == n:
            raise SimulatedCrash
    return hook


@pytest.fixture
def target(tmp_path: Path) -> Path:
    path = tmp_path / "out.csv"
    path.write_bytes(b"".join(OLD))
    return path


def test_atomic_write_replaces_content(target):
    atomic_write(target, NEW)
    assert target.read_bytes() == b"".join(NEW)


def test_atomic_write_creates_missing_file(tmp_path):
    path = tmp_path / "fresh.csv"
    atomic_write(path, NEW)
    assert path.read_bytes() == b"".join(NEW)


def test_naive_write_leaves_a_torn_file_on_crash(target):
    with pytest.raises(SimulatedCrash):
        naive_write(target, NEW, on_chunk=crash_after(0))
    # Neither the old nor the new content: a reader would get a broken file.
    assert target.read_bytes() == NEW[0]
    assert target.read_bytes() not in (b"".join(OLD), b"".join(NEW))


@pytest.mark.parametrize("crash_at", [0, 1, 2])
def test_atomic_write_keeps_old_file_on_crash(target, crash_at):
    with pytest.raises(SimulatedCrash):
        atomic_write(target, NEW, on_chunk=crash_after(crash_at))
    assert target.read_bytes() == b"".join(OLD)


def test_crash_cleans_up_temp_file(target):
    with pytest.raises(SimulatedCrash):
        atomic_write(target, NEW, on_chunk=crash_after(1))
    assert sorted(p.name for p in target.parent.iterdir()) == ["out.csv"]


def test_reader_holding_old_file_is_unaffected(target):
    # An open file descriptor points at the *inode*, not the name. After the
    # rename the name points at a new inode, and the reader keeps the old one.
    with target.open("rb") as reader:
        atomic_write(target, NEW)
        assert reader.read() == b"".join(OLD)
    assert target.read_bytes() == b"".join(NEW)


def test_rename_swaps_the_inode(target):
    before = os.stat(target).st_ino
    atomic_write(target, NEW)
    assert os.stat(target).st_ino != before
