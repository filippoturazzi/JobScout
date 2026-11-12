// How a search's results fall on a page: the best three in a highlighted row (page 1 only),
// then the rest of the scored jobs and the unscored ones, PER_PAGE cards a page, with a
// divider before the first unscored card. Pure.

export const PER_PAGE = 9;
export const HIGHLIGHTED = 3;

// scored: MatchRead[] best first. unscored: UnscoredRead[] in API order. page: 1-based.
// -> { highlighted, items: [{kind: "match", match} | {kind: "divider"} | {kind: "unscored", item}], page, pages }
export function resultsLayout(scored, unscored, page) {
  const rest = scored.slice(HIGHLIGHTED);
  const cards = rest.length + unscored.length;
  const pages = Math.max(1, Math.ceil(cards / PER_PAGE));
  const current = Math.min(Math.max(Math.trunc(page) || 1, 1), pages);
  const start = (current - 1) * PER_PAGE;
  const end = Math.min(start + PER_PAGE, cards);

  const items = [];
  for (let i = start; i < end; i++) {
    if (i < rest.length) {
      items.push({ kind: "match", match: rest[i] });
      continue;
    }
    if (i === rest.length) items.push({ kind: "divider" });
    items.push({ kind: "unscored", item: unscored[i - rest.length] });
  }
  return { highlighted: current === 1 ? scored.slice(0, HIGHLIGHTED) : [], items, page: current, pages };
}
