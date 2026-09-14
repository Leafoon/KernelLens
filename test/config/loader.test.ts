import { mkdtempSync, unlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { loadSettings, parseDotEnv } from '../../src/config/loader.js';

describe('parseDotEnv', () => {
  it('parses key=value pairs', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kl-test-'));
    const file = join(dir, '.env');
    writeFileSync(file, 'API_KEY=sk-test123\nMODEL=gpt-4o\n');

    const result = parseDotEnv(file);
    expect(result.API_KEY).toBe('sk-test123');
    expect(result.MODEL).toBe('gpt-4o');

    unlinkSync(file);
  });

  it('strips surrounding quotes', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kl-test-'));
    const file = join(dir, '.env');
    writeFileSync(file, `KEY1="double"\nKEY2='single'\n`);

    const result = parseDotEnv(file);
    expect(result.KEY1).toBe('double');
    expect(result.KEY2).toBe('single');

    unlinkSync(file);
  });

  it('skips comments and blank lines', () => {
    const dir = mkdtempSync(join(tmpdir(), 'kl-test-'));
    const file = join(dir, '.env');
    writeFileSync(file, '# comment\n\nKEY=value\n');

    const result = parseDotEnv(file);
    expect(Object.keys(result)).toEqual(['KEY']);

    unlinkSync(file);
  });

  it('returns empty object for missing file', () => {
    const result = parseDotEnv('/nonexistent/.env');
    expect(result).toEqual({});
  });
});

describe('loadSettings', () => {
  const originalEnv = { ...process.env };

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it('throws if no API key is set', () => {
    process.env.KERNELLENS_API_KEY = '';
    process.env.OPENAI_API_KEY = '';
    expect(() => loadSettings()).toThrow('API key not found');
  });

  it('loads settings from env vars', () => {
    process.env.KERNELLENS_API_KEY = 'sk-test-key-12345678';
    process.env.KERNELLENS_MODEL = 'gpt-4o';
    process.env.KERNELLENS_BASE_URL = 'https://api.openai.com/v1';

    const settings = loadSettings();
    expect(settings.model.apiKey).toBe('sk-test-key-12345678');
    expect(settings.model.model).toBe('gpt-4o');
    expect(settings.runtime.maxDecisions).toBe(30);
  });

  it('uses default values for optional fields', () => {
    process.env.KERNELLENS_API_KEY = 'sk-test-1234';

    // Pass non-existent path to skip auto-discovery of .env in cwd
    const settings = loadSettings('/tmp/nonexistent-env-file');
    expect(settings.model.baseUrl).toBe('https://api.openai.com/v1');
    expect(settings.runtime.logLevel).toBe('info');
    expect(settings.runtime.workspace).toBe('.');
  });
});
