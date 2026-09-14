/**
 * KnowledgeBase — FTS5-powered knowledge retrieval.
 *
 * Loads a pre-built SQLite knowledge index and provides:
 *   - search(): multi-index FTS5 retrieval with BM25 ranking
 *   - read(): paginated unit content retrieval
 *
 * Mirrors python-legacy/kernellens/knowledge/search.py.
 */

import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import Database from 'better-sqlite3';
import { KnowledgeError } from '../exceptions.js';
import { INDEXES, type IndexName, KnowledgeUnit, SCHEMA_VERSION } from './schema.js';
import { route, tokenize } from './terms.js';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Manifest {
  schema_version: number;
  delivery_mode: 'source' | 'snapshot';
  repo_relative?: string;
  source_repository?: string;
  delivery_hashes: Record<string, string>;
  source_files: Record<string, string>;
  source_revision: string;
  indexes: string[];
  limitations: string[];
  public_exports?: Record<string, string>;
}

interface SearchResult {
  id: string;
  category: string;
  name: string;
  description: string;
  excerpt: string;
  excerpt_truncated: boolean;
  source_complete: boolean;
  source_location: { path: string; start_line: number; end_line: number };
  source_hash: string;
  source_revision: string;
  evidence_quality: string;
  match: 'exact_symbol' | 'lexical';
  score: number;
  examples?: unknown[];
  context?: string;
  dependencies?: string[];
}

export interface SearchResponse {
  status: 'ok' | 'stale' | 'budget_limited' | 'no_match';
  intent: string;
  indexes: string[];
  candidate_counts: Record<string, number>;
  missing_symbols: string[];
  source_revision: string;
  source_root: string;
  delivery_mode: string;
  results: SearchResult[];
  stale_sources: string[];
  omitted_for_budget: string[];
  truncated: boolean;
  context_chars: number;
}

export interface ReadResponse {
  id: string;
  category: string;
  name: string;
  description: string;
  signature: string;
  source_location: { path: string; start_line: number; end_line: number };
  source_hash: string;
  source_revision: string;
  evidence_quality: string;
  source_root: string;
  delivery_mode: string;
  context: string;
  parameters: unknown[];
  returns: string;
  dependencies: string[];
  examples: unknown[];
  content: string;
  start_line: number;
  next_line: number | null;
  truncated: boolean;
  context_chars: number;
}

// ── KnowledgeBase ─────────────────────────────────────────────────────────────

export class KnowledgeBase {
  readonly directory: string;
  private readonly manifest: Manifest;
  private readonly db: Database.Database;
  private readonly repo: string | null;

  constructor(directory: string) {
    this.directory = resolve(directory);

    // Load manifest
    const manifestPath = join(this.directory, 'manifest.json');
    let manifestRaw: string;
    try {
      manifestRaw = readFileSync(manifestPath, 'utf-8');
    } catch {
      throw new KnowledgeError('Cannot read manifest.json');
    }

    try {
      this.manifest = JSON.parse(manifestRaw);
    } catch {
      throw new KnowledgeError('Invalid manifest.json');
    }

    if (this.manifest.schema_version !== SCHEMA_VERSION) {
      throw new KnowledgeError('Knowledge schema mismatch; rebuild the knowledge base');
    }

    this.repo =
      this.manifest.delivery_mode === 'source'
        ? join(this.directory, this.manifest.repo_relative ?? '..')
        : null;

    // Open SQLite index
    const indexPath = join(this.directory, 'index.sqlite3');
    this.db = new Database(indexPath, { readonly: true });
    this.db.pragma('query_only = ON');
  }

  /** Close the database connection. */
  close(): void {
    this.db.close();
  }

  /** Source root path. */
  get sourceRoot(): string {
    return this.repo ?? this.manifest.source_repository ?? '';
  }

  /** Delivery mode. */
  get deliveryMode(): string {
    return this.manifest.delivery_mode;
  }

  /** The manifest (for evidence tracking). */
  get manifestData(): Manifest {
    return this.manifest;
  }

  // ── Read a unit by ID ──────────────────────────────────────────────────────

