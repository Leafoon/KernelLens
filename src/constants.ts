/**
 * Global constants for KernelLens.
 *
 * All magic numbers and thresholds are centralized here for easy tuning.
 */

// ── Input Limits ──────────────────────────────────────────────────────────────
/** Maximum character length for a user goal. */
export const MAX_GOAL_LENGTH = 20_000;

// ── Tool Output Limits ────────────────────────────────────────────────────────
/** Maximum characters returned from any tool result before truncation. */
export const MAX_TOOL_RESULT_CHARS = 22_000;
/** Characters kept in a truncated preview. */
export const TOOL_RESULT_PREVIEW_CHARS = 21_000;

// ── Knowledge Search Limits ───────────────────────────────────────────────────
/** Maximum characters for a knowledge excerpt in search results. */
export const KNOWLEDGE_EXCERPT_LIMIT = 1_200;
/** Maximum characters for a knowledge source read. */
export const KNOWLEDGE_SOURCE_LIMIT = 4_000;
/** Fallback character limit when excerpt budget is exhausted. */
export const KNOWLEDGE_FALLBACK_LIMIT = 300;
/** Maximum number of search results returned. */
export const KNOWLEDGE_MAX_RESULTS = 10;

// ── Network / Streaming ───────────────────────────────────────────────────────
/** Maximum bytes accepted in a single HTTP response. */
export const MAX_RESPONSE_BYTES = 2_000_000;
/** Seconds to wait for an SSE chunk before timing out. */
export const SSE_CHUNK_TIMEOUT_SEC = 5;
/** Interval in seconds for coalescing streamed text into displayable chunks. */
export const STREAM_COALESCE_INTERVAL_SEC = 0.05;

// ── Context Window ────────────────────────────────────────────────────────────
/** Ratio of context window to trigger compaction at. */
export const COMPACTION_TARGET_RATIO = 0.55;
/** Divisor for computing token estimation margin. */
export const TOKEN_MARGIN_DIVISOR = 100;
/** Minimum token estimation margin. */
export const TOKEN_MARGIN_MIN = 1024;

// ── Retry ─────────────────────────────────────────────────────────────────────
/** Maximum retry backoff in seconds. */
export const MAX_RETRY_BACKOFF_SEC = 4;
/** Maximum consecutive retry attempts for API calls. */
export const MAX_RETRY_ATTEMPTS = 3;

// ── Workspace ─────────────────────────────────────────────────────────────────
/** Maximum file size in bytes for workspace reads. */
export const MAX_FILE_BYTES = 1_000_000;
/** Default file listing limit. */
export const DEFAULT_LIST_LIMIT = 100;
/** Maximum directory scan depth for file listing. */
export const MAX_SCAN_ENTRIES = 10_000;

// ── Decision Budget ───────────────────────────────────────────────────────────
/** Default maximum decisions per agent run. */
export const DEFAULT_MAX_DECISIONS = 30;

/** Application version (synced with package.json). */
export const APP_VERSION = '0.2.0';
