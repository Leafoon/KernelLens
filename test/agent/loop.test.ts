import { describe, expect, it, vi } from 'vitest';
import { createDecisionBudget } from '../../src/agent/budget.js';
import { runAgent } from '../../src/agent/loop.js';
import type { AgentAction, CallToolAction, FinishAction } from '../../src/domain/action.js';
import type { ToolObservation } from '../../src/domain/observation.js';
import type { DecisionAdapter } from '../../src/models/adapter.js';
import type { Reviewer } from '../../src/review/reviewer.js';
import type { ToolRegistry } from '../../src/tools/registry.js';

function mockAdapter(actions: AgentAction[]): DecisionAdapter {
  let i = 0;
  return {
    decide: vi.fn(async () => {
      if (i >= actions.length) throw new Error('No more actions');
      return actions[i++]!;
    }),
    observe: vi.fn(),
    feedback: vi.fn(),
  } as unknown as DecisionAdapter;
}

function mockRegistry(observation?: ToolObservation): ToolRegistry {
  return {
    execute: vi.fn(
      async () =>
        observation ?? {
          tool: 'test_tool',
          ok: true,
          output: 'ok',
          evidenceId: 'E1',
          truncated: false,
        },
    ),
    evidence: [],
  } as unknown as ToolRegistry;
}

function mockReviewer(reject = false): Reviewer {
  return {
    review: vi.fn(() => (reject ? ['Not enough evidence'] : [])),
  };
}

describe('runAgent', () => {
  it('completes immediately when LLM returns finish', async () => {
    const finishAction: FinishAction = { type: 'finish', answer: 'Done' };
    const adapter = mockAdapter([finishAction]);
    const registry = mockRegistry();
    const reviewer = mockReviewer();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
    });

    expect(result.status).toBe('COMPLETED');
    expect(result.answer).toBe('Done');
    expect(result.steps).toHaveLength(1);
    expect(result.steps[0]!.action.type).toBe('finish');
  });

  it('runs tool call then finish', async () => {
    const toolAction: CallToolAction = {
      type: 'call_tool',
      tool: 'read_file',
      arguments: { path: 'test.py' },
    };
    const finishAction: FinishAction = { type: 'finish', answer: 'Read complete' };
    const adapter = mockAdapter([toolAction, finishAction]);
    const registry = mockRegistry();
    const reviewer = mockReviewer();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
    });

    expect(result.status).toBe('COMPLETED');
    expect(result.steps).toHaveLength(2);
    expect(result.steps[0]!.action.type).toBe('call_tool');
    expect(result.steps[1]!.action.type).toBe('finish');
    expect(adapter.observe).toHaveBeenCalledTimes(1);
  });

  it('transitions to WAITING_INPUT on request_input', async () => {
    const requestAction = {
      type: 'request_input' as const,
      prompt: 'What GPU?',
    };
    const adapter = mockAdapter([requestAction]);
    const registry = mockRegistry();
    const reviewer = mockReviewer();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
    });

    expect(result.status).toBe('WAITING_INPUT');
    expect(result.steps).toHaveLength(1);
  });

  it('runs out of budget and returns BUDGET_EXHAUSTED', async () => {
    const toolAction: CallToolAction = {
      type: 'call_tool',
      tool: 'read_file',
      arguments: { path: 'test.py' },
    };
    // Always return a tool call (never finishes) — budget = 2 should exhaust
    const adapter = mockAdapter([toolAction, toolAction, toolAction]);
    const registry = mockRegistry();
    const reviewer = mockReviewer();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(2),
      registry,
      reviewer,
    });

    expect(result.status).toBe('BUDGET_EXHAUSTED');
    // 2 successful steps + 1 budget-exhausted step
    expect(result.steps).toHaveLength(3);
  });

  it('feeds finish rejection as feedback and retries', async () => {
    const badFinish: FinishAction = { type: 'finish', answer: 'See [E99]' };
    const goodFinish: FinishAction = { type: 'finish', answer: 'All done properly' };

    // First reviewer rejects, second accepts
    let callCount = 0;
    const reviewer: Reviewer = {
      review: vi.fn(() => {
        callCount++;
        return callCount === 1 ? ['Invalid evidence E99'] : [];
      }),
    };

    // Adapter: badFinish → feedback injected → goodFinish
    let decideCalls = 0;
    const adapter = {
      decide: vi.fn(async () => {
        decideCalls++;
        return decideCalls === 1 ? badFinish : goodFinish;
      }),
      observe: vi.fn(),
      feedback: vi.fn(),
    } as unknown as DecisionAdapter;

    const registry = mockRegistry();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
    });

    expect(result.status).toBe('COMPLETED');
    expect(result.answer).toBe('All done properly');
    expect(adapter.feedback).toHaveBeenCalledTimes(1);
    expect((adapter.feedback as ReturnType<typeof vi.fn>).mock.calls[0][0]).toContain(
      'Invalid evidence E99',
    );
  });

  it('calls onStep callback for each step', async () => {
    const finishAction: FinishAction = { type: 'finish', answer: 'Done' };
    const adapter = mockAdapter([finishAction]);
    const registry = mockRegistry();
    const reviewer = mockReviewer();
    const onStep = vi.fn();

    await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
      onStep,
    });

    expect(onStep).toHaveBeenCalledTimes(1);
    expect(onStep.mock.calls[0][0].action.type).toBe('finish');
  });

  it('records step duration', async () => {
    const finishAction: FinishAction = { type: 'finish', answer: 'Done' };
    const adapter = mockAdapter([finishAction]);
    const registry = mockRegistry();
    const reviewer = mockReviewer();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
    });

    expect(result.steps[0]!.durationMs).toBeGreaterThanOrEqual(0);
    expect(result.totalDurationMs).toBeGreaterThanOrEqual(0);
  });

  it('handles adapter throwing an error', async () => {
    const adapter = {
      decide: vi.fn(async () => {
        throw new Error('API error');
      }),
      observe: vi.fn(),
      feedback: vi.fn(),
    } as unknown as DecisionAdapter;
    const registry = mockRegistry();
    const reviewer = mockReviewer();

    const result = await runAgent({
      adapter,
      budget: createDecisionBudget(10),
      registry,
      reviewer,
    });

    expect(result.status).toBe('FAILED');
    expect(result.steps[0]!.error).toContain('API error');
  });
});
