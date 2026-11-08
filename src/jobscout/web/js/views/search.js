// The search page (#/search/<id>): the conversation, its questions, the summary, and the run
// area under it (progress, results, nothing found) with the job detail panel.
// The view redraws from the SearchRead each mutation returns; the app shell redraws it only
// on a route change, so a background refresh never wipes the composer. While a run is in
// flight it polls every 2 s and redraws only the run area, unless the run's state changes.
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { api, ApiError } from "../api.js";
import { refreshSearches, refreshStatus, state as store } from "../store.js";
import { composer } from "../composer.js";
import { buildTranscript } from "../transcript.js";
import { renderEntries } from "../conversation.js";
import { createGuard } from "../guard.js";
import { runView } from "../runview.js";
import { runSection } from "../results.js";
import { openDetail } from "../detail.js";

const POLL_MS = 2000;
const guard = createGuard();
let pollTimer = null;
let detail = null; // the open panel's controller
let detailRoot = null; // the element that makes room for it

function stopPolling() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function closeDetail() {
  const open = detail;
  detail = null;
  if (open) open.close(false);
  if (detailRoot) detailRoot.classList.remove("has-detail");
  detailRoot = null;
}

// Called by the shell when another view takes the page: late responses must not redraw over
// it, the polling stops and the panel closes.
export function leaveSearch() {
  guard.invalidate();
  stopPolling();
  closeDetail();
}

const runningId = () => (store.status ? store.status.running_search_id : null);

