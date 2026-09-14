/**
 * Action handlers — dispatch agent actions to the appropriate executor.
 *
 * Each handler validates the current state, performs the action's effect,
 * and returns the resulting StepRecord.
 */

import type { CallToolAction, FinishAction, RequestInputAction } from '../domain/action.js';
import type { ToolObservation } from '../domain/observation.js';
import type { TaskStatus } from '../domain/state.js';
import { FinishRejectedError } from '../exceptions.js';
import type { Reviewer } from '../review/reviewer.js';
import type { ToolRegistry } from '../tools/registry.js';

/** A recorded step in the agent loop. */
export interface StepResult {
  readonly action: CallToolAction | FinishAction | RequestInputAction;
  readonly status: TaskStatus;
  readonly observation?: ToolObservation;
  readonly error?: string;
}

/** Apply a request_input action — transitions to WAITING_INPUT. */
export function applyRequestInput(action: RequestInputAction): StepResult {
  return { action, status: 'WAITING_INPUT' };
}

/** Apply a finish action — calls the reviewer; throws FinishRejectedError if rejected. */
export async function applyFinish(
  action: FinishAction,
  reviewer: Reviewer,
  evidenceIds: ReadonlySet<string>,
): Promise<StepResult> {
  const reasons = reviewer.review(action.answer, evidenceIds);
  if (reasons.length > 0) {
    throw new FinishRejectedError(reasons);
  }
  return { action, status: 'COMPLETED' };
}

/** Apply a call_tool action — dispatches to the ToolRegistry. */
export async function applyCallTool(
  action: CallToolAction,
  registry: ToolRegistry,
): Promise<StepResult> {
  const observation = await registry.execute(action);
  return { action, status: 'RUNNING', observation };
}
