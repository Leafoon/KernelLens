/**
 * OpenAIProvider — ModelProvider implementation using the official openai SDK.
 *
 * Handles:
 *   - Chat completions with native tool calling
 *   - Streaming with automatic accumulation
 *   - Retry with exponential backoff on transient errors
 *   - Usage tracking (prompt + completion tokens)
 */

import OpenAI from 'openai';
import type {
  ChatCompletionMessageParam,
  ChatCompletionTool,
} from 'openai/resources/chat/completions';
import { MAX_RETRY_ATTEMPTS, MAX_RETRY_BACKOFF_SEC } from '../constants.js';
import { ModelError } from '../exceptions.js';
import type {
  CompletionMessage,
  CompletionParams,
  CompletionResult,
  ModelProvider,
  ToolCall,
  UsageInfo,
} from './provider.js';

/** Extract the API key prefix for display (first 8 chars). */
function redactKey(key: string): string {
  return key.length > 8 ? `${key.slice(0, 4)}...${key.slice(-4)}` : '****';
}

export interface OpenAIProviderConfig {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly model: string;
  readonly contextWindow: number;
  readonly maxOutputTokens: number;
  /** Request timeout in milliseconds. Default: 120_000 */
  readonly timeoutMs?: number;
  /** Maximum retry attempts for transient errors. Default: MAX_RETRY_ATTEMPTS */
  readonly maxRetries?: number;
}

export class OpenAIProvider implements ModelProvider {
  readonly model: string;
  readonly contextWindow: number;
  readonly maxOutputTokens: number;

  private readonly client: OpenAI;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;

  /** Cumulative usage stats for this provider instance. */
  public totalPromptTokens = 0;
  public totalCompletionTokens = 0;
  public requestCount = 0;

  constructor(config: OpenAIProviderConfig) {
    this.model = config.model;
    this.contextWindow = config.contextWindow;
    this.maxOutputTokens = config.maxOutputTokens;
    this.timeoutMs = config.timeoutMs ?? 120_000;
    this.maxRetries = config.maxRetries ?? MAX_RETRY_ATTEMPTS;

    this.client = new OpenAI({
      apiKey: config.apiKey,
      baseURL: config.baseUrl,
      timeout: this.timeoutMs,
      maxRetries: 0, // We handle retries ourselves
    });
  }

