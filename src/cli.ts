/**
 * CLI entry point for KernelLens.
 *
 * Parses command-line arguments and dispatches to the appropriate mode
 * (interactive terminal, single-shot, or utility commands).
 */

import { resolve } from 'node:path';
import { Command } from 'commander';
import { AgentApplication } from './application.js';
import { loadSettings } from './config/loader.js';
import { OpenAIProvider } from './models/client.js';
import { ToolRegistry } from './tools/registry.js';
import { startTerminal } from './tui/terminal.js';

async function startTui(opts: Record<string, string | undefined>): Promise<void> {
  const config = loadSettings(opts.env);
  const workspaceRoot = resolve(opts.workspace ?? config.runtime.workspace);
  const model = opts.model ?? config.model.model;
  const maxDecisions = Number(opts.maxDecisions ?? config.runtime.maxDecisions);

  const provider = new OpenAIProvider({
    model,
    apiKey: config.model.apiKey,
    baseUrl: config.model.baseUrl,
    contextWindow: config.model.contextWindow ?? 128_000,
    maxOutputTokens: config.model.maxOutputTokens ?? 4_096,
  });

  const registry = new ToolRegistry({ tools: [] });

  const application = new AgentApplication({
    provider,
    registry,
    emit: () => {},
    maxDecisions,
    workspaceRoot,
  });

  await startTerminal({ app: application, model });
}

export function createCli(): Command {
  const program = new Command()
    .name('kernellens')
    .description('AI agent for TileLang GPU kernel development and optimization')
    .version('0.2.0');

  // Default action: start TUI (same as `run`)
  program
    .option('-w, --workspace <path>', 'Working directory for kernel files')
    .option('-m, --model <name>', 'LLM model to use')
    .option('--max-decisions <n>', 'Maximum decisions per run')
    .option('--env <path>', 'Path to .env file')
    .action(async (opts) => {
      await startTui(opts);
    });

  program
    .command('run')
    .description('Start an interactive agent session')
    .option('-w, --workspace <path>', 'Working directory for kernel files')
    .option('-m, --model <name>', 'LLM model to use')
    .option('--max-decisions <n>', 'Maximum decisions per run')
    .option('--env <path>', 'Path to .env file')
    .action(async (opts) => {
      await startTui(opts);
    });

  program
    .command('config')
    .description('Show current configuration')
    .action(async () => {
      const config = loadSettings();
      console.log(
        JSON.stringify(
          {
            model: config.model.model,
            baseUrl: config.model.baseUrl,
            maxDecisions: config.runtime.maxDecisions,
            workspace: config.runtime.workspace,
          },
          null,
          2,
        ),
      );
    });

  program
    .command('doctor')
    .description('Check environment health')
    .action(async () => {
      console.log('KernelLens Doctor');
      try {
        const config = loadSettings();
        console.log(`  ✓ Model configured: ${config.model.model}`);
        console.log(`  ✓ API key set: ${config.model.apiKey.slice(0, 4)}...`);
        console.log(`  ✓ Workspace: ${config.runtime.workspace}`);
      } catch (error) {
        console.log(`  ✗ Configuration error: ${error instanceof Error ? error.message : error}`);
      }
    });

  return program;
}

export async function main(argv = process.argv): Promise<void> {
  const program = createCli();
  await program.parseAsync(argv);
}
