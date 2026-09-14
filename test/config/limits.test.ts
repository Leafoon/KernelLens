import { describe, expect, it } from 'vitest';
import { MODEL_LIMITS, lookupModelLimit } from '../../src/config/limits.js';

describe('MODEL_LIMITS', () => {
  it('contains at least 8 models', () => {
    expect(MODEL_LIMITS.length).toBeGreaterThanOrEqual(8);
  });

  it('all entries have required fields', () => {
    for (const limit of MODEL_LIMITS) {
      expect(limit.model).toBeTruthy();
      expect(limit.contextWindow).toBeGreaterThan(0);
      expect(limit.maxOutputTokens).toBeGreaterThan(0);
      expect(limit.source).toMatch(/^https?:\/\//);
    }
  });
});

describe('lookupModelLimit', () => {
  it('finds known models', () => {
    const gpt4o = lookupModelLimit('gpt-4o');
    expect(gpt4o).toBeDefined();
    expect(gpt4o!.contextWindow).toBe(128_000);
  });

  it('returns undefined for unknown models', () => {
    expect(lookupModelLimit('nonexistent-model')).toBeUndefined();
  });
});
