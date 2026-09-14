/**
 * TUI types — shared interfaces for the terminal UI.
 */

/** A message in the conversation. */
export interface ChatMessage {
  readonly role: 'user' | 'assistant' | 'system';
  readonly content: string;
  readonly timestamp: number;
}

/** TUI status. */
export type TuiStatus = 'idle' | 'running' | 'waiting_input' | 'error';

/** Slash command definition. */
export interface SlashCommand {
  readonly name: string;
  readonly description: string;
  readonly usage: string;
}

/** Available slash commands. */
export const SLASH_COMMANDS: readonly SlashCommand[] = [
  {
    name: '/generate',
    description: 'Generate a new kernel candidate',
    usage: '/generate <requirement>',
  },
  {
    name: '/optimize',
    description: 'Optimize an existing kernel',
    usage: '/optimize <requirement>',
  },
  { name: '/diagnose', description: 'Diagnose or explain code', usage: '/diagnose <requirement>' },
  { name: '/help', description: 'Show help information', usage: '/help' },
  { name: '/clear', description: 'Clear conversation history', usage: '/clear' },
  { name: '/status', description: 'Show current configuration', usage: '/status' },
] as const;
