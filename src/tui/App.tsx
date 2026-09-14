/**
 * KernelLens TUI — main Ink application component.
 *
 * Provides a chat-based interface for interacting with the KernelLens agent.
 * Supports slash commands (/generate, /optimize, /diagnose) and natural language input.
 */

import { Box, Text, useApp, useInput } from 'ink';
import TextInput from 'ink-text-input';
import type React from 'react';
import { useCallback, useState } from 'react';
import type { AgentApplication, TurnResult } from '../application.js';
import { ChatPane } from './ChatPane.js';
import { StatusLine } from './StatusLine.js';
import type { ChatMessage, TuiStatus } from './types.js';
import { SLASH_COMMANDS } from './types.js';

interface Props {
  readonly app: AgentApplication;
  readonly initialModel?: string;
}

export function KernelLensApp({ app, initialModel }: Props): React.ReactElement {
  const { exit } = useApp();
  const [messages, setMessages] = useState<readonly ChatMessage[]>([]);
  const [status, setStatus] = useState<TuiStatus>('idle');
  const [input, setInput] = useState('');
  const [model] = useState(initialModel ?? '');
  const [stepCount, setStepCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const addMessage = useCallback((role: ChatMessage['role'], content: string) => {
    setMessages((prev) => [...prev, { role, content, timestamp: Date.now() }]);
  }, []);

  const handleSubmit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      setInput('');

      // Handle slash commands
      if (trimmed.startsWith('/')) {
        const [cmd, ...rest] = trimmed.split(/\s+/);
        const argument = rest.join(' ');

        switch (cmd) {
          case '/help':
            addMessage(
              'system',
              SLASH_COMMANDS.map((c) => `${c.usage.padEnd(30)} ${c.description}`).join('\n'),
            );
            return;
          case '/clear':
            setMessages([]);
            return;
          case '/generate':
          case '/optimize':
          case '/diagnose':
            if (!argument) {
              addMessage('system', `Usage: ${cmd} <requirement>`);
              return;
            }
            break;
          default:
            addMessage('system', `Unknown command: ${cmd}. Type /help for available commands.`);
            return;
        }
      }

      // Send to agent
      addMessage('user', trimmed);
      setStatus('running');
      setStepCount(0);
      setError(null);

      try {
        const result: TurnResult = await app.turn(trimmed);
        addMessage('assistant', result.answer);
        setStepCount(result.runResult.steps.length);
        setStatus('idle');
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Unknown error';
        setError(msg);
        addMessage('system', `Error: ${msg}`);
        setStatus('error');
      }
    },
    [app, addMessage],
  );

  // Ctrl+C to exit
  useInput((inputChar, key) => {
    if (key.ctrl && inputChar === 'c') {
      exit();
    }
  });

  return (
    <Box flexDirection="column" height="100%">
      {/* Header */}
      <Box borderStyle="double" borderColor="green" paddingX={1}>
        <Text bold color="green">
          ◌ KernelLens
        </Text>
        <Text dimColor> — TileLang Kernel Workspace</Text>
      </Box>

      {/* Chat area */}
      <Box flexDirection="column" flexGrow={1} overflow="hidden">
        <ChatPane messages={messages} />
      </Box>

      {/* Error banner */}
      {error && (
        <Box paddingX={1}>
          <Text color="red">⚠ {error}</Text>
        </Box>
      )}

      {/* Status bar — elapsed timer is self-contained inside StatusLine */}
      <StatusLine
        status={status}
        model={model}
        stepCount={status === 'running' ? stepCount : undefined}
      />

      {/* Input */}
      <Box paddingX={1}>
        <Text color="cyan">❯ </Text>
        <TextInput
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          placeholder={
            status === 'running'
              ? 'Agent is running...'
              : 'Describe your goal or type / for commands...'
          }
          focus={status !== 'running'}
        />
      </Box>

      {/* Hint */}
      <Box paddingX={1}>
        <Text dimColor>
          Enter to send · Ctrl+C to exit
          {status === 'running' ? ' · Please wait...' : ''}
        </Text>
      </Box>
    </Box>
  );
}
