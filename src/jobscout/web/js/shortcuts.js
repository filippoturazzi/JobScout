// Keyboard shortcuts (Ctrl on Windows and Linux, Cmd on a Mac):
//   Ctrl K        the search palette
//   Ctrl B        fold or unfold the sidebar
//   Ctrl Shift O  a new search

// The shortcut a keydown means, or null. Pure.
export function shortcutFor(event) {
  const mod = event.ctrlKey || event.metaKey;
  if (!mod || event.altKey) return null;
  const k = String(event.key).toLowerCase();
  if (event.shiftKey) return k === "o" ? "new" : null;
  if (k === "k") return "palette";
  if (k === "b") return "sidebar";
  return null;
}

// actions: { palette(), sidebar(), new() }
export function listenForShortcuts(actions) {
  document.addEventListener("keydown", (event) => {
    const name = shortcutFor(event);
    if (!name || !actions[name]) return;
    event.preventDefault();
    actions[name]();
  });
}
