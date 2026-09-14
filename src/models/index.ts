/**
 * Models layer — LLM provider abstraction, context management, and adapters.
 */

export type {
  ModelProvider,
  CompletionParams,
  CompletionResult,
  CompletionMessage,
  ToolCall,
  ToolDef,
  UsageInfo,
} from './provider.js';
export { OpenAIProvider } from './client.js';
export type { OpenAIProviderConfig } from './client.js';
export {
  TokenMeter,
  ContextWindow,
  approximateTokens,
} from './context.js';
export type { ContextSnapshot } from './context.js';
export { DecisionAdapter } from './adapter.js';
export type { EmitFn, AdapterConfig, AdapterSnapshot } from './adapter.js';
