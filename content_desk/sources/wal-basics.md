---
title: SQLite write-ahead logging, the basics
---
SQLite normally protects a transaction with a rollback journal that copies the original pages before they change.
In write-ahead logging mode, SQLite leaves the database file alone during a write and appends the changed pages to a separate file with the -wal suffix.
A transaction commits when a commit record is appended to the WAL file, so a commit can happen without touching the main database file.
Readers look for the newest version of each page in the WAL file first and fall back to the main database file.
A checkpoint copies the pages from the WAL file back into the main database file.
Write-ahead logging has been available since SQLite version 3.7.0, released in 2010.
