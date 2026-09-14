/**
 * Security utilities — redaction and path safety.
 */

export { createRedactor, collectSecretsFromEnv } from './redactor.js';
export {
  resolveSafePath,
  internalPath,
  isSensitivePath,
  SENSITIVE_PATTERNS,
} from './path-safety.js';
