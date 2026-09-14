/**
 * Agent action types — the three kinds of decisions the LLM can make.
 *
 * Actions are a discriminated union on the `type` field:
 *   - call_tool: execute a tool with the given arguments
 *   - finish: submit the final answer for review
 *   - request_input: ask the user for missing information
 */

import { z } from 'zod';

/** Execute a registered tool. */
export const CallToolAction = z.object({
  type: z.literal('call_tool'),
  tool: z.string().min(1),
  arguments: z.record(z.unknown()),
});
export type CallToolAction = z.infer<typeof CallToolAction>;

/** Submit the final answer. */
export const FinishAction = z.object({
  type: z.literal('finish'),
  answer: z.string().min(1),
});
export type FinishAction = z.infer<typeof FinishAction>;

/** Pause the run and ask the user for information. */
export const RequestInputAction = z.object({
  type: z.literal('request_input'),
  prompt: z.string().min(1),
});
export type RequestInputAction = z.infer<typeof RequestInputAction>;

/** Discriminated union of all possible agent actions. */
export const AgentAction = z.discriminatedUnion('type', [
  CallToolAction,
  FinishAction,
  RequestInputAction,
]);
export type AgentAction = z.infer<typeof AgentAction>;
