/**
 * Tool observation — the result of executing a tool.
 *
 * Every successful tool call produces an observation with a unique evidence
 * number (E-number) that can be referenced in the final answer.
 */

import { z } from 'zod';

export const ToolObservation = z.object({
  /** The tool that was called. */
  tool: z.string(),
  /** Whether the tool executed successfully. */
  ok: z.boolean(),
  /** The tool's output (string or structured). */
  output: z.string(),
  /** Evidence number assigned to this observation (e.g. "E1", "E2"). */
  evidenceId: z.string().optional(),
  /** Truncation notice if the output was truncated. */
  truncated: z.boolean().optional(),
});
export type ToolObservation = z.infer<typeof ToolObservation>;
