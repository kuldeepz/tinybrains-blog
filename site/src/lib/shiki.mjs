// Shiki theme + transformer matching the hi-fi design's code palette.
// Code surfaces are always dark (#0A0B0F) in both site themes.

/** @type {import('shiki').ThemeRegistration} */
export const tinybrainsTheme = {
  name: 'tinybrains',
  type: 'dark',
  colors: {
    'editor.background': '#0A0B0F',
    'editor.foreground': '#C9CCD6',
  },
  tokenColors: [
    { settings: { foreground: '#C9CCD6' } },
    { scope: ['comment', 'punctuation.definition.comment'], settings: { foreground: '#8B92A3', fontStyle: 'italic' } },
    { scope: ['string', 'string.quoted', 'string.template', 'punctuation.definition.string'], settings: { foreground: '#67E8F9' } },
    { scope: ['constant.numeric', 'constant.language', 'constant.character'], settings: { foreground: '#F5C77E' } },
    { scope: ['keyword', 'storage', 'storage.type', 'storage.modifier', 'keyword.control', 'keyword.operator.new', 'keyword.operator.expression', 'keyword.operator.logical.python'], settings: { foreground: '#B4A5FF' } },
    { scope: ['entity.name.function', 'support.function', 'meta.function-call entity.name.function', 'variable.function'], settings: { foreground: '#F2F3F7', fontStyle: 'bold' } },
    { scope: ['entity.name.type', 'entity.name.class', 'support.type', 'support.class', 'entity.other.inherited-class'], settings: { foreground: '#5EE3F5' } },
    { scope: ['meta.decorator', 'entity.name.function.decorator', 'punctuation.definition.decorator', 'variable.parameter.function.language.special.self', 'variable.language'], settings: { foreground: '#F5C77E' } },
    { scope: ['variable.parameter'], settings: { foreground: '#E3E5EC' } },
    { scope: ['entity.name.tag', 'support.type.property-name', 'meta.object-literal.key'], settings: { foreground: '#A897FF' } },
    { scope: ['entity.other.attribute-name'], settings: { foreground: '#5EE3F5' } },
    { scope: ['punctuation', 'meta.brace', 'keyword.operator'], settings: { foreground: '#9BA1B0' } },
    { scope: ['markup.inserted'], settings: { foreground: '#4ADE80' } },
    { scope: ['markup.deleted'], settings: { foreground: '#F87171' } },
    { scope: ['markup.heading'], settings: { foreground: '#B4A5FF', fontStyle: 'bold' } },
  ],
};

/** Parse "{1,3-5}" line ranges from a fence meta string. */
function parseLines(meta) {
  const m = /\{([\d,\s-]+)\}/.exec(meta || '');
  const set = new Set();
  if (!m) return set;
  for (const part of m[1].split(',')) {
    const [a, b] = part.trim().split('-').map(Number);
    if (!a) continue;
    for (let i = a; i <= (b || a); i++) set.add(i);
  }
  return set;
}

/**
 * Fence meta support:
 *   ```py title="supervisor.py" {3,5-6}
 * - title="…" (or file="…") → data-title on <pre> (rendered in the code header)
 * - {n,m-k}               → highlighted lines
 */
export function codeMetaTransformer() {
  return {
    name: 'tinybrains:code-meta',
    pre(node) {
      const raw = this.options.meta?.__raw || '';
      const t = /(?:title|file)=(?:"([^"]+)"|'([^']+)'|(\S+))/.exec(raw);
      if (t) node.properties['data-title'] = t[1] || t[2] || t[3];
      if (parseLines(raw).size) node.properties['data-hl'] = 'true';
    },
    line(node, line) {
      const hl = parseLines(this.options.meta?.__raw || '');
      if (hl.has(line)) this.addClassToHast(node, 'hl');
    },
  };
}
