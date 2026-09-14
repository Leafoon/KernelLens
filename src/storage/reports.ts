/**
 * Report file I/O — writes Markdown and JSON result files.
 *
 * Separated from Store (which handles SQLite) to keep concerns distinct.
 * Reports are written to the .kernellens/reports/ directory within the workspace.
 */

import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import type { Run, Step } from './store.js';

/** Write a Markdown report for a completed run. */
export function writeReport(workspace: string, run: Run, steps: readonly Step[]): string {
  const reportsDir = resolve(workspace, '.kernellens', 'reports');
  if (!existsSync(reportsDir)) {
    mkdirSync(reportsDir, { recursive: true });
  }

  const filename = `${run.id}.md`;
  const filepath = join(reportsDir, filename);

  const lines: string[] = [
    '# KernelLens Report',
    '',
    `**Status:** ${run.status}`,
    `**Task:** ${run.taskType ?? 'unknown'}`,
    `**Goal:** ${run.goal}`,
    '',
  ];

  if (run.gpu) lines.push(`**GPU:** ${run.gpu}`);
  if (run.backend) lines.push(`**Backend:** ${run.backend}`);
  if (run.totalTokens) lines.push(`**Tokens:** ${run.totalTokens}`);
  if (run.durationMs) lines.push(`**Duration:** ${run.durationMs}ms`);
  lines.push('');

  if (run.answer) {
    lines.push('## Answer', '', run.answer, '');
  }

  if (steps.length > 0) {
    lines.push('## Steps', '');
    for (const step of steps) {
      lines.push(`### Step ${step.stepIndex}: ${step.actionType}`);
      if (step.toolName) lines.push(`- **Tool:** ${step.toolName}`);
      if (step.evidenceId) lines.push(`- **Evidence:** ${step.evidenceId}`);
      if (step.durationMs) lines.push(`- **Duration:** ${step.durationMs}ms`);
      lines.push('');
    }
  }

  writeFileSync(filepath, lines.join('\n'), 'utf-8');
  return filepath;
}

/** Write a JSON result file for machine-readable consumption. */
export function writeResultJson(workspace: string, run: Run, steps: readonly Step[]): string {
  const reportsDir = resolve(workspace, '.kernellens', 'reports');
  if (!existsSync(reportsDir)) {
    mkdirSync(reportsDir, { recursive: true });
  }

  const filename = `${run.id}.json`;
  const filepath = join(reportsDir, filename);

  const result = {
    id: run.id,
    status: run.status,
    taskType: run.taskType,
    goal: run.goal,
    gpu: run.gpu,
    backend: run.backend,
    answer: run.answer,
    totalTokens: run.totalTokens,
    durationMs: run.durationMs,
    steps: steps.map((s) => ({
      index: s.stepIndex,
      action: s.actionType,
      tool: s.toolName,
      evidence: s.evidenceId,
      durationMs: s.durationMs,
    })),
  };

  writeFileSync(filepath, JSON.stringify(result, null, 2), 'utf-8');
  return filepath;
}
