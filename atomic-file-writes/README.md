# Atomic file writes: temp file + fsync + rename

A pipeline that overwrites its output file in place can leave a **torn file** if it
crashes partway through: no longer the old data, not yet the new. This project shows
the pattern that databases, Spark's output committers and most file-based tools use
to avoid that. It's built directly on the POSIX file API.

> Concept from BU CX651 (Computer Systems), Week 7: files, file descriptors, inodes
> and directories. Applied here to a data engineering problem.

## The pattern

```
1. os.open(".out.csv.tmp", O_CREAT | O_EXCL)   write to a temp file in the same directory
2. os.fsync(fd)                                force the bytes from RAM onto disk
3. os.replace(tmp, "out.csv")                  rename(2), which POSIX makes atomic
4. os.fsync(directory)                         make the rename itself durable
```

Readers see either the whole old file or the whole new file, never anything in between.

## Run it

```bash
python atomic-file-writes/atomic_write.py
```

```
 naive write crashed mid-way; file now holds: b'date,total\n'
atomic write crashed mid-way; file now holds: b'date,total\n2026-10-20,100\n'
```

The naive writer opened the file with `O_TRUNC`, which wiped yesterday's data before
any new data arrived. The atomic writer crashed at the same point, but the old file
is untouched.

## Why each step is there

| Step | What breaks without it |
|------|------------------------|
| Temp file in the **same directory** | `rename` is only atomic within one filesystem, and `/tmp` is often a different one |
| `O_EXCL` | Two writers could silently share and corrupt one temp file |
| Loop on `os.write` | `write(2)` can do a *short write* and return fewer bytes than asked |
| `fsync(file)` | After a power cut, the rename may survive while the data, still in the page cache, doesn't |
| `fsync(directory)` | A directory is a file of name → inode entries, so the rename lives there |
| Clean up on failure | Stale `.tmp` files pile up and confuse the next run |

## What the tests prove

- A crash after any chunk leaves the old content intact and no temp files behind.
- The naive approach really does produce a torn file.
- A reader that already has the file open keeps reading the **old inode** after the
  swap. File descriptors point at inodes, not names.

```bash
pytest atomic-file-writes
```

## Where this shows up in data engineering

- Writing a daily extract or a checkpoint/state file that the next run reads
- Spark and Hadoop output committers: write to `_temporary/`, then rename into place
- Object stores like S3 don't have POSIX rename. That's one reason table formats such
  as Delta and Iceberg commit through an atomic metadata or log write instead.
