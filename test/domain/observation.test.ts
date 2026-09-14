import { describe, expect, it } from 'vitest';
import { ToolObservation } from '../../src/domain/observation.js';

describe('ToolObservation', () => {
  it('parses a successful observation', () => {
    const obs = ToolObservation.parse({
      tool: 'read_file',
      ok: true,
      output: 'file content here',
      evidenceId: 'E1',
    });
    expect(obs.ok).toBe(true);
    expect(obs.evidenceId).toBe('E1');
  });

  it('parses a failed observation', () => {
    const obs = ToolObservation.parse({
      tool: 'read_file',
      ok: false,
      output: 'File not found',
    });
    expect(obs.ok).toBe(false);
    expect(obs.evidenceId).toBeUndefined();
  });

  it('parses truncated output', () => {
    const obs = ToolObservation.parse({
      tool: 'read_file',
      ok: true,
      output: 'truncated...',
      truncated: true,
    });
    expect(obs.truncated).toBe(true);
  });
});
