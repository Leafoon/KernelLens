import { describe, expect, it } from 'vitest';
import { TaskRequest, TaskType } from '../../src/domain/task.js';

describe('TaskType', () => {
  it('accepts valid types', () => {
    expect(TaskType.parse('generate')).toBe('generate');
    expect(TaskType.parse('optimize')).toBe('optimize');
    expect(TaskType.parse('diagnose')).toBe('diagnose');
  });

  it('rejects invalid types', () => {
    expect(() => TaskType.parse('unknown')).toThrow();
    expect(() => TaskType.parse('')).toThrow();
  });
});

describe('TaskRequest', () => {
  it('parses a minimal request', () => {
    const req = TaskRequest.parse({ type: 'generate', goal: 'build GEMM' });
    expect(req.type).toBe('generate');
    expect(req.goal).toBe('build GEMM');
    expect(req.gpu).toBeUndefined();
  });

  it('parses a full request', () => {
    const req = TaskRequest.parse({
      type: 'optimize',
      goal: 'optimize GEMM M=N=K=256',
      gpu: 'A100',
      backend: 'cuda',
    });
    expect(req.gpu).toBe('A100');
    expect(req.backend).toBe('cuda');
  });

  it('rejects empty goal', () => {
    expect(() => TaskRequest.parse({ type: 'generate', goal: '' })).toThrow();
  });

  it('rejects missing type', () => {
    expect(() => TaskRequest.parse({ goal: 'build GEMM' })).toThrow();
  });
});
