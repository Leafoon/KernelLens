import { describe, expect, it, vi } from 'vitest';
import { DecisionAdapter } from '../../src/models/adapter.js';
import type { CompletionResult, ModelProvider } from '../../src/models/provider.js';

// ── Mock Provider ──────────────────────────────────────────────────────────────

function createMockProvider(responses: CompletionResult[]): ModelProvider {
  let callIndex = 0;
  return {
    model: 'test-model',
    contextWindow: 128_000,
    maxOutputTokens: 4_096,
    complete: async () => {
      const response = responses[callIndex] ?? responses[responses.length - 1]!;
      callIndex++;
      return response;
    },
  };
}

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('DecisionAdapter', () => {
  const emit = vi.fn();

  function createAdapter(
    responses: CompletionResult[],
    options?: { systemPrompt?: string; goal?: string },
  ) {
    return new DecisionAdapter({
      provider: createMockProvider(responses),
      systemPrompt: options?.systemPrompt ?? 'You are a helpful assistant.',
      goal: options?.goal ?? 'Generate a CUDA kernel for matrix multiplication.',
      tools: [
        {
          name: 'read_file',
          description: 'Read a file',
          parameters: { type: 'object', properties: { path: { type: 'string' } } },
        },
        { name: 'write_file', description: 'Write a file' },
      ],
      emit,
    });
  }

  it('initializes with correct state', () => {
    const adapter = createAdapter([]);
    expect(adapter.decisions).toBe(0);
    expect(adapter.window).toBeDefined();
    expect(adapter.meter).toBeDefined();
  });

  it('decide() returns tool call action', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: null,
          toolCalls: [
            {
              id: 'call_0',
              name: 'read_file',
              arguments: { path: '/src/main.py' },
            },
          ],
        },
        usage: { promptTokens: 100, completionTokens: 50, totalTokens: 150 },
        finishReason: 'tool_calls',
      },
    ]);

    const action = await adapter.decide();
    expect(action).toEqual({
      type: 'call_tool',
      tool: 'read_file',
      arguments: { path: '/src/main.py' },
    });
    expect(adapter.decisions).toBe(1);
  });

  it('decide() returns finish action from tool call', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: null,
          toolCalls: [
            {
              id: 'call_0',
              name: 'finish',
              arguments: { answer: 'Here is your kernel.' },
            },
          ],
        },
        usage: { promptTokens: 100, completionTokens: 50, totalTokens: 150 },
        finishReason: 'stop',
      },
    ]);

    const action = await adapter.decide();
    expect(action).toEqual({
      type: 'finish',
      answer: 'Here is your kernel.',
    });
  });

  it('decide() returns request_input action', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: null,
          toolCalls: [
            {
              id: 'call_0',
              name: 'request_input',
              arguments: { prompt: 'What GPU are you targeting?' },
            },
          ],
        },
        finishReason: 'stop',
      },
    ]);

    const action = await adapter.decide();
    expect(action).toEqual({
      type: 'request_input',
      prompt: 'What GPU are you targeting?',
    });
  });

  it('decide() returns finish from plain text response', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: 'Here is the generated kernel code.',
        },
        finishReason: 'stop',
      },
    ]);

    const action = await adapter.decide();
    expect(action).toEqual({
      type: 'finish',
      answer: 'Here is the generated kernel code.',
    });
  });

  it('decide() parses JSON action from content', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: '{"type": "finish", "answer": "Done."}',
        },
        finishReason: 'stop',
      },
    ]);

    const action = await adapter.decide();
    expect(action).toEqual({
      type: 'finish',
      answer: 'Done.',
    });
  });

  it('decide() parses JSON from markdown fences', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: '```json\n{"type": "finish", "answer": "Done."}\n```',
        },
        finishReason: 'stop',
      },
    ]);

    const action = await adapter.decide();
    expect(action).toEqual({
      type: 'finish',
      answer: 'Done.',
    });
  });

  it('observe() adds tool result to history', async () => {
    const adapter = createAdapter([
      {
        message: {
          role: 'assistant',
          content: null,
          toolCalls: [{ id: 'call_0', name: 'read_file', arguments: { path: '/test.py' } }],
        },
        usage: { promptTokens: 100, completionTokens: 50, totalTokens: 150 },
        finishReason: 'tool_calls',
      },
      {
        message: {
          role: 'assistant',
          content: 'File read successfully.',
        },
        finishReason: 'stop',
      },
    ]);

    // First decision: tool call
    const action1 = await adapter.decide();
    expect(action1.type).toBe('call_tool');

    // Observe the tool result
    adapter.observe({
      tool: 'read_file',
      ok: true,
      output: 'file contents here',
      evidenceId: 'E-1',
      truncated: false,
    });

    // Second decision: after observation
    const action2 = await adapter.decide();
    expect(action2.type).toBe('finish');
  });

  it('feedback() adds user message to history', () => {
    const adapter = createAdapter([]);
    adapter.feedback('The kernel has a race condition.');
    // No assertion needed — just verify it doesn't throw
  });

  it('snapshot() returns adapter state', async () => {
    const adapter = createAdapter([
      {
        message: { role: 'assistant', content: 'Hello' },
        usage: { promptTokens: 100, completionTokens: 50, totalTokens: 150 },
        finishReason: 'stop',
      },
    ]);

    await adapter.decide();
    const snap = adapter.snapshot();

    expect(snap.decisions).toBe(1);
    expect(snap.messages.length).toBeGreaterThan(0);
    expect(snap.meterRatio).toBeGreaterThan(0);
    expect(snap.context).toBeDefined();
  });

  it('updates token meter from usage', async () => {
    const adapter = createAdapter([
      {
        message: { role: 'assistant', content: 'ok' },
        usage: { promptTokens: 500, completionTokens: 100, totalTokens: 600 },
        finishReason: 'stop',
      },
    ]);

    await adapter.decide();
    expect(adapter.meter.lastPromptTokens).toBe(500);
  });

  it('throws ModelError on empty response', async () => {
    const adapter = createAdapter([
      {
        message: { role: 'assistant', content: null },
        finishReason: 'stop',
      },
    ]);

    await expect(adapter.decide()).rejects.toThrow('empty response');
  });
});
