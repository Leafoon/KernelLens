/**
 * Knowledge layer — FTS5-powered knowledge retrieval.
 */

export { KnowledgeBase } from './base.js';
export type { SearchResponse, ReadResponse } from './base.js';
export {
  KnowledgeUnit,
  SourceLocation,
  Category,
  SCHEMA_VERSION,
  INDEXES,
  unitId,
} from './schema.js';
export type { IndexName } from './schema.js';
export { tokenize, families, route } from './terms.js';
