/**
 * DecisionAdapter — bridges the agent loop with the LLM provider.
 *
 * Responsibilities:
 *   - Manages conversation history (message groups)
 *   - Converts between OpenAI message format and AgentAction
 *   - Handles context overflow by requesting compaction
 *   - Tracks decisions count and emits status updates
 */

import type { ChatCompletionMessageParam } from 'openai/resources/chat/completions';
import {
  AgentAction,
  type CallToolAction,
  type FinishAction,
  type RequestInputAction,
} from '../domain/action.js';
import type { ToolObservation } from '../domain/observation.js';
import { ContextOverflowError, ModelError } from '../exceptions.js';
import { type ContextSnapshot, ContextWindow, TokenMeter } from './context.js';
import type { CompletionMessage, ModelProvider, OnTokenFn, ToolDef } from './provider.js';

/** Callback for emitting status messages to the user. */
export type EmitFn = (message: string) => void;

/** Adapter configuration. */
export interface AdapterConfig {
  readonly provider: ModelProvider;
  readonly systemPrompt: string;
  readonly goal: string;
  readonly tools: readonly ToolDef[];
  readonly emit: EmitFn;
  /** Saved context from a previous run (for session resume). */
  readonly savedContext?: ContextSnapshot;
}

/**
 * DecisionAdapter manages the conversation with the LLM and converts
 * its responses into typed AgentAction objects.
 */
export class DecisionAdapter {
  readonly window: ContextWindow;
  readonly meter: TokenMeter;

  private readonly provider: ModelProvider;
  private readonly tools: readonly ToolDef[];
  private readonly emit: EmitFn;

  /** Conversation history as flat message list. */
  private messages: ChatCompletionMessageParam[] = [];
  /** Number of observations processed. */
  private seen = 0;
  /** Number of decisions made. */
  public decisions = 0;

  constructor(config: AdapterConfig) {
    this.provider = config.provider;
    this.tools = config.tools;
    this.emit = config.emit;

    this.meter = new TokenMeter();
    this.window = new ContextWindow(config.provider, this.meter, {
      summary: config.savedContext?.summary,
      compactions: config.savedContext?.compactions,
    });

    // Initialize with system message + goal
    this.messages = [
      { role: 'system', content: config.systemPrompt },
      { role: 'user', content: config.goal },
    ];
  }

  /**
   * Ask the LLM for the next action.
   * Returns a typed AgentAction.
   * @param onToken - Optional callback to receive streaming text tokens.
   */
  async decide(onToken?: OnTokenFn): Promise<AgentAction> {
    this.decisions++;
    this.emit(`[${this.decisions}] Requesting model decision...`);

    // Check context window
    const messages = this.prepareMessages();

    try {
      const result = await this.provider.complete({
        messages,
        tools: this.tools.length ? this.tools : undefined,
        onToken,
      });

      // Update token meter
      if (result.usage) {
        this.meter.observe(messages, this.tools, result.usage.promptTokens);
      }

      // Parse the response into an action
      const action = this.parseResponse(result.message);

      // Add assistant message to history
      this.messages.push({
        role: 'assistant',
        content: result.message.content,
        ...(result.message.toolCalls?.length
          ? {
              tool_calls: result.message.toolCalls.map((tc) => ({
                id: tc.id,
                type: 'function' as const,
                function: {
                  name: tc.name,
                  arguments: JSON.stringify(tc.arguments),
                },
              })),
            }
          : {}),
      });

      return action;
    } catch (error) {
      if (error instanceof ContextOverflowError) {
        this.emit('Context window overflow — compacting and retrying...');
        // TODO: implement compaction (Phase 5)
        throw error;
      }
      throw error;
    }
  }

  /**
   * Add a tool observation to the conversation history.
   */
  observe(observation: ToolObservation): void {
    // Add tool result message
    this.messages.push({
      role: 'tool',
      tool_call_id: `call_${this.seen}`,
      content: observation.output,
    } as ChatCompletionMessageParam);
    this.seen++;
  }

  /**
   * Add a feedback message (e.g. review rejection) to the conversation.
   */
  feedback(content: string): void {
    this.messages.push({
      role: 'user',
      content: `System feedback: ${content}`,
    });
  }

  /**
   * Get a snapshot for persistence.
   */
  snapshot(): AdapterSnapshot {
    return {
      messages: [...this.messages],
      decisions: this.decisions,
      context: this.window.snapshot(),
      meterRatio: this.meter.ratio,
    };
  }

  /**
   * Get estimated context tokens.
   */
  estimateContextTokens(): number {
    return this.meter.estimate(this.messages, this.tools);
  }

  // ── Private ──────────────────────────────────────────────────────────────

  /**
   * Prepare messages for the API call (may include summary if compacted).
   */
  private prepareMessages(): ChatCompletionMessageParam[] {
    const messages: ChatCompletionMessageParam[] = [];

    // System prompt
    messages.push(this.messages[0]!);

    // Summary if available
    if (this.window.summary) {
      messages.push({
        role: 'user',
        content: `Previous conversation summary (historical context, not a substitute for current tool verification):\n${this.window.summary}`,
      });
    }

    // Rest of conversation (skip system message)
    for (let i = 1; i < this.messages.length; i++) {
      messages.push(this.messages[i]!);
    }

    // Check if it fits
    if (!this.window.fits(messages, this.tools)) {
      this.emit(
        `Context: ~${this.window.estimatedTokens.toLocaleString()} / ${this.provider.contextWindow.toLocaleString()} tokens`,
      );
    }

    return messages;
  }

  /**
   * Parse a model response into a typed AgentAction.
   */
  private parseResponse(message: CompletionMessage): AgentAction {
    // Tool calls → call_tool action
    if (message.toolCalls?.length) {
      const tc = message.toolCalls[0]!;
      if (tc.name === 'finish') {
        return {
          type: 'finish',
          answer: (tc.arguments.answer as string) ?? message.content ?? '',
        } as FinishAction;
      }
      if (tc.name === 'request_input') {
        return {
          type: 'request_input',
          prompt: (tc.arguments.prompt as string) ?? 'More information needed.',
        } as RequestInputAction;
      }
      return {
        type: 'call_tool',
        tool: tc.name,
        arguments: tc.arguments,
      } as CallToolAction;
    }

    // Text-only response → try to parse as action JSON, or treat as finish
    const content = message.content?.trim() ?? '';
    if (!content) {
      throw new ModelError('Model returned empty response');
    }

    // Try to parse as JSON action
    if (content.startsWith('{') || content.startsWith('```')) {
      try {
        const json = extractJson(content);
        return AgentAction.parse(json);
      } catch {
        // Not valid JSON — treat as finish
      }
    }

    // Plain text → finish action
    return { type: 'finish', answer: content } as FinishAction;
  }
}

/** Serializable snapshot of the adapter state. */
export interface AdapterSnapshot {
  readonly messages: readonly ChatCompletionMessageParam[];
  readonly decisions: number;
  readonly context: ContextSnapshot;
  readonly meterRatio: number;
}

/**
 * Extract JSON from a string that may be wrapped in markdown code fences.
 */
function extractJson(text: string): unknown {
  let stripped = text.trim();
  if (stripped.startsWith('```') && stripped.endsWith('```')) {
    stripped = stripped.split('\n', 2)[1]?.trim() ?? stripped;
    if (stripped.endsWith('```')) {
      stripped = stripped.slice(0, -3).trim();
    }
  }
  return JSON.parse(stripped);
}
