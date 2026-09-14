/**
 * StatusLine — shows current agent status and config.
 *
 * When running, the elapsed timer is self-contained — it only re-renders
 * this component every second, not the entire App tree.
 * Memoized to avoid re-rendering on unrelated parent state changes.
 */

import { Box, Text } from 'ink';
import { memo, useEffect, useRef, useState } from 'react';
import type React from 'react';
import type { TuiStatus } from './types.js';

interface Props {
  readonly status: TuiStatus;
  readonly model?: string;
  readonly stepCount?: number;
}

const STATUS_DISPLAY: Record<TuiStatus, { label: string; color: string }> = {
  idle: { label: 'Ready', color: 'green' },
  running: { label: 'Running', color: 'yellow' },
  waiting_input: { label: 'Waiting for input', color: 'cyan' },
  error: { label: 'Error', color: 'red' },
};

export const StatusLine = memo(function StatusLine({
  status,
  model,
  stepCount,
}: Props): React.ReactElement {
  const { label, color } = STATUS_DISPLAY[status];
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef(Date.now());

  useEffect(() => {
    if (status === 'running') {
      startRef.current = Date.now();
      setElapsed(0);
      const id = setInterval(() => {
        setElapsed(Date.now() - startRef.current);
      }, 1000);
      return () => clearInterval(id);
    }
    setElapsed(0);
  }, [status]);

  return (
    <Box borderStyle="single" borderColor="gray" paddingX={1}>
      <Text color={color} bold>
        {label}
      </Text>
      {status === 'running' && (
        <Text dimColor>
          {' '}
          · {Math.floor(elapsed / 1000)}s{stepCount != null ? ` · ${stepCount} steps` : ''}
        </Text>
      )}
      {model && <Text dimColor> · {model}</Text>}
    </Box>
  );
});
