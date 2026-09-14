import type { ChatCompletionMessageParam } from 'openai/resources/chat/completions';
import { describe, expect, it } from 'vitest';
import { ContextWindow, TokenMeter, approximateTokens } from '../../src/models/context.js';

// ── approximateTokens ──────────────────────────────────────────────────────────

describe('approximateTokens', () => {
  it('estimates ASCII text at ~4 chars per token', () => {
    const tokens = approximateTokens('hello world');
    // 11 chars → ~3 tokens (11/4 ≈ 2.75, ceil = 3)
    expect(tokens).toBeGreaterThanOrEqual(2);
    expect(tokens).toBeLessThanOrEqual(4);
  });

  it('estimates non-ASCII text at higher rate', () => {
    const ascii = approximateTokens('abcd'); // 4 ASCII chars
    const nonAscii = approximateTokens('你好世界'); // 4 non-ASCII chars
    expect(nonAscii).toBeGreaterThan(ascii);
  });

  it('handles empty string', () => {
    expect(approximateTokens('')).toBe(1); // Math.max(1, ...)
  });

  it('handles objects by JSON-serializing them', () => {
    const tokens = approximateTokens({ key: 'value' });
    expect(tokens).toBeGreaterThan(0);
  });

  it('handles arrays', () => {
    const tokens = approximateTokens([1, 2, 3]);
    expect(tokens).toBeGreaterThan(0);
  });
});

// ── TokenMeter ─────────────────────────────────────────────────────────────────

describe('TokenMeter', () => {
  const messages: ChatCompletionMessageParam[] = [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Hello, how are you?' },
  ];

  it('starts with ratio 1.0', () => {
    const meter = new TokenMeter();
    expect(meter.ratio).toBe(1.0);
    expect(meter.lastPromptTokens).toBeUndefined();
  });

  it('estimate() returns a positive number', () => {
    const meter = new TokenMeter();
    const estimate = meter.estimate(messages);
    expect(estimate).toBeGreaterThan(0);
  });

  it('estimate() includes tool overhead', () => {
    const meter = new TokenMeter();
    const withoutTools = meter.estimate(messages);
    const withTools = meter.estimate(messages, [{ name: 'test_tool' }]);
    // Tools add tokens to the estimate
    expect(withTools).toBeGreaterThanOrEqual(withoutTools);
  });

  it('raw() returns uncalibrated estimate', () => {
    const meter = new TokenMeter();
    const raw = meter.raw(messages);
    const estimate = meter.estimate(messages);
    // With ratio 1.0, estimate = ceil(raw * 1.0)
    expect(estimate).toBe(Math.ceil(raw));
  });

  it('observe() calibrates the ratio', () => {
    const meter = new TokenMeter();
    const raw = meter.raw(messages);

    // Simulate the provider reporting 2x the raw estimate
    const actualPromptTokens = raw * 2;
    meter.observe(messages, [], actualPromptTokens);

    expect(meter.lastPromptTokens).toBe(actualPromptTokens);
    expect(meter.ratio).toBeCloseTo(2.0, 1);
  });

  it('observe() clamps ratio to [0.5, 4.0]', () => {
    const meter = new TokenMeter();
    const raw = meter.raw(messages);

    // Try to set ratio to 10.0 (should be clamped to 4.0)
    // Use integer promptTokens to pass the Number.isInteger check
    meter.observe(messages, [], raw * 10);
    expect(meter.ratio).toBe(4.0);

    // Try to set ratio to 0.1 (should be clamped to 0.5)
    // Use an integer that gives ratio < 0.5: raw * 0.1 is likely non-integer
    // so use 1 (which is < raw * 0.5 for any raw > 2)
    meter.observe(messages, [], 1);
    expect(meter.ratio).toBe(0.5);
  });

  it('observe() ignores invalid promptTokens', () => {
    const meter = new TokenMeter();
    const originalRatio = meter.ratio;

    // Negative value
    meter.observe(messages, [], -1);
    expect(meter.ratio).toBe(originalRatio);
    expect(meter.lastPromptTokens).toBeUndefined();

    // Non-integer
    meter.observe(messages, [], 3.14);
    expect(meter.lastPromptTokens).toBeUndefined();

    // undefined
    meter.observe(messages, [], undefined);
    expect(meter.lastPromptTokens).toBeUndefined();
  });
});

// ── ContextWindow ──────────────────────────────────────────────────────────────

describe('ContextWindow', () => {
  function makeProvider(contextWindow: number, maxOutputTokens: number) {
    return {
      model: 'test-model',
      contextWindow,
      maxOutputTokens,
      complete: async () => ({
        message: { role: 'assistant' as const, content: 'ok' },
        finishReason: 'stop',
      }),
    };
  }

  const messages: ChatCompletionMessageParam[] = [
    { role: 'system', content: 'You are a helpful assistant.' },
    { role: 'user', content: 'Hello' },
  ];

  it('limit reserves space for output tokens and margin', () => {
    const provider = makeProvider(128_000, 4_096);
    const meter = new TokenMeter();
    const window = new ContextWindow(provider, meter);

    // limit = 128000 - 4096 - max(1024, 128000/8)
    // = 128000 - 4096 - 16000 = 107904
    expect(window.limit).toBeLessThan(provider.contextWindow);
    expect(window.limit).toBeGreaterThan(0);
  });

  it('fits() returns true for small messages', () => {
    const provider = makeProvider(128_000, 4_096);
    const meter = new TokenMeter();
    const window = new ContextWindow(provider, meter);

    expect(window.fits(messages)).toBe(true);
  });

  it('fits() returns false when messages exceed limit', () => {
    // Tiny context window: 100 tokens
    const provider = makeProvider(100, 50);
    const meter = new TokenMeter();
    const window = new ContextWindow(provider, meter);

    // With a 100-token window and 50 output tokens, limit is very small
    // A real conversation should exceed it
    const bigMessages: ChatCompletionMessageParam[] = [
      { role: 'system', content: 'You are a helpful assistant.' },
      { role: 'user', content: 'a'.repeat(2000) },
    ];
    expect(window.fits(bigMessages)).toBe(false);
  });

  it('snapshot() returns current state', () => {
    const provider = makeProvider(128_000, 4_096);
    const meter = new TokenMeter();
    const window = new ContextWindow(provider, meter);

    window.fits(messages);
    const snap = window.snapshot();

    expect(snap).toEqual({
      summary: '',
      compactions: 0,
      estimatedTokens: expect.any(Number),
    });
    expect(snap.estimatedTokens).toBeGreaterThan(0);
  });

  it('restores from saved context', () => {
    const provider = makeProvider(128_000, 4_096);
    const meter = new TokenMeter();
    const window = new ContextWindow(provider, meter, {
      summary: 'Previous summary',
      compactions: 3,
    });

    expect(window.summary).toBe('Previous summary');
    expect(window.compactions).toBe(3);
  });

  it('estimatedTokens updates after fits()', () => {
    const provider = makeProvider(128_000, 4_096);
    const meter = new TokenMeter();
    const window = new ContextWindow(provider, meter);

    expect(window.estimatedTokens).toBe(0);
    window.fits(messages);
    expect(window.estimatedTokens).toBeGreaterThan(0);
  });
});
