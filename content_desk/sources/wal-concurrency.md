---
title: Readers and writers in WAL mode
---
In WAL mode, readers do not block writers and a writer does not block readers.
Each reader works from a snapshot: it records the last valid commit in the WAL file when its transaction starts and ignores commits appended after that point.
There is still only one writer at a time, because all writes append to the same WAL file.
A second connection that tries to write while another write transaction is open gets SQLITE_BUSY until the first one finishes.
A busy timeout lets a connection wait and retry instead of failing immediately with SQLITE_BUSY.
