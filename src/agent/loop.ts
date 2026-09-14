/**
 * runAgent — the main agent loop.
 *
 * Repeatedly calls decideOnce until a terminal state is reached:
 *   - COMPLETED (finish accepted by reviewer)
 *   - WAITING_INPUT (request_input action)
 *   - BUDGET_EXHAUSTED (ran out of decision steps)
 *   - FAILED (unrecoverable error)
 */

import { type TaskStatus, transition } from '../domain/state.js';
import { BudgetExhaustedError, FinishRejectedError } from '../exceptions.js';
import type { DecisionAdapter } from '../models/adapter.js';
import type { OnTokenFn } from '../models/provider.js';
import type { Reviewer } from '../review/reviewer.js';
import type { ToolRegistry } from '../tools/registry.js';
import { type DecisionBudget, consume } from './budget.js';
import type { RunResult, StepRecord } from './records.js';
import type { StepContext } from './step.js';
import { decideOnce } from './step.js';

/** Callback invoked after each step is recorded. */
export type OnStepFn = (step: StepRecord) => void;

/** Callback invoked when a finish is rejected. */
export type OnRejectionFn = (reasons: readonly string[]) => void;

/** Configuration for the agent loop. */
export interface RunAgentConfig {
  readonly adapter: DecisionAdapter;
  readonly budget: DecisionBudget;
  readonly registry: ToolRegistry;
  readonly reviewer: Reviewer;
  readonly onStep?: OnStepFn;
  readonly onRejection?: OnRejectionFn;
  /** Stream text tokens to this callback as they arrive. */
  readonly onToken?: OnTokenFn;
}

/**
 * Run the agent loop until a terminal state is reached.
 *
 * Returns a RunResult with the final status, all steps, and duration.
 */
export async function runAgent(config: RunAgentConfig): Promise<RunResult> {
  const { adapter, registry, reviewer, onStep, onRejection, onToken } = config;
  let budget = config.budget;
  let status: TaskStatus = 'RUNNING';
  const steps: StepRecord[] = [];
  const start = Date.now();

  // Evidence IDs set — grows as tools produce observations
  const evidenceIds = new Set<string>();
  for (const e of registry.evidence) {
    evidenceIds.add(e.id);
  }

  while (status === 'RUNNING') {
    const stepStart = Date.now();
    let stepResult: StepRecord;

    try {
      // Consume budget (throws BudgetExhaustedError if none remaining)
      budget = consume(budget);
      const ctx: StepContext = {
        adapter,
        registry,
        reviewer,
        evidenceIds,
        onToken,
      };

      const result = await decideOnce(ctx);

      // Update evidence IDs from tool observations
      if (result.observation?.evidenceId) {
        evidenceIds.add(result.observation.evidenceId);
      }

      stepResult = {
        stepIndex: steps.length,
        action: result.action,
        toolOutput: result.observation?.output,
        evidenceId: result.observation?.evidenceId,
        durationMs: Date.now() - stepStart,
      };

      // Feed observation back to adapter
      if (result.observation) {
        adapter.observe(result.observation);
      }

      // Transition state
      status = transition(status, result.status);
    } catch (error) {
      if (error instanceof FinishRejectedError) {
        // Feed rejection reason as feedback
        adapter.feedback(`审核未通过: ${error.reasons.join('; ')}`);
        onRejection?.(error.reasons);

        stepResult = {
          stepIndex: steps.length,
          action: { type: 'finish', answer: '[rejected]' },
          error: `Finish rejected: ${error.reasons.join('; ')}`,
          durationMs: Date.now() - stepStart,
        };
        // Continue running — the agent will retry
        status = 'RUNNING';
      } else if (error instanceof BudgetExhaustedError) {
        stepResult = {
          stepIndex: steps.length,
          action: { type: 'finish', answer: '[budget exhausted]' },
          error: error.message,
          durationMs: Date.now() - stepStart,
        };
        status = 'BUDGET_EXHAUSTED';
      } else {
        const message = error instanceof Error ? error.message : 'Unknown error';
        stepResult = {
          stepIndex: steps.length,
          action: { type: 'finish', answer: '[error]' },
          error: message,
          durationMs: Date.now() - stepStart,
        };
        status = 'FAILED';
      }
    }

    steps.push(stepResult);
    onStep?.(stepResult);
  }

  const totalDurationMs = Date.now() - start;

  // Extract the final answer
  const lastStep = steps.at(-1);
  let answer: string | undefined;
  if (lastStep?.action.type === 'finish') {
    answer = lastStep.action.answer;
  }

  return {
    status,
    answer,
    steps,
    totalDurationMs,
  };
}
