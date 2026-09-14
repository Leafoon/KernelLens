/**
 * Workspace — bounded local file operations.
 *
 * All file I/O goes through this class to enforce:
 *   - Workspace containment (no path traversal)
 *   - Sensitive file blocking (.env, .git, .ssh, etc.)
 *   - SHA-256 hashing for optimistic concurrency
 *   - 1MB read limit, 200KB write limit
 *   - No symlinks
 */

import { createHash } from 'node:crypto';
import { mkdir, opendir, readFile, rename, stat, unlink, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
import { MAX_FILE_BYTES } from '../constants.js';
import { WorkspaceError } from '../exceptions.js';
import { isSensitivePath } from '../security/path-safety.js';

/** Maximum file write size (200 KB). */
const MAX_WRITE_BYTES = 200_000;

export class Workspace {
  readonly root: string;

  constructor(path: string) {
    this.root = resolve(path);
  }

  // ── Path resolution ────────────────────────────────────────────────────────

  /**
   * Resolve a user-provided path to an absolute path within the workspace.
   * Rejects traversal, symlinks, and sensitive files.
   */
  async resolvePath(name: string): Promise<string> {
    const absolute = resolve(this.root, name);
    const rel = relative(this.root, absolute);

    // Allow the workspace root itself (e.g. '.')
    if (absolute === this.root) {
      return absolute;
    }

    if (rel.startsWith('..') || rel === '') {
      throw new WorkspaceError('Path is outside workspace');
    }

    // Check sensitive patterns
    if (isSensitivePath(absolute)) {
      throw new WorkspaceError('Path matches a sensitive file pattern');
    }

    // Check symlinks on existing paths
    try {
      const stats = await stat(absolute);
      if (stats.isSymbolicLink()) {
        throw new WorkspaceError('Symlinks are not allowed');
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      // ENOENT is OK — file may not exist yet (for writes)
    }

    return absolute;
  }

  // ── Read ───────────────────────────────────────────────────────────────────

  /**
   * Read a file from the workspace. Returns content with line numbers and SHA-256.
   */
  async readFile(
    path: string,
    startLine = 1,
    maxLines = 200,
  ): Promise<{
    path: string;
    sha256: string;
    totalLines: number;
    startLine: number;
    content: string;
    truncated: boolean;
  }> {
    const absolute = await this.resolvePath(path);
    const content = await readSafe(absolute);
    const lines = content.split('\n');
    const chosen = lines.slice(startLine - 1, startLine - 1 + maxLines);
    const numbered = chosen.map((line, i) => `${startLine + i}: ${line}`).join('\n');

    return {
      path: relative(this.root, absolute),
      sha256: hash(content),
      totalLines: lines.length,
      startLine,
      content: numbered.slice(0, 16_000),
      truncated: numbered.length > 16_000 || startLine - 1 + chosen.length < lines.length,
    };
  }

  /**
   * Read raw bytes from a file (for internal use).
   */
  async readBytes(path: string): Promise<{ absolute: string; data: string }> {
    const absolute = await this.resolvePath(path);
    const data = await readSafe(absolute);
    return { absolute, data };
  }

  // ── List ───────────────────────────────────────────────────────────────────

  /**
   * List files in a directory matching a glob pattern.
   */
  async listFiles(
    path = '.',
    pattern = '*',
    limit = 100,
  ): Promise<{ files: string[]; truncated: boolean; scanLimit: number }> {
    const absolute = await this.resolvePath(path);
    const files: string[] = [];
    const scanLimit = 10_000;
    let scanned = 0;

    const walk = async (dir: string): Promise<void> => {
      if (scanned > scanLimit) return;
      let entries: string[];
      try {
        entries = [];
        const dirHandle = await opendir(dir);
        for await (const entry of dirHandle) {
          entries.push(entry.name);
        }
      } catch {
        return;
      }

      entries.sort();
      for (const name of entries) {
        if (scanned > scanLimit) return;
        scanned++;

        const full = join(dir, name);
        const rel = relative(this.root, full);

        // Skip sensitive paths
        if (isSensitivePath(full)) continue;

        // Skip symlinks
        try {
          const stats = await stat(full);
          if (stats.isSymbolicLink()) continue;
          if (stats.isDirectory()) {
            await walk(full);
            continue;
          }
        } catch {
          continue;
        }

        // Pattern match
        if (matchGlob(name, pattern) || matchGlob(rel, pattern)) {
          files.push(rel);
          if (files.length > limit) return;
        }
      }
    };

    await walk(absolute);

    return {
      files: files.slice(0, limit),
      truncated: files.length > limit,
      scanLimit,
    };
  }

  // ── Search ─────────────────────────────────────────────────────────────────

  /**
   * Search for a literal substring in workspace files.
   */
  async searchText(
    query: string,
    path = '.',
    pattern = '*',
    limit = 100,
  ): Promise<{
    matches: Array<{ path: string; line: number; text: string; sha256: string }>;
    truncated: boolean;
    scannedFiles: number;
  }> {
    const absolute = await this.resolvePath(path);
    const matches: Array<{ path: string; line: number; text: string; sha256: string }> = [];
    let scanned = 0;
    const maxScan = 300;

    const walk = async (dir: string): Promise<void> => {
      if (scanned >= maxScan || matches.length >= limit) return;
      let entries: string[];
      try {
        entries = [];
        const dirHandle = await opendir(dir);
        for await (const entry of dirHandle) {
          entries.push(entry.name);
        }
      } catch {
        return;
      }

      entries.sort();
      for (const name of entries) {
        if (scanned >= maxScan || matches.length >= limit) return;
        const full = join(dir, name);
        if (isSensitivePath(full)) continue;

        try {
          const stats = await stat(full);
          if (stats.isSymbolicLink()) continue;
          if (stats.isDirectory()) {
            await walk(full);
            continue;
          }
        } catch {
          continue;
        }

        if (!matchGlob(name, pattern) && !matchGlob(relative(this.root, full), pattern)) continue;

        scanned++;
        let content: string;
        try {
          content = await readSafe(full);
        } catch {
          continue;
        }

        const fileLines = content.split('\n');
        const rel = relative(this.root, full);
        const sha = hash(content);
        const lowerQuery = query.toLowerCase();

        for (let i = 0; i < fileLines.length; i++) {
          if (fileLines[i]!.toLowerCase().includes(lowerQuery)) {
            matches.push({
              path: rel,
              line: i + 1,
              text: fileLines[i]!.slice(0, 500),
              sha256: sha,
            });
            if (matches.length >= limit) break;
          }
        }
      }
    };

    await walk(absolute);

    return {
      matches,
      truncated: scanned >= maxScan,
      scannedFiles: Math.min(scanned, maxScan),
    };
  }

  // ── Write ──────────────────────────────────────────────────────────────────

  /**
   * Write a file to the workspace with optimistic concurrency.
   * Requires expected_sha256 for overwrites.
   */
  async writeFile(
    path: string,
    content: string,
    expectedSha256 = '',
  ): Promise<{
    path: string;
    sha256: string;
    bytes: number;
    backup: string | null;
  }> {
    const absolute = await this.resolvePath(path);
    const data = Buffer.from(content, 'utf-8');

    if (data.length > MAX_WRITE_BYTES) {
      throw new WorkspaceError(`Write exceeds ${MAX_WRITE_BYTES} byte limit`);
    }

    const newHash = hash(content);
    let existingData: string | null = null;

    try {
      existingData = await readSafe(absolute);
      // File exists — require matching SHA
      if (!expectedSha256 || hash(existingData) !== expectedSha256) {
        throw new WorkspaceError(
          'File exists or has changed; read_file first and provide correct expected_sha256',
        );
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        // File doesn't exist
        if (expectedSha256) {
          throw new WorkspaceError('File no longer exists; cannot overwrite stale version');
        }
      } else if (error instanceof WorkspaceError) {
        throw error;
      } else {
        throw error;
      }
    }

    // Ensure parent directory exists
    await mkdir(dirname(absolute), { recursive: true });

    // Atomic write via temp file
    const tmpPath = join(dirname(absolute), `.kernellens-write-${Date.now()}`);
    let backupPath: string | null = null;

    try {
      await writeFile(tmpPath, data, { mode: 0o600 });

      if (existingData) {
        // Create backup
        const backupDir = join(this.root, '.kernellens', 'backups');
        await mkdir(backupDir, { recursive: true });
        backupPath = join(backupDir, `${hash(existingData)}.bak`);
        try {
          await writeFile(backupPath, existingData, { mode: 0o600 });
        } catch {
          backupPath = null;
        }
      }

      await rename(tmpPath, absolute);
    } finally {
      try {
        await unlink(tmpPath);
      } catch {
        // Ignore cleanup errors
      }
    }

    return {
      path: relative(this.root, absolute),
      sha256: newHash,
      bytes: data.length,
      backup: backupPath ? relative(this.root, backupPath) : null,
    };
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** SHA-256 hash of a string. */
export function hash(data: string): string {
  return createHash('sha256').update(data, 'utf-8').digest('hex');
}

/** Read a file safely with size limit. */
async function readSafe(path: string): Promise<string> {
  const stats = await stat(path);
  if (!stats.isFile()) {
    throw new WorkspaceError('Can only read regular files');
  }
  if (stats.size > MAX_FILE_BYTES) {
    throw new WorkspaceError(`File exceeds ${MAX_FILE_BYTES} byte limit`);
  }
  const content = await readFile(path, 'utf-8');
  if (content.includes('\0')) {
    throw new WorkspaceError('Binary files are not allowed');
  }
  return content;
}

/** Simple glob pattern matching (supports * and ?). */
function matchGlob(name: string, pattern: string): boolean {
  const regex = new RegExp(
    `^${pattern
      .replace(/[.+^${}()|[\]\\]/g, '\\$&')
      .replace(/\*/g, '.*')
      .replace(/\?/g, '.')}$`,
    'i',
  );
  return regex.test(name);
}
