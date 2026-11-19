// Home (#/): Julius's badge, the two-line heading, the no-key notice when needed, the big composer,
// suggestion chips that fill it in (they never send) and the active sources.
import { h, mount } from "../dom.js";
import { icon } from "../icons.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { go } from "../router.js";
import { refreshSearches } from "../store.js";
import { composer } from "../composer.js";
import { withCode } from "./common.js";
import { sourceName } from "../format.js";

const SUGGESTIONS = [
  ["database", "sugg_data"],
  ["code", "sugg_frontend"],
  ["graduation-cap", "sugg_first"],
  ["globe", "sugg_abroad"],
];

const SETUP_URL = "https://github.com/filippoturazzi/JobScout#quick-start";

function notice() {
  return h(
    "div",
    { class: "home-notice", role: "status" },
    icon("info", 20),
    h(
      "div",
      { class: "home-notice__text" },
      h("p", { class: "text-body home-notice__title" }, t("no_key_title")),
      h("p", { class: "text-body-sm home-notice__hint" }, withCode(t("no_key_hint"), ["LLM_API_KEY", "GOOGLE_API_KEY", ".env"])),
    ),
    h("a", { class: "text-label home-notice__link", href: SETUP_URL, target: "_blank", rel: "noopener noreferrer" }, t("no_key_setup")),
  );
}

export function renderHome(root, ctx) {
  const status = ctx.state.status;
  let noKey = Boolean(status) && status.llm_key_found === false;
  let busy = false;

  const noticeSlot = h("div", { class: "home-notice-slot" }, noKey ? notice() : null);
  const box = composer({
    placeholder: t("home_placeholder"),
    multiline: true,
    // The paragraph is where a search starts: the design system's highlight marks it.
    highlight: true,
    submitLabel: t("start_search"),
    disabled: noKey,
    onSubmit: submit,
  });

  async function submit(paragraph) {
    if (busy) return;
    busy = true;
    box.setDisabled(true);
    box.setSubmitLabel(t("searching"));
    try {
      const created = await api.post("/searches", { paragraph });
      go(`/search/${created.id}`);
      await refreshSearches();
    } catch (e) {
      busy = false;
      box.setSubmitLabel(t("start_search"));
      if (e && e.code === "no_llm_key") {
        noKey = true;
        mount(noticeSlot, notice());
      } else {
        mount(noticeSlot, h("p", { class: "text-body-sm home-error", role: "alert" }, t("request_failed")));
      }
      box.setDisabled(noKey);
    }
  }

  const chips = h(
    "div",
    { class: "home-suggestions", role: "group", "aria-label": t("suggestions") },
    SUGGESTIONS.map(([iconName, key]) =>
      h(
        "button",
        {
          class: "home-chip text-body-sm",
          type: "button",
          disabled: noKey,
          onclick: () => {
            box.setText(t(`${key}_text`));
            box.focus({ end: true });
          },
        },
        icon(iconName, 14),
        t(key),
      ),
    ),
  );
  const active = ((status && status.sources) || []).filter((s) => s.active).map((s) => sourceName(s.name));

  mount(
    root,
    h(
      "div",
      { class: "app-column home" },
      h(
        "div",
        { class: "home-hero" },
        h("p", { class: "home-badge text-body-sm" }, h("span", { class: "home-badge__icon" }, icon("sparkles", 12)), t("home_badge")),
        h("h1", { class: "text-title home-title" }, t("home_title"), h("span", { class: "home-title__sub" }, t("home_subtitle"))),
      ),
      noticeSlot,
      box.el,
      chips,
    ),
    active.length ? h("p", { class: "text-meta home-sources" }, t("sources_footer", { names: active.join(" · ") })) : null,
  );
  box.focus();
}
