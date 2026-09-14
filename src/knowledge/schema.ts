/**
 * Knowledge unit schema — stable, JSON-serializable semantic units and provenance.
 * Mirrors python-legacy/kernellens/knowledge/schema.py.
 */

import { createHash } from 'node:crypto';
import { z } from 'zod';

export const SCHEMA_VERSION = 1;
export const INDEXES = ['api', 'concept', 'example', 'compiler', 'operator'] as const;
export type IndexName = (typeof INDEXES)[number];

// ── SourceLocation ────────────────────────────────────────────────────────────

export const SourceLocation = z.object({
  path: z.string(),
  start_line: z.number().int().min(1),
  end_line: z.number().int().min(1),
});
export type SourceLocation = z.infer<typeof SourceLocation>;

// ── KnowledgeUnit ─────────────────────────────────────────────────────────────

export const Category = z.enum([
  'api',
  'instruction',
  'concept',
  'operator',
  'compiler',
  'example',
]);
export type Category = z.infer<typeof Category>;

export const KnowledgeUnit = z.object({
  id: z.string(),
  category: Category,
  name: z.string(),
  description: z.string(),
  when_to_use: z.string(),
  parameters: z.array(z.record(z.unknown())).default([]),
  returns: z.string().default(''),
  examples: z.array(z.record(z.unknown())).default([]),
  related_concepts: z.array(z.string()).default([]),
  source_location: SourceLocation,
  keywords: z.array(z.string()).default([]),
  indexes: z.array(z.enum(INDEXES)),
  layer: z.enum(['user', 'implementation']),
  visibility: z.enum(['public', 'module', 'internal', 'example', 'documentation']),
  aliases: z.array(z.string()).default([]),
  signature: z.string().default(''),
  symbols: z.array(z.string()).default([]),
  targets: z.array(z.string()).default([]),
  evidence_quality: z.enum(['source', 'documentation', 'example', 'structural']),
  source_revision: z.string(),
  source_hash: z.string(),
  content: z.string(),
  context: z.string().default(''),
  cautions: z.array(z.string()).default([]),
  constraints: z.array(z.string()).default([]),
  hardware_mapping: z.array(z.string()).default([]),
  operator_structure: z.record(z.unknown()).default({}),
  dependencies: z.array(z.string()).default([]),
});
export type KnowledgeUnit = z.infer<typeof KnowledgeUnit>;

// ── Helper ────────────────────────────────────────────────────────────────────

/**
 * Generate a deterministic unit ID from category, path, and name.
 * Mirrors Python: "K" + sha256(f"{category}:{path}:{name}")[:16]
 */
export function unitId(category: string, path: string, name: string): string {
  const h = createHash('sha256').update(`${category}:${path}:${name}`).digest('hex');
  return `K${h.slice(0, 16)}`;
}
