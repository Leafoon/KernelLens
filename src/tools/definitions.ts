/**
 * Zod schemas for all tool arguments.
 *
 * Each schema validates and constrains the arguments the LLM sends.
 * Mirrors python-legacy/kernellens/tools/arguments.py.
 */

import { z } from 'zod';

// ── Common ────────────────────────────────────────────────────────────────────

const nonEmpty = z.string().min(1);
const nonBlank = z.string().min(1).regex(/\S/);

// ── Set Task Context ──────────────────────────────────────────────────────────

export const SetTaskContextArgs = z.object({
  task_type: z.enum(['generate', 'optimize', 'diagnose']),
  gpu_model: z.string().max(160).optional().nullable(),
  backend: z.enum(['', 'cuda', 'hip', 'metal', 'cpu', 'webgpu']).optional().nullable(),
  reason: z.string().min(1).max(1000).regex(/\S/),
});
export type SetTaskContextArgs = z.infer<typeof SetTaskContextArgs>;

// ── Read Report ───────────────────────────────────────────────────────────────

export const ReadReportArgs = z.object({
  path: nonBlank,
});
export type ReadReportArgs = z.infer<typeof ReadReportArgs>;

// ── List Files ────────────────────────────────────────────────────────────────

export const ListFilesArgs = z.object({
  path: nonEmpty.default('.'),
  pattern: z.string().min(1).max(200).default('*'),
  limit: z.number().int().min(1).max(200).default(100),
});
export type ListFilesArgs = z.infer<typeof ListFilesArgs>;

// ── Read File ─────────────────────────────────────────────────────────────────

export const ReadFileArgs = z.object({
  path: nonBlank,
  start_line: z.number().int().min(1).default(1),
  max_lines: z.number().int().min(1).max(500).default(200),
});
export type ReadFileArgs = z.infer<typeof ReadFileArgs>;

// ── Search Text ───────────────────────────────────────────────────────────────

export const SearchTextArgs = z.object({
  query: z.string().min(1).max(500),
  path: nonEmpty.default('.'),
  pattern: z.string().min(1).max(200).default('*'),
  limit: z.number().int().min(1).max(200).default(100),
});
export type SearchTextArgs = z.infer<typeof SearchTextArgs>;

// ── Write File ────────────────────────────────────────────────────────────────

export const WriteFileArgs = z.object({
  path: nonBlank,
  content: z.string().max(100_000),
  expected_sha256: z
    .string()
    .regex(/^(|[a-f0-9]{64})$/)
    .default(''),
});
export type WriteFileArgs = z.infer<typeof WriteFileArgs>;

// ── Request Input ─────────────────────────────────────────────────────────────

export const RequestInputArgs = z.object({
  question: nonBlank,
  reason: nonBlank,
});
export type RequestInputArgs = z.infer<typeof RequestInputArgs>;

// ── Compare Reports ───────────────────────────────────────────────────────────

export const CompareReportsArgs = z.object({
  baseline_path: nonBlank,
  candidate_path: nonBlank,
});
export type CompareReportsArgs = z.infer<typeof CompareReportsArgs>;

// ── Finish ────────────────────────────────────────────────────────────────────

export const FinishArgs = z.object({
  answer: z.string().min(1).regex(/\S/).max(50_000),
  reason: nonBlank,
});
export type FinishArgs = z.infer<typeof FinishArgs>;

// ── Search Knowledge ──────────────────────────────────────────────────────────

export const SearchKnowledgeArgs = z.object({
  query: z.string().min(1).max(20_000).regex(/\S/),
  index: z.enum(['auto', 'api', 'concept', 'example', 'compiler', 'operator']).default('auto'),
  top_k: z.number().int().min(1).max(10).default(5),
  max_chars: z.number().int().min(1500).max(20_000).default(10_000),
  target: z.enum(['', 'cuda', 'hip', 'metal', 'cpu', 'webgpu']).default(''),
  include_source: z.boolean().default(false),
});
export type SearchKnowledgeArgs = z.infer<typeof SearchKnowledgeArgs>;

// ── Read Knowledge ────────────────────────────────────────────────────────────

export const ReadKnowledgeArgs = z.object({
  unit_id: z.string().regex(/^K[a-f0-9]{16}$/),
  start_line: z.number().int().min(0).default(0),
  max_chars: z.number().int().min(1500).max(20_000).default(10_000),
});
export type ReadKnowledgeArgs = z.infer<typeof ReadKnowledgeArgs>;

// ── All schemas map ───────────────────────────────────────────────────────────

export const TOOL_SCHEMAS = {
  set_task_context: SetTaskContextArgs,
  read_report: ReadReportArgs,
  list_files: ListFilesArgs,
  read_file: ReadFileArgs,
  search_text: SearchTextArgs,
  write_file: WriteFileArgs,
  request_input: RequestInputArgs,
  compare_reports: CompareReportsArgs,
  finish: FinishArgs,
  search_knowledge: SearchKnowledgeArgs,
  read_knowledge: ReadKnowledgeArgs,
} as const;

export type ToolName = keyof typeof TOOL_SCHEMAS;
