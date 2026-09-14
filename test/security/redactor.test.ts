import { describe, expect, it } from 'vitest';
import { collectSecretsFromEnv, createRedactor } from '../../src/security/redactor.js';

describe('createRedactor', () => {
  it('redacts registered secrets', () => {
    const redact = createRedactor(['sk-my-secret-key-12345']);
    const result = redact('Using key sk-my-secret-key-12345 here');
    expect(result).toBe('Using key [REDACTED] here');
    expect(result).not.toContain('sk-my-secret-key');
  });

  it('redacts Bearer tokens', () => {
    const redact = createRedactor([]);
    const result = redact('Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.signature');
    expect(result).toContain('[REDACTED]');
    expect(result).not.toContain('eyJhbGciOiJIUzI1NiJ9');
  });

  it('redacts OpenAI-style keys', () => {
    const redact = createRedactor([]);
    const result = redact('Key is sk-abcdefghijklmnopqrstuvwxyz123456');
    expect(result).toContain('[REDACTED]');
    expect(result).not.toContain('sk-abcdef');
  });

  it('ignores short strings', () => {
    const redact = createRedactor(['ab']);
    const result = redact('Contains ab in text');
    expect(result).toBe('Contains ab in text');
  });

  it('handles multiple secrets', () => {
    const redact = createRedactor(['secret-one-12345', 'secret-two-67890']);
    const result = redact('Using secret-one-12345 and secret-two-67890');
    expect(result).not.toContain('secret-one');
    expect(result).not.toContain('secret-two');
  });
});

describe('collectSecretsFromEnv', () => {
  it('collects values matching secret patterns', () => {
    const env = {
      MY_API_KEY: 'sk-test-12345',
      SOME_SECRET: 'super-secret-value',
      NORMAL_VAR: 'not-a-secret',
    };
    const secrets = collectSecretsFromEnv(env);
    expect(secrets).toContain('sk-test-12345');
    expect(secrets).toContain('super-secret-value');
    expect(secrets).not.toContain('not-a-secret');
  });

  it('skips empty values', () => {
    const env = { EMPTY_KEY: '' };
    const secrets = collectSecretsFromEnv(env);
    expect(secrets).toHaveLength(0);
  });
});
