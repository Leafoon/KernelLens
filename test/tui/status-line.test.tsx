import { render } from 'ink-testing-library';
import { describe, expect, it } from 'vitest';
import { StatusLine } from '../../src/tui/StatusLine.js';

describe('StatusLine', () => {
  it('renders idle status', () => {
    const { lastFrame } = render(<StatusLine status="idle" />);
    const output = lastFrame();
    expect(output).toContain('Ready');
  });

  it('renders running status with step count', () => {
    const { lastFrame } = render(<StatusLine status="running" stepCount={3} />);
    const output = lastFrame();
    expect(output).toContain('Running');
    expect(output).toContain('3 steps');
  });

  it('renders running status with elapsed timer', () => {
    const { lastFrame } = render(<StatusLine status="running" />);
    const output = lastFrame();
    expect(output).toContain('Running');
    expect(output).toContain('0s');
  });

  it('renders error status', () => {
    const { lastFrame } = render(<StatusLine status="error" />);
    const output = lastFrame();
    expect(output).toContain('Error');
  });

  it('renders waiting_input status', () => {
    const { lastFrame } = render(<StatusLine status="waiting_input" />);
    const output = lastFrame();
    expect(output).toContain('Waiting for input');
  });

  it('renders model name when provided', () => {
    const { lastFrame } = render(<StatusLine status="idle" model="gpt-4o" />);
    const output = lastFrame();
    expect(output).toContain('gpt-4o');
  });

  it('does not render elapsed when idle', () => {
    const { lastFrame } = render(<StatusLine status="idle" />);
    const output = lastFrame();
    expect(output).not.toContain('0s');
  });
});
