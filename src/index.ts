#!/usr/bin/env node

/**
 * KernelLens — AI agent for TileLang GPU kernel development.
 *
 * This is the package entry point. The CLI is wired up in `cli.ts`.
 */

import { main } from './cli.js';

main().catch((error) => {
  console.error('Fatal error:', error instanceof Error ? error.message : error);
  process.exit(1);
});