  async complete(params: CompletionParams): Promise<CompletionResult> {
    const maxTokens = params.maxTokens ?? this.maxOutputTokens;
    const tools: ChatCompletionTool[] | undefined = params.tools?.length
      ? params.tools.map((t) => ({
          type: 'function' as const,
          function: {
            name: t.name,
            ...(t.description ? { description: t.description } : {}),
            ...(t.parameters ? { parameters: t.parameters } : {}),
          },
        }))
      : undefined;

    let lastError: Error | undefined;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      this.requestCount++;

      try {
        if (params.onToken) {
          // Streaming mode
          const stream = await this.client.chat.completions.create({
            model: this.model,
            messages: params.messages as ChatCompletionMessageParam[],
            max_tokens: maxTokens,
            ...(tools ? { tools, tool_choice: 'auto' } : {}),
            stream: true,
          });

          let content = '';
          const toolCallsMap = new Map<number, { id: string; name: string; arguments: string }>();
          let finishReason: string | null = null;

          for await (const chunk of stream) {
            const delta = chunk.choices[0]?.delta;
            if (!delta) continue;

            if (delta.content) {
              content += delta.content;
              params.onToken(delta.content);
            }

            if (delta.tool_calls) {
              for (const tc of delta.tool_calls) {
                const idx = tc.index ?? 0;
                const existing = toolCallsMap.get(idx);
                if (existing) {
                  if (tc.function?.arguments) existing.arguments += tc.function.arguments;
                } else if (tc.id && tc.function?.name) {
                  toolCallsMap.set(idx, {
                    id: tc.id,
                    name: tc.function.name,
                    arguments: tc.function?.arguments ?? '',
                  });
                }
              }
            }

            if (chunk.choices[0]?.finish_reason) {
              finishReason = chunk.choices[0].finish_reason;
            }
          }

          const toolCalls: ToolCall[] | undefined =
            toolCallsMap.size > 0
              ? [...toolCallsMap.values()].map((tc) => ({
                  id: tc.id,
                  name: tc.name,
                  arguments: parseArguments(tc.arguments),
                }))
              : undefined;

          if (finishReason === 'length') {
            throw new ModelError(
              'Model output truncated; increase max_output_tokens or simplify the task',
            );
          }

          return {
            message: {
              role: 'assistant',
              content: content || null,
              ...(toolCalls?.length ? { toolCalls } : {}),
            },
            usage: undefined, // streaming doesn't always return usage
            finishReason,
          };
        }

        // Non-streaming mode
        const response = await this.client.chat.completions.create({
          model: this.model,
          messages: params.messages as ChatCompletionMessageParam[],
          max_tokens: maxTokens,
          ...(tools ? { tools, tool_choice: 'auto' } : {}),
          stream: false,
        });

        // Track usage
        if (response.usage) {
          this.totalPromptTokens += response.usage.prompt_tokens;
          this.totalCompletionTokens += response.usage.completion_tokens;
        }

        const choice = response.choices[0];
        if (!choice) {
          throw new ModelError('API response missing choices[0]');
        }

        if (choice.finish_reason === 'length') {
          throw new ModelError(
            'Model output truncated; increase max_output_tokens or simplify the task',
          );
        }

        const message = choice.message;
        const toolCalls: ToolCall[] | undefined = message.tool_calls?.map((tc) => ({
          id: tc.id,
          name: tc.function.name,
          arguments: parseArguments(tc.function.arguments),
        }));

        const result: CompletionMessage = {
          role: 'assistant',
          content: message.content,
          ...(toolCalls?.length ? { toolCalls } : {}),
        };

        return {
          message: result,
          usage: response.usage
            ? {
                promptTokens: response.usage.prompt_tokens,
                completionTokens: response.usage.completion_tokens,
                totalTokens: response.usage.total_tokens,
              }
            : undefined,
          finishReason: choice.finish_reason,
        };
      } catch (error) {
        lastError = error as Error;

        // Non-retryable errors
        if (error instanceof ModelError) throw error;

        // OpenAI API errors
        if (error instanceof OpenAI.APIError) {
          const status = error.status;

          if (status === 401) {
            throw new ModelError(
              `Authentication failed. Check API key: ${redactKey(this.client.apiKey as string)}`,
              status,
            );
          }
          if (status === 429) {
            // Rate limit — retryable
            if (attempt < this.maxRetries) {
              await sleep(backoffDelay(attempt));
              continue;
            }
            throw new ModelError('Rate limited after retries', status);
          }
          if (status && status >= 500) {
            // Server error — retryable
            if (attempt < this.maxRetries) {
              await sleep(backoffDelay(attempt));
              continue;
            }
            throw new ModelError(`Server error: ${status}`, status);
          }

          // Other API errors — not retryable
          throw new ModelError(`API error ${status}: ${error.message}`, status);
        }

        // Network errors — retryable
        if (attempt < this.maxRetries) {
          await sleep(backoffDelay(attempt));
        }
      }
    }

    throw new ModelError(
      `Request failed after ${this.maxRetries + 1} attempts: ${lastError?.message}`,
    );
  }

  /** Get cumulative usage stats. */
  getUsage(): UsageInfo {
    return {
      promptTokens: this.totalPromptTokens,
      completionTokens: this.totalCompletionTokens,
      totalTokens: this.totalPromptTokens + this.totalCompletionTokens,
    };
  }
}

/** Parse tool call arguments from JSON string, with fallback. */
function parseArguments(raw: string): Record<string, unknown> {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return {};
  } catch {
    return {};
  }
}

/** Exponential backoff delay in milliseconds. */
function backoffDelay(attempt: number): number {
  return Math.min(2 ** attempt * 1000, MAX_RETRY_BACKOFF_SEC * 1000);
}

/** Sleep for the given milliseconds. */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
