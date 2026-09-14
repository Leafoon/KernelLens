/**
 * ChatPane — renders the conversation messages.
 * Memoized: only re-renders when messages array reference changes.
 */

import { Box, Text } from 'ink';
import type React from 'react';
import { memo } from 'react';
import type { ChatMessage } from './types.js';

interface Props {
  readonly messages: readonly ChatMessage[];
}

/** Color for each role. */
const ROLE_COLORS: Record<string, string> = {
  user: 'cyan',
  assistant: 'green',
  system: 'yellow',
};

const ROLE_LABELS: Record<string, string> = {
  user: 'You',
  assistant: 'KernelLens',
  system: 'System',
};

export const ChatPane = memo(function ChatPane({ messages }: Props): React.ReactElement {
  if (messages.length === 0) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text bold color="green">
          KernelLens — TileLang Kernel Workspace
        </Text>
        <Text dimColor>Describe your goal. Use /generate, /optimize, or /diagnose.</Text>
        <Text dimColor>Type /help for available commands.</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {messages.map((msg) => (
        <Box key={msg.timestamp} flexDirection="column" marginBottom={1}>
          <Text bold color={ROLE_COLORS[msg.role] ?? 'white'}>
            {ROLE_LABELS[msg.role] ?? msg.role}
          </Text>
          <Text wrap="wrap">{msg.content}</Text>
        </Box>
      ))}
    </Box>
  );
});
