# 0010. A project store on disk; cleaning as flags, not deletions; one operation log

**Status:** Proposed. Designed in the build plan; to be confirmed before Phase 1 starts.

## Context

A session's data lives in server memory. After a restart only `runconfig.json` is restored;
the timeseries, cleaning log, tables and results are lost. Cleaning writes "missing" into the
working table, so the record of why a value is missing exists only in the cleaning log.

## Proposal

- **Project on disk:** raw input files kept untouched, each with its SHA-256; working data
  as Parquet; a small SQLite catalogue for the operation log, selections, flags and the
  results index.
- **Flags instead of deletion:** a per-record flag table (rule, reason code, actor, time).
  The clean series is the raw data with flags applied, and undoing a cleaning step removes
  its flags. Gate: every published number on the reference campaigns is identical before
  and after.
- **One operation log** for undo and redo, the audit trail, the reproducibility record and
  the assistant's history. Each entry carries the actor ([0003](0003-local-single-user.md)),
  inputs, parameters, code version and the resulting data version.
- **Results cached by content hash,** extending today's `data_version` stamps, so reopening a
  project recomputes nothing and nothing is recomputed silently.
- `SessionState` stays as an in-memory view over the project during the migration.

## Consequences

- Existing sessions and stored sweeps are not migrated (owner, 2026-11-17).
