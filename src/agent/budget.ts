/**
 * Decision budget — immutable counter for agent loop steps.
 *
 * Each call to `consume()` returns a new Budget with an incremented count,
 * preserving the original. When the budget is exhausted, `consume()` throws.
 */

import { BudgetExhaustedError } from '../exceptions.js';

export interface DecisionBudget {
  readonly current: number;
  readonly max: number;
  readonly remaining: number;
  readonly exhausted: boolean;
}

export function createDecisionBudget(max: number): DecisionBudget {
  return {
    current: 0,
    max,
    get remaining() {
      return max;
    },
    get exhausted() {
      return false;
    },
  };
}

/**
 * Consume one step of the budget. Returns a new budget with count + 1.
 * Throws BudgetExhaustedError if no steps remain.
 */
export function consume(budget: DecisionBudget): DecisionBudget {
  if (budget.current >= budget.max) {
    throw new BudgetExhaustedError(budget.max);
  }
  const newCurrent = budget.current + 1;
  return {
    current: newCurrent,
    max: budget.max,
    get remaining() {
      return budget.max - newCurrent;
    },
    get exhausted() {
      return newCurrent >= budget.max;
    },
  };
}
