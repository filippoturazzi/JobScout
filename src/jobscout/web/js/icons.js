// Lucide outlines (24x24 viewBox). The only file that may write markup from a string,
// and only these fixed strings, never data.

const circle = (cx, cy, r) => `<circle cx="${cx}" cy="${cy}" r="${r}"/>`;
const path = (d) => `<path d="${d}"/>`;
const BOOKMARK = path("m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z");

const SHAPES = {
  search: circle(11, 11, 8) + path("m21 21-4.3-4.3"),
  plus: path("M5 12h14") + path("M12 5v14"),
  settings:
    path("M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z") +
    circle(12, 12, 3),
  bookmark: BOOKMARK,
  "bookmark-filled": BOOKMARK,
  pencil:
    path("M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z") +
    path("m15 5 4 4"),
  check: path("M20 6 9 17l-5-5"),
  "check-circle": circle(12, 12, 10) + path("m9 12 2 2 4-4"),
  clock: circle(12, 12, 10) + path("M12 6v6l4 2"),
  loader: path("M21 12a9 9 0 1 1-6.219-8.56"),
  "alert-triangle":
    path("m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3") +
    path("M12 9v4") +
    path("M12 17h.01"),
  info: circle(12, 12, 10) + path("M12 16v-4") + path("M12 8h.01"),
  "external-link":
    path("M15 3h6v6") + path("M10 14 21 3") + path("M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"),
  x: path("M18 6 6 18") + path("m6 6 12 12"),
  "eye-off":
    path("M10.733 5.076a10.744 10.744 0 0 1 11.205 6.575 1 1 0 0 1 0 .696 10.747 10.747 0 0 1-1.444 2.49") +
    path("M14.084 14.158a3 3 0 0 1-4.242-4.242") +
    path("M17.479 17.499a10.75 10.75 0 0 1-15.417-5.151 1 1 0 0 1 0-.696 10.75 10.75 0 0 1 4.446-5.143") +
    path("m2 2 20 20"),
  minus: path("M5 12h14"),
  "rotate-ccw": path("M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8") + path("M3 3v5h5"),
  lock: '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/>' + path("M7 11V7a5 5 0 0 1 10 0v4"),
  "chevron-down": path("m6 9 6 6 6-6"),
  trash:
    path("M3 6h18") +
    path("M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6") +
    path("M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2") +
    '<line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
  menu: path("M4 12h16") + path("M4 6h16") + path("M4 18h16"),
};

export function icon(name, size = 16) {
  const shape = SHAPES[name];
  if (shape === undefined) throw new Error(`Unknown icon: ${name}`);
  const fill = name === "bookmark-filled" ? "currentColor" : "none";
  const holder = document.createElement("div");
  holder.innerHTML =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="${size}" height="${size}" ` +
    `fill="${fill}" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" ` +
    `aria-hidden="true" focusable="false">${shape}</svg>`;
  return holder.firstChild;
}
