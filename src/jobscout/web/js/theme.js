// The theme: dark (the default), light, or system (follows the operating system, live).
// index.html applies the same rule before first paint, so the page never flashes.

const KEY = "jobscout.theme";
const CHOICES = ["dark", "light", "system"];
const LIGHT_QUERY = "(prefers-color-scheme: light)";
let unsaved = null; // the choice of this visit when storage is blocked

// The saved value as a choice. Pure.
export function readTheme(saved) {
  return CHOICES.includes(saved) ? saved : "dark";
}

// The theme a choice paints, given whether the system prefers light. Pure.
export function resolveTheme(choice, prefersLight) {
  if (choice === "system") return prefersLight ? "light" : "dark";
  return choice;
}

export function currentChoice() {
  try {
    return readTheme(localStorage.getItem(KEY));
  } catch (e) {
    return unsaved || "dark"; // Storage can be blocked; dark is the default.
  }
}

function prefersLight() {
  return typeof matchMedia === "function" && matchMedia(LIGHT_QUERY).matches;
}

export function applyTheme() {
  document.documentElement.dataset.theme = resolveTheme(currentChoice(), prefersLight());
}

// Called once at start: while the choice is system, a change in the OS repaints the page.
export function watchSystemTheme() {
  if (typeof matchMedia !== "function") return;
  matchMedia(LIGHT_QUERY).addEventListener("change", () => {
    if (currentChoice() === "system") applyTheme();
  });
}

export function setTheme(choice) {
  try {
    localStorage.setItem(KEY, readTheme(choice));
  } catch (e) {
    unsaved = readTheme(choice); // The theme still applies for this visit.
  }
  applyTheme();
}
