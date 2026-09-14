/**
 * ToolRegistry — registers tool definitions and dispatches execution.
 *
 * Each tool is defined with a Zod schema for arguments and an executor function.
 * The registry validates arguments, executes the tool, and wraps results in
 * ToolObservation with evidence tracking.
 */

import type { ZodSchema } from 'zod';
import type { CallToolAction } from '../domain/action.js';
import type { ToolObservation } from '../domain/observation.js';

/** A registered tool definition. */
export interface ToolDefinition {
  readonly name: string;
  readonly description: string;
  readonly schema: ZodSchema;
  readonly execute: (
    args: Record<string, unknown>,
  ) => Promise<Record<string, unknown>> | Record<string, unknown>;
}

/** Evidence entry for a completed tool call. */
export interface EvidenceEntry {
  readonly id: string;
  readonly tool: string;
  readonly path?: string;
  readonly sha256?: string;
  readonly timestamp: string;
}

/** Registry configuration. */
export interface RegistryConfig {
  /** Built-in tools to register. */
  readonly tools: readonly ToolDefinition[];
}

/**
 * ToolRegistry manages tool definitions and executes tool calls.
 */
export class ToolRegistry {
  private readonly tools = new Map<string, ToolDefinition>();
  public readonly evidence: EvidenceEntry[] = [];

  constructor(config: RegistryConfig) {
    for (const tool of config.tools) {
      this.register(tool);
    }
  }

  /**
   * Register a tool definition.
   * Throws if a tool with the same name is already registered.
   */
  register(tool: ToolDefinition): void {
    if (this.tools.has(tool.name)) {
      throw new Error(`Duplicate tool name: ${tool.name}`);
    }
    this.tools.set(tool.name, tool);
  }

  /**
   * Get a tool definition by name.
   */
  get(name: string): ToolDefinition | undefined {
    return this.tools.get(name);
  }

  /**
   * Get all registered tool names.
   */
  names(): string[] {
    return [...this.tools.keys()];
  }

  /**
   * Generate JSON Schema for all registered tools (for LLM function calling).
   */
  schemas(): Array<{ name: string; description: string; parameters: Record<string, unknown> }> {
    return [...this.tools.values()].map((tool) => ({
      name: tool.name,
      description: tool.description,
      parameters: zodToJsonSchema(tool.schema),
    }));
  }

  /**
   * Execute a tool call action.
   * Returns a ToolObservation with the result or error.
   */
  async execute(action: CallToolAction): Promise<ToolObservation> {
    const tool = this.tools.get(action.tool);
    if (!tool) {
      return {
        tool: action.tool,
        ok: false,
        output: JSON.stringify({
          error: 'unknown_tool',
          message: `Unknown tool: ${action.tool}. Available: ${[...this.tools.keys()].join(', ')}`,
        }),
        evidenceId: undefined,
        truncated: false,
      };
    }

    // Validate arguments
    const parsed = tool.schema.safeParse(action.arguments);
    if (!parsed.success) {
      return {
        tool: action.tool,
        ok: false,
        output: JSON.stringify({
          error: 'invalid_arguments',
          details: parsed.error.issues.map((i) => ({
            path: i.path.join('.'),
            message: i.message,
          })),
        }),
        evidenceId: undefined,
        truncated: false,
      };
    }

    // Execute
    try {
      const result = await tool.execute(parsed.data as Record<string, unknown>);

      // Assign evidence ID
      const evidenceId = `E${this.evidence.length + 1}`;
      const resultWithEvidence = { evidence_id: evidenceId, ...result };

      // Track evidence
      this.evidence.push({
        id: evidenceId,
        tool: action.tool,
        path: result.path as string | undefined,
        sha256: result.sha256 as string | undefined,
        timestamp: new Date().toISOString(),
      });

      // Serialize and truncate
      const output = JSON.stringify(resultWithEvidence);
      const truncated = output.length > 22_000;
      const finalOutput = truncated
        ? JSON.stringify({
            evidence_id: evidenceId,
            truncated: true,
            preview: output.slice(0, 21_000),
            next: 'Reduce read range or search scope',
          })
        : output;

      return {
        tool: action.tool,
        ok: true,
        output: finalOutput,
        evidenceId,
        truncated,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message.slice(0, 1000) : 'Unknown error';
      return {
        tool: action.tool,
        ok: false,
        output: JSON.stringify({
          error: error instanceof Error ? error.constructor.name : 'Error',
          message,
        }),
        evidenceId: undefined,
        truncated: false,
      };
    }
  }
}

// ── Simple Zod → JSON Schema converter ────────────────────────────────────────

/**
 * Minimal Zod to JSON Schema converter.
 * Handles the subset of Zod types used in tool definitions.
 */
function zodToJsonSchema(schema: ZodSchema): Record<string, unknown> {
  const def = (schema as unknown as { _def: unknown })._def as Record<string, unknown>;

  if (!def) return { type: 'object' };

  const typeName = def.typeName as string;

  if (typeName === 'ZodObject') {
    const shapeFn = def.shape as (() => Record<string, ZodSchema>) | Record<string, ZodSchema>;
    const shape = typeof shapeFn === 'function' ? shapeFn() : shapeFn;
    const properties: Record<string, unknown> = {};
    const required: string[] = [];

    for (const [key, value] of Object.entries(shape ?? {})) {
      properties[key] = zodPropertySchema(value);
      if (!isOptional(value)) {
        required.push(key);
      }
    }

    return {
      type: 'object',
      properties,
      ...(required.length ? { required } : {}),
    };
  }

  return { type: 'object' };
}

function zodPropertySchema(schema: ZodSchema): Record<string, unknown> {
  const def = (schema as unknown as { _def: unknown })._def as Record<string, unknown>;
  const typeName = def?.typeName as string;

  // Unwrap optional
  if (typeName === 'ZodOptional' || typeName === 'ZodDefault' || typeName === 'ZodNullable') {
    const inner = def.innerType as ZodSchema | undefined;
    if (inner) return zodPropertySchema(inner);
  }

  if (typeName === 'ZodString') {
    const checks = (def.checks as Array<{ kind: string; value?: number; regex?: RegExp }>) ?? [];
    const schema: Record<string, unknown> = { type: 'string' };
    for (const check of checks) {
      if (check.kind === 'min') schema.minLength = check.value;
      if (check.kind === 'max') schema.maxLength = check.value;
    }
    return schema;
  }

  if (typeName === 'ZodNumber') {
    const checks = (def.checks as Array<{ kind: string; value?: number }>) ?? [];
    const schema: Record<string, unknown> = { type: 'number' };
    for (const check of checks) {
      if (check.kind === 'min') schema.minimum = check.value;
      if (check.kind === 'max') schema.maximum = check.value;
      if (check.kind === 'int') schema.type = 'integer';
    }
    return schema;
  }

  if (typeName === 'ZodBoolean') {
    return { type: 'boolean' };
  }

  if (typeName === 'ZodEnum') {
    return { type: 'string', enum: def.values as string[] };
  }

  return {};
}

function isOptional(schema: ZodSchema): boolean {
  const typeName = ((schema as unknown as { _def: unknown })._def as Record<string, unknown>)
    ?.typeName as string;
  return typeName === 'ZodOptional' || typeName === 'ZodDefault' || typeName === 'ZodNullable';
}
