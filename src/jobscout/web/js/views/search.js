// The search page (#/search/<id>): the conversation, its questions and the summary.
// The view redraws from the SearchRead each mutation returns; the app shell redraws it only
// on a route change, so a background refresh never wipes the composer.
import { h, mount } from "../dom.js";
import { t } from "../i18n.js";
import { api, ApiError } from "../api.js";
import { refreshSearches } from "../store.js";
import { composer } from "../composer.js";
import { buildTranscript } from "../transcript.js";
import { renderEntries } from "../conversation.js";
import { createGuard } from "../guard.js";

const guard = createGuard();

// Called by the shell when another view takes the page: late responses must not redraw over it.
export function leaveSearch() {
  guard.invalidate();
}

export async function renderSearch(root, ctx, id) {
  const mine = guard.next();
  mount(root, h("div", { class: "app-column" }));
  let search;
  try {
    search = await api.get(`/searches/${id}`);
  } catch (e) {
    if (!guard.isCurrent(mine)) return;
    mount(root, h("div", { class: "app-column" }, h("p", { class: "text-body conv-error", role: "alert" }, t("request_failed"))));
    return;
  }
  if (!guard.isCurrent(mine)) return;

  const ui = { editing: null, error: null, otherFor: null, reading: false, busy: false, sources: [] };
  const status = ctx.state.status;
  ui.sources = ((status && status.sources) || []).filter((s) => s.active).map((s) => s.name);

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
  };

  function submitText(text) {
    if (ui.otherFor) {
      const qid = ui.otherFor;
      const choice = qid === "city" ? "city" : "country";
      return mutate(qid, () => api.post(`/searches/${id}/answers`, { question: qid, choice, values: [text] }), () => {
        ui.otherFor = null;
        ui.editing = null;
      });
    }
    return mutate("composer", () => api.post(`/searches/${id}/refinements`, { text }), () => {
      ui.editing = null;
    });
  }

  let box = null;

  function draw() {
    // A failed submit keeps what the user typed.
    const kept = ui.error && box ? box.getText() : "";
    const active = search.question;
    const roleActive = Boolean(active) && active.id === "role";
    const locked = Boolean(active) && !roleActive && !ui.otherFor;
    let placeholder = t("composer_ask");
    if (ui.otherFor) placeholder = ui.otherFor === "city" ? t("type_city") : t("type_country");
    else if (locked) placeholder = t("composer_locked");
    else if (search.latest_run) placeholder = t("composer_refine");

    box = composer({ placeholder, locked, primary: false, submitLabel: t("send"), disabled: ui.busy, onSubmit: submitText });
    if (kept) box.setText(kept);
    const entries = buildTranscript(search, t);
    const column = h("div", { class: "app-column conv" }, renderEntries(entries, search, ui, handlers));
    const composerError = ui.error && ui.error.qid === "composer" ? ui.error.text : null;
    mount(
      root,
      column,
      h("div", { class: "app-composer" }, composerError ? h("p", { class: "text-body-sm conv-error", role: "alert" }, composerError) : null, box.el),
    );
    if (!locked) box.focus();
    const last = column.lastElementChild;
    if (last && typeof last.scrollIntoView === "function") last.scrollIntoView({ block: "end" });
  }

  draw();
}
