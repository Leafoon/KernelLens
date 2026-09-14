/**
 * Tool implementations — bind Zod schemas to Workspace and KnowledgeBase.
 *
 * Each ToolDefinition connects a schema (for LLM argument validation)
 * to an executor function (for actual side effects).
 */

import type { KnowledgeBase } from '../knowledge/base.js';
import {
  ListFilesArgs,
  ReadFileArgs,
  ReadKnowledgeArgs,
  SearchKnowledgeArgs,
  SearchTextArgs,
  WriteFileArgs,
} from './definitions.js';
import type { ToolDefinition } from './registry.js';
import type { Workspace } from './workspace.js';

/**
 * Create tool definitions bound to a Workspace and optional KnowledgeBase.
 */
export function createToolDefinitions(
  workspace: Workspace,
  knowledge: KnowledgeBase | null,
): ToolDefinition[] {
  const tools: ToolDefinition[] = [
    // ── Workspace tools ─────────────────────────────────────────────────────
    {
      name: 'list_files',
      description:
        'List files in a directory. Returns relative paths, sorted. Use to explore the workspace before reading.',
      schema: ListFilesArgs,
      execute: async (args) => {
        const { path, pattern, limit } = args as { path: string; pattern: string; limit: number };
        return (await workspace.listFiles(path, pattern, limit)) as unknown as Record<
          string,
          unknown
        >;
      },
    },
    {
      name: 'read_file',
      description:
        'Read a file with line numbers. Returns content, SHA-256, and truncation info. Required before write_file (for expected_sha256).',
      schema: ReadFileArgs,
      execute: async (args) => {
        const { path, start_line, max_lines } = args as {
          path: string;
          start_line: number;
          max_lines: number;
        };
        return (await workspace.readFile(path, start_line, max_lines)) as unknown as Record<
          string,
          unknown
        >;
      },
    },
    {
      name: 'search_text',
      description:
        'Search for a literal string in workspace files. Returns matching paths, line numbers, and context. Use to locate code patterns before reading.',
      schema: SearchTextArgs,
      execute: async (args) => {
        const { query, path, pattern, limit } = args as {
          query: string;
          path: string;
          pattern: string;
          limit: number;
        };
        return (await workspace.searchText(query, path, pattern, limit)) as unknown as Record<
          string,
          unknown
        >;
      },
    },
    {
      name: 'write_file',
      description:
        'Write a file. New files: omit expected_sha256. Overwrites: must provide expected_sha256 from a prior read_file. Creates parent directories automatically.',
      schema: WriteFileArgs,
      execute: async (args) => {
        const { path, content, expected_sha256 } = args as {
          path: string;
          content: string;
          expected_sha256: string;
        };
        return (await workspace.writeFile(
          path,
          content,
          expected_sha256 || undefined,
        )) as unknown as Record<string, unknown>;
      },
    },
  ];

  // ── Knowledge tools ───────────────────────────────────────────────────────
  if (knowledge) {
    tools.push({
      name: 'search_knowledge',
      description:
        'Search the TileLang knowledge base. Use to find APIs, concepts, examples, compiler internals, or operator patterns. Returns ranked results with excerpts.',
      schema: SearchKnowledgeArgs,
      execute: (args) => {
        const { query, index, top_k, max_chars, target, include_source } = args as {
          query: string;
          index: string;
          top_k: number;
          max_chars: number;
          target: string;
          include_source: boolean;
        };
        const result = knowledge.search(query, index, top_k, max_chars, target, include_source);
        return result as unknown as Record<string, unknown>;
      },
    });

    tools.push({
      name: 'read_knowledge',
      description:
        'Read a knowledge unit by ID (e.g. K0123456789abcdef). Use after search_knowledge to get the full source code when excerpt_truncated=true or source_complete=false.',
      schema: ReadKnowledgeArgs,
      execute: (args) => {
        const { unit_id, start_line, max_chars } = args as {
          unit_id: string;
          start_line: number;
          max_chars: number;
        };
        const result = knowledge.read(unit_id, start_line, max_chars);
        return result as unknown as Record<string, unknown>;
      },
    });
  }

  return tools;
}
