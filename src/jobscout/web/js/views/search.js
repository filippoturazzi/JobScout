// The search page (#/search/<id>): the conversation, its questions, the summary, and the run
// area under it (progress, results, nothing found) with the job detail panel.
// The view redraws from the SearchRead each mutation returns; the app shell redraws it only
// on a route change, so a background refresh never wipes the composer. While a run is in
// flight it polls every 2 s and redraws only the run area, unless the run's state changes.
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { api, ApiError } from "../api.js";
import { refreshSearches, refreshStatus, runningMismatch, state as store } from "../store.js";
import { composer } from "../composer.js";
import { buildTranscript } from "../transcript.js";
import { renderEntries } from "../conversation.js";
import { createGuard } from "../guard.js";
import { freshFor, matchChanged, runView, shouldKeepPolling, withVerdict } from "../runview.js";
import { runSection } from "../results.js";
import { openDetail } from "../detail.js";
import { cardKey } from "../jobcard.js";
import { convBar } from "../convbar.js";
import { confirmDelete } from "../sidebar.js";
import { showToast } from "../toast.js";
import { openEditModal } from "../editmodal.js";
import { nextStep } from "../liverefine.js";

const POLL_MS = 2000;
const guard = createGuard();
let pollTimer = null;
let polling = false; // a run's polling is on: the shell's own watcher leaves /status to it
let detail = null; // the open panel's controller
let detailRoot = null; // the element that makes room for it
let escapeStops = null; // while a run is in flight here: what Escape does (stop it)

// Escape stops the running search, unless something on top of the page takes it first: the
// detail panel, a dialog, the palette, or a field with text in it (the composer stays open
// while a run is in flight, for a refinement: empty, Escape still stops).
if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || !escapeStops || detail) return;
    if (document.querySelector("dialog[open], .pal-list")) return;
    const target = event.target;
    if (target && (target.tagName === "INPUT" || (target.tagName === "TEXTAREA" && !target.disabled && String(target.value || "").trim()))) return;
    event.preventDefault();
    escapeStops();
  });
}

