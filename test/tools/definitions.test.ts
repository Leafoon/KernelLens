import { describe, expect, it } from 'vitest';
import {
  CompareReportsArgs,
  FinishArgs,
  ListFilesArgs,
  ReadFileArgs,
  ReadKnowledgeArgs,
  SearchKnowledgeArgs,
  SearchTextArgs,
  SetTaskContextArgs,
  WriteFileArgs,
} from '../../src/tools/definitions.js';

describe('ReadFileArgs', () => {
  it('accepts valid input', () => {
    const result = ReadFileArgs.parse({ path: 'src/main.py' });
    expect(result).toEqual({ path: 'src/main.py', start_line: 1, max_lines: 200 });
  });

  it('rejects empty path', () => {
    expect(() => ReadFileArgs.parse({ path: '' })).toThrow();
  });

  it('rejects max_lines > 500', () => {
    expect(() => ReadFileArgs.parse({ path: 'test.py', max_lines: 501 })).toThrow();
  });

  it('rejects start_line < 1', () => {
    expect(() => ReadFileArgs.parse({ path: 'test.py', start_line: 0 })).toThrow();
  });
});

describe('WriteFileArgs', () => {
  it('accepts valid input', () => {
    const result = WriteFileArgs.parse({
      path: 'output/kernel.py',
      content: 'print("hello")',
    });
    expect(result.path).toBe('output/kernel.py');
    expect(result.expected_sha256).toBe('');
  });

  it('accepts valid sha256', () => {
    const sha = 'a'.repeat(64);
    const result = WriteFileArgs.parse({
      path: 'test.py',
      content: 'x',
      expected_sha256: sha,
    });
    expect(result.expected_sha256).toBe(sha);
  });

  it('rejects invalid sha256 format', () => {
    expect(() =>
      WriteFileArgs.parse({
        path: 'test.py',
        content: 'x',
        expected_sha256: 'not-a-hash',
      }),
    ).toThrow();
  });
});

describe('ListFilesArgs', () => {
  it('accepts defaults', () => {
    const result = ListFilesArgs.parse({});
    expect(result).toEqual({ path: '.', pattern: '*', limit: 100 });
  });

  it('rejects limit > 200', () => {
    expect(() => ListFilesArgs.parse({ limit: 201 })).toThrow();
  });
});

describe('SearchTextArgs', () => {
  it('accepts valid query', () => {
    const result = SearchTextArgs.parse({ query: 'def gemm_kernel' });
    expect(result.query).toBe('def gemm_kernel');
  });

  it('rejects empty query', () => {
    expect(() => SearchTextArgs.parse({ query: '' })).toThrow();
  });
});

describe('SearchKnowledgeArgs', () => {
  it('accepts valid input', () => {
    const result = SearchKnowledgeArgs.parse({ query: 'How to use T.gemm?' });
    expect(result.index).toBe('auto');
    expect(result.top_k).toBe(5);
  });

  it('rejects invalid index', () => {
    expect(() => SearchKnowledgeArgs.parse({ query: 'test', index: 'invalid' })).toThrow();
  });

  it('rejects top_k > 10', () => {
    expect(() => SearchKnowledgeArgs.parse({ query: 'test', top_k: 11 })).toThrow();
  });
});

describe('ReadKnowledgeArgs', () => {
  it('accepts valid unit_id', () => {
    const id = `K${'a'.repeat(16)}`;
    const result = ReadKnowledgeArgs.parse({ unit_id: id });
    expect(result.unit_id).toBe(id);
  });

  it('rejects invalid unit_id format', () => {
    expect(() => ReadKnowledgeArgs.parse({ unit_id: 'invalid' })).toThrow();
    expect(() => ReadKnowledgeArgs.parse({ unit_id: 'K123' })).toThrow();
  });
});

describe('SetTaskContextArgs', () => {
  it('accepts valid input', () => {
    const result = SetTaskContextArgs.parse({
      task_type: 'generate',
      gpu_model: 'NVIDIA A100',
      reason: 'User wants to generate a new kernel',
    });
    expect(result.task_type).toBe('generate');
  });

  it('rejects invalid task_type', () => {
    expect(() => SetTaskContextArgs.parse({ task_type: 'invalid', reason: 'test' })).toThrow();
  });
});

describe('FinishArgs', () => {
  it('accepts valid input', () => {
    const result = FinishArgs.parse({ answer: 'Here is your kernel.', reason: 'Task complete' });
    expect(result.answer).toBe('Here is your kernel.');
  });

  it('rejects empty answer', () => {
    expect(() => FinishArgs.parse({ answer: '', reason: 'done' })).toThrow();
  });
});

describe('CompareReportsArgs', () => {
  it('accepts valid input', () => {
    const result = CompareReportsArgs.parse({
      baseline_path: 'reports/baseline.json',
      candidate_path: 'reports/candidate.json',
    });
    expect(result.baseline_path).toBe('reports/baseline.json');
  });
});
