import { describe, expect, it } from 'vitest';
import { TaskStatus, createTaskState, isTerminal, transition } from '../../src/domain/state.js';

describe('TaskStatus', () => {
  it('accepts all valid statuses', () => {
    const statuses = [
      'PENDING',
      'RUNNING',
      'COMPLETED',
      'FAILED',
      'BUDGET_EXHAUSTED',
      'CANCELLED',
      'WAITING_INPUT',
    ];
    for (const s of statuses) {
      expect(TaskStatus.parse(s)).toBe(s);
    }
  });

  it('rejects invalid status', () => {
    expect(() => TaskStatus.parse('UNKNOWN')).toThrow();
  });
});

describe('isTerminal', () => {
  it('identifies terminal states', () => {
    expect(isTerminal('COMPLETED')).toBe(true);
    expect(isTerminal('FAILED')).toBe(true);
    expect(isTerminal('BUDGET_EXHAUSTED')).toBe(true);
    expect(isTerminal('CANCELLED')).toBe(true);
  });

  it('identifies non-terminal states', () => {
    expect(isTerminal('PENDING')).toBe(false);
    expect(isTerminal('RUNNING')).toBe(false);
    expect(isTerminal('WAITING_INPUT')).toBe(false);
  });
});

describe('transition', () => {
  it('allows PENDING → RUNNING', () => {
    expect(transition('PENDING', 'RUNNING')).toBe('RUNNING');
  });

  it('allows RUNNING → all terminal + WAITING_INPUT', () => {
    expect(transition('RUNNING', 'COMPLETED')).toBe('COMPLETED');
    expect(transition('RUNNING', 'FAILED')).toBe('FAILED');
    expect(transition('RUNNING', 'BUDGET_EXHAUSTED')).toBe('BUDGET_EXHAUSTED');
    expect(transition('RUNNING', 'CANCELLED')).toBe('CANCELLED');
    expect(transition('RUNNING', 'WAITING_INPUT')).toBe('WAITING_INPUT');
  });

  it('allows WAITING_INPUT → RUNNING', () => {
    expect(transition('WAITING_INPUT', 'RUNNING')).toBe('RUNNING');
  });

  it('rejects illegal transitions', () => {
    expect(() => transition('PENDING', 'COMPLETED')).toThrow('Illegal transition');
    expect(() => transition('PENDING', 'FAILED')).toThrow('Illegal transition');
  });

  it('rejects transitions from terminal states', () => {
    expect(() => transition('COMPLETED', 'RUNNING')).toThrow('terminal state');
    expect(() => transition('FAILED', 'RUNNING')).toThrow('terminal state');
    expect(() => transition('CANCELLED', 'RUNNING')).toThrow('terminal state');
  });
});

describe('createTaskState', () => {
  it('creates initial state', () => {
    const state = createTaskState();
    expect(state.status).toBe('PENDING');
    expect(state.stepCount).toBe(0);
    expect(state.gpu).toBeUndefined();
    expect(state.startedAt).toBeUndefined();
  });
});
