/**
 * Agent run records — immutable snapshots of each step and the final result.
 */

import type { AgentAction } from '../domain/action.js';
import type { TaskStatus } from '../domain/state.js';

/** A single step in the agent loop: the LLM's decision and the tool result. */
export interface StepRecord {
  /** Sequential step number (0-indexed). */
  readonly stepIndex: number;
  /** The action the LLM chose. */
  readonly action: AgentAction;
  /** The tool's output (undefined for non-call_tool actions). */
  readonly toolOutput?: string;
  /** Evidence number if this step produced one. */
  readonly evidenceId?: string;
  /** Error message if the step failed. */
  readonly error?: string;
  /** Wall-clock duration of this step in milliseconds. */
  readonly durationMs: number;
}

/** The outcome of an entire agent run. */
export interface RunResult {
  /** Final task status. */
  readonly status: TaskStatus;
  /** The final answer (if completed successfully). */
  readonly answer?: string;
  /** All steps taken during the run. */
  readonly steps: readonly StepRecord[];
  /** Total wall-clock duration in milliseconds. */
  readonly totalDurationMs: number;
  /** Total tokens consumed (input + output). */
  readonly totalTokens?: number;
  /** Why the run ended (human-readable). */
  readonly reason?: string;
}
