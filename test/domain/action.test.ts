import { describe, expect, it } from 'vitest';
import {
  AgentAction,
  CallToolAction,
  FinishAction,
  RequestInputAction,
} from '../../src/domain/action.js';

describe('CallToolAction', () => {
  it('parses valid action', () => {
    const action = CallToolAction.parse({
      type: 'call_tool',
      tool: 'read_file',
      arguments: { path: 'kernel.py' },
    });
    expect(action.type).toBe('call_tool');
    expect(action.tool).toBe('read_file');
  });

  it('rejects empty tool name', () => {
    expect(() => CallToolAction.parse({ type: 'call_tool', tool: '', arguments: {} })).toThrow();
  });
});

describe('FinishAction', () => {
  it('parses valid action', () => {
    const action = FinishAction.parse({ type: 'finish', answer: 'Here is the kernel.' });
    expect(action.type).toBe('finish');
    expect(action.answer).toBe('Here is the kernel.');
  });

  it('rejects empty answer', () => {
    expect(() => FinishAction.parse({ type: 'finish', answer: '' })).toThrow();
  });
});

describe('RequestInputAction', () => {
  it('parses valid action', () => {
    const action = RequestInputAction.parse({
      type: 'request_input',
      prompt: 'Which GPU?',
    });
    expect(action.type).toBe('request_input');
  });
});

describe('AgentAction discriminated union', () => {
  it('parses call_tool', () => {
    const action = AgentAction.parse({
      type: 'call_tool',
      tool: 'search_knowledge',
      arguments: { query: 'GEMM' },
    });
    expect(action.type).toBe('call_tool');
  });

  it('parses finish', () => {
    const action = AgentAction.parse({ type: 'finish', answer: 'Done.' });
    expect(action.type).toBe('finish');
  });

  it('parses request_input', () => {
    const action = AgentAction.parse({ type: 'request_input', prompt: 'Info needed.' });
    expect(action.type).toBe('request_input');
  });

  it('rejects unknown type', () => {
    expect(() => AgentAction.parse({ type: 'unknown', data: 'x' })).toThrow();
  });
});
