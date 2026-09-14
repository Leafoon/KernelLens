import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Workspace, hash } from '../../src/tools/workspace.js';

describe('Workspace', () => {
  let tmpDir: string;
  let workspace: Workspace;

  beforeEach(async () => {
    tmpDir = await mkdtemp(join(tmpdir(), 'kernellens-test-'));
    workspace = new Workspace(tmpDir);
  });

  afterEach(async () => {
    await rm(tmpDir, { recursive: true, force: true });
  });

  describe('hash()', () => {
    it('returns consistent SHA-256', () => {
      const h = hash('hello world');
      expect(h).toMatch(/^[a-f0-9]{64}$/);
      expect(hash('hello world')).toBe(h);
    });

    it('returns different hashes for different inputs', () => {
      expect(hash('a')).not.toBe(hash('b'));
    });
  });

  describe('resolvePath()', () => {
    it('resolves relative paths within workspace', async () => {
      const resolved = await workspace.resolvePath('src/main.py');
      expect(resolved).toContain(tmpDir);
      expect(resolved).toContain('main.py');
    });

    it('resolves absolute paths within workspace', async () => {
      const target = join(tmpDir, 'test.py');
      const resolved = await workspace.resolvePath(target);
      expect(resolved).toBe(target);
    });

    it('rejects path traversal', async () => {
      await expect(workspace.resolvePath('../escape')).rejects.toThrow('outside workspace');
    });

    it('rejects sensitive files', async () => {
      await expect(workspace.resolvePath('.env')).rejects.toThrow('sensitive');
      await expect(workspace.resolvePath('.git/config')).rejects.toThrow('sensitive');
    });
  });

  describe('readFile()', () => {
    it('reads a file with line numbers', async () => {
      await writeFile(join(tmpDir, 'test.py'), 'line1\nline2\nline3');
      const result = await workspace.readFile('test.py');

      expect(result.path).toBe('test.py');
      expect(result.totalLines).toBe(3);
      expect(result.content).toContain('1: line1');
      expect(result.content).toContain('2: line2');
      expect(result.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(result.truncated).toBe(false);
    });

    it('respects start_line and max_lines', async () => {
      const lines = Array.from({ length: 10 }, (_, i) => `line${i + 1}`).join('\n');
      await writeFile(join(tmpDir, 'big.py'), lines);

      const result = await workspace.readFile('big.py', 3, 2);
      expect(result.content).toContain('3: line3');
      expect(result.content).toContain('4: line4');
      expect(result.truncated).toBe(true); // more lines remain
    });

    it('throws for non-existent file', async () => {
      await expect(workspace.readFile('nope.py')).rejects.toThrow();
    });
  });

  describe('writeFile()', () => {
    it('creates a new file', async () => {
      const result = await workspace.writeFile('output/result.py', 'print("hello")');

      expect(result.path).toBe('output/result.py');
      expect(result.sha256).toMatch(/^[a-f0-9]{64}$/);
      expect(result.bytes).toBeGreaterThan(0);

      const content = await readFile(join(tmpDir, 'output/result.py'), 'utf-8');
      expect(content).toBe('print("hello")');
    });

    it('requires sha256 for overwrites', async () => {
      await workspace.writeFile('test.py', 'v1');

      await expect(workspace.writeFile('test.py', 'v2')).rejects.toThrow('expected_sha256');
    });

    it('accepts matching sha256 for overwrites', async () => {
      const first = await workspace.writeFile('test.py', 'v1');
      const second = await workspace.writeFile('test.py', 'v2', first.sha256);

      expect(second.sha256).not.toBe(first.sha256);
      const content = await readFile(join(tmpDir, 'test.py'), 'utf-8');
      expect(content).toBe('v2');
    });

    it('rejects size over 200KB', async () => {
      const big = 'x'.repeat(200_001);
      await expect(workspace.writeFile('big.py', big)).rejects.toThrow('limit');
    });
  });

  describe('listFiles()', () => {
    it('lists files in workspace', async () => {
      await writeFile(join(tmpDir, 'a.py'), '');
      await writeFile(join(tmpDir, 'b.ts'), '');
      await mkdir(join(tmpDir, 'sub'), { recursive: true });
      await writeFile(join(tmpDir, 'sub', 'c.py'), '');

      const result = await workspace.listFiles('.', '*');
      expect(result.files).toContain('a.py');
      expect(result.files).toContain('b.ts');
      expect(result.files.some((f) => f.includes('c.py'))).toBe(true);
    });

    it('filters by pattern', async () => {
      await writeFile(join(tmpDir, 'a.py'), '');
      await writeFile(join(tmpDir, 'b.ts'), '');

      const result = await workspace.listFiles('.', '*.py');
      expect(result.files).toContain('a.py');
      expect(result.files).not.toContain('b.ts');
    });

    it('respects limit', async () => {
      for (let i = 0; i < 5; i++) {
        await writeFile(join(tmpDir, `f${i}.txt`), '');
      }

      const result = await workspace.listFiles('.', '*', 3);
      expect(result.files.length).toBeLessThanOrEqual(3);
    });

    it('skips .git directory', async () => {
      await mkdir(join(tmpDir, '.git'), { recursive: true });
      await writeFile(join(tmpDir, '.git', 'config'), '');
      await writeFile(join(tmpDir, 'safe.py'), '');

      const result = await workspace.listFiles('.');
      expect(result.files).toContain('safe.py');
      expect(result.files.every((f) => !f.includes('.git'))).toBe(true);
    });
  });

  describe('searchText()', () => {
    it('finds literal matches', async () => {
      await writeFile(join(tmpDir, 'a.py'), 'def gemm_kernel():\n    pass\n');
      await writeFile(join(tmpDir, 'b.py'), 'def softmax():\n    pass\n');

      const result = await workspace.searchText('gemm');
      expect(result.matches).toHaveLength(1);
      expect(result.matches[0]!.path).toBe('a.py');
      expect(result.matches[0]!.line).toBe(1);
    });

    it('returns empty for no match', async () => {
      await writeFile(join(tmpDir, 'a.py'), 'hello');
      const result = await workspace.searchText('xyz');
      expect(result.matches).toHaveLength(0);
    });

    it('respects limit', async () => {
      const lines = Array.from({ length: 10 }, () => 'match here').join('\n');
      await writeFile(join(tmpDir, 'a.py'), lines);

      const result = await workspace.searchText('match', '.', '*', 3);
      expect(result.matches.length).toBeLessThanOrEqual(3);
    });
  });
});
