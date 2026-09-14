/**
 * Task state machine.
 *
 * A task progresses through a strict state graph:
 *   PENDING → RUNNING → COMPLETED / FAILED / BUDGET_EXHAUSTED / CANCELLED
 *                       → WAITING_INPUT → RUNNING / FAILED / CANCELLED
 *
 * Terminal states have no outgoing transitions.
 */

import { z } from 'zod';

export const TaskStatus = z.enum([
  'PENDING',
  'RUNNING',
  'COMPLETED',
  'FAILED',
  'BUDGET_EXHAUSTED',
  'CANCELLED',
  'WAITING_INPUT',
]);
export type TaskStatus = z.infer<typeof TaskStatus>;

/** States that have no outgoing transitions. */
const TERMINAL_STATUSES: ReadonlySet<TaskStatus> = new Set([
  'COMPLETED',
  'FAILED',
  'BUDGET_EXHAUSTED',
  'CANCELLED',
]);

/** Valid transitions: from → set of allowed targets. */
const TRANSITIONS: ReadonlyMap<TaskStatus, ReadonlySet<TaskStatus>> = new Map<
  TaskStatus,
  Set<TaskStatus>
>([
  ['PENDING', new Set<TaskStatus>(['RUNNING'])],
  [
    'RUNNING',
    new Set<TaskStatus>([
      'RUNNING',
      'COMPLETED',
      'FAILED',
      'BUDGET_EXHAUSTED',
      'CANCELLED',
      'WAITING_INPUT',
    ]),
  ],
  ['WAITING_INPUT', new Set<TaskStatus>(['RUNNING', 'FAILED', 'CANCELLED'])],
]);

/** Check whether a status is terminal (no further transitions). */
export function isTerminal(status: TaskStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

/**
 * Validate a state transition.
 * Returns the target status on success, throws on illegal transition.
 */
export function transition(from: TaskStatus, to: TaskStatus): TaskStatus {
  if (isTerminal(from)) {
    throw new Error(`Cannot transition from terminal state ${from}`);
  }
  const allowed = TRANSITIONS.get(from);
  if (!allowed?.has(to)) {
    throw new Error(`Illegal transition: ${from} → ${to}`);
  }
  return to;
}

/**
 * Immutable task state snapshot.
 */
export interface TaskState {
  readonly status: TaskStatus;
  readonly taskType: string | undefined;
  readonly gpu: string | undefined;
  readonly backend: string | undefined;
  readonly stepCount: number;
  readonly startedAt: number | undefined;
  readonly endedAt: number | undefined;
}

export function createTaskState(): TaskState {
  return {
    status: 'PENDING',
    taskType: undefined,
    gpu: undefined,
    backend: undefined,
    stepCount: 0,
    startedAt: undefined,
    endedAt: undefined,
  };
}
