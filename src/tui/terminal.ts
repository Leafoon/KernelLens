/**
 * Terminal UI — plain readline-based chat interface.
 *
 * No React, no alternate screen. Just stdin/stdout with colored output.
 * Compatible with any terminal and avoids Ink's full-screen redraw flicker.
 */

import * as readline from 'node:readline';
import chalk from 'chalk';
import type { AgentApplication, TaskMode, TurnResult } from '../application.js';
import { SLASH_COMMANDS } from './types.js';

interface TerminalConfig {
  readonly app: AgentApplication;
  readonly model?: string;
}

const HELP_TEXT = [
  '',
  chalk.bold('KernelLens — TileLang Kernel Workspace'),
  '',
  ...SLASH_COMMANDS.map((c) => `  ${chalk.cyan(c.usage.padEnd(32))} ${c.description}`),
  '',
  `  ${chalk.dim('Ctrl+C 退出')}`,
  '',
].join('\n');

export async function startTerminal(config: TerminalConfig): Promise<void> {
  const { app, model } = config;

  console.log(chalk.green.bold('◌ KernelLens') + chalk.dim(' — TileLang Kernel Workspace'));
  if (model) console.log(chalk.dim(`  Model: ${model}`));
  console.log(chalk.dim('  Type /help for commands, Ctrl+C to exit'));
  console.log();

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: chalk.cyan('❯ '),
  });

  let busy = false;

  const prompt = () => {
    if (!busy) rl.prompt();
  };

  rl.on('line', async (line) => {
    const input = line.trim();
    if (!input) {
      prompt();
      return;
    }

    // Slash commands
    let mode: TaskMode | undefined;
    let goal = input;

    if (input.startsWith('/')) {
      const [cmd, ...rest] = input.split(/\s+/);
      const argument = rest.join(' ');

      switch (cmd) {
        case '/help':
          console.log(HELP_TEXT);
          prompt();
          return;
        case '/clear':
          console.clear();
          prompt();
          return;
        case '/generate':
          mode = 'generate';
          break;
        case '/optimize':
          mode = 'optimize';
          break;
        case '/diagnose':
          mode = 'diagnose';
          break;
        default:
          console.log(chalk.yellow(`Unknown command: ${cmd}. Type /help.`));
          prompt();
          return;
      }

      if (!argument) {
        console.log(chalk.yellow(`Usage: ${cmd} <requirement>`));
        prompt();
        return;
      }
      goal = argument;
    }

    // Send to agent
    busy = true;
    const start = Date.now();
    let streamedContent = '';

    // Stream tokens to stdout as they arrive
    const onToken = (token: string) => {
      if (!streamedContent) {
        // First token — print header before streaming starts
        console.log();
        console.log(chalk.green.bold('KernelLens'));
      }
      streamedContent += token;
      process.stdout.write(token);
    };

    try {
      const result: TurnResult = await app.turn(goal, onToken, mode);
      const elapsed = ((Date.now() - start) / 1000).toFixed(1);

      // If nothing was streamed (tool-only turn), print the answer now
      if (!streamedContent) {
        console.log();
        console.log(chalk.green.bold('KernelLens'));
        console.log(result.answer);
      } else {
        // Ensure a newline after streamed content
        console.log();
      }
      console.log();
      console.log(
        chalk.dim(
          `  ${result.runResult.status} · ${result.runResult.steps.length} steps · ${elapsed}s`,
        ),
      );
      if (result.evidence.length > 0) {
        console.log(chalk.dim(`  Evidence: ${result.evidence.map((e) => e.id).join(', ')}`));
      }
      console.log();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      console.log();
      console.log(chalk.red(`Error: ${msg}`));
      console.log();
    } finally {
      busy = false;
      prompt();
    }
  });

  rl.on('close', () => {
    console.log(chalk.dim('\nBye!'));
    process.exit(0);
  });

  prompt();
}
