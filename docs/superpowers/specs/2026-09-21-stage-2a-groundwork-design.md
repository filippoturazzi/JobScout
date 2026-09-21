# Stage 2a — Groundwork for matching: Design Spec

**Date:** 2026-09-21
**Status:** Approved for planning
**Parent spec:** `docs/superpowers/specs/2026-09-19-jobscout-design.md` (this document amends §4, §5, §8 as noted)
**Input:** `docs/superpowers/notes/2026-09-20-stage-1-followups.md`

## 1. Purpose

Prepare the stage-1 pipeline to receive the matching graph (stage 2b) without any AI code yet. Every item here was surfaced by the stage-1 whole-branch review; each either changes a contract stage 2b will build on, or fixes a defect that would otherwise be baked into embeddings and matches. No new dependencies except `mypy`.

## 2. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Ingest scope | Ingest is instance-global. `run_ingest(session, settings, sources=None)` takes no `user_id` and passes an empty `SearchQuery()` to sources. `build_query` is removed. | `Job` is global (§7). Per-user ingest starves the table and breaks stage-3 liveness and stage-6 multi-user. Stage 5 reintroduces a query built from the union of all users' keywords for sources with server-side search. |
| Metadata refresh | Every sighting refreshes `company, location, remote, url, salary_min, salary_max, salary_currency, tags, posted_at, raw`. `content_hash` (title + description) alone decides `changed`: update title/description, clear `embedding`, and (stage 2b) mark matches stale. | Metadata feeds the deterministic filter and the LLM prompt; a stale salary or work mode is a wrong decision. Re-embedding only on text change keeps LLM cost tied to real content changes. |
| Upsert result | `UpsertStats` gains `created_ids: list[int]` and `changed_ids: list[int]`, populated after `session.flush()`. `IngestResult` exposes them too. | Stage 2b matches exactly these ids and marks their matches stale in one bulk `UPDATE`; a timestamp query would be racy. |
| Engine seam | `db.get_engine(settings: Settings \| None = None)` caches one engine per `database_url`; `db.reset_engines()` disposes and clears. CLI and API lifespan both use it. | One engine story before the stage-3 scheduler adds a third caller; makes the lifespan testable. |
| Filters | One tokenizer; exclusions match contiguous token sequences in title tokens or equal a tag's tokens; regions match a comma-separated location segment (equal or contiguous subsequence); titles keep the word-subset rule. No alias map. | Substring matching produced silent false negatives (`"ai"` rejected "Maintenance") and false positives (`"US"` accepted "Australia"). Aliases (US/USA/United States) are deferred until a real user needs them. |
| `html_to_text` | Text nodes concatenate with `""`; block-level tags emit `"\n"`; final whitespace collapse. | Inline tags no longer split words (`Java<b>Script</b>`), so embeddings see intact tokens. |
| mypy | `mypy --strict` on `src/` only, pydantic plugin, in CI. Targeted `# type: ignore[code]` allowed; global rule relaxation is not. | Cheap now; catches graph-state mistakes in stage 2b. |
| Non-nullable preference fields | `api/schemas.py` derives the "cannot be null" field set from `UserPreferences.__table__` columns (non-nullable, not protected); a test asserts it equals what `update_preferences` enforces. | One source of truth for a rule enforced in two layers. |

## 3. Amendments to the parent spec

- **§4 `pipeline/run.py`:** `run_ingest(session, settings, sources=None)`; `list_jobs` unchanged (per user).
- **§5 step 1:** "Sources return everything they fetch; `SearchQuery` only parameterizes APIs that require server-side search; user filtering happens in `pipeline/filters.py` and, from stage 2b, in the matching graph."
- **§5 step 2:** replace the three bullets with: *known → refresh metadata and `last_seen_at`, reactivate; if `content_hash` differs → also update title/description, clear `embedding`, mark matches stale (stage 2b).*
- **§8:** unchanged in intent; the engine seam adds "the API lifespan is covered by a test that runs `init_db` and the default-user bootstrap through `get_engine()`."

## 4. Components

```
src/jobscout/db.py               get_engine(settings=None), reset_engines(), _engines dict
src/jobscout/pipeline/ingest.py  UpsertStats(+created_ids, +changed_ids); IngestResult(+created_ids, +changed_ids);
                                 upsert_jobs refreshes metadata every sighting
src/jobscout/pipeline/run.py     run_ingest(session, settings, sources=None); build_query removed
src/jobscout/pipeline/filters.py tokenize(); exclusions/regions rewritten on tokens
src/jobscout/sources/text.py     block-aware joining
src/jobscout/cli.py              fetch uses get_engine(settings); no user lookup
src/jobscout/api/app.py          lifespan uses get_engine()
src/jobscout/api/schemas.py      NON_NULLABLE_PREFERENCE_FIELDS derived from the table
src/jobscout/pipeline/users.py   exports the same derivation (or imports it) so both layers share it
pyproject.toml                   mypy dev dep + [tool.mypy]; CI step
tests/                           updated + new tests per section 6
```

