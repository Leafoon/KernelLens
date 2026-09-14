/**
 * Verified model specifications.
 *
 * Each entry documents the context window and max output tokens for a
 * known model, along with a source URL for verification. This table is
 * used as a fallback when the user does not explicitly set contextWindow
 * in their config.
 */

export interface ModelLimit {
  /** Model identifier (must match what the API returns). */
  readonly model: string;
  /** Maximum context window in tokens. */
  readonly contextWindow: number;
  /** Maximum output tokens. */
  readonly maxOutputTokens: number;
  /** Source URL where this spec was verified. */
  readonly source: string;
}

/**
 * Known model limits. Extend this table as new models are verified.
 *
 * To add a new model: verify its context window from official docs,
 * add the entry, and include the source URL.
 */
export const MODEL_LIMITS: readonly ModelLimit[] = [
  {
    model: 'mimo-v2.5',
    contextWindow: 1_048_576,
    maxOutputTokens: 131_072,
    source: 'https://huggingface.co/XiaomiMiMo/MiMo-7B-RL',
  },
  {
    model: 'mimo-v2.5-pro',
    contextWindow: 1_048_576,
    maxOutputTokens: 131_072,
    source: 'https://huggingface.co/XiaomiMiMo/MiMo-7B-RL',
  },
  {
    model: 'gpt-4o',
    contextWindow: 128_000,
    maxOutputTokens: 16_384,
    source: 'https://platform.openai.com/docs/models',
  },
  {
    model: 'gpt-4o-mini',
    contextWindow: 128_000,
    maxOutputTokens: 16_384,
    source: 'https://platform.openai.com/docs/models',
  },
  {
    model: 'gpt-4-turbo',
    contextWindow: 128_000,
    maxOutputTokens: 4_096,
    source: 'https://platform.openai.com/docs/models',
  },
  {
    model: 'claude-sonnet-4-20250514',
    contextWindow: 200_000,
    maxOutputTokens: 16_384,
    source: 'https://docs.anthropic.com/en/docs/about-claude/models',
  },
  {
    model: 'claude-3-5-sonnet-20241022',
    contextWindow: 200_000,
    maxOutputTokens: 8_192,
    source: 'https://docs.anthropic.com/en/docs/about-claude/models',
  },
  {
    model: 'deepseek-chat',
    contextWindow: 65_536,
    maxOutputTokens: 8_192,
    source: 'https://platform.deepseek.com/api-docs',
  },
  {
    model: 'deepseek-reasoner',
    contextWindow: 65_536,
    maxOutputTokens: 16_384,
    source: 'https://platform.deepseek.com/api-docs',
  },
];

/**
 * Look up model limits by model identifier.
 * Returns undefined if the model is not in the table.
 */
export function lookupModelLimit(model: string): ModelLimit | undefined {
  return MODEL_LIMITS.find((m) => m.model === model);
}
