// Invalidates async work that outlives its view: take a ticket, check it after each await.
export function createGuard() {
  let current = 0;
  return {
    next: () => ++current,
    isCurrent: (ticket) => ticket === current,
    invalidate: () => {
      current += 1;
    },
  };
}
