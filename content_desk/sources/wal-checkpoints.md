---
title: Checkpoints and WAL file growth
---
By default SQLite runs an automatic checkpoint when the WAL file reaches 1000 pages.
The PRAGMA wal_autocheckpoint setting changes that threshold, and a value of zero turns automatic checkpoints off.
The PRAGMA wal_checkpoint statement runs a checkpoint by hand in one of four modes: PASSIVE, FULL, RESTART or TRUNCATE.
A checkpoint cannot copy pages that an active reader may still need, so a long-running read transaction can stop the WAL file from being reset.
When readers never pause, the WAL file can keep growing, a problem known as checkpoint starvation.
The TRUNCATE mode resets the WAL file to zero bytes after a successful checkpoint.
