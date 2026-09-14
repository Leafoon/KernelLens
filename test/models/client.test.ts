import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OpenAIProvider } from '../../src/models/client.js';

// ── Mock OpenAI SDK ────────────────────────────────────────────────────────────

const mockCreate = vi.fn();

vi.mock('openai', () => {
  return {
    default: class MockOpenAI {
      apiKey = 'test-key';
      chat = {
        completions: {
          create: mockCreate,
        },
      };
      static APIError = class APIError extends Error {
        status: number;
        constructor(message: string, status: number) {
          super(message);
          this.status = status;
        }
      };
    },
  };
});

// ── Tests ──────────────────────────────────────────────────────────────────────

describe('OpenAIProvider', () => {
  let provider: OpenAIProvider;

  beforeEach(() => {
    vi.clearAllMocks();
    provider = new OpenAIProvider({
      apiKey: 'test-key-12345678',
      baseUrl: 'https://api.openai.com/v1',
      model: 'gpt-4o',
      contextWindow: 128_000,
      maxOutputTokens: 4_096,
    });
  });

  it('has correct model info', () => {
    expect(provider.model).toBe('gpt-4o');
    expect(provider.contextWindow).toBe(128_000);
    expect(provider.maxOutputTokens).toBe(4_096);
  });

  it('returns parsed completion result', async () => {
    mockCreate.mockResolvedValueOnce({
      choices: [
        {
          message: {
            role: 'assistant',
            content: 'Hello!',
            tool_calls: null,
          },
          finish_reason: 'stop',
        },
      ],
      usage: {
        prompt_tokens: 100,
        completion_tokens: 50,
        total_tokens: 150,
      },
    });

    const result = await provider.complete({
      messages: [{ role: 'user', content: 'Hi' }],
    });

    expect(result.message.role).toBe('assistant');
    expect(result.message.content).toBe('Hello!');
    expect(result.message.toolCalls).toBeUndefined();
    expect(result.finishReason).toBe('stop');
    expect(result.usage).toEqual({
      promptTokens: 100,
      completionTokens: 50,
      totalTokens: 150,
    });
  });

  it('parses tool calls', async () => {
    mockCreate.mockResolvedValueOnce({
      choices: [
        {
          message: {
            role: 'assistant',
            content: null,
            tool_calls: [
              {
                id: 'call_123',
                type: 'function',
                function: {
                  name: 'read_file',
                  arguments: '{"path": "/test.py"}',
                },
              },
            ],
          },
          finish_reason: 'tool_calls',
        },
      ],
      usage: null,
    });

    const result = await provider.complete({
      messages: [{ role: 'user', content: 'Read the file' }],
    });

    expect(result.message.toolCalls).toHaveLength(1);
    expect(result.message.toolCalls![0]).toEqual({
      id: 'call_123',
      name: 'read_file',
      arguments: { path: '/test.py' },
    });
  });

  it('tracks cumulative usage', async () => {
    mockCreate.mockResolvedValue({
      choices: [
        {
          message: { role: 'assistant', content: 'ok', tool_calls: null },
          finish_reason: 'stop',
        },
      ],
      usage: { prompt_tokens: 100, completion_tokens: 50, total_tokens: 150 },
    });

    await provider.complete({ messages: [{ role: 'user', content: 'a' }] });
    await provider.complete({ messages: [{ role: 'user', content: 'b' }] });

    expect(provider.totalPromptTokens).toBe(200);
    expect(provider.totalCompletionTokens).toBe(100);
    expect(provider.requestCount).toBe(2);
    expect(provider.getUsage().totalTokens).toBe(300);
  });

  it('throws ModelError on missing choices', async () => {
    mockCreate.mockResolvedValueOnce({
      choices: [],
      usage: null,
    });

    await expect(
      provider.complete({ messages: [{ role: 'user', content: 'test' }] }),
    ).rejects.toThrow('missing choices');
  });

  it('throws ModelError on finish_reason length', async () => {
    mockCreate.mockResolvedValueOnce({
      choices: [
        {
          message: { role: 'assistant', content: 'truncated', tool_calls: null },
          finish_reason: 'length',
        },
      ],
      usage: null,
    });

    await expect(
      provider.complete({ messages: [{ role: 'user', content: 'test' }] }),
    ).rejects.toThrow('truncated');
  });

  it('retries on rate limit (429)', async () => {
    const APIError = (await import('openai')).default.APIError;
    // Simulate 429 then success
    mockCreate.mockRejectedValueOnce(new APIError('Rate limited', 429)).mockResolvedValueOnce({
      choices: [
        {
          message: { role: 'assistant', content: 'ok', tool_calls: null },
          finish_reason: 'stop',
        },
      ],
      usage: { prompt_tokens: 50, completion_tokens: 10, total_tokens: 60 },
    });

    const result = await provider.complete({
      messages: [{ role: 'user', content: 'test' }],
    });

    expect(result.message.content).toBe('ok');
    expect(mockCreate).toHaveBeenCalledTimes(2);
  });

  it('passes tools to the API correctly', async () => {
    mockCreate.mockResolvedValueOnce({
      choices: [
        {
          message: { role: 'assistant', content: 'ok', tool_calls: null },
          finish_reason: 'stop',
        },
      ],
      usage: null,
    });

    await provider.complete({
      messages: [{ role: 'user', content: 'test' }],
      tools: [
        {
          name: 'read_file',
          description: 'Read a file',
          parameters: { type: 'object', properties: {} },
        },
      ],
    });

    const callArgs = mockCreate.mock.calls[0]![0];
    expect(callArgs.tools).toHaveLength(1);
    expect(callArgs.tools[0].type).toBe('function');
    expect(callArgs.tools[0].function.name).toBe('read_file');
    expect(callArgs.tool_choice).toBe('auto');
  });
});
