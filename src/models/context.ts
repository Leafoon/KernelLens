import type { ChatCompletionMessageParam } from 'openai/resources/chat/completions';
import { TOKEN_MARGIN_DIVISOR, TOKEN_MARGIN_MIN } from '../constants.js';
import type { ModelProvider } from './provider.js';

// ── Token Estimation ─────────────────────────────────────────────────────────

/**
 * Approximate token count from a value by JSON-serializing it and applying
 * a heuristic: ASCII chars ≈ 1/4 token each, non-ASCII ≈ 1.5 tokens each.
 *
 * This is intentionally simple — the real calibration comes from TokenMeter.observe()
 * which adjusts the ratio based on actual provider usage.
 */
export function approximateTokens(value: unknown): number {
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 0);
  let asciiChars = 0;
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) < 128) asciiChars++;
  }
  const nonAscii = text.length - asciiChars;
  return Math.max(1, Math.ceil(asciiChars / 4 + nonAscii * 1.5));
}

// ── TokenMeter ───────────────────────────────────────────────────────────────

/**
 * Estimates pending input tokens and calibrates from actual provider usage.
 *
 * After each request, call `observe()` with the actual prompt_tokens from the
 * provider's response. The meter adjusts its internal ratio so future estimates
 * are more accurate.
 */
export class TokenMeter {
  /** Calibration ratio: estimated → actual. Starts at 1.0. */
  public ratio = 1.0;
  /** Last observed prompt_tokens from the provider. */
  public lastPromptTokens: number | undefined;

  /**
   * Estimate the token count for a set of messages + tool schemas.
   * Returns the calibrated estimate.
   */
  estimate(messages: readonly ChatCompletionMessageParam[], tools?: readonly unknown[]): number {
    return Math.ceil(this.raw(messages, tools) * this.ratio);
  }

  /**
   * Raw (uncalibrated) token estimate.
   */
  raw(messages: readonly ChatCompletionMessageParam[], tools?: readonly unknown[]): number {
    return approximateTokens([messages, tools ?? []]) + 12 * messages.length + 32;
  }

  /**
   * Calibrate the meter from actual provider usage.
   * Call this after each successful completion with the provider's prompt_tokens.
   */
  observe(
    messages: readonly ChatCompletionMessageParam[],
    tools: readonly unknown[],
    promptTokens: number | undefined,
  ): void {
    if (typeof promptTokens === 'number' && Number.isInteger(promptTokens) && promptTokens >= 0) {
      this.lastPromptTokens = promptTokens;
      const raw = this.raw(messages, tools);
      if (raw > 0) {
        // Clamp ratio to [0.5, 4.0] to resist malformed data
        this.ratio = Math.min(4.0, Math.max(0.5, promptTokens / raw));
      }
    } else {
      this.lastPromptTokens = undefined;
    }
  }
}

// ── ContextWindow ────────────────────────────────────────────────────────────

/**
 * Manages the active conversation window, triggering compaction when
 * the estimated token usage approaches the model's context limit.
 */
export class ContextWindow {
  /** Rolling summary of compacted older messages. */
  public summary = '';
  /** Number of compactions performed. */
  public compactions = 0;
  /** Last estimated token count. */
  public estimatedTokens = 0;

  private readonly meter: TokenMeter;
  private readonly provider: ModelProvider;

  constructor(
    provider: ModelProvider,
    meter: TokenMeter,
    options?: { summary?: string; compactions?: number },
  ) {
    this.provider = provider;
    this.meter = meter;
    if (options?.summary) this.summary = options.summary;
    if (options?.compactions) this.compactions = options.compactions;
  }

  /**
   * The effective token limit for input messages.
   * Reserves space for output tokens and a small estimation margin.
   */
  get limit(): number {
    const window = this.provider.contextWindow;
    return (
      window -
      this.provider.maxOutputTokens -
      Math.max(TOKEN_MARGIN_MIN, Math.floor(window / TOKEN_MARGIN_DIVISOR))
    );
  }

  /**
   * Estimate the token count for the given messages.
   */
  estimateTokens(
    messages: readonly ChatCompletionMessageParam[],
    tools?: readonly unknown[],
  ): number {
    return this.meter.estimate(messages, tools);
  }

  /**
   * Check if the messages fit within the context window.
   * Returns true if they fit, false if compaction is needed.
   */
  fits(messages: readonly ChatCompletionMessageParam[], tools?: readonly unknown[]): boolean {
    this.estimatedTokens = this.estimateTokens(messages, tools);
    return this.estimatedTokens <= this.limit;
  }

  /**
   * Get a snapshot of the current context state for persistence.
   */
  snapshot(): ContextSnapshot {
    return {
      summary: this.summary,
      compactions: this.compactions,
      estimatedTokens: this.estimatedTokens,
    };
  }
}

/** Serializable snapshot of context window state. */
export interface ContextSnapshot {
  readonly summary: string;
  readonly compactions: number;
  readonly estimatedTokens: number;
}
