// The conversation as a list of entries. Pure: no DOM, no fetch.

const LEVELS = ["intern", "junior", "mid", "senior"];
const MODES = ["remote", "hybrid", "onsite"];

export function gotitWhat(search) {
  const s = search.summary || {};
  const reading = search.reading || {};
  const answers = search.answers || {};
  let place = null;
  if (s.abroad_from) place = { kind: "abroad", name: s.abroad_from };
  else if (s.city) place = { kind: "city", name: s.city };
  else if (s.country) place = { kind: "country", name: s.country };
  else if ((answers.location && answers.location.choice === "anywhere") || (answers.country && answers.country.choice === "anywhere")) {
    place = { kind: "anywhere", name: null };
  }
  const skills = s.skills && s.skills.length ? s.skills : reading.required_skills || [];
  const role = s.role || (s.terms && s.terms.length ? s.terms.join(" / ") : null);
  return { role, skills: [...skills], place };
}

// ctx.country fills "Anywhere in {country}" (the stored answer does not carry it).
export function answerLabel(qid, answer, t, ctx = {}) {
  const values = answer.values || [];
  switch (answer.choice) {
    case "any":
      return t("dont_mind");
    case "pick":
      return values.map((v) => (MODES.includes(v) && qid === "work_modes" ? t(`mode_${v}`) : v)).join(", ");
    case "anywhere":
      return qid === "city" && ctx.country ? t("anywhere_in", { country: ctx.country }) : t("anywhere");
    case "abroad":
      return t("abroad_not", { country: values[0] || "" });
    case "country":
    case "city":
      return values.join(", ");
    default:
      return LEVELS.includes(answer.choice) && qid === "level" ? t(`level_${answer.choice}`) : answer.choice;
  }
}

// t labels the user's answers; without it the raw choice keys show.
export function buildTranscript(search, t = (key) => key) {
  const entries = [{ kind: "user", text: search.paragraph }];
  for (const text of search.refinements || []) entries.push({ kind: "user", text });
  const active = search.question || null;
  const asked = (search.asked || []).filter((qid) => !(active && active.id === qid));
  if (search.reading_error) {
    entries.push({ kind: "error", text: search.reading_error });
  } else if (search.reading) {
    entries.push({ kind: "gotit", what: gotitWhat(search), asking: Boolean(active) || asked.length > 0 });
  }
  const ctx = { country: (search.summary || {}).country || null };
  for (const qid of asked) {
    const answered = (search.answers || {})[qid] || null;
    entries.push({ kind: "question", question: { id: qid }, answered, active: false });
    if (answered) entries.push({ kind: "user", text: answerLabel(qid, answered, t, ctx) });
  }
  if (active) entries.push({ kind: "question", question: active, answered: null, active: true });
  else if (search.reading) entries.push({ kind: "summary", summary: search.summary, confirmed: Boolean(search.confirmed) });
  return entries;
}
