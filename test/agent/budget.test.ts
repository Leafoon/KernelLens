import { describe, expect, it } from 'vitest';
import { consume, createDecisionBudget } from '../../src/agent/budget.js';
import { BudgetExhaustedError } from '../../src/exceptions.js';

describe('DecisionBudget', () => {
  it('creates with correct initial state', () => {
    const budget = createDecisionBudget(10);
    expect(budget.current).toBe(0);
    expect(budget.max).toBe(10);
    expect(budget.remaining).toBe(10);
    expect(budget.exhausted).toBe(false);
  });

  it('consume increments count and returns new budget', () => {
    const initial = createDecisionBudget(3);
    const step1 = consume(initial);
    expect(step1.current).toBe(1);
    expect(step1.remaining).toBe(2);
    expect(step1.exhausted).toBe(false);

    const step2 = consume(step1);
    expect(step2.current).toBe(2);
    expect(step2.remaining).toBe(1);

    const step3 = consume(step2);
    expect(step3.current).toBe(3);
    expect(step3.remaining).toBe(0);
    expect(step3.exhausted).toBe(true);
  });

  it('consume does not mutate original', () => {
    const initial = createDecisionBudget(5);
    consume(initial);
    expect(initial.current).toBe(0);
    expect(initial.remaining).toBe(5);
  });

  it('throws when budget exhausted', () => {
    const budget = createDecisionBudget(1);
    const used = consume(budget);
    expect(() => consume(used)).toThrow(BudgetExhaustedError);
  });

  it('exhausted error includes max decisions', () => {
    const budget = createDecisionBudget(5);
    let current = budget;
    for (let i = 0; i < 5; i++) {
      current = consume(current);
    }
    try {
      consume(current);
      expect.unreachable('Should have thrown');
    } catch (e) {
      expect(e).toBeInstanceOf(BudgetExhaustedError);
      expect((e as BudgetExhaustedError).maxDecisions).toBe(5);
    }
  });
});
