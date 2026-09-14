import { render } from 'ink-testing-library';
import { describe, expect, it } from 'vitest';
import { ChatPane } from '../../src/tui/ChatPane.js';
import type { ChatMessage } from '../../src/tui/types.js';

describe('ChatPane', () => {
  it('renders welcome message when no messages', () => {
    const { lastFrame } = render(<ChatPane messages={[]} />);
    const output = lastFrame();
    expect(output).toContain('KernelLens');
    expect(output).toContain('/generate');
  });

  it('renders user messages', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'Generate a GEMM kernel', timestamp: 1 },
    ];
    const { lastFrame } = render(<ChatPane messages={messages} />);
    const output = lastFrame();
    expect(output).toContain('You');
    expect(output).toContain('Generate a GEMM kernel');
  });

  it('renders assistant messages', () => {
    const messages: ChatMessage[] = [
      { role: 'assistant', content: 'Generated kernel at artifacts/gemm.py', timestamp: 2 },
    ];
    const { lastFrame } = render(<ChatPane messages={messages} />);
    const output = lastFrame();
    expect(output).toContain('KernelLens');
    expect(output).toContain('Generated kernel at artifacts/gemm.py');
  });

  it('renders system messages', () => {
    const messages: ChatMessage[] = [{ role: 'system', content: 'Unknown command', timestamp: 3 }];
    const { lastFrame } = render(<ChatPane messages={messages} />);
    const output = lastFrame();
    expect(output).toContain('System');
    expect(output).toContain('Unknown command');
  });

  it('renders multiple messages in order', () => {
    const messages: ChatMessage[] = [
      { role: 'user', content: 'Hello', timestamp: 1 },
      { role: 'assistant', content: 'Hi there', timestamp: 2 },
      { role: 'user', content: 'Generate kernel', timestamp: 3 },
    ];
    const { lastFrame } = render(<ChatPane messages={messages} />);
    const output = lastFrame();
    expect(output).toContain('Hello');
    expect(output).toContain('Hi there');
    expect(output).toContain('Generate kernel');
  });
});
