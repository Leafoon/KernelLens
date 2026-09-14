/**
 * Configuration schema — validated with Zod.
 *
 * All config is loaded from environment variables or a .env file.
 * Field names use KERNELLENS_ prefix for project-specific settings,
 * falling back to standard OPENAI_ / ANTHROPIC_ prefixes.
 */

import { z } from 'zod';

/** LLM provider settings. */
export const ModelConfig = z.object({
  /** API base URL (e.g. "https://api.openai.com/v1"). */
  baseUrl: z.string().url(),
  /** API key for the provider. */
  apiKey: z.string().min(1),
  /** Model identifier (e.g. "gpt-4o", "mimo-v2.5"). */
  model: z.string().min(1),
  /** Context window size in tokens. Overrides model limits table if set. */
  contextWindow: z.number().int().positive().optional(),
  /** Maximum output tokens the model can generate. */
  maxOutputTokens: z.number().int().positive().optional(),
});
export type ModelConfig = z.infer<typeof ModelConfig>;

/** Runtime settings for the agent. */
export const RuntimeConfig = z.object({
  /** Maximum decisions per agent run. */
  maxDecisions: z.number().int().positive().default(30),
  /** Log level for the application logger. */
  logLevel: z.enum(['debug', 'info', 'warn', 'error']).default('info'),
  /** Working directory for kernel files. */
  workspace: z.string().default('.'),
});
export type RuntimeConfig = z.infer<typeof RuntimeConfig>;

/** Complete application settings. */
export const Settings = z.object({
  model: ModelConfig,
  runtime: RuntimeConfig,
});
export type Settings = z.infer<typeof Settings>;
