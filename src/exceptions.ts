/**
 * KernelLens error hierarchy.
 *
 * All custom errors extend KernelLensError so callers can distinguish
 * expected failures from unexpected ones with a single catch.
 */

/** Base class for all KernelLens-specific errors. */
export class KernelLensError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'KernelLensError';
  }
}

/** Workspace file operations: path traversal, permission, I/O. */
export class WorkspaceError extends KernelLensError {
  constructor(message: string) {
    super(message);
    this.name = 'WorkspaceError';
  }
}

/** Knowledge base operations: missing index, corrupt data. */
export class KnowledgeError extends KernelLensError {
  constructor(message: string) {
    super(message);
    this.name = 'KnowledgeError';
  }
}

/** LLM provider errors: rate limit, auth, network. */
export class ModelError extends KernelLensError {
  constructor(
    message: string,
    public readonly statusCode?: number,
  ) {
    super(message);
    this.name = 'ModelError';
  }
}

/** Decision budget exhausted — the agent loop ran out of steps. */
export class BudgetExhaustedError extends KernelLensError {
  constructor(public readonly maxDecisions: number) {
    super(`Decision budget exhausted after ${maxDecisions} steps`);
    this.name = 'BudgetExhaustedError';
  }
}

/** Context window overflow — cannot fit messages within the model's limit. */
export class ContextOverflowError extends KernelLensError {
  constructor(message = 'Context window overflow') {
    super(message);
    this.name = 'ContextOverflowError';
  }
}

/** Report review rejected the finish action. */
export class FinishRejectedError extends KernelLensError {
  constructor(public readonly reasons: readonly string[]) {
    super(`Finish rejected: ${reasons.join('; ')}`);
    this.name = 'FinishRejectedError';
  }
}
