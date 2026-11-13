// Popovers and menus anchored under a button: one open at a time. A click outside or Escape
// closes it and gives the focus back to its button. The popover is placed in the button's
// parent, which must be position: relative, so it scrolls with the page.
import { h } from "./dom.js";
import { icon } from "./icons.js";

let current = null; // { el, anchor, onClose }

function onPointer(event) {
  if (current && !current.el.contains(event.target) && !current.anchor.contains(event.target)) closePopover({ restoreFocus: false });
}

// Capture, and stop it there: Escape closes the popover, not the detail panel behind it.
function onKey(event) {
  if (event.key !== "Escape" || !current) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closePopover();
}

export function closePopover({ restoreFocus = true } = {}) {
  if (!current) return;
  const { el, anchor, onClose } = current;
  current = null;
  document.removeEventListener("mousedown", onPointer, true);
  document.removeEventListener("keydown", onKey, true);
  el.remove();
  anchor.setAttribute("aria-expanded", "false");
  if (onClose) onClose();
  if (restoreFocus && anchor.isConnected) anchor.focus();
}

export function isOpenFor(anchor) {
  return Boolean(current) && current.anchor === anchor;
}

// Opens `el` under `anchor`; a second call for the same anchor closes it (a toggle).
export function togglePopover(anchor, el, { onClose = null, align = "end" } = {}) {
  if (isOpenFor(anchor)) {
    closePopover();
    return false;
  }
  closePopover({ restoreFocus: false });
  el.classList.add("pop", `pop--${align}`);
  anchor.parentElement.appendChild(el);
  anchor.setAttribute("aria-expanded", "true");
  current = { el, anchor, onClose };
  document.addEventListener("mousedown", onPointer, true);
  document.addEventListener("keydown", onKey, true);
  return true;
}

// A menu: items are { label, icon, run, checked (radio items), danger }. Arrow keys move,
// Enter picks, Escape closes. Returns the element to hand to togglePopover.
export function menu(label, items) {
  const buttons = items.map((item) =>
    h(
      "button",
      {
        class: `pop-item text-body-sm${item.danger ? " pop-item--danger" : ""}`,
        type: "button",
        role: item.checked === undefined ? "menuitem" : "menuitemradio",
        "aria-checked": item.checked === undefined ? null : String(item.checked),
        tabindex: "-1",
        onclick: () => {
          closePopover();
          item.run();
        },
      },
      item.icon ? icon(item.icon, 16) : null,
      h("span", { class: "pop-item__label" }, item.label),
      item.checked ? h("span", { class: "pop-item__check" }, icon("check", 14)) : null,
    ),
  );
  const el = h(
    "div",
    {
      class: "pop-menu",
      role: "menu",
      "aria-label": label,
      onkeydown: (event) => {
        const at = buttons.indexOf(document.activeElement);
        let next = null;
        if (event.key === "ArrowDown") next = (at + 1) % buttons.length;
        else if (event.key === "ArrowUp") next = (at - 1 + buttons.length) % buttons.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = buttons.length - 1;
        else if (event.key === "Tab") closePopover({ restoreFocus: false });
        if (next === null) return;
        event.preventDefault();
        buttons[next].focus();
      },
    },
    buttons,
  );
  return { el, focusFirst: () => (buttons.find((b) => b.getAttribute("aria-checked") === "true") || buttons[0]).focus() };
}

// Opens a menu under its button and puts the keyboard on it.
export function toggleMenu(anchor, label, items) {
  const m = menu(label, items);
  if (togglePopover(anchor, m.el)) m.focusFirst();
}
