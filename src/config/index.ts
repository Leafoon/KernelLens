/**
 * Configuration management — schema, loader, model limits.
 */

export { Settings, ModelConfig, RuntimeConfig } from './schema.js';
export { loadSettings, parseDotEnv } from './loader.js';
export { MODEL_LIMITS, lookupModelLimit } from './limits.js';
export type { ModelLimit } from './limits.js';
