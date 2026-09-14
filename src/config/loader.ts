/**
 * Configuration loader.
 *
 * Reads settings from environment variables and an optional .env file.
 * Resolution order for each field:
 *   1. KERNELLENS_* env var (project-specific)
 *   2. Provider-specific env var (OPENAI_*, ANTHROPIC_*)
 *   3. Default value from schema
 *
 * The .env file is parsed literally (no shell expansion) to avoid
 * surprises with values containing special characters.
 */

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { lookupModelLimit } from './limits.js';
import { type ModelConfig, type RuntimeConfig, Settings } from './schema.js';

/** Parse a .env file into a record of key-value pairs. No shell expansion. */
export function parseDotEnv(filePath: string): Record<string, string> {
  if (!existsSync(filePath)) {
    return {};
  }
  const content = readFileSync(filePath, 'utf-8');
  const result: Record<string, string> = {};

  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const eqIndex = trimmed.indexOf('=');
    if (eqIndex === -1) continue;

    const key = trimmed.slice(0, eqIndex).trim();
    let value = trimmed.slice(eqIndex + 1).trim();

    // Strip surrounding quotes (single or double)
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }

    result[key] = value;
  }

  return result;
}

/** Resolve a config value with fallback chain. */
function resolveEnv(env: Record<string, string>, ...keys: readonly string[]): string | undefined {
  for (const key of keys) {
    const value = env[key];
    if (value !== undefined && value !== '') {
      return value;
    }
  }
  return undefined;
}

/** Load and validate application settings. */
export function loadSettings(dotEnvPath?: string): Settings {
  // Load .env file: explicit path, or auto-discover in cwd
  const envPath = dotEnvPath ?? resolve(process.cwd(), '.env');
  const fileEnv = parseDotEnv(envPath);

  // Merge: file env < process.env (process.env takes precedence)
  const processEnv: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined) processEnv[k] = v;
  }
  const env: Record<string, string> = { ...fileEnv, ...processEnv };

  // Resolve model config
  const baseUrl =
    resolveEnv(env, 'KERNELLENS_BASE_URL', 'OPENAI_BASE_URL') ?? 'https://api.openai.com/v1';
  const apiKey = resolveEnv(env, 'KERNELLENS_API_KEY', 'OPENAI_API_KEY');
  if (!apiKey) {
    throw new Error(
      'API key not found. Set KERNELLENS_API_KEY or OPENAI_API_KEY in .env or environment.',
    );
  }
  const model = resolveEnv(env, 'KERNELLENS_MODEL', 'OPENAI_MODEL') ?? 'gpt-4o';

  // Look up model limits for context window
  const limits = lookupModelLimit(model);
  const contextWindow =
    resolveEnv(env, 'KERNELLENS_CONTEXT_WINDOW') !== undefined
      ? Number(resolveEnv(env, 'KERNELLENS_CONTEXT_WINDOW'))
      : limits?.contextWindow;
  const maxOutputTokens =
    resolveEnv(env, 'KERNELLENS_MAX_OUTPUT_TOKENS') !== undefined
      ? Number(resolveEnv(env, 'KERNELLENS_MAX_OUTPUT_TOKENS'))
      : limits?.maxOutputTokens;

  const modelConfig: ModelConfig = {
    baseUrl,
    apiKey,
    model,
    ...(contextWindow !== undefined ? { contextWindow } : {}),
    ...(maxOutputTokens !== undefined ? { maxOutputTokens } : {}),
  };

  // Resolve runtime config
  const maxDecisions =
    resolveEnv(env, 'KERNELLENS_MAX_DECISIONS') !== undefined
      ? Number(resolveEnv(env, 'KERNELLENS_MAX_DECISIONS'))
      : 30;
  const logLevel = (resolveEnv(env, 'KERNELLENS_LOG_LEVEL') ?? 'info') as
    | 'debug'
    | 'info'
    | 'warn'
    | 'error';
  const workspace = resolveEnv(env, 'KERNELLENS_WORKSPACE') ?? '.';

  const runtimeConfig: RuntimeConfig = { maxDecisions, logLevel, workspace };

  return Settings.parse({ model: modelConfig, runtime: runtimeConfig });
}
