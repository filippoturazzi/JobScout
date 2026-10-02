# Stage 4 — Notifier and the first channel: Design Spec

**Date:** 2026-10-01
**Status:** Approved for planning
**Parent spec:** `docs/superpowers/specs/2026-09-19-jobscout-design.md` (amends §4, §5 step 4, §7)
**Input:** the stage-4 items in `docs/superpowers/notes/2026-09-20-stage-1-followups.md`

## 1. Purpose

Close the loop. JobScout already collects and scores on its own, but the user only
learns about a match by asking. This stage makes it reach out: a daily digest e-mail
of matches that cleared the user's threshold and have never been sent before.

Parent-spec success criterion: *a notification arrives.*

## 2. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Channel | E-mail over SMTP, via the stdlib (`smtplib` + `email.message`). No new dependency. | Universal, needs no app or account on the user's side, and the recipient is a per-user value — which is what lets the hosted demo work without the operator registering anyone. |
| Cadence | One digest per day at `DIGEST_HOUR`, batching everything above the threshold since the last send. | Matching runs every 15 minutes; notifying on discovery would mean up to 96 e-mails a day. A daily digest is the format e-mail is good at, and it matches how job-hunting actually works. |
| Re-notification | A new `Match.notified_at` column. Selection keys on `notified_at IS NULL`, never on `status`. | `notified` sat in `MATCH_STATUSES` beside `saved` and `dismissed`, conflating *what the system did* with *what the user thinks*. Staling rewrote the status to `new`, so an already-announced job would return to the next digest. Separating the two fixes the category error, not just the symptom. |
| Send failure | `notified_at` is written only after the SMTP server accepts the message. A failed attempt leaves the matches pending and retries hourly until it succeeds or the day ends. | Marking before sending would make a transient failure silently swallow those matches forever — the same mistake as recording that something happened before it happened. Hourly retry turns a one-minute outage into a one-hour delay instead of a lost day. |
| Threshold | `min_score_to_notify` stays at 70. | Deliberate, not an oversight. Measured on the live corpus, relevant and irrelevant postings overlap and the LLM scores most of this (largely German, largely non-technical) corpus between 0 and 35. **The likely outcome is that no e-mail is sent at all until stage 5 adds sources that contain relevant jobs.** Lowering the default to force a send would make the first notification a false positive, which is worse than silence. |
| Body format | Plain text. | Better deliverability for self-hosters, no template engine, no new dependency, and the content is a short list. The `Notifier` protocol isolates this if HTML is wanted later. |
| Labels | English, while the LLM's `reasoning` keeps coming through in the user's `locale`. | The e-mail will read as mixed. A label dictionary is cheap but starts i18n from the edge, before stage 6 decides where translations live. Six or seven labels is a small, visible debt. |

## 3. Amendments to the parent spec

- **§4 components:** `notifiers/base.py` gains `email.py` and a `build_notifier` factory;
  `pipeline/digest.py` and `scheduler.py::digest_job` are new.
