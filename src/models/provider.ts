/**
 * ModelProvider — abstract interface for LLM backends.
 *
 * This protocol decouples the agent loop from any specific LLM provider.
 * Implementations: OpenAIProvider, AnthropicProvider (future), MockProvider (testing).
 */

import type { ChatCompletionMessageParam } from 'openai/resources/chat/completions';

/**
 * A single tool definition (JSON Schema format).
 * Matches the OpenAI function calling schema: { name, description?, parameters? }.
 */
export interface ToolDef {
  readonly name: string;
  readonly description?: string;
  readonly parameters?: Record<string, unknown>;
}

/** Callback for streaming text tokens. */
export type OnTokenFn = (token: string) => void;

/** Parameters for a single completion request. */
export interface CompletionParams {
  /** Conversation messages. */
  readonly messages: readonly ChatCompletionMessageParam[];
  /** Tool definitions. */
  readonly tools?: readonly ToolDef[];
  /** Maximum output tokens. */
  readonly maxTokens?: number;
  /** Stream text tokens to this callback as they arrive. */
  readonly onToken?: OnTokenFn;
}

/** Usage statistics from a completion. */
export interface UsageInfo {
  readonly promptTokens: number;
  readonly completionTokens: number;
  readonly totalTokens: number;
}

/** A structured message returned by the model. */
export interface CompletionMessage {
  readonly role: 'assistant';
  readonly content: string | null;
  readonly toolCalls?: readonly ToolCall[];
}

/** A tool call requested by the model. */
export interface ToolCall {
  readonly id: string;
  readonly name: string;
  readonly arguments: Record<string, unknown>;
}

/** Full result of a completion request. */
export interface CompletionResult {
  readonly message: CompletionMessage;
  readonly usage?: UsageInfo;
  readonly finishReason: string | null;
}

/**
 * The ModelProvider protocol.
 *
 * All LLM backends must implement this interface to be used by the agent loop.
 */
export interface ModelProvider {
  /** The model identifier (e.g. "gpt-4o"). */
  readonly model: string;

  /** Context window size in tokens. */
  readonly contextWindow: number;

  /** Maximum output tokens. */
  readonly maxOutputTokens: number;

  /**
   * Send a completion request to the model.
   * Returns the parsed response with message and usage info.
   */
  complete(params: CompletionParams): Promise<CompletionResult>;
}
