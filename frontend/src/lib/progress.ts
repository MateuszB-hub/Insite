/**
 * First-run progress that the server has no record of. Per browser only: it
 * ticks a "Get started" step, nothing depends on it, and losing it just
 * shows that step again.
 */
const PATHWAY_KEY = 'insite.pathwayExplored'

export function markPathwayExplored(): void {
  try {
    localStorage.setItem(PATHWAY_KEY, '1')
  } catch {
    // Private window or blocked storage: the step simply stays unticked.
  }
}

export function hasExploredPathway(): boolean {
  try {
    return localStorage.getItem(PATHWAY_KEY) === '1'
  } catch {
    return false
  }
}