export async function renderSearch(root, ctx, id) {
  const mine = guard.next();
  stopPolling();
  closeDetail();
  mount(root, h("div", { class: "app-column" }));
  let search;
  let matchList = null;
  try {
    search = await api.get(`/searches/${id}`);
    if (search.latest_run) {
      // A fresh /status tells a run in flight from one a restart left unfinished.
      [matchList] = await Promise.all([api.get(`/searches/${id}/matches`), refreshStatus().catch(() => null)]);
    }
  } catch (e) {
    if (!guard.isCurrent(mine)) return;
    mount(root, h("div", { class: "app-column" }, h("p", { class: "text-body conv-error", role: "alert" }, t("request_failed"))));
    return;
  }
  if (!guard.isCurrent(mine)) return;

  const ui = {
    editing: null,
    error: null,
    otherFor: null,
    reading: false,
    busy: false,
    sources: [],
    clearComposer: false,
    // The run area
    run: search.latest_run,
    matches: matchList,
    runningId: runningId(),
    runState: "none",
    starting: false,
    ranking: false,
    busyOther: null,
    runError: null,
    selectedId: null,
    wide: false,
  };
  const status = ctx.state.status;
  ui.sources = ((status && status.sources) || []).filter((s) => s.active).map((s) => s.name);

  const view = () => runView(search, ui.run, ui.matches, ui.runningId);
  const isWide = (v) => v.state === "results" || (v.state === "running" && v.matches.length > 0);

  function problem(qid, e) {
    ui.error = { qid, text: e instanceof ApiError && e.status === 422 && e.detail ? e.detail : t("request_failed") };
  }

  // Runs one mutation; `after` clears the state a success makes obsolete.
  async function mutate(qid, call, after) {
    if (ui.busy) return;
    ui.busy = true;
    ui.error = null;
    try {
      const next = await call();
      if (!guard.isCurrent(mine)) return;
      search = next;
      after();
      refreshSearches().catch(() => {});
    } catch (e) {
      if (!guard.isCurrent(mine)) return;
      problem(qid, e);
    } finally {
      ui.busy = false;
    }
    if (guard.isCurrent(mine)) draw();
  }

  // --- The run ---------------------------------------------------------------------------

  function schedule() {
    stopPolling();
    if (guard.isCurrent(mine) && view().state === "running") pollTimer = setTimeout(poll, POLL_MS);
  }

  async function poll() {
    pollTimer = null;
    if (!guard.isCurrent(mine) || !ui.run) return;
    const runId = ui.run.id;
    try {
      const [run, list] = await Promise.all([api.get(`/searches/${id}/runs/${runId}`), api.get(`/searches/${id}/matches`)]);
      if (!guard.isCurrent(mine)) return;
      ui.run = run;
      ui.matches = list;
      if (run.finished_at) {
        ui.runningId = null;
        refreshSearches().catch(() => {});
        refreshStatus().catch(() => {});
      }
    } catch (e) {
      if (!guard.isCurrent(mine)) return;
      // Ask the server whether it still runs this search; a restart leaves the run unfinished.
      try {
        await refreshStatus();
      } catch (err) {
        // Keep what we knew; the next poll asks again.
      }
      if (!guard.isCurrent(mine)) return;
      ui.runningId = runningId();
    }
    drawRun();
    schedule();
  }

  async function startRun(kind) {
    if (ui.starting) return;
    ui.starting = true;
    ui.busyOther = null;
    ui.runError = null;
    draw({ focus: false });
    try {
      const started = await api.post(`/searches/${id}/${kind}`);
      if (!guard.isCurrent(mine)) return;
      ui.run = { id: started.run_id, search_id: id, finished_at: null, sources: [], counters: {} };
      ui.runningId = id;
      ui.ranking = kind === "rank";
      ui.starting = false;
      refreshSearches().catch(() => {});
      await poll();
      return;
    } catch (e) {
      if (!guard.isCurrent(mine)) return;
      // A refused start changes nothing: the summary, the results and the run stay as they were.
      if (e instanceof ApiError && e.code === "search_busy") ui.busyOther = e.searchId;
      else if (e instanceof ApiError && e.code === "questions_pending") ui.runError = t("questions_pending");
      else ui.runError = t("request_failed");
    }
    ui.starting = false;
    draw({ focus: false });
  }

  // --- The detail panel ------------------------------------------------------------------

  const detailHost = h("aside", { class: "app-detail", hidden: true, "aria-label": t("job_detail") });

  function onVerdict(updated) {
    const list = ui.matches;
    if (!list) return null;
    const leaves = updated.status === "dismissed" || updated.status === "applied";
    const matches = list.matches.map((m) => (m.id === updated.id ? updated : m));
    ui.matches = leaves
      ? { ...list, matches: matches.filter((m) => m.id !== updated.id), found: Math.max(list.found - 1, 0) }
      : { ...list, matches };
    drawRun();
    if (updated.status === "dismissed") return t("verdict_dismissed");
    if (updated.status === "applied") return t("verdict_applied");
    return null;
  }

  function openMatch(match) {
    ui.selectedId = match.id;
    if (detail) detail.update(match);
    else {
      detail = openDetail(detailHost, match, {
        onVerdict,
        onClose: () => {
          const closedId = ui.selectedId;
          detail = null;
          ui.selectedId = null;
          root.classList.remove("has-detail");
          detailRoot = null;
          if (!guard.isCurrent(mine)) return;
          drawRun();
          const card = root.querySelector(`[data-match-id="${closedId}"]`);
          if (card) card.focus();
        },
      });
      root.classList.add("has-detail");
      detailRoot = root;
    }
    drawRun();
  }

  // --- Drawing ---------------------------------------------------------------------------

  const handlers = {
    onAnswer: (qid, answer) =>
      mutate(qid, () => api.post(`/searches/${id}/answers`, { question: qid, choice: answer.choice, values: answer.values }), () => {
        ui.editing = null;
        ui.otherFor = null;
      }),
    onOther: (qid) => {
      ui.otherFor = qid;
      ui.error = null;
      draw();
    },
    onEdit: async (qid) => {
      try {
        const q = await api.get(`/searches/${id}/questions/${qid}`);
        if (!guard.isCurrent(mine)) return;
        ui.editing = q;
        ui.otherFor = null;
        ui.error = null;
      } catch (e) {
        if (!guard.isCurrent(mine)) return;
        problem(qid, e);
      }
      draw();
    },
    onReread: () => {
      ui.reading = true;
      draw();
      return mutate("composer", () => api.post(`/searches/${id}/reread`), () => {}).finally(() => {
        ui.reading = false;
        if (guard.isCurrent(mine)) draw();
      });
    },
    onRun: () => startRun("run"),
    onSearchAgain: () => startRun("run"),
    onRank: () => startRun("rank"),
    // A widening changes one answer and the summary; it does not search.
    onWiden: (w) => mutate("widen", () => api.post(`/searches/${id}/answers`, { question: w.question, choice: w.answer.choice, values: w.answer.values }), () => {}),
    onOpen: (match) => openMatch(match),
  };

  function submitText(text) {
    if (ui.otherFor) {
      const qid = ui.otherFor;
      const choice = qid === "city" ? "city" : "country";
      return mutate(qid, () => api.post(`/searches/${id}/answers`, { question: qid, choice, values: [text] }), () => {
        ui.otherFor = null;
        ui.editing = null;
        ui.clearComposer = true;
      });
    }
    return mutate("composer", () => api.post(`/searches/${id}/refinements`, { text }), () => {
      ui.editing = null;
      ui.clearComposer = true;
    });
  }

  let box = null;
  let runHost = null;

  function draw({ focus = true } = {}) {
    // Only a submit that went through clears what the user typed.
    const kept = box && !ui.clearComposer ? box.getText() : "";
    ui.clearComposer = false;
    const v = view();
    ui.runState = v.state;
    ui.wide = isWide(v);
    const active = search.question;
    const roleActive = Boolean(active) && active.id === "role";
    const locked = Boolean(active) && !roleActive && !ui.otherFor;
    let placeholder = t("composer_ask");
    if (ui.otherFor) placeholder = ui.otherFor === "city" ? t("type_city") : t("type_country");
    else if (locked) placeholder = t("composer_locked");
    else if (ui.run) placeholder = t("composer_refine");

    box = composer({ placeholder, locked, primary: false, submitLabel: t("send"), disabled: ui.busy, onSubmit: submitText });
    if (kept) box.setText(kept);
    const entries = buildTranscript(search, t);
    runHost = h("div", { class: "run" }, runSection(v, search, ui, handlers));
    const column = h("div", { class: `app-column conv${ui.wide ? " app-column--wide" : ""}` }, renderEntries(entries, search, ui, handlers), runHost);
    const composerError = ui.error && ui.error.qid === "composer" ? ui.error.text : null;
    mount(
      root,
      column,
      h(
        "div",
        { class: `app-composer${ui.wide ? " app-composer--wide" : ""}` },
        composerError ? h("p", { class: "text-body-sm conv-error", role: "alert" }, composerError) : null,
        box.el,
      ),
      detailHost,
    );
    if (!focus) return;
    if (!locked) box.focus();
    const last = column.lastElementChild;
    if (last && typeof last.scrollIntoView === "function") last.scrollIntoView({ block: "end" });
  }

  // Redraws the run area alone, so polling never touches the composer or the open panel.
  function drawRun() {
    const v = view();
    if (!runHost || v.state !== ui.runState || isWide(v) !== ui.wide) {
      draw({ focus: false });
      return;
    }
    mount(runHost, runSection(v, search, ui, handlers));
  }

  draw();
  schedule();
}
