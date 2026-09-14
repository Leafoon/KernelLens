import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import type { CallToolAction } from '../../src/domain/action.js';
import { ToolRegistry } from '../../src/tools/registry.js';
import type { ToolDefinition } from '../../src/tools/registry.js';

// ── Mock Tools ────────────────────────────────────────────────────────────────

const EchoSchema = z.object({
  message: z.string().min(1),
});

const echoTool: ToolDefinition = {
  name: 'echo',
  description: 'Echo back the message',
  schema: EchoSchema,
  execute: (args) => ({ output: (args as { message: string }).message }),
};

const failTool: ToolDefinition = {
  name: 'fail',
  description: 'Always fails',
  schema: z.object({}),
  execute: () => {
    throw new Error('Tool execution failed');
  },
};

const asyncTool: ToolDefinition = {
  name: 'async_echo',
  description: 'Async echo',
  schema: EchoSchema,
  execute: async (args) => {
    await new Promise((r) => setTimeout(r, 10));
    return { output: (args as { message: string }).message };
  },
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('ToolRegistry', () => {
  it('registers and retrieves tools', () => {
    const registry = new ToolRegistry({ tools: [echoTool] });

    expect(registry.names()).toEqual(['echo']);
    expect(registry.get('echo')).toBeDefined();
    expect(registry.get('nonexistent')).toBeUndefined();
  });

  it('rejects duplicate tool names', () => {
    expect(() => new ToolRegistry({ tools: [echoTool, echoTool] })).toThrow('Duplicate tool name');
  });

  it('generates JSON schemas for LLM', () => {
    const registry = new ToolRegistry({ tools: [echoTool] });
    const schemas = registry.schemas();

    expect(schemas).toHaveLength(1);
    expect(schemas[0]!.name).toBe('echo');
    expect(schemas[0]!.description).toBe('Echo back the message');
    expect(schemas[0]!.parameters).toEqual({
      type: 'object',
      properties: {
        message: { type: 'string', minLength: 1 },
      },
      required: ['message'],
    });
  });

  it('executes a tool successfully', async () => {
    const registry = new ToolRegistry({ tools: [echoTool] });

    const action: CallToolAction = {
      type: 'call_tool',
      tool: 'echo',
      arguments: { message: 'hello' },
    };

    const result = await registry.execute(action);

    expect(result.ok).toBe(true);
    expect(result.tool).toBe('echo');
    expect(result.evidenceId).toBe('E1');
    expect(JSON.parse(result.output)).toEqual({
      evidence_id: 'E1',
      output: 'hello',
    });
  });

  it('tracks evidence', async () => {
    const registry = new ToolRegistry({ tools: [echoTool] });

    await registry.execute({
      type: 'call_tool',
      tool: 'echo',
      arguments: { message: 'first' },
    });
    await registry.execute({
      type: 'call_tool',
      tool: 'echo',
      arguments: { message: 'second' },
    });

    expect(registry.evidence).toHaveLength(2);
    expect(registry.evidence[0]!.id).toBe('E1');
    expect(registry.evidence[1]!.id).toBe('E2');
  });

  it('returns error for unknown tool', async () => {
    const registry = new ToolRegistry({ tools: [echoTool] });

    const result = await registry.execute({
      type: 'call_tool',
      tool: 'nonexistent',
      arguments: {},
    });

    expect(result.ok).toBe(false);
    expect(result.evidenceId).toBeUndefined();
    expect(JSON.parse(result.output).error).toBe('unknown_tool');
  });

  it('returns error for invalid arguments', async () => {
    const registry = new ToolRegistry({ tools: [echoTool] });

    const result = await registry.execute({
      type: 'call_tool',
      tool: 'echo',
      arguments: { message: '' }, // empty string fails min(1)
    });

    expect(result.ok).toBe(false);
    expect(JSON.parse(result.output).error).toBe('invalid_arguments');
  });

  it('handles tool execution errors', async () => {
    const registry = new ToolRegistry({ tools: [failTool] });

    const result = await registry.execute({
      type: 'call_tool',
      tool: 'fail',
      arguments: {},
    });

    expect(result.ok).toBe(false);
    expect(JSON.parse(result.output).message).toBe('Tool execution failed');
  });

  it('handles async tools', async () => {
    const registry = new ToolRegistry({ tools: [asyncTool] });

    const result = await registry.execute({
      type: 'call_tool',
      tool: 'async_echo',
      arguments: { message: 'async hello' },
    });

    expect(result.ok).toBe(true);
    expect(JSON.parse(result.output).output).toBe('async hello');
  });
});
