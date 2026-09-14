import { describe, expect, it, vi } from 'vitest';
import { applyCallTool, applyFinish, applyRequestInput } from '../../src/agent/handlers.js';
import type { CallToolAction, FinishAction, RequestInputAction } from '../../src/domain/action.js';
import { FinishRejectedError } from '../../src/exceptions.js';
import { ReportReviewer } from '../../src/review/reviewer.js';
import type { ToolRegistry } from '../../src/tools/registry.js';

describe('action handlers', () => {
  describe('applyRequestInput', () => {
    it('returns WAITING_INPUT status', () => {
      const action: RequestInputAction = { type: 'request_input', prompt: 'What GPU?' };
      const result = applyRequestInput(action);

      expect(result.action).toBe(action);
      expect(result.status).toBe('WAITING_INPUT');
      expect(result.observation).toBeUndefined();
      expect(result.error).toBeUndefined();
    });
  });

  describe('applyFinish', () => {
    const reviewer = new ReportReviewer();

    it('returns COMPLETED when review passes', async () => {
      const action: FinishAction = {
        type: 'finish',
        answer: 'Generated kernel at artifacts/gemm.py',
      };
      const result = await applyFinish(action, reviewer, new Set());

      expect(result.status).toBe('COMPLETED');
      expect(result.action).toBe(action);
    });

    it('throws FinishRejectedError when review fails', async () => {
      const action: FinishAction = { type: 'finish', answer: 'See [E5] for details' };
      const evidenceIds = new Set(['E1', 'E2']);

      await expect(applyFinish(action, reviewer, evidenceIds)).rejects.toThrow(FinishRejectedError);
    });

    it('throws FinishRejectedError for empty answer', async () => {
      const action: FinishAction = { type: 'finish', answer: '   ' };
      await expect(applyFinish(action, reviewer, new Set())).rejects.toThrow(FinishRejectedError);
    });

    it('accepts answer with valid evidence IDs', async () => {
      const action: FinishAction = { type: 'finish', answer: 'Result based on [E1] and [E2]' };
      const evidenceIds = new Set(['E1', 'E2', 'E3']);
      const result = await applyFinish(action, reviewer, evidenceIds);

      expect(result.status).toBe('COMPLETED');
    });

    it('rejects answer with invalid evidence ID', async () => {
      const action: FinishAction = { type: 'finish', answer: 'Based on [E99]' };
      const evidenceIds = new Set(['E1']);

      try {
        await applyFinish(action, reviewer, evidenceIds);
        expect.fail('Should have thrown');
      } catch (error) {
        expect(error).toBeInstanceOf(FinishRejectedError);
        expect((error as FinishRejectedError).reasons).toEqual(
          expect.arrayContaining([expect.stringContaining('E99')]),
        );
      }
    });
  });

  describe('applyCallTool', () => {
    it('dispatches to registry and returns observation', async () => {
      const mockObservation = {
        tool: 'read_file',
        ok: true,
        output: '{"content": "hello"}',
        evidenceId: 'E1',
        truncated: false,
      };
      const registry = {
        execute: vi.fn().mockResolvedValue(mockObservation),
      } as unknown as ToolRegistry;

      const action: CallToolAction = {
        type: 'call_tool',
        tool: 'read_file',
        arguments: { path: 'test.py' },
      };

      const result = await applyCallTool(action, registry);

      expect(result.status).toBe('RUNNING');
      expect(result.observation).toBe(mockObservation);
      expect(registry.execute).toHaveBeenCalledWith(action);
    });

    it('returns error observation when registry throws', async () => {
      const mockObservation = {
        tool: 'read_file',
        ok: false,
        output: '{"error": "not_found"}',
        evidenceId: undefined,
        truncated: false,
      };
      const registry = {
        execute: vi.fn().mockResolvedValue(mockObservation),
      } as unknown as ToolRegistry;

      const action: CallToolAction = {
        type: 'call_tool',
        tool: 'read_file',
        arguments: { path: 'missing.py' },
      };

      const result = await applyCallTool(action, registry);

      expect(result.status).toBe('RUNNING');
      expect(result.observation!.ok).toBe(false);
    });
  });
});

describe('ReportReviewer', () => {
  const reviewer = new ReportReviewer();

  it('passes for non-empty answer with no citations', () => {
    expect(reviewer.review('Done', new Set())).toEqual([]);
  });

  it('rejects empty answer', () => {
    const reasons = reviewer.review('', new Set());
    expect(reasons.length).toBeGreaterThan(0);
    expect(reasons[0]).toContain('empty');
  });

  it('rejects whitespace-only answer', () => {
    const reasons = reviewer.review('   \n\t  ', new Set());
    expect(reasons.length).toBeGreaterThan(0);
  });

  it('passes when cited evidence IDs exist', () => {
    const reasons = reviewer.review('Based on [E1] and [E2]', new Set(['E1', 'E2', 'E3']));
    expect(reasons).toEqual([]);
  });

  it('rejects when cited evidence ID does not exist', () => {
    const reasons = reviewer.review('See [E5]', new Set(['E1', 'E2']));
    expect(reasons.length).toBe(1);
    expect(reasons[0]).toContain('E5');
  });

  it('rejects multiple invalid evidence IDs', () => {
    const reasons = reviewer.review('See [E5] and [E99]', new Set(['E1']));
    expect(reasons.length).toBe(2);
  });

  it('handles mixed valid and invalid evidence IDs', () => {
    const reasons = reviewer.review('[E1] is ok but [E99] is not', new Set(['E1']));
    expect(reasons.length).toBe(1);
    expect(reasons[0]).toContain('E99');
  });

  it('does not treat non-E-number brackets as evidence', () => {
    const reasons = reviewer.review('Output [1] and [2] are valid', new Set());
    expect(reasons).toEqual([]);
  });
});