- **§4 config:** add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`,
  `SMTP_STARTTLS`, `DIGEST_HOUR`, `DIGEST_INTERVAL_MINUTES`.
- **§5 step 4:** replace "`Notifier.send(match)` fires when `match.score >=
  prefs.min_score_to_notify` and `status == new`" with the digest rule in §5.2 below.
  Notification no longer keys on `status`.
- **§7:** `Match` gains `notified_at: datetime | None`; `UserPreferences` gains
  `notify_email: str | None`.

## 4. Components

```
src/jobscout/notifiers/base.py       Notifier protocol: send(subject, body) -> None
src/jobscout/notifiers/email.py      SmtpNotifier; render_digest(rows, locale) -> (subject, body)
src/jobscout/notifiers/__init__.py   build_notifier(settings) -> Notifier | None
src/jobscout/pipeline/digest.py      select_unnotified(...); mark_notified(...)
src/jobscout/scheduler.py            + digest_job(engine, settings)
src/jobscout/models/match.py         + notified_at: datetime | None
src/jobscout/models/user.py          + notify_email: str | None
src/jobscout/config.py               the eight settings above
```

`notifiers` depends only on `models` — no DB session, no scheduler, no HTTP. All queries
live in `pipeline/digest.py`. `scheduler.py` composes the two, exactly as it already
composes ingest and matching.

**Operator config vs user preference**, the project's hard rule: SMTP credentials and
`DIGEST_HOUR` identify *who runs the instance* and live in env. The recipient address
describes *what a person wants* and lives in `UserPreferences`.

## 5. Behavior details

### 5.1 `digest_job`

Registered on the scheduler at `DIGEST_INTERVAL_MINUTES` (default 60), **not** on a daily
schedule. That one setting is both the polling interval and, therefore, the retry cadence —
there is no second retry setting, because a separate one would be a value nothing reads.
Each firing, per user with a `notify_email`:

1. If `max(notified_at)` for that user is today, return — already sent.
2. If the current local hour is **before** `DIGEST_HOUR`, return. At or after it, proceed —
   so a window missed because the process was down is still served later the same day,
   rather than skipped until tomorrow.
3. Select the rows (§5.2). If none, return **without writing a `Run` row** — the same
   shape as a tick the backoff skips.
4. Render and send. On success, set `notified_at = utcnow()` on exactly the rows sent.
5. Write one `Run` row for the attempt, success or failure.

An hour-interval job with a date check gives the hourly retry without a second schedule or
any in-memory retry state: the decision is derived from `notified_at` and the `Run` table,
both of which survive a restart.

**Timezone.** `DIGEST_HOUR` is interpreted in the **server's local timezone**, which is what
a self-hoster means when they write `9`. It must be computed from an explicitly aware
datetime. This is called out because the project's "all timestamps are naive UTC" rule
already came within one commit of shipping a wake that fired three hours late; this is the
second value that crosses into timezone-interpreting territory. Per-user timezones are
stage 6.

### 5.2 Selection

A `Match` enters the digest when **all** hold:

- `score >= prefs.min_score_to_notify`
- `notified_at IS NULL`
- `status != "dismissed"`
- the joined `Job.is_active` is true

Ordered by `score DESC`, capped at **20 rows**. Rows beyond the cap are **not** marked
notified, so they appear in the next digest; the body says how many were held back.

Three consequences, stated so nobody has to re-derive them:
- `low` rows (null score) never qualify — they cannot clear a threshold.
- A **dismissed** job never returns, even if re-scoring raises it. The user's no persists,
  exactly as it does through staling.
- A job that **went inactive** between scoring and sending is not announced. Notifying
  about a dead posting is worse than not notifying.

### 5.3 The message

```
Subject: JobScout: 4 new matches

[88] Senior AI Engineer — Acme (remote)
     Strong overlap on Python, LLM work and LangGraph.
     Missing: Kubernetes
     https://www.arbeitnow.com/jobs/...

[81] ML Engineer — Beta (Berlin)
     ...

7 more — see /matches
```

`reasoning` arrives in the user's `locale` because `build_user_prompt` already asks the LLM
for it; the surrounding labels are English (§2).

### 5.4 Degradation

- No SMTP configured → `build_notifier` returns `None`, `digest_job` logs once and returns.
- A user with no `notify_email` → skipped silently; other users still receive theirs.
- Send raises → no `notified_at`, a `Run` row with `ok=False` and the SMTP message, and the
  stage-3 consecutive-failure backoff spaces out later attempts. A broken SMTP server does
  not produce 24 attempts a day.
- Nothing above threshold → no e-mail, no `Run` row. The operator sees a gap in `/runs`
  rather than a daily "nothing to do" line. Accepted: one row a day means a two-day gap is
  visible.

## 6. Out of scope

HTML bodies; more than one channel at a time; a per-user digest hour or timezone;
unsubscribe links; retries that cross into the next day; i18n of the labels; and changing
`min_score_to_notify`.

## 7. Testing

No test touches SMTP, the network, or a real clock.

- A project-owned fake `Notifier` records what it was asked to send, in the shape of the
  existing test doubles.
- **Selection:** threshold respected; `notified_at IS NULL` respected; a dismissed match
  excluded; an inactive job excluded; a `low` row excluded; ordering by score.
- **Cap:** 25 qualifying rows send 20 and mark 20; the remaining 5 appear next time and the
  body names the count.
- **Failure:** a raising notifier leaves every `notified_at` null, writes `ok=False` with
  the message, and the same rows are selected on the next attempt.
- **Idempotence:** two firings in the same day send once.
- **Retry:** a failure at the digest hour is retried on the next hourly firing.
- **Degradation:** no SMTP, and a user without `notify_email`, are both no-ops that do not
  raise and do not stop other users.
- **Rendering:** the body is asserted as a string, including the "N more" line.

## 8. Done when

`uv run pytest` green with no warnings; `mypy src` clean; ruff clean; CI green; and a real
digest arrives in a real inbox from a real SMTP server, with `GET /runs` showing the
`digest` row that sent it.

## 9. Carried forward, deliberately not solved here

With `min_score_to_notify` at 70 and the current corpus, **the live check in §8 may be
impossible to satisfy until stage 5**: nothing scores high enough to send. The stage-3
similarity-distribution log (`LOG_LEVEL=INFO`) is the instrument for deciding whether the
threshold or the corpus is the problem. If the live check cannot be run, that is a finding
about matching quality, not a failure of this stage — record it and move on rather than
lowering the threshold to manufacture a send.
