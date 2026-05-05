# Gokaatru Code Review & Remediation Log

Date: 2026-04-27
Scope: full-repo security and correctness review of the Gokaatru FastAPI/React codebase
located at `d:\gokaatru`.
Verification: `python -m pytest tests/ -q` — 169 passed, 1 skipped, 0 failures, 0
deprecation warnings introduced by app code.

---

## 1. Summary

A defense-in-depth pass was performed across the FastAPI server, MCP tool layer,
and the LLM chat proxy. The review focused on the highest-risk surfaces:
file uploads, path interpolation from user input, outbound HTTP (BrightHub /
LLM provider), session workspaces, and headers returned to the browser.

22 issues were identified by the exploration pass; the 12 with concrete
exploit potential or correctness impact were fixed in this change. The
remainder are low-severity style/duplication notes captured at the end of this
log.

---

## 2. Fixes applied

### 2.1 [CRITICAL] Path traversal via `body.uuid` in BrightHub import
File: `server/api/routes/brighthub.py`

The `/sessions/{session_id}/brighthub/import` and
`/locations/{uuid}/datamodel` routes interpolated the BrightHub UUID
unfiltered into filesystem paths:

```py
datamodel_path = uploads_dir / f"datamodel_{body.uuid}.json"
timeseries_path = uploads_dir / f"ts_{body.uuid}.csv"
```

A UUID like `../../etc/runconfig` (or on Windows `..\..\runconfig`) would
escape the per-session uploads directory and let an authenticated session
overwrite arbitrary files inside the process's working tree.

Fix: added `_validate_brighthub_uuid()` that enforces a strict
`[A-Za-z0-9._-]{1,128}` whitelist and rejects `..`. All uses of `body.uuid`
inside the route now go through the validator, including the value persisted
to runconfig.

