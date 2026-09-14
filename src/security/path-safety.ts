/**
 * Path safety — prevents directory traversal and access to sensitive files.
 *
 * All file operations in the workspace must go through these checks.
 * The workspace root is resolved to an absolute path, and all target
 * paths are checked to ensure they resolve within it.
 */

import { lstatSync } from 'node:fs';
import { isAbsolute, normalize, relative, resolve } from 'node:path';
import { WorkspaceError } from '../exceptions.js';

/** File patterns that are always blocked, even within the workspace. */
export const SENSITIVE_PATTERNS: readonly RegExp[] = [
  /\.env(\..+)?$/, // .env, .env.local, .env.production
  /\.git\b/, // .git directory or files
  /\.kernellens\b/, // internal state directory
  /\.ssh\b/, // SSH keys
  /\.gnupg\b/, // GPG keys
  /\.aws\b/, // AWS credentials
  /node_modules\b/, // dependencies
  /\.DS_Store$/, // macOS metadata
];

/**
 * Resolve a target path against a workspace root.
 * Returns the absolute, normalized path if safe.
 * Throws WorkspaceError if the path escapes the workspace or targets a sensitive file.
 */
export function resolveSafePath(target: string, workspaceRoot: string): string {
  const root = resolve(workspaceRoot);
  const resolved = resolve(root, target);
  const normalized = normalize(resolved);

  // Check: resolved path must be inside workspace
  const rel = relative(root, normalized);
  if (rel.startsWith('..') || isAbsolute(rel)) {
    throw new WorkspaceError(`Path "${target}" escapes workspace root "${root}"`);
  }

  // Check: no sensitive file patterns
  for (const pattern of SENSITIVE_PATTERNS) {
    if (pattern.test(normalized)) {
      throw new WorkspaceError(`Access denied: "${target}" matches sensitive file pattern`);
    }
  }

  // Check: symlink resolution (prevent symlink attacks)
  try {
    const stat = lstatSync(normalized);
    if (stat.isSymbolicLink()) {
      const realPath = resolveSymlink(normalized);
      const realRel = relative(root, realPath);
      if (realRel.startsWith('..') || isAbsolute(realRel)) {
        throw new WorkspaceError(`Symlink "${target}" resolves outside workspace`);
      }
    }
  } catch (e) {
    // File doesn't exist yet — that's fine for write operations
    if (e instanceof WorkspaceError) throw e;
  }

  return normalized;
}

/** Resolve a symlink to its real path. */
function resolveSymlink(path: string): string {
  const { realpathSync } = require('node:fs') as typeof import('node:fs');
  try {
    return realpathSync(path);
  } catch {
    return path;
  }
}

/**
 * Resolve the internal KernelLens state directory within a workspace.
 * Creates the path but does not create the directory itself.
 */
/**
 * Check if a path matches any sensitive file pattern.
 * Non-throwing version for use in workspace traversal.
 */
export function isSensitivePath(absolutePath: string): boolean {
  return SENSITIVE_PATTERNS.some((pattern) => pattern.test(absolutePath));
}

export function internalPath(workspaceRoot: string, ...segments: string[]): string {
  const internal = resolve(workspaceRoot, '.kernellens', ...segments);
  // Ensure the internal path is still within workspace
  const rel = relative(resolve(workspaceRoot), internal);
  if (rel.startsWith('..') || isAbsolute(rel)) {
    throw new WorkspaceError('Internal path escapes workspace');
  }
  return internal;
}