  /**
   * Read a knowledge unit by ID with paginated content.
   */
  read(unitId: string, startLine = 0, maxChars = 10_000): ReadResponse {
    if (maxChars < 1500 || maxChars > 20_000) {
      throw new KnowledgeError('max_chars must be 1500..20000');
    }

    const unit = this.getUnit(unitId);
    const location = unit.source_location;
    const effectiveStart = startLine || location.start_line;

    if (effectiveStart < location.start_line || effectiveStart > location.end_line) {
      throw new KnowledgeError('start_line must be inside the semantic unit');
    }

    const result: ReadResponse = {
      id: unit.id,
      category: unit.category,
      name: unit.name,
      description: unit.description.slice(0, 800),
      signature: unit.signature.slice(0, 1800),
      source_location: { ...location },
      source_hash: unit.source_hash,
      source_revision: unit.source_revision,
      evidence_quality: unit.evidence_quality,
      source_root: this.sourceRoot,
      delivery_mode: this.deliveryMode,
      context: unit.context,
      parameters: unit.parameters,
      returns: unit.returns,
      dependencies: unit.dependencies.filter((d) => !(d in this.manifest.source_files)),
      examples: unit.examples.slice(0, 3),
      content: '',
      start_line: effectiveStart,
      next_line: null,
      truncated: false,
      context_chars: 0,
    };

    // Paginate content
    const lines = unit.content.split('\n');
    const offset = effectiveStart - location.start_line;
    for (let i = offset; i < lines.length; i++) {
      const line = `${lines[i]}\n`;
      const candidate = { ...result, content: result.content + line };
      if (JSON.stringify(candidate).length > maxChars - 150) {
        result.truncated = true;
        result.next_line = location.start_line + i;
        break;
      }
      result.content += line;
    }

    if (!result.content) {
      throw new KnowledgeError(
        'A source line or its metadata exceeds this budget; increase max_chars',
      );
    }

    result.context_chars = JSON.stringify(result).length;
    return result;
  }

  // ── Search ─────────────────────────────────────────────────────────────────

  /**
   * Search the knowledge base using FTS5 and BM25 ranking.
   */
  search(
    query: string,
    index = 'auto',
    topK = 5,
    maxChars = 10_000,
    target = '',
    includeSource = false,
  ): SearchResponse {
    if (!query.trim() || query.length > 20_000) {
      throw new KnowledgeError('Query must contain 1..20000 characters');
    }
    if (index !== 'auto' && !INDEXES.includes(index as IndexName)) {
      throw new KnowledgeError('Unknown knowledge index');
    }
    if (topK < 1 || topK > 10 || maxChars < 1500 || maxChars > 20_000) {
      throw new KnowledgeError('top_k must be 1..10 and max_chars 1500..20000');
    }

    let { intent, selected } = route(query);
    if (index !== 'auto') selected = [index];

    const symbols = query.match(/\b(?:T|tilelang)(?:\.[A-Za-z_]\w*)+/g) ?? [];
    const terms = tokenize(query).slice(0, 32);

    // Exact symbol matching
    const exact = new Set<string>();
    const missing: string[] = [];
    for (const symbol of symbols) {
      const hits = this.db
        .prepare('SELECT id FROM aliases WHERE alias = ?')
        .all(symbol.toLowerCase()) as Array<{ id: string }>;
      if (hits.length > 0) {
        for (const h of hits) exact.add(h.id);
      } else {
        missing.push(symbol);
      }
    }

    // FTS5 search
    const scores = new Map<string, number>();
    for (const uid of exact) scores.set(uid, 1000);

    const candidates: Record<string, number> = {};
    if (terms.length > 0 && !(intent === 'api' && symbols.length > 0 && exact.size === 0)) {
      const match = terms.map((t) => `"${t.replace(/"/g, '""')}"`).join(' OR ');

      for (let priority = 0; priority < selected.length; priority++) {
        const table = `${selected[priority]}_index`;
        try {
          const rows = this.db
            .prepare(
              `SELECT id, bm25(${table}, 0, 8, 4, 2, 0.3) FROM ${table} WHERE ${table} MATCH ? ORDER BY 2, id LIMIT 100`,
            )
            .all(match) as Array<[string, number]>;

          candidates[selected[priority]!] = rows.length;
          for (let rank = 0; rank < rows.length; rank++) {
            const uid = rows[rank]![0];
            const existing = scores.get(uid) ?? 0;
            scores.set(uid, Math.max(existing, (1 - 0.12 * priority) / (10 + rank)));
          }
        } catch {
          // Table may not exist
          candidates[selected[priority]!] = 0;
        }
      }
    }

    // Score and rank results
    const records = new Map<string, KnowledgeUnit>();
    for (const uid of [...scores.keys()]) {
      try {
        const row = this.db.prepare('SELECT record FROM units WHERE id = ?').get(uid) as
          | { record: string }
          | undefined;
        if (!row) {
          scores.delete(uid);
          continue;
        }

        const unit = KnowledgeUnit.parse(JSON.parse(row.record));

        // Filter by index and target
        if (!unit.indexes.some((i) => selected.includes(i))) {
          scores.delete(uid);
          continue;
        }
        if (target && unit.targets.length > 0 && !unit.targets.includes(target)) {
          scores.delete(uid);
          continue;
        }

        // Adjust scores for non-exact matches
        if (!exact.has(uid)) {
          const unitTokens = new Set(tokenize(`${unit.name} ${unit.aliases.join(' ')}`));
          const asciiTerms = terms.filter((t) => /^[\x20-\x7E]+$/.test(t));
          const coverage =
            asciiTerms.filter((t) => unitTokens.has(t)).length / Math.max(1, asciiTerms.length);
          scores.set(uid, (scores.get(uid) ?? 0) + Math.min(0.12, 0.12 * coverage));

          if (['concept', 'target'].includes(intent) && unit.category === 'concept') {
            scores.set(uid, (scores.get(uid) ?? 0) + 0.13);
          }
          if (['operator', 'example'].includes(intent) && unit.category === 'example') {
            scores.set(uid, (scores.get(uid) ?? 0) + 0.06);
          }
        }

        records.set(uid, unit);
      } catch {
        scores.delete(uid);
      }
    }

    // Build response
    const response: SearchResponse = {
      status: 'ok',
      intent,
      indexes: selected,
      candidate_counts: candidates,
      missing_symbols: missing,
      source_revision: this.manifest.source_revision,
      source_root: this.sourceRoot,
      delivery_mode: this.deliveryMode,
      results: [],
      stale_sources: [],
      omitted_for_budget: [],
      truncated: false,
      context_chars: 0,
    };

    const ranked = [...scores.entries()]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([uid]) => uid);

