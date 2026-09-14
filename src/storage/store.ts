/**
 * Store — CRUD operations for sessions, runs, steps, and messages.
 *
 * All methods are synchronous (better-sqlite3 is sync).
 * The store is safe to use from a single-threaded Node.js process.
 */

import { randomUUID } from 'node:crypto';
import type Database from 'better-sqlite3';
import { migrate, openDatabase } from './db.js';

// ── Types ────────────────────────────────────────────────────────────────────

export interface Session {
  readonly id: string;
  readonly workspace: string;
  readonly createdAt: string;
}

export interface Run {
  readonly id: string;
  readonly sessionId: string;
  readonly taskType: string | null;
  readonly goal: string;
  readonly gpu: string | null;
  readonly backend: string | null;
  readonly status: string;
  readonly answer: string | null;
  readonly totalTokens: number | null;
  readonly durationMs: number | null;
  readonly createdAt: string;
  readonly endedAt: string | null;
}

export interface Step {
  readonly id: number;
  readonly runId: string;
  readonly stepIndex: number;
  readonly actionType: string;
  readonly toolName: string | null;
  readonly toolArguments: string | null;
  readonly toolOutput: string | null;
  readonly evidenceId: string | null;
  readonly durationMs: number | null;
  readonly createdAt: string;
}

export interface Message {
  readonly id: number;
  readonly runId: string;
  readonly role: string;
  readonly content: string;
  readonly tokenCount: number | null;
  readonly createdAt: string;
}

// ── SQL column aliases (snake_case → camelCase) ──────────────────────────────

const SESSION_COLS = 'id, workspace, created_at AS createdAt FROM sessions';
const RUN_COLS =
  'id, session_id AS sessionId, task_type AS taskType, goal, gpu, backend, status, answer, total_tokens AS totalTokens, duration_ms AS durationMs, created_at AS createdAt, ended_at AS endedAt FROM runs';
const STEP_COLS =
  'id, run_id AS runId, step_index AS stepIndex, action_type AS actionType, tool_name AS toolName, tool_arguments AS toolArguments, tool_output AS toolOutput, evidence_id AS evidenceId, duration_ms AS durationMs, created_at AS createdAt FROM steps';
const MSG_COLS =
  'id, run_id AS runId, role, content, token_count AS tokenCount, created_at AS createdAt FROM messages';

// ── Store ────────────────────────────────────────────────────────────────────

export class Store {
  private readonly db: Database.Database;

  constructor(dbPath: string) {
    this.db = openDatabase(dbPath);
    migrate(this.db);
  }

  close(): void {
    this.db.close();
  }

  // ── Sessions ─────────────────────────────────────────────────────────────

  createSession(workspace: string): Session {
    const id = randomUUID();
    this.db.prepare('INSERT INTO sessions (id, workspace) VALUES (?, ?)').run(id, workspace);
    return this.getSession(id)!;
  }

  getSession(id: string): Session | undefined {
    return this.db.prepare(`SELECT ${SESSION_COLS} WHERE id = ?`).get(id) as Session | undefined;
  }

  // ── Runs ─────────────────────────────────────────────────────────────────

  createRun(
    sessionId: string,
    goal: string,
    taskType?: string,
    gpu?: string,
    backend?: string,
  ): Run {
    const id = randomUUID();
    this.db
      .prepare(
        'INSERT INTO runs (id, session_id, goal, task_type, gpu, backend) VALUES (?, ?, ?, ?, ?, ?)',
      )
      .run(id, sessionId, goal, taskType ?? null, gpu ?? null, backend ?? null);
    return this.getRun(id)!;
  }

  getRun(id: string): Run | undefined {
    return this.db.prepare(`SELECT ${RUN_COLS} WHERE id = ?`).get(id) as Run | undefined;
  }

  updateRunStatus(id: string, status: string): void {
    this.db
      .prepare("UPDATE runs SET status = ?, updated_at = datetime('now') WHERE id = ?")
      .run(status, id);
  }

  finishRun(
    id: string,
    status: string,
    answer?: string,
    totalTokens?: number,
    durationMs?: number,
  ): void {
    this.db
      .prepare(
        `UPDATE runs SET
          status = ?,
          answer = ?,
          total_tokens = ?,
          duration_ms = ?,
          ended_at = datetime('now')
        WHERE id = ?`,
      )
      .run(status, answer ?? null, totalTokens ?? null, durationMs ?? null, id);
  }

  getRunsBySession(sessionId: string): readonly Run[] {
    return this.db
      .prepare(`SELECT ${RUN_COLS} WHERE session_id = ? ORDER BY createdAt`)
      .all(sessionId) as readonly Run[];
  }

  // ── Steps ────────────────────────────────────────────────────────────────

  recordStep(
    runId: string,
    stepIndex: number,
    actionType: string,
    toolName?: string,
    toolArguments?: string,
    toolOutput?: string,
    evidenceId?: string,
    durationMs?: number,
  ): Step {
    this.db
      .prepare(
        `INSERT INTO steps (run_id, step_index, action_type, tool_name, tool_arguments, tool_output, evidence_id, duration_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        runId,
        stepIndex,
        actionType,
        toolName ?? null,
        toolArguments ?? null,
        toolOutput ?? null,
        evidenceId ?? null,
        durationMs ?? null,
      );
    const row = this.db
      .prepare(`SELECT ${STEP_COLS} WHERE run_id = ? ORDER BY id DESC LIMIT 1`)
      .get(runId) as Step;
    return row;
  }

  getStepsByRun(runId: string): readonly Step[] {
    return this.db
      .prepare(`SELECT ${STEP_COLS} WHERE run_id = ? ORDER BY stepIndex`)
      .all(runId) as readonly Step[];
  }

  // ── Messages ─────────────────────────────────────────────────────────────

  recordMessage(runId: string, role: string, content: string, tokenCount?: number): void {
    this.db
      .prepare('INSERT INTO messages (run_id, role, content, token_count) VALUES (?, ?, ?, ?)')
      .run(runId, role, content, tokenCount ?? null);
  }

  getMessagesByRun(runId: string): readonly Message[] {
    return this.db
      .prepare(`SELECT ${MSG_COLS} WHERE run_id = ? ORDER BY id`)
      .all(runId) as readonly Message[];
  }
}
