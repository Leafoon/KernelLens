import { describe, expect, it } from 'vitest';
import { families, route, tokenize } from '../../src/knowledge/terms.js';

describe('tokenize()', () => {
  it('extracts ASCII tokens', () => {
    const tokens = tokenize('How to use T.gemm for matrix multiplication');
    expect(tokens).toContain('gemm');
    expect(tokens).toContain('matrix');
    expect(tokens).toContain('multiplication');
  });

  it('expands Chinese terms', () => {
    const tokens = tokenize('如何使用矩阵乘');
    expect(tokens).toContain('gemm');
    expect(tokens).toContain('matmul');
  });

  it('splits CamelCase', () => {
    const tokens = tokenize('FlashAttention kernel');
    expect(tokens).toContain('flash');
    expect(tokens).toContain('attention');
  });

  it('removes stop words', () => {
    const tokens = tokenize('the quick brown fox');
    expect(tokens).not.toContain('the');
    expect(tokens).not.toContain('a');
  });

  it('deduplicates tokens', () => {
    const tokens = tokenize('gemm gemm gemm');
    const gemmCount = tokens.filter((t) => t === 'gemm').length;
    expect(gemmCount).toBe(1);
  });
});

describe('families()', () => {
  it('detects gemm family', () => {
    expect(families('T.gemm matmul kernel')).toContain('gemm');
  });

  it('detects attention family', () => {
    expect(families('FlashAttention implementation')).toContain('attention');
  });

  it('detects reduction family', () => {
    expect(families('softmax reduction')).toContain('reduction');
  });

  it('returns empty for unrelated text', () => {
    expect(families('hello world')).toEqual([]);
  });

  it('detects multiple families', () => {
    const result = families('attention with gemm and softmax');
    expect(result).toContain('attention');
    expect(result).toContain('gemm');
    expect(result).toContain('reduction');
  });
});

describe('route()', () => {
  it('routes compiler errors', () => {
    const result = route('tilelang compilation error: unsupported lowering');
    expect(result.intent).toBe('compiler');
    expect(result.selected).toContain('compiler');
  });

  it('routes generation requests', () => {
    const result = route('Generate a CUDA kernel for matrix multiplication');
    expect(result.intent).toBe('operator');
    expect(result.selected).toContain('operator');
    expect(result.selected).toContain('example');
  });

  it('routes API queries', () => {
    const result = route('What does T.gemm do?');
    expect(result.intent).toBe('api');
    expect(result.symbols.length).toBeGreaterThan(0);
  });

  it('routes target queries', () => {
    const result = route('How to target CUDA backend?');
    expect(result.intent).toBe('target');
  });

  it('routes example queries', () => {
    const result = route('Show me an example of tilelang');
    expect(result.intent).toBe('example');
  });

  it('defaults to concept', () => {
    const result = route('What is tilelang?');
    expect(result.intent).toBe('concept');
  });

  it('extracts TileLang API symbols', () => {
    const result = route('How to use T.gemm and T.alloc_fragment?');
    expect(result.symbols).toContain('T.gemm');
    expect(result.symbols).toContain('T.alloc_fragment');
  });
});
