// Home (#/): the heading, the no-key notice when needed, and the big composer.
import { h, mount } from "../dom.js";
import { icon } from "../icons.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { go } from "../router.js";
import { refreshSearches } from "../store.js";
import { composer } from "../composer.js";
import { withCode } from "./common.js";

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
    submitLabel: t("start_search"),
    submitIcon: "search",
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

  mount(
    root,
    h("div", { class: "app-column home" }, h("h1", { class: "text-title home-title" }, t("home_title")), noticeSlot, box.el),
  );
  box.focus();
}
