/**
 * ReportReviewer — validates finish answers for correctness.
 *
 * Checks:
 *   1. Evidence IDs cited in the answer must be valid
 *   2. Answer must contain meaningful content (not empty)
 *
 * Returns an array of rejection reasons (empty = accepted).
 */

/** Reviewer interface — accept any implementation. */
export interface Reviewer {
  /** Review an answer against the run context. Returns reasons to reject (empty = pass). */
  review(answer: string, evidenceIds: ReadonlySet<string>): readonly string[];
}

/**
 * Default report reviewer.
 *
 * Validates:
 *   - Answer is non-empty (after trimming)
 *   - Cited evidence IDs (E1, E2, etc.) match actual observations
 */
export class ReportReviewer implements Reviewer {
  review(answer: string, evidenceIds: ReadonlySet<string>): readonly string[] {
    const reasons: string[] = [];

    // Check answer is non-empty
    if (!answer.trim()) {
      reasons.push('finish answer is empty');
    }

    // Validate cited evidence IDs
    const cited = extractEvidenceIds(answer);
    for (const id of cited) {
      if (!evidenceIds.has(id)) {
        reasons.push(`Cited [${id}] but no tool observation produced that evidence ID`);
      }
    }

    return reasons;
  }
}

/**
 * Extract E-number references from text.
 * Matches patterns like [E1], [E2], [E12] etc.
 */
function extractEvidenceIds(text: string): Set<string> {
  const matches = text.matchAll(/\[E(\d+)\]/g);
  const ids = new Set<string>();
  for (const match of matches) {
    ids.add(`E${match[1]}`);
  }
  return ids;
}
