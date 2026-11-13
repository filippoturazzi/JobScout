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
  "chevron-left": path("m15 18-6-6 6-6"),
  "chevron-right": path("m9 18 6-6-6-6"),
  trash:
    path("M3 6h18") +
    path("M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6") +
    path("M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2") +
    '<line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
  menu: path("M4 12h16") + path("M4 6h16") + path("M4 18h16"),
  "square-pen":
    path("M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7") +
    path("M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"),
  "arrow-up": path("m5 12 7-7 7 7") + path("M12 19V5"),
  "arrow-up-right": path("M7 7h10v10") + path("M7 17 17 7"),
  github:
    path("M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4") +
    path("M9 18c-4.51 2-5-2-7-2"),
  sparkles:
    path("M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z") +
    path("M20 3v4") + path("M22 5h-4") + path("M4 17v2") + path("M5 18H3"),
  "bookmark-check": path("m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2Z") + path("m9 10 2 2 4-4"),
  moon: path("M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"),
  sun:
    circle(12, 12, 4) + path("M12 2v2") + path("M12 20v2") + path("m4.93 4.93 1.41 1.41") + path("m17.66 17.66 1.41 1.41") +
    path("M2 12h2") + path("M20 12h2") + path("m6.34 17.66-1.41 1.41") + path("m19.07 4.93-1.41 1.41"),
  "book-open":
    path("M12 7v14") +
    path("M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"),
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/>' + path("M3 5V19A9 3 0 0 0 21 19V5") + path("M3 12A9 3 0 0 0 21 12"),
  code: path("m16 18 6-6-6-6") + path("m8 6-6 6 6 6"),
  "graduation-cap":
    path("M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z") +
    path("M22 10v6") + path("M6 12.5V16a6 3 0 0 0 12 0v-3.5"),
  globe: circle(12, 12, 10) + path("M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20") + path("M2 12h20"),
  "panel-left": '<rect width="18" height="18" x="3" y="3" rx="2"/>' + path("M9 3v18"),
  "message-square": path("M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"),
  "corner-down-left": path("M20 4v7a4 4 0 0 1-4 4H4") + path("m9 10-5 5 5 5"),
  ellipsis: circle(12, 12, 1) + circle(19, 12, 1) + circle(5, 12, 1),
  download: path("M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4") + path("m7 10 5 5 5-5") + path("M12 15V3"),
  paperclip: path("m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"),
  "file-text":
    path("M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z") + path("M14 2v4a2 2 0 0 0 2 2h4") +
    path("M10 9H8") + path("M16 13H8") + path("M16 17H8"),
  "list-filter": path("M3 6h18") + path("M7 12h10") + path("M10 18h4"),
  "arrow-down-up": path("m3 16 4 4 4-4") + path("M7 20V4") + path("m21 8-4-4-4 4") + path("M17 4v16"),
  square: '<rect width="14" height="14" x="5" y="5" rx="2"/>',
  "circle-dashed":
    path("M10.1 2.182a10 10 0 0 1 3.8 0") + path("M13.9 21.818a10 10 0 0 1-3.8 0") + path("M17.609 3.721a10 10 0 0 1 2.69 2.7") +
    path("M2.182 13.9a10 10 0 0 1 0-3.8") + path("M20.279 17.609a10 10 0 0 1-2.7 2.69") + path("M21.818 10.1a10 10 0 0 1 0 3.8") +
    path("M3.721 6.391a10 10 0 0 1 2.7-2.69") + path("M6.391 20.279a10 10 0 0 1-2.69-2.7"),
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

// The jobscout eye (design/logos/jobscout-glyph.svg), filled with currentColor so the theme
// colours it. A fixed string, never data.
const EYE =
  '<path transform="translate(0 3.869)" fill-rule="evenodd" d="M12.476 .014c.427-.03 .897-.006 1.326 .017 4.522 .239 8.622 3.011 10.991 6.799 .469 .75 .833 1.502 1.207 2.305-.278 .616-.553 1.186-.893 1.771-2.475 4.249-6.628 7.093-11.588 7.344-.352 .02-.714 .012-1.067-.002-5.592-.217-10.298-4.069-12.452-9.115 2.307-5.191 6.697-8.787 12.476-9.119zM12.582 2.287c.997-.082 2.461 .152 3.41 .433 2.343 .697 4.402 2.205 5.9 4.123 .615 .786 .982 1.426 1.458 2.289-.411 .848-1.207 2.026-1.822 2.734-2.146 2.471-4.736 3.884-8.009 4.121-1.213 .056-2.427-.097-3.589-.451-3.288-1.012-5.695-3.412-7.275-6.399 2.025-3.86 5.434-6.63 9.927-6.85z"/>' +
  '<path transform="translate(7.1711 7.1864)" d="M5.329 .023c.159-.026 .531-.025 .694-.021 1.102 .029 2.006 .353 2.952 .899-.136 .338-.353 .728-.516 1.059-.28 .569-.558 1.149-.864 1.702 .223 .189 .432 .403 .635 .613l2.662-1.32c.055 .085 .115 .193 .159 .283 1.449 2.982 .226 6.316-2.67 7.807-.597 .298-1.244 .487-1.908 .558-1.547 .171-3.098-.284-4.307-1.264-1.206-.97-1.975-2.382-2.136-3.921-.157-1.548 .313-3.095 1.305-4.294 1.031-1.256 2.389-1.941 3.994-2.101z"/>';

export function logoMark(size = 26) {
  const holder = document.createElement("div");
  holder.innerHTML =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 26 26" width="${size}" height="${size}" fill="currentColor" ` +
    `aria-hidden="true" focusable="false">${EYE}</svg>`;
  return holder.firstChild;
}
