---
title: When WAL mode is the wrong choice
---
WAL mode uses a shared-memory index in a file with the -shm suffix, so every process that opens the database must run on the same host.
WAL mode does not work on a network filesystem, because the shared-memory index cannot be shared across machines.
A database in WAL mode is enabled with PRAGMA journal_mode=WAL, and the setting persists: later connections open the database in WAL mode too.
Opening a WAL database needs write access to the directory, or the -wal and -shm files must already exist.
Reads can get slower when the WAL file grows large, because a reader must search the WAL index before reading a page.