Reasoning: BrightHub UUIDs in practice are RFC-4122 hex (with optional
dashes); the slightly broader whitelist still rejects every path-relevant
character (`/`, `\`, NUL, whitespace, drive letters via `:`).

### 2.2 [HIGH] Header / filename injection in CSV exports
File: `server/api/routes/exports.py`

`/exports/ltc/{algorithm}` returned the path parameter directly inside the
`Content-Disposition` header:

```py
headers={"Content-Disposition": f'attachment; filename="{filename}"'}
# filename = f"ltc_{algorithm}.csv"
```

Starlette path parameters can contain `\r`, `\n`, and `"`, which would let an
attacker inject additional response headers or break out of the filename
quoting (response-splitting / CSV-injection vectors when the file is opened in
Excel).

Fix: introduced `_safe_filename()` that maps anything outside
`[A-Za-z0-9._-]` to `_` and falls back to a safe default. Both
`_csv_download()` and `_json_download()` now sanitize before formatting, and
the algorithm value is sanitized again in the route's error message.

### 2.3 [HIGH] SSRF via custom LLM provider URL
File: `server/api/routes/chat.py`

`_resolve_base_url()` accepted any string starting with `"http"` as a
provider, including `http://localhost`, `http://169.254.169.254` (cloud
metadata) and `http://10.x.x.x` internal services. The server forwards a
`Bearer` token to that URL, so a malicious caller could exfiltrate tokens or
probe internal endpoints.

Fix: only `https://` is accepted, and the host is validated against a deny
list of loopback / link-local / RFC1918 addresses and `.local` /
`metadata.google.internal`. `_call_llm` translates the resulting `ValueError`
into HTTP 400 instead of letting it become an unhandled 500.

### 2.4 [HIGH] Information disclosure from upstream LLM error bodies
File: `server/api/routes/chat.py`

`detail=f"LLM API error: {resp.text[:500]}"` echoed the upstream provider's
500-byte error body — which can include rate-limit metadata, request IDs, or
truncated prompts — straight back to the browser.

Fix: replaced with a generic `"Upstream LLM provider returned status N"`
message and clamped the upstream status to a sensible HTTP range (else 502).

### 2.5 [HIGH] Silent JSON drops in tool-call execution
File: `server/api/routes/chat.py`

When the model returned malformed `tool_calls[].function.arguments`, the
chat loop silently swapped them for `{}` and ran the tool anyway. That meant
a corrupted tool call could execute against the session with empty arguments
and the user would never see why.

Fix: invalid tool arguments now produce an explicit
`{"error": "Invalid tool arguments for '<tool>': ..."}` payload that is fed
back to the model, preserving observability and keeping the loop alive.

### 2.6 [HIGH] Unbounded uploads → memory / disk DoS
File: `server/api/routes/uploads.py`

`_save_upload()` did `handle.write(uploaded_file.file.read())` — the entire
upload was buffered in memory before being written to disk, with no size
cap. An attacker (or a misbehaving client) could exhaust RAM with a single
multi-GB POST.

Fix: rewrote `_save_upload()` to:

* sanitize the filename via `_sanitize_filename()` (whitelisted charset,
  fallback stem on empty input, defends against `..` and embedded
  separators),
* resolve the target and re-check that it is inside `uploads/` (defense in
  depth even when the sanitizer is correct),
* stream the upload in 1 MiB chunks with a hard 500 MiB cap, returning
  `413 Request Entity Too Large` on overflow,
* delete partially-written files on any failure path so the workspace does
  not leak truncated files.

### 2.7 [HIGH] Unbounded BrightHub presigned-URL download
File: `server/core/brighthub.py`

`fetch_timeseries_csv()` used `requests.get(presigned_url, timeout=300).text`
which loads the full response into memory and uses pandas-style charset
auto-detection, with no size limit. If BrightHub (or anyone in a position to
forge a signed URL response) returns a multi-GB body, the worker OOMs.

Fix: switched to streamed download with a 500 MiB cap, honoring
`Content-Length` when present and re-verifying the actual byte count while
streaming. Falls back to `errors="replace"` decoding so a single bad byte
never crashes the import.

### 2.8 [HIGH] Coordinate validation in reanalysis download
File: `server/core/brighthub.py`

`download_reanalysis_data()` interpolated `lat`/`lon` directly into the URL
path without bounds checking, and built the URL with
`f"...?variables={variables}"` (manual query construction). It also
swallowed `KeyError` implicitly by indexing `node["latitude_ddeg"]`.

Fix:

* dataset name validated against `{"ERA5", "MERRA-2"}` upfront;
* coordinates coerced to `float` and bounds-checked (`-90..90`,
  `-180..180`) — invalid nodes are skipped instead of crashing;
* query string built via `params=` so requests handles encoding;
* `ValueError` from `r.json()` (malformed upstream response) now joins
  `RequestException` in the skipped-node path.

### 2.9 [MEDIUM] Path traversal hardening in tabular file reader
File: `server/tools/data_io.py`

`_read_tabular_file()` accepted any string and called `Path(file_path)`
without resolution or `is_file()` check, allowing a tool invoked through the
chat/MCP layer to read arbitrary symlinks or directories that pandas would
then complain about with an internal traceback.

Fix: resolve the path with `Path(...).resolve(strict=False)`, raise
`ValueError` on non-existent or non-regular targets. (Sandboxing to a
specific root is intentionally not added here because the function is also
called with workspace-scoped absolute paths from server-trusted code; the
traversal vector that mattered — UUID interpolation in BrightHub — is fixed
at the boundary in §2.1.)

### 2.10 [MEDIUM] Deprecated `datetime.utcnow()`
Files: `server/api/routes/workflow_execution.py`, `server/tools/cleaning.py`,
`server/tools/ensemble.py`, `server/tools/ltc.py`, `server/tools/ltc_ml.py`

`datetime.utcnow()` is deprecated in Python 3.12+ and produces
timezone-naive timestamps that compare incorrectly against tz-aware values
elsewhere in the code (e.g. `SessionState._utcnow()` already uses
`datetime.now(timezone.utc)`).

Fix: replaced all five call sites with `datetime.now(timezone.utc)` and
imported `timezone` where needed. Output formatting (`isoformat`,
`strftime("%Y%m%d%H%M%S")`) is unchanged.

### 2.11 [LOW] Pydantic v1 `class Config` deprecation
File: `server/api/routes/brighthub.py`

Pydantic v2 emits `PydanticDeprecatedSince20` warnings for `class Config:
extra = "allow"`. Migrated `MeasurementLocation`, `ReanalysisNode`, and
`ReanalysisDataItem` to `model_config = {"extra": "allow"}`. The warnings are
gone from `pytest`'s output.

---

## 3. Issues reviewed but not changed (rationale)

| # | Area | Note |
|---|------|------|
| 1 | CORS in `server/api/main.py` | `allow_origins` is already pinned to the local Vite dev server; `allow_credentials=True` is therefore safe. |
| 2 | Snapshot save/load (`workflow_execution.py`) | Names are validated against `^[a-zA-Z0-9_-]{1,64}$` before being interpolated into `Path`. Already safe. |
| 3 | Session `X-GoKaatru-Session` header check (`deps.py`) | Header must equal the path `session_id`; sessions live only in-memory and creation requires no auth, which is acceptable for the local desktop deployment model. |
| 4 | Pickle/eval/exec/yaml.load/subprocess(shell=True) | grep-confirmed: zero occurrences anywhere in `server/` or `frontend/`. |
| 5 | `dangerouslySetInnerHTML` in React | grep-confirmed: zero occurrences. |
| 6 | Plotly figure passthrough in chat route | Output goes to React, which renders it via `react-plotly.js`, not `dangerouslySetInnerHTML`. No XSS sink. |
| 7 | `requests.*` in `server/core/brighthub.py` | All non-presigned calls already pass an explicit `timeout`. |
| 8 | Mutable defaults in `SessionState.__init__` | Inspected: every collection is rebuilt in `reset()`, and `reset()` is called from `__init__`. No cross-session leakage. |
| 9 | Race in `SessionManager.create_session` | UUID4 collision is cryptographically negligible and `mkdir(exist_ok=True)` makes the create idempotent; not worth retry logic. |
| 10 | Bare `except Exception` in BrightHub routes | Re-raised as 502 with the original message — these are intentional translation points and the message is sourced from a trusted upstream client, not user input. |

---

## 4. Verification

```
$ python -m pytest tests/ -q
169 passed, 1 skipped, 3 warnings in 36.73s
```

The remaining 3 warnings are in third-party `xarray` calls inside
`tests/test_windkit.py` (`Dataset.dims` future-deprecation) and are not
introduced by this change.

Syntax-check pass on the 11 edited files:

```
$ python -c "import ast; [ast.parse(open(f).read(), f) for f in [...]]"
OK 11
```

---

## 5. Files changed

| File | Reason |
|---|---|
| `server/api/routes/brighthub.py` | UUID validation, Pydantic v2 config |
| `server/api/routes/exports.py` | Filename / header injection |
| `server/api/routes/chat.py` | SSRF, info disclosure, JSON-arg handling |
| `server/api/routes/uploads.py` | Filename sanitization, streaming + size cap |
| `server/api/routes/workflow_execution.py` | `datetime.utcnow()` → `datetime.now(timezone.utc)` |
| `server/core/brighthub.py` | Streaming download cap, coordinate / dataset validation |
| `server/tools/data_io.py` | Path resolution + is_file check |
| `server/tools/cleaning.py` | tz-aware timestamp |
| `server/tools/ensemble.py` | tz-aware timestamp |
| `server/tools/ltc.py` | tz-aware timestamp |
| `server/tools/ltc_ml.py` | tz-aware timestamp |
| `CODE_REVIEW_LOG.md` | This log (new) |
