/**
 * Task type definitions and request model.
 *
 * TaskType is inferred from the user's natural language goal (model-led intake)
 * or set explicitly via CLI commands (/generate, /optimize, /diagnose).
 */

import { z } from 'zod';

/** The three core task types the agent supports. */
export const TaskType = z.enum(['generate', 'optimize', 'diagnose']);
export type TaskType = z.infer<typeof TaskType>;

/**
 * Parsed task request extracted from the user's goal.
 *
 * The LLM populates this during model-led intake (ADR-005), or the user
 * provides explicit fields via CLI flags.
 */
export const TaskRequest = z.object({
  type: TaskType,
  goal: z.string().min(1).describe('The user natural language goal'),
  gpu: z.string().optional().describe('Target GPU model, e.g. A100'),
  backend: z.string().optional().describe('TileLang backend, e.g. cuda'),
});
export type TaskRequest = z.infer<typeof TaskRequest>;
