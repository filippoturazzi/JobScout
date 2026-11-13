// Settings (#/settings): read-only model and source facts, theme and language, about and credits.
// Each section is a column of title and description beside a card.
import { h, mount } from "../dom.js";
import { icon, logoMark } from "../icons.js";
import { REPO_URL } from "../sidebar.js";
import { t, loadLocale, currentLocale } from "../i18n.js";
import { api } from "../api.js";
import { refreshStatus } from "../store.js";
import { sourceName } from "../format.js";
import { withCode } from "./common.js";
import { currentChoice, setTheme } from "../theme.js";

function row(label, value) {
  return h("div", { class: "set-row" }, h("span", { class: "text-body set-label" }, label), value);
}

// note: the line under the card's rows (what to change in .env), or null.
function section(title, desc, rows, note = null) {
  return h(
    "section",
    { class: "set-section" },
    h("div", { class: "set-info" }, h("h2", { class: "text-label set-heading" }, title), h("p", { class: "text-body-sm set-desc" }, desc)),
    h("div", { class: "set-card" }, rows, note),
  );
}

function note(text, names) {
  return h("p", { class: "text-body-sm set-note" }, icon("info", 14), withCode(text, names));
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

function sourceRow(s) {
  const reason = s.reason && s.reason !== "off" ? s.reason : null;
  const name = sourceName(s.name);
  return h(
    "div",
    { class: `set-row set-source${s.active ? "" : " set-source--off"}` },
    h(
      "div",
      { class: "set-source__main" },
      h("span", { class: "set-source__logo", "aria-hidden": "true" }, name.charAt(0)),
      h(
        "div",
        { class: "set-source__text" },
        h("span", { class: "text-body-sm set-source__name" }, name),
        h("span", { class: "text-body-sm set-source__desc" }, reason || t(`source_${s.name}`)),
      ),
    ),
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
    t("model_desc"),
    [
    row(t("provider"), h("span", { class: "text-meta" }, status.llm_provider || "")),
    row(t("chat_model"), h("span", { class: "text-meta" }, status.llm_model || "")),
    row(
      t("embeddings"),
      h("span", { class: "text-meta" }, [status.embedding_provider, status.embedding_model].filter(Boolean).join(" · ")),
    ),
    row(
      t("status"),
      h(
        "span",
        { class: `text-meta set-status ${keyFound ? "set-status--ok" : "set-status--bad"}` },
        keyFound ? icon("check-circle") : icon("alert-triangle"),
        keyFound ? t("key_found") : t("key_missing"),
      ),
    ),
    ],
    note(t("model_note"), [".env"]),
  );

  const sources = section(t("sources"), t("sources_desc"), (status.sources || []).map(sourceRow), note(t("sources_note"), ["SOURCES", ".env"]));

  function pickTheme(value) {
    setTheme(value);
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
    t("appearance_desc"),
    [
    row(
      t("theme"),
      segmented(t("theme"), [{ value: "dark", label: t("theme_dark") }, { value: "light", label: t("theme_light") }, { value: "system", label: t("theme_system") }], currentChoice(), pickTheme),
    ),
    row(
      t("language"),
      segmented(t("language"), [{ value: "pt-BR", label: "Português" }, { value: "en", label: "English" }], currentLocale(), pickLocale),
    ),
    ],
  );

  const link = (label, iconName, href) =>
    h("a", { class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--outline", href, target: "_blank", rel: "noopener noreferrer", "aria-label": label, title: label }, icon(iconName, 16));
  const about = section(
    t("about"),
    t("about_note"),
    h(
      "div",
      { class: "set-row" },
      h(
        "div",
        { class: "set-about" },
        h("span", { class: "set-about__tile", "aria-hidden": "true" }, logoMark(26)),
        h("div", {}, h("p", { class: "text-label set-about__name" }, "jobscout"), h("p", { class: "text-body-sm set-about__sub" }, t("license"))),
      ),
      h("div", { class: "set-links" }, link(t("github_repo"), "github", REPO_URL), link("README", "book-open", `${REPO_URL}#readme`)),
    ),
  );

  const credits = h(
    "footer",
    { class: "text-body-sm set-credits" },
    t("made_by"),
    h(
      "a",
      { class: "set-credits__link text-label", href: "https://turazzi.dev", target: "_blank", rel: "noopener noreferrer" },
      h("img", { src: "/static/design/logos/turazzi-dev.png", alt: "" }),
      "turazzi.dev",
      icon("arrow-up-right", 14),
    ),
  );

  mount(
    root,
    h(
      "div",
      { class: "app-column app-column--wide settings" },
      h("h1", { class: "text-h1 app-title" }, t("settings")),
      model,
      sources,
      appearance,
      about,
      credits,
    ),
  );
}
