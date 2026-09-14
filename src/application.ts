/**
 * AgentApplication — the top-level coordinator.
 *
 * Wires together the LLM provider, tool registry, adapter, reviewer, and
 * agent loop into a single `turn()` method that processes one user message.
 *
 * In the TypeScript rewrite, this is simpler than the Python original:
 *   - No Store/persistence (handled externally)
 *   - No GPU profile management (simplified to config)
 *   - No Redactor (handled at call sites)
 */

import { createDecisionBudget } from './agent/budget.js';
import { runAgent } from './agent/loop.js';
import type { RunResult } from './agent/records.js';
import { DecisionAdapter, type EmitFn } from './models/adapter.js';
import type { ModelProvider, OnTokenFn } from './models/provider.js';
import { buildSystemPrompt } from './prompts/system.js';
import { ReportReviewer } from './review/reviewer.js';
import type { ToolRegistry } from './tools/registry.js';

/** Result of a single turn. */
export interface TurnResult {
  readonly runResult: RunResult;
  /** The final answer to display to the user. */
  readonly answer: string;
  /** Evidence entries from tool calls. */
  readonly evidence: readonly { id: string; tool: string }[];
}

/** Configuration for AgentApplication. */
export type TaskMode = 'generate' | 'optimize' | 'diagnose';

export interface AgentApplicationConfig {
  readonly provider: ModelProvider;
  readonly registry: ToolRegistry;
  readonly emit: EmitFn;
  /** Maximum decisions per turn. */
  readonly maxDecisions?: number;
  /** Current task type string (default: 'auto'). */
  readonly taskType?: string;
  /** Workspace root path for system prompt. */
  readonly workspaceRoot?: string;
}

/**
 * AgentApplication orchestrates a single agent turn.
 *
 * Usage:
 *   const app = new AgentApplication(config);
 *   const result = await app.turn('Generate a GEMM kernel for A100');
 */
export class AgentApplication {
  private readonly provider: ModelProvider;
  private readonly registry: ToolRegistry;
  private readonly emit: EmitFn;
  private readonly maxDecisions: number;
  private readonly taskType: string;
  private readonly workspaceRoot: string;

  constructor(config: AgentApplicationConfig) {
    this.provider = config.provider;
    this.registry = config.registry;
    this.emit = config.emit;
    this.maxDecisions = config.maxDecisions ?? 30;
    this.taskType = config.taskType ?? 'auto';
    this.workspaceRoot = config.workspaceRoot ?? '.';
  }

  /**
   * Process one user turn — creates the adapter, reviewer, and runs the agent loop.
   * @param goal - The user's input or task description.
   * @param onToken - Optional callback to receive streaming text tokens.
   * @param mode - Optional task mode override ('generate'|'optimize'|'diagnose').
   */
  async turn(goal: string, onToken?: OnTokenFn, mode?: TaskMode): Promise<TurnResult> {
    if (!goal.trim()) {
      throw new Error('任务内容不能为空');
    }

    const effectiveTaskType = mode ?? this.taskType;
    const systemPrompt = buildSystemPrompt(effectiveTaskType, this.workspaceRoot);

    const adapter = new DecisionAdapter({
      provider: this.provider,
      systemPrompt,
      goal,
      tools: this.registry.schemas().map((s) => ({
        name: s.name,
        description: s.description,
        parameters: s.parameters,
      })),
      emit: this.emit,
    });

    const reviewer = new ReportReviewer();
    const budget = createDecisionBudget(this.maxDecisions);

    const runResult = await runAgent({
      adapter,
      budget,
      registry: this.registry,
      reviewer,
      onToken,
      onStep: (step) => {
        if (step.action.type === 'call_tool') {
          this.emit(`  → ${step.action.tool}: ${step.error ?? 'ok'}`);
        } else if (step.error) {
          this.emit(`  → ${step.error}`);
        }
      },
      onRejection: (reasons) => {
        this.emit(`  → Finish rejected: ${reasons.join('; ')}`);
      },
    });

    const answer = runResult.answer ?? this.buildFallbackAnswer(runResult);

    return {
      runResult,
      answer,
      evidence: this.registry.evidence.map((e) => ({ id: e.id, tool: e.tool })),
    };
  }

  private buildFallbackAnswer(result: RunResult): string {
    if (result.status === 'BUDGET_EXHAUSTED') {
      return '本轮决策次数已耗尽。已执行步骤和产物已保存；可缩小任务后继续，或提高 max-decisions。';
    }
    if (result.status === 'FAILED') {
      const lastStep = result.steps.at(-1);
      return `本轮运行失败：${lastStep?.error ?? 'unknown error'}`;
    }
    return `本轮未完成：${result.status}`;
  }
}
