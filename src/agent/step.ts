/**
 * decideOnce — one iteration of the agent loop.
 *
 * Calls the DecisionAdapter for the next action, dispatches it to the
 * appropriate handler, and returns a StepRecord.
 */

import type { DecisionAdapter } from '../models/adapter.js';
import type { OnTokenFn } from '../models/provider.js';
import type { Reviewer } from '../review/reviewer.js';
import type { ToolRegistry } from '../tools/registry.js';
import { type StepResult, applyCallTool, applyFinish, applyRequestInput } from './handlers.js';

/** Context for a single decision step. */
export interface StepContext {
  readonly adapter: DecisionAdapter;
  readonly registry: ToolRegistry;
  readonly reviewer: Reviewer;
  readonly evidenceIds: ReadonlySet<string>;
  /** Stream text tokens to this callback as they arrive. */
  readonly onToken?: OnTokenFn;
}

/**
 * Execute one decision step: decide → dispatch → record.
 *
 * @returns The StepResult containing the action taken and its outcome.
 */
export async function decideOnce(ctx: StepContext): Promise<StepResult> {
  const action = await ctx.adapter.decide(ctx.onToken);

  switch (action.type) {
    case 'call_tool':
      return applyCallTool(action, ctx.registry);

    case 'finish':
      return applyFinish(action, ctx.reviewer, ctx.evidenceIds);

    case 'request_input':
      return applyRequestInput(action);
  }
}
