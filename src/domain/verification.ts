/**
 * Verification states for kernel code.
 *
 * Each verification dimension is tracked independently.
 * A dimension can be: not_run | passed | failed | inconclusive.
 */

import { z } from 'zod';

export const VerificationResult = z.enum(['not_run', 'passed', 'failed', 'inconclusive']);
export type VerificationResult = z.infer<typeof VerificationResult>;

export const VerificationState = z.object({
  syntax: VerificationResult.default('not_run'),
  api: VerificationResult.default('not_run'),
  compilation: VerificationResult.default('not_run'),
  correctness: VerificationResult.default('not_run'),
  performance: VerificationResult.default('not_run'),
});
export type VerificationState = z.infer<typeof VerificationState>;

/** Create a fresh verification state with all dimensions unset. */
export function createVerificationState(): VerificationState {
  return {
    syntax: 'not_run',
    api: 'not_run',
    compilation: 'not_run',
    correctness: 'not_run',
    performance: 'not_run',
  };
}
