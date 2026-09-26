/**
 * Recent searches, so a search can be re-run with one click (tester: "It
 * would be nice if it cached previous searches"). Kept per signed-in user in
 * this browser; a blocked or cleared store just shows none.
 */
const MAX = 5

const storageKey = (kind: string, userId: string) => `insite.recent.${kind}.${userId}`

export function loadRecent<T>(kind: string, userId?: string | null): T[] {
  if (!userId) return []
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey(kind, userId)) ?? '[]')
    return Array.isArray(raw) ? (raw as T[]) : []
  } catch {
    return []
  }
}

/** Put `entry` first, dropping an older copy of the same search. */
export function saveRecent<T>(
  kind: string,
  userId: string | null | undefined,
  entry: T,
  keyOf: (t: T) => string,
): T[] {
  if (!userId) return []
  const next = [entry, ...loadRecent<T>(kind, userId).filter((e) => keyOf(e) !== keyOf(entry))]
    .slice(0, MAX)
  try {
    localStorage.setItem(storageKey(kind, userId), JSON.stringify(next))
  } catch {
    // Storage blocked or full: nothing is remembered, nothing breaks.
  }
  return next
}
