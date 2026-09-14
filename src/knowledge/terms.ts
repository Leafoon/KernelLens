/**
 * Bilingual vocabulary for knowledge search — explicit term expansion.
 * Mirrors python-legacy/kernellens/knowledge/terms.py.
 *
 * These are search aliases, not claims about API semantics or device support.
 */

const TERMS: ReadonlyMap<string, string> = new Map([
  ['flashattention', 'flash attention'],
  ['flashattn', 'flash attention'],
  ['前向', 'forward fwd'],
  ['反向', 'backward bwd'],
  ['分块', 'tile tiled'],
  ['矩阵乘', 'gemm matmul'],
  ['矩阵乘法', 'gemm matmul'],
  ['乘法', 'gemm matmul'],
  ['注意力', 'attention'],
  ['归约', 'reduction reduce'],
  ['规约', 'reduction reduce'],
  ['布局', 'layout'],
  ['转置', 'transpose'],
  ['流水线', 'pipeline pipelined'],
  ['共享内存', 'shared memory'],
  ['寄存器', 'fragment register'],
  ['异步', 'async'],
  ['同步', 'synchronous synchronization'],
  ['拷贝', 'copy'],
  ['复制', 'copy'],
  ['屏障', 'barrier'],
  ['等待', 'wait'],
  ['编译', 'compile compiler'],
  ['编译器', 'compiler'],
  ['报错', 'error'],
  ['错误', 'error'],
  ['后端', 'backend target'],
  ['降级', 'lower lowering'],
  ['代码生成', 'codegen'],
  ['线程', 'thread'],
  ['编程模型', 'programming model'],
  ['语义', 'semantics'],
  ['语法', 'syntax'],
  ['类型', 'type dtype'],
  ['动态形状', 'dynamic shape'],
  ['调优', 'autotune'],
  ['优化', 'optimize'],
  ['稀疏', 'sparse'],
  ['卷积', 'convolution im2col'],
  ['张量', 'tensor'],
  ['分配', 'allocation allocate alloc'],
  ['基本', 'basic'],
  ['基础', 'basic'],
  ['简单', 'basic'],
  ['参数', 'parameters'],
  ['返回值', 'returns'],
  ['用法', 'usage'],
  ['生成', 'generate'],
  ['实现', 'implementation'],
  ['解释', 'explain'],
  ['入门', 'quickstart'],
  ['边界', 'boundary bounds'],
  ['越界', 'bounds'],
  ['向量化', 'vectorize vectorization'],
  ['苹果', 'metal'],
  ['英伟达', 'cuda'],
  ['英特尔', 'cpu'],
  ['黑威尔', 'blackwell'],
]);

const STOP = new Set(
  'a an the is are in on of to for and or with how what does can i it as be from this that tilelang t please explain use usage parameters returns error generate implementation optimize'.split(
    ' ',
  ),
);

const OPERATOR_FAMILIES: ReadonlyMap<string, readonly string[]> = new Map([
  ['gemm', ['gemm', 'matmul', 'gemv']],
  ['attention', ['attention', 'decoding', 'mla', 'gqa', 'mha']],
  ['reduction', ['reduce', 'reduction', 'softmax', 'norm', 'topk']],
  ['layout', ['layout', 'transpose', 'reshape']],
  ['pipeline', ['pipeline', 'pipelined', 'warp_special', 'async_copy']],
  ['convolution', ['conv', 'im2col']],
  ['elementwise', ['elementwise', 'cast', 'fusion']],
]);

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Extract search tokens from text, expanding bilingual terms.
 */
export function tokenize(text: string): string[] {
  // Expand known terms
  let expanded = text;
  const lowerText = text.toLowerCase();
  for (const [word, replacement] of TERMS) {
    if (lowerText.includes(word)) {
      expanded += ` ${replacement}`;
    }
  }

  // CamelCase split
  expanded = expanded.replace(/([a-z])([A-Z])/g, '$1 $2');

  // Extract tokens
  const parts = expanded.toLowerCase().match(/[a-z][a-z0-9_]*|[一-鿿]{2,}/g) ?? [];
  const result: string[] = [];

  for (const part of parts) {
    const baseTerms = [part, ...part.split('_')];
    const allTerms = [
      ...baseTerms,
      ...baseTerms.filter((t) => t.endsWith('s') && t.length > 4).map((t) => t.slice(0, -1)),
    ];

    for (const term of allTerms) {
      if (!STOP.has(term) && term.length > 1 && !result.includes(term)) {
        result.push(term);
      }
    }
  }

  return result;
}

/**
 * Detect operator families from text.
 */
export function families(text: string): string[] {
  const lower = text.toLowerCase();
  const found: string[] = [];
  for (const [family, patterns] of OPERATOR_FAMILIES) {
    if (patterns.some((p) => lower.includes(p))) {
      found.push(family);
    }
  }
  return found;
}

/**
 * Route a query to intent, selected indexes, and extracted symbols.
 */
export function route(query: string): { intent: string; selected: string[]; symbols: string[] } {
  const lower = query.toLowerCase();

  // Extract TileLang API symbols
  const symbolMatches = query.match(/\b(?:T|tilelang)(?:\.[A-Za-z_]\w*)+/g) ?? [];
  const symbols = [...symbolMatches];

  // Classify intent
  const classificationText = lower.replace(/\b(?:T|tilelang)(?:\.[a-z_]\w*)+/gi, ' ');

  if (
    /报错|错误|traceback|error|mismatch|unsupported|lowering|codegen|pass\b|编译失败|编译器/.test(
      classificationText,
    )
  ) {
    return { intent: 'compiler', selected: ['compiler', 'api', 'concept'], symbols };
  }
  if (/生成|写一个|实现|优化|generate|implement|optimi[sz]e|kernel development/.test(lower)) {
    return { intent: 'operator', selected: ['operator', 'example', 'api', 'concept'], symbols };
  }
  if (symbols.length > 0) {
    return { intent: 'api', selected: ['api', 'concept'], symbols };
  }
  if (/后端|target|backend|metal|rocm|hip\b|cuda|硬件|gpu/.test(lower)) {
    return { intent: 'target', selected: ['concept', 'compiler', 'api'], symbols };
  }
  if (/示例|example|tutorial|参考/.test(lower)) {
    return { intent: 'example', selected: ['example', 'concept', 'operator'], symbols };
  }
  return { intent: 'concept', selected: ['concept', 'api', 'operator'], symbols };
}
