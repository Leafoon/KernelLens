import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { resolveSafePath } from '../../src/security/path-safety.js';

describe('resolveSafePath', () => {
  let workspace: string;

  beforeEach(() => {
    workspace = mkdtempSync(join(tmpdir(), 'kl-path-test-'));
    mkdirSync(join(workspace, 'src'), { recursive: true });
    writeFileSync(join(workspace, 'src', 'kernel.py'), 'print("hello")');
  });

  afterEach(() => {
    rmSync(workspace, { recursive: true, force: true });
  });

  it('resolves valid paths within workspace', () => {
    const result = resolveSafePath('src/kernel.py', workspace);
    expect(result).toContain('kernel.py');
    expect(result).toContain(workspace);
  });

  it('rejects path traversal', () => {
    expect(() => resolveSafePath('../etc/passwd', workspace)).toThrow('escapes workspace');
  });

  it('rejects absolute paths outside workspace', () => {
    expect(() => resolveSafePath('/etc/passwd', workspace)).toThrow('escapes workspace');
  });

  it('rejects .env files', () => {
    writeFileSync(join(workspace, '.env'), 'KEY=value');
    expect(() => resolveSafePath('.env', workspace)).toThrow('sensitive file');
  });

  it('rejects .git access', () => {
    expect(() => resolveSafePath('.git/config', workspace)).toThrow('sensitive file');
  });

  it('rejects .ssh access', () => {
    expect(() => resolveSafePath('.ssh/id_rsa', workspace)).toThrow('sensitive file');
  });

  it('allows normal kernel files', () => {
    writeFileSync(join(workspace, 'gemm.cu'), 'kernel code');
    const result = resolveSafePath('gemm.cu', workspace);
    expect(result).toContain('gemm.cu');
  });

  it('allows nested paths', () => {
    const result = resolveSafePath('src/subdir/file.py', workspace);
    expect(result).toContain('file.py');
  });
});
