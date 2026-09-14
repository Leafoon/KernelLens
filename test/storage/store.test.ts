import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { Store } from '../../src/storage/store.js';

function createStore(): { store: Store; dir: string } {
  const dir = mkdtempSync(join(tmpdir(), 'kl-store-test-'));
  const store = new Store(join(dir, 'test.db'));
  return { store, dir };
}

describe('Store', () => {
  let store: Store;
  let dir: string;

  afterEach(() => {
    store?.close();
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('creates and retrieves sessions', () => {
    ({ store, dir } = createStore());
    const session = store.createSession('/workspace');
    expect(session.id).toBeTruthy();
    expect(session.workspace).toBe('/workspace');

    const retrieved = store.getSession(session.id);
    expect(retrieved?.id).toBe(session.id);
  });

  it('creates and retrieves runs', () => {
    ({ store, dir } = createStore());
    const session = store.createSession('/workspace');
    const run = store.createRun(session.id, 'Build GEMM', 'generate', 'A100');

    expect(run.id).toBeTruthy();
    expect(run.goal).toBe('Build GEMM');
    expect(run.taskType).toBe('generate');
    expect(run.gpu).toBe('A100');
    expect(run.status).toBe('PENDING');
  });

  it('finishes a run', () => {
    ({ store, dir } = createStore());
    const session = store.createSession('/workspace');
    const run = store.createRun(session.id, 'Build GEMM');

    store.finishRun(run.id, 'COMPLETED', 'Here is the answer.', 5000, 3000);

    const updated = store.getRun(run.id)!;
    expect(updated.status).toBe('COMPLETED');
    expect(updated.answer).toBe('Here is the answer.');
    expect(updated.totalTokens).toBe(5000);
    expect(updated.durationMs).toBe(3000);
    expect(updated.endedAt).toBeTruthy();
  });

  it('records and retrieves steps', () => {
    ({ store, dir } = createStore());
    const session = store.createSession('/workspace');
    const run = store.createRun(session.id, 'Build GEMM');

    store.recordStep(
      run.id,
      0,
      'call_tool',
      'read_file',
      '{"path":"a.py"}',
      'file content',
      'E1',
      100,
    );
    store.recordStep(run.id, 1, 'call_tool', 'write_file', '{"path":"b.py"}', 'ok', 'E2', 50);

    const steps = store.getStepsByRun(run.id);
    expect(steps).toHaveLength(2);
    expect(steps[0].stepIndex).toBe(0);
    expect(steps[0].toolName).toBe('read_file');
    expect(steps[0].evidenceId).toBe('E1');
    expect(steps[1].stepIndex).toBe(1);
  });

  it('records and retrieves messages', () => {
    ({ store, dir } = createStore());
    const session = store.createSession('/workspace');
    const run = store.createRun(session.id, 'Build GEMM');

    store.recordMessage(run.id, 'user', 'Build a GEMM kernel', 100);
    store.recordMessage(run.id, 'assistant', 'Here is the kernel...', 500);

    const messages = store.getMessagesByRun(run.id);
    expect(messages).toHaveLength(2);
    expect(messages[0].role).toBe('user');
    expect(messages[1].role).toBe('assistant');
  });

  it('gets runs by session', () => {
    ({ store, dir } = createStore());
    const session = store.createSession('/workspace');
    store.createRun(session.id, 'Goal 1');
    store.createRun(session.id, 'Goal 2');
    store.createRun(session.id, 'Goal 3');

    const runs = store.getRunsBySession(session.id);
    expect(runs).toHaveLength(3);
  });
});
