/**
 * Secret redaction — removes API keys and tokens from text output.
 *
 * Patterns detected:
 *   - Bearer tokens (Authorization: Bearer sk-...)
 *   - OpenAI-style keys (sk-...)
 *   - Environment variable values that look like keys
 *   - Any registered secret strings
 */

/** Minimum length for a string to be considered a redactable secret. */
const MIN_SECRET_LENGTH = 8;

/**
 * Create a redactor that replaces known secret values in text.
 *
 * Usage:
 *   const redact = createRedactor(['sk-abc123...', 'Bearer xyz...']);
 *   redact('Using key sk-abc123...') // => 'Using key [REDACTED]'
 */
export function createRedactor(secrets: readonly string[]): (text: string) => string {
  // Pre-filter secrets to meaningful lengths
  const validSecrets = secrets.filter((s) => s.length >= MIN_SECRET_LENGTH);

  // Build a combined regex for speed (avoids O(n) replace calls)
  let combinedPattern: RegExp | undefined;
  if (validSecrets.length > 0) {
    const escaped = validSecrets.map((s) => escapeRegex(s));
    combinedPattern = new RegExp(escaped.join('|'), 'g');
  }

  // Pattern-based redaction for keys not explicitly registered
  const patternRedactors: RegExp[] = [
    // Bearer tokens
    /Bearer\s+[A-Za-z0-9\-._~+/]+=*/g,
    // OpenAI-style API keys (sk-...)
    /sk-[A-Za-z0-9]{20,}/g,
    // Anthropic-style API keys (sk-ant-...)
    /sk-ant-[A-Za-z0-9\-]{20,}/g,
  ];

  return (text: string): string => {
    let result = text;

    // Redact registered secrets
    if (combinedPattern) {
      result = result.replace(combinedPattern, '[REDACTED]');
    }

    // Redact pattern-matched secrets
    for (const pattern of patternRedactors) {
      // Reset lastIndex for global regexes
      pattern.lastIndex = 0;
      result = result.replace(pattern, '[REDACTED]');
    }

    return result;
  };
}

/** Escape special regex characters in a string. */
function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Extract secret values from environment variables for auto-registration. */
export function collectSecretsFromEnv(env?: Record<string, string | undefined>): string[] {
  const source = env ?? process.env;
  const secrets: string[] = [];
  const secretPatterns = [/API_KEY$/, /SECRET$/, /TOKEN$/, /PASSWORD$/];

  for (const [key, value] of Object.entries(source)) {
    if (!value) continue;
    if (secretPatterns.some((p) => p.test(key))) {
      secrets.push(value);
    }
  }

  return secrets;
}
