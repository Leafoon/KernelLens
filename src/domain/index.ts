/**
 * Domain layer — pure data types and state machines.
 *
 * No I/O, no side effects, no external dependencies beyond Zod.
 */

export { TaskType, TaskRequest } from './task.js';
export { TaskStatus, TaskState, isTerminal, transition, createTaskState } from './state.js';
export {
  AgentAction,
  CallToolAction,
  FinishAction,
  RequestInputAction,
} from './action.js';
export { ToolObservation } from './observation.js';
export {
  VerificationState,
  VerificationResult,
  createVerificationState,
} from './verification.js';
