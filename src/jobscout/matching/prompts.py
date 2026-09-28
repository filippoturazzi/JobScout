"""Prompt construction. Pure functions over models — no I/O."""

from jobscout.models import Job, UserPreferences

MAX_DESCRIPTION_CHARS = 6000

# The prefilter and the LLM want different things. The LLM reads carefully and benefits from
# the whole posting; the embedding is a coarse ranking signal that a few thousand characters
# of company boilerplate actively harm — measured 2026-09-27 over a relevant/irrelevant pair
# set, the overlap between the two groups narrowed from -0.078 to -0.020 when the embedded
# text was cut to the title, the tags and the opening of the description. It also cuts the
# cost of a vector from ~1,070 tokens to ~175, which is what makes the per-minute budget
# comfortable rather than binding.
MAX_EMBEDDING_DESCRIPTION_CHARS = 600

SYSTEM_PROMPT = """You evaluate how well a job posting fits a candidate's profile.

Rules:
- Be conservative: a high score means the candidate could apply today with a real chance.
- Use only what the two texts state. Never invent skills, seniority or benefits.
- List a skill under matched_skills only if the job asks for it AND the profile shows it.
- red_flags are concrete mismatches (seniority far off, wrong location for an on-site role,
  salary below the stated minimum, contract type), not vague doubts.
- Score bands: 0-39 wrong role, 40-59 adjacent, 60-79 plausible, 80-100 strong fit."""


def profile_text(prefs: UserPreferences) -> str:
    """One paragraph describing the candidate — also the text that gets embedded."""
    parts = [prefs.profile_summary.strip()]
    for label, values in (
        ("Target titles", prefs.titles),
        ("Seniority", prefs.seniority),
        ("Required skills", prefs.required_skills),
        ("Nice to have", prefs.nice_to_have_skills),
        ("Regions", prefs.regions),
        ("Work modes", prefs.work_modes),
    ):
        if values:
            parts.append(f"{label}: {', '.join(values)}.")
    if prefs.min_salary:
        currency = prefs.salary_currency or ""
        parts.append(f"Minimum salary: {prefs.min_salary} {currency}".strip() + ".")
    return " ".join(part for part in parts if part)


def job_text(job: Job) -> str:
    """Job rendered for embedding and for the prompt; description truncated."""
    description = job.description.strip()
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "…"
    location_str = job.location or "not stated"
    if job.remote:
        location_str = f"{location_str}, remote"
    header = [
        f"Title: {job.title}",
        f"Company: {job.company}",
        f"Location: {location_str}",
    ]
    if job.salary_min or job.salary_max:
        salary_str = (
            f"Salary: {job.salary_min or '?'}-{job.salary_max or '?'} {job.salary_currency or ''}"
        ).strip()
        header.append(salary_str)
    if job.tags:
        header.append(f"Tags: {', '.join(job.tags)}")
    return "\n".join(header) + f"\n\n{description}"


def job_embedding_text(job: Job) -> str:
    """Short, role-focused rendering used for the vector — not what the LLM is shown.

    Deliberately omits company, salary and location: the deterministic filter already
    handles region and salary, so spending vector budget on them only blurs the role.
    """
    parts = [f"Title: {job.title}"]
    if job.tags:
        parts.append(f"Tags: {', '.join(job.tags)}")
    description = job.description.strip()
    if len(description) > MAX_EMBEDDING_DESCRIPTION_CHARS:
        description = description[:MAX_EMBEDDING_DESCRIPTION_CHARS].rstrip() + "…"
    header = "\n".join(parts)
    return f"{header}\n\n{description}" if description else header


def build_user_prompt(prefs: UserPreferences, job: Job, locale: str) -> str:
    return (
        f"CANDIDATE PROFILE:\n{profile_text(prefs)}\n\n"
        f"JOB POSTING:\n{job_text(job)}\n\n"
        f"Write `reasoning` in the language with code '{locale}'. "
        "Everything else stays in English."
    )