function stopPolling() {
  polling = false;
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

// Whether the open search is polling its run (and so /status) right now.
export function isPollingRun() {
  return polling;
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
  escapeStops = null;
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
      [matchList] = await Promise.all([api.get(`/searches/${id}/matches?limit=500`), refreshStatus().catch(() => null)]);
    }
  } catch (e) {
    if (!guard.isCurrent(mine)) return;
    mount(root, h("div", { class: "app-column" }, h("p", { class: "text-body conv-error", role: "alert" }, t("request_failed"))));
    return;
  }
  if (!guard.isCurrent(mine)) return;
  // The fresh /status may say a run ended (or started) that the sidebar still shows otherwise.
  if (search.latest_run && runningMismatch(store.status, store.searches)) refreshSearches().catch(() => {});

  const ui = {
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
    stopping: false,
    busyOther: null,
    runError: null,
    selectedId: null,
    page: 1,
    wide: false,
    // Live refinement: a run waits for a pending question or for the stopped run to end, and
    // the cards on screen when an update began stay, dimmed, until it scores its first job.
    queued: false,
    previous: null,
  };
  const status = ctx.state.status;
  ui.sources = ((status && status.sources) || []).filter((s) => s.active).map((s) => s.name);

  const view = () => runView(search, ui.run, ui.matches, ui.runningId, ui.previous);

  // After a refinement or an edit: once the search has run, the results update by themselves.
  function afterChange() {
    const v = view();
    const step = nextStep({ hasRun: Boolean(ui.run), running: v.state === "running", queued: ui.queued, question: search.question });
    if (step === "ask") ui.queued = true;
    else if (step === "stop") {
      ui.queued = true;
      stopRun();
    } else if (step === "run") {
      ui.queued = false;
      if (v.matches.length) ui.previous = v.matches;
      startRun("run");
    }
  }
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
    if (guard.isCurrent(mine) && shouldKeepPolling(view())) {
      pollTimer = setTimeout(poll, POLL_MS);
      polling = true;
    }
  }

  // The panel follows its match while the run rescores it, without moving the user's focus.
  function refreshDetail() {
    if (!detail || !ui.matches) return;
    const fresh = freshFor(ui.matches, detail.match);
    if (!fresh || !matchChanged(detail.match, fresh)) return;
    // A job opened with no score keeps its place in the list under its new match id.
    if (ui.selectedId === cardKey(detail.match)) ui.selectedId = cardKey(fresh);
    detail.update(fresh, { focus: false });
  }

  // Each poll reads the run, the matches and /status together: nothing finishes a run that a
  // restart orphaned, so only /status can tell it is no longer running (runView: interrupted).
  async function poll() {
    pollTimer = null;
    if (!guard.isCurrent(mine) || !ui.run) return;
    const runId = ui.run.id;
    const wasRunning = ui.runningId;
    try {
      const [run, list] = await Promise.all([
        api.get(`/searches/${id}/runs/${runId}`),
        // A running search shows no unscored jobs: do not build them every poll.
        api.get(`/searches/${id}/matches?limit=500&unscored=false`),
        // Silent: a notifying refresh would redraw the sidebar (and close the menu) every 2 s.
        refreshStatus({ silent: true }).catch(() => null),
      ]);
      if (!guard.isCurrent(mine)) return;
      ui.run = run;
      ui.matches = list;
      ui.runningId = runningId();
      if (run.finished_at) {
        ui.previous = null;
        // The matches above may predate the run's last writes: read them once more.
        try {
          const last = await api.get(`/searches/${id}/matches?limit=500`);
          if (!guard.isCurrent(mine)) return;
          ui.matches = last;
        } catch (e) {
          // Keep the list we have.
        }
      }
    } catch (e) {
      if (!guard.isCurrent(mine)) return;
      try {
        await refreshStatus({ silent: true });
      } catch (err) {
        // Keep what we knew; the next poll asks again.
      }
      if (!guard.isCurrent(mine)) return;
      ui.runningId = runningId();
    }
    // The sidebar's running marker changes once, when the run ends or is found interrupted:
    // one notifying refresh then, never on every poll.
    const ended = Boolean(ui.run && ui.run.finished_at) || ui.runningId !== wasRunning;
    if (ended && !shouldKeepPolling(view())) refreshSearches().catch(() => {});
    refreshDetail();
    drawRun();
    schedule();
    // A refinement stopped this run: now that it has ended, the queued one starts.
    if (ui.queued && ui.run && ui.run.finished_at && !search.question) afterChange();
  }

  // Stop: the run ends at its next term or job, keeping what it has; polling sees it finish.
  async function stopRun() {
    if (ui.stopping || ui.runState !== "running") return;
    ui.stopping = true;
    draw({ focus: false });
    try {
      const answer = await api.post(`/searches/${id}/stop`);
      if (!guard.isCurrent(mine)) return;
      // Nothing to stop: the run ended meanwhile, and the next poll shows how.
      if (!answer.stopping) ui.stopping = false;
    } catch (e) {
      if (!guard.isCurrent(mine)) return;
      ui.stopping = false;
      showToast({ message: t("request_failed"), kind: "error" });
    }
    draw({ focus: false });
  }

  async function startRun(kind) {
    if (ui.starting) return;
    ui.stopping = false;
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
      // Starting confirmed the conversation, which may have retitled the search.
      api
        .get(`/searches/${id}`)
        .then((next) => {
          if (!guard.isCurrent(mine)) return;
          search = next;
          bar.update(search, jobCount());
        })
        .catch(() => {});
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
    ui.matches = withVerdict(list, updated);
    drawRun();
    if (updated.status === "dismissed") return t("verdict_dismissed");
    if (updated.status === "applied") return t("verdict_applied");
    return null;
  }

  function openMatch(match) {
    ui.selectedId = cardKey(match);
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
        ui.otherFor = null;
        if (ui.queued) afterChange();
      }),
    onOther: (qid) => {
      ui.otherFor = qid;
      ui.error = null;
      draw();
    },
    onEdit: (qid) => openEdit(qid),
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
    onPage: (n, key) => {
      ui.page = n;
      drawRun();
      if (runHost && typeof runHost.scrollIntoView === "function") runHost.scrollIntoView({ block: "start" });
      // The redraw replaced the pressed button: give focus back to its twin on the new page.
      const again = runHost && runHost.querySelector(`[data-pager="${key}"]`);
      if (again && !again.disabled) again.focus();
      else if (runHost) {
        const current = runHost.querySelector(`[data-pager="${n}"]`);
        if (current) current.focus();
      }
    },
  };

  // The summary's pencil: the question in a modal. An edit that opens a new need (hybrid now
  // needs a city) goes straight on to that question, in the modal too.
  async function openEdit(qid) {
    let q;
    try {
      q = await api.get(`/searches/${id}/questions/${qid}`);
    } catch (e) {
      if (!guard.isCurrent(mine)) return;
      problem(qid, e);
      draw();
      return;
    }
    if (!guard.isCurrent(mine)) return;
    let saved = false;
    const modal = openEditModal(q, {
      country: (search.summary || {}).country || null,
      answer: (search.answers || {})[q.id],
      summary: search.summary,
      onSave: async (answer) => {
        try {
          const next = await api.post(`/searches/${id}/answers`, { question: q.id, choice: answer.choice, values: answer.values });
          if (!guard.isCurrent(mine)) return;
          search = next;
          saved = true;
          ui.error = null;
          modal.close();
          refreshSearches().catch(() => {});
          afterChange();
        } catch (e) {
          if (!guard.isCurrent(mine)) return;
          modal.showError(e instanceof ApiError && e.status === 422 && e.detail ? e.detail : t("request_failed"));
        }
      },
      onClose: () => {
        if (!guard.isCurrent(mine)) return;
        if (saved) {
          draw({ focus: false });
          if (search.question) {
            openEdit(search.question.id);
            return;
          }
        }
        const pencil = root.querySelector(`[data-edit="${q.id}"]`);
        if (pencil) pencil.focus();
      },
    });
  }

  function submitText(text) {
    if (ui.otherFor) {
      const qid = ui.otherFor;
      const choice = qid === "city" ? "city" : "country";
      return mutate(qid, () => api.post(`/searches/${id}/answers`, { question: qid, choice, values: [text] }), () => {
        ui.otherFor = null;
        ui.clearComposer = true;
        if (ui.queued) afterChange();
      });
    }
    return mutate("composer", () => api.post(`/searches/${id}/refinements`, { text }), () => {
      ui.clearComposer = true;
      afterChange();
    });
  }

  // --- The top bar: title, job count, and Rename · Export CSV · Delete --------------------

  const jobCount = () => (ui.matches && ui.matches.found) || 0;
  const bar = convBar(search, jobCount(), {
    onRename: async (title) => {
      try {
        const next = await api.patch(`/searches/${id}`, { title });
        if (!guard.isCurrent(mine)) return;
        search = next;
        bar.update(search, jobCount());
        refreshSearches().catch(() => {});
      } catch (e) {
        if (guard.isCurrent(mine)) showToast({ message: t("rename_failed"), kind: "error" });
        throw e;
      }
    },
    onExport: () => {
      const link = h("a", { href: `/searches/${id}/export.csv`, download: "" });
      document.body.appendChild(link);
      link.click();
      link.remove();
    },
    onDelete: () => {
      const listed = store.searches.find((s) => s.id === id);
      confirmDelete({ id, title: search.title, running: listed ? listed.running : ui.runningId === id }, { name: "search", id });
    },
  });

  let box = null;
  let runHost = null;

  function draw({ focus = true } = {}) {
    // Only a submit that went through clears what the user typed.
    const kept = box && !ui.clearComposer ? box.getText() : "";
    // A redraw the user did not ask for (the run changed state) must not take their focus away.
    const hadFocus = Boolean(box) && box.hasFocus();
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

    const running = v.state === "running";
    if (!running) ui.stopping = false;
    escapeStops = running ? stopRun : null;
    if (running) placeholder = ui.stopping ? t("stopping") : t("composer_running_refine");
    box = composer({
      placeholder,
      locked,
      primary: false,
      submitLabel: t("send"),
      disabled: ui.busy,
      onSubmit: submitText,
      running,
      stopping: ui.stopping,
      stopLabel: t("stop"),
      onStop: stopRun,
    });
    if (kept) box.setText(kept);
    const entries = buildTranscript(search, t);
    runHost = h("div", { class: "run" }, runSection(v, search, ui, handlers));
    bar.update(search, jobCount());
    const column = h("div", { class: `app-column conv${ui.wide ? " app-column--wide" : ""}` }, bar.el, renderEntries(entries, search, ui, handlers), runHost);
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
    if (!focus) {
      if (hadFocus && !locked) box.focus({ end: true });
      return;
    }
    if (!locked) box.focus();
    // A run waiting on a question (a refinement opened one): show the question, which sits
    // above the results, rather than the end of the column.
    const waitingOn = ui.queued && search.question ? column.querySelector(".conv-question:not(.conv-question--past)") : null;
    const last = waitingOn || column.lastElementChild;
    if (last && typeof last.scrollIntoView === "function") last.scrollIntoView({ block: waitingOn ? "center" : "end" });
  }

  // Redraws the run area alone, so polling never touches the composer or the open panel.
  function drawRun() {
    bar.update(search, jobCount());
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
