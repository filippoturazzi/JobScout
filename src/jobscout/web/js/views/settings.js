// Settings (#/settings): read-only model and source facts, plus theme and language.
import { h, mount } from "../dom.js";
import { icon } from "../icons.js";
import { t, loadLocale, currentLocale } from "../i18n.js";
import { api } from "../api.js";
import { refreshStatus } from "../store.js";
import { withCode } from "./common.js";

const SOURCE_NAMES = { himalayas: "Himalayas", remotive: "Remotive", linkedin: "LinkedIn", indeed: "Indeed", arbeitnow: "Arbeitnow" };

function row(label, value) {
  return h("div", { class: "set-row" }, h("span", { class: "text-body set-label" }, label), value);
}

function section(title, ...children) {
  return h("section", { class: "set-section" }, h("h2", { class: "text-label set-heading" }, title), ...children);
}

function segmented(label, options, current, onPick) {
  return h(
    "div",
    { class: "set-seg", role: "radiogroup", "aria-label": label },
    options.map((o) =>
      h(
        "button",
        {
          class: "set-seg__opt text-body-sm",
          type: "button",
          role: "radio",
          "aria-checked": o.value === current ? "true" : "false",
          onclick: () => onPick(o.value),
        },
        o.value === current ? icon("check") : null,
        o.label,
      ),
    ),
  );
}

function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function sourceRow(s) {
  const reason = s.reason && s.reason !== "off" ? s.reason : null;
  return h(
    "div",
    { class: "set-row set-source" },
    h("span", { class: "text-body set-source__name" }, SOURCE_NAMES[s.name] || s.name),
    h("span", { class: "text-body-sm set-source__desc" }, reason || t(`source_${s.name}`)),
    s.active
      ? h("span", { class: "js-tag js-tag--success" }, icon("check-circle", 12), t("source_active"))
      : h("span", { class: "js-tag" }, icon("minus", 12), t("source_off")),
  );
}

export function renderSettings(root, ctx) {
  const status = ctx.state.status || {};
  const keyFound = status.llm_key_found === true;

  const model = section(
    t("model"),
    row(t("provider"), h("span", { class: "text-meta" }, status.llm_provider || "")),
    row(t("chat_model"), h("span", { class: "text-meta" }, status.llm_model || "")),
    row(t("embeddings"), h("span", { class: "text-meta" }, status.embedding_model || "")),
    row(
      t("status"),
      h(
        "span",
        { class: `text-meta set-status ${keyFound ? "set-status--ok" : "set-status--bad"}` },
        keyFound ? icon("check-circle") : icon("alert-triangle"),
        keyFound ? t("key_found") : t("key_missing"),
      ),
    ),
    h("p", { class: "text-body-sm set-note" }, withCode(t("model_note"), [".env"])),
  );

  const sources = section(
    t("sources"),
    (status.sources || []).map(sourceRow),
    h("p", { class: "text-body-sm set-note" }, withCode(t("sources_note"), ["SOURCES", ".env"])),
  );

  function pickTheme(value) {
    try {
      localStorage.setItem("jobscout.theme", value);
    } catch (e) {
      // Storage can be blocked; the theme still applies for this visit.
    }
    document.documentElement.dataset.theme = value;
    ctx.rerender();
  }

  async function pickLocale(code) {
    if (code === currentLocale()) return;
    try {
      await api.put("/me/locale", { locale: code });
      await loadLocale(code);
      document.documentElement.lang = code;
      await refreshStatus();
      ctx.rerender();
    } catch (e) {
      console.error(e);
    }
  }

  const appearance = section(
    t("appearance"),
    row(
      t("theme"),
      segmented(t("theme"), [{ value: "dark", label: t("theme_dark") }, { value: "light", label: t("theme_light") }], currentTheme(), pickTheme),
    ),
    row(
      t("language"),
      segmented(t("language"), [{ value: "en", label: "English" }, { value: "pt-BR", label: "Português" }], currentLocale(), pickLocale),
    ),
  );

  mount(root, h("div", { class: "app-column settings" }, h("h1", { class: "text-h1 app-title" }, t("settings")), model, sources, appearance));
}
