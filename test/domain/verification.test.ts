import { describe, expect, it } from 'vitest';
import {
  VerificationResult,
  VerificationState,
  createVerificationState,
} from '../../src/domain/verification.js';

describe('VerificationResult', () => {
  it('accepts all valid results', () => {
    expect(VerificationResult.parse('not_run')).toBe('not_run');
    expect(VerificationResult.parse('passed')).toBe('passed');
    expect(VerificationResult.parse('failed')).toBe('failed');
    expect(VerificationResult.parse('inconclusive')).toBe('inconclusive');
  });

  it('rejects invalid result', () => {
    expect(() => VerificationResult.parse('unknown')).toThrow();
  });
});

describe('createVerificationState', () => {
  it('creates default state with all dimensions not_run', () => {
    const state = createVerificationState();
    expect(state.syntax).toBe('not_run');
    expect(state.api).toBe('not_run');
    expect(state.compilation).toBe('not_run');
    expect(state.correctness).toBe('not_run');
    expect(state.performance).toBe('not_run');
  });

  it('is a valid VerificationState', () => {
    const state = createVerificationState();
    expect(() => VerificationState.parse(state)).not.toThrow();
  });
});