Dependency rules from the parent spec still hold: `sources` has no DB imports; `pipeline` is the only composer; `api`/`cli` thin. `api/schemas.py` importing `jobscout.models` is allowed (`api` → `models` is downward).

## 5. Behavior details

### 5.1 `upsert_jobs`

For each `(source, external_id)` in the batch (duplicates collapsed, last wins):

- **new:** insert; `first_seen_at = last_seen_at = now`; `is_active = True`; `content_hash` computed. Appended to `created_ids` after flush.
- **known:** set `last_seen_at = now`, `is_active = True`, and copy all metadata fields from the `RawJob`. If `content_hash(raw.title, raw.description) != job.content_hash`: also set `title`, `description`, `content_hash`, `embedding = None`; append to `changed_ids`; count `changed`. Otherwise count `updated`.

Idempotency: a second run with identical data changes only `last_seen_at` (and `updated_at`).

### 5.2 `get_engine`

```python
_engines: dict[str, Engine] = {}

def get_engine(settings: Settings | None = None) -> Engine:
    url = (settings or get_settings()).database_url
    if url not in _engines:
        _engines[url] = create_engine_from_url(url)
    return _engines[url]

def reset_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
```

`tests/conftest.py` gets an autouse fixture that calls `reset_engines()` and `get_settings.cache_clear()` after each test.

### 5.3 Filters

- `tokenize(text) -> list[str]`: lowercase; regex `[a-z0-9+#.]+`; strip trailing `.`; drop empties. Preserves order (needed for contiguous matching).
- `_contains_sequence(haystack: list[str], needle: list[str]) -> bool`.
- Exclusions: for each keyword, `needle = tokenize(keyword)`; reject if `_contains_sequence(tokenize(job.title), needle)` or any `tokenize(tag) == needle`.
- Regions: `segments = [tokenize(s) for s in (job.location or "").split(",")]`; pass if any `_contains_sequence(segment, tokenize(region))`. Remote jobs and empty `regions` pass, as today.
- Titles: unchanged rule, implemented with `set(tokenize(...))`.

### 5.4 `html_to_text`

`_TextExtractor` keeps `parts`; `handle_starttag`/`handle_endtag` append `"\n"` when the tag is in `_BLOCK_TAGS`; `handle_startendtag` (e.g. `<br/>`) likewise; script/style skipping unchanged; result `"".join(parts)` → replace `\xa0` → collapse whitespace → strip. Double-encoding heuristic unchanged.

## 6. Testing

- `test_ingest.py`: metadata refresh on same-hash sighting (salary/location/tags change → persisted, `updated` counted, `embedding` kept); `created_ids`/`changed_ids` populated and empty on no-op re-run; existing tests kept.
- `test_run.py`: `run_ingest` signature; `build_query` tests deleted.
- `test_cli.py`: unchanged expectations; `fetch` no longer bootstraps a user (assert no `User` row after `fetch`).
- `tests/api/test_lifespan.py`: `with TestClient(app)` against a tmp SQLite via monkeypatched `jobscout.db.get_settings`; `GET /preferences` returns defaults; no dependency overrides.
- `test_db.py`: `get_engine` returns the same engine for the same URL, different for different URLs; `reset_engines()` yields a fresh instance.
- `test_filters.py`: existing tests as regression + `"ai"` does not reject "Maintenance Engineer"; `"machine learning"` rejects "Machine Learning Engineer"; `"US"` does not match "Sydney, Australia"; `"Germany"` matches "Berlin, Berlin, Germany"; `"New York"` matches "New York City, NY".
- `test_text.py`: existing 10 + `Java<b>Script</b>` → "JavaScript"; `<p>a</p><p>b</p>` → "a b"; `<li>x</li><li>y</li>` → "x y"; `a<br>b` → "a b".
- `tests/api/test_preferences.py`: existing + a test that `NON_NULLABLE_PREFERENCE_FIELDS == {c.name for c in UserPreferences.__table__.columns if not c.nullable} - PROTECTED`.
- CI: `uv run mypy src` added after ruff.

## 7. Out of scope

Everything in stage 2b (LLM/embeddings factory, `Match`, graph, backfill, `GET /matches`, CLI `match`); `SOURCES` dedupe, `HttpUrl` on `RawJob`, table rename `user`→`users`, region aliases, `list_jobs` batching (moves to `Match`-driven queries in 2b).

## 8. Done when

`uv run pytest` green with no warnings; `uv run mypy src` clean; CI green on GitHub; `uv run jobscout fetch && uv run jobscout jobs` behave as before on real data; parent spec amended per §3.