    const categoryCounts: Record<string, number> = {};

    for (const uid of ranked) {
      const unit = records.get(uid);
      if (!unit) continue;

      // Category limits
      const maxPerCategory = includeSource ? 1 : 2;
      if (
        ['operator', 'example'].includes(intent) &&
        topK >= 3 &&
        (categoryCounts[unit.category] ?? 0) >= maxPerCategory
      ) {
        continue;
      }

      const result: SearchResult = {
        id: unit.id,
        category: unit.category,
        name: unit.name,
        description: unit.description.slice(0, 800),
        excerpt: unit.content.slice(0, 1200),
        excerpt_truncated: unit.content.length > 1200,
        source_complete: false,
        source_location: { ...unit.source_location },
        source_hash: unit.source_hash,
        source_revision: unit.source_revision,
        evidence_quality: unit.evidence_quality,
        match: exact.has(uid) ? 'exact_symbol' : 'lexical',
        score: Math.round((scores.get(uid) ?? 0) * 1_000_000) / 1_000_000,
        examples: unit.examples.slice(0, 2),
      };

      // Include source for short units
      if (includeSource && unit.content.length + unit.context.length <= 4000) {
        result.excerpt = unit.content;
        result.excerpt_truncated = false;
        result.source_complete = true;
        result.context = unit.context;
        result.dependencies = unit.dependencies.filter((d) => !(d in this.manifest.source_files));
      }

      // Budget check
      const candidate = { ...response, results: [...response.results, result] };
      if (JSON.stringify(candidate).length > maxChars - 150) {
        // Try trimming
        result.examples = undefined;
        result.excerpt = unit.content.slice(0, 300);
        result.excerpt_truncated = unit.content.length > 300;
        result.source_complete = unit.content.length <= 300 && !unit.context;
        result.context = undefined;
        result.dependencies = undefined;

        const trimmed = { ...response, results: [...response.results, result] };
        if (JSON.stringify(trimmed).length > maxChars - 150) {
          response.truncated = true;
          if (response.omitted_for_budget.length < 3) {
            response.omitted_for_budget.push(uid);
          }
          continue;
        }
      }

      response.results.push(result);
      categoryCounts[unit.category] = (categoryCounts[unit.category] ?? 0) + 1;
      if (response.results.length >= topK) break;
    }

    // Status
    if (response.results.length === 0) {
      response.status =
        response.stale_sources.length > 0
          ? 'stale'
          : response.omitted_for_budget.length > 0
            ? 'budget_limited'
            : 'no_match';
    }

    response.context_chars = JSON.stringify(response).length;
    return response;
  }

  // ── Private ────────────────────────────────────────────────────────────────

  private getUnit(uid: string): KnowledgeUnit {
    const row = this.db.prepare('SELECT record FROM units WHERE id = ?').get(uid) as
      | { record: string }
      | undefined;
    if (!row) throw new KnowledgeError(`Unknown knowledge unit: ${uid}`);
    return KnowledgeUnit.parse(JSON.parse(row.record));
  }
}
