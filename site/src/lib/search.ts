// Client-side search: Pagefind when the index exists (production build),
// otherwise a small keyword search over the embedded post index (astro dev).

export interface LitePost {
  title: string;
  url: string;
  topic: string;
  level: string;
  type: string;
  desc: string;
  tags: string[];
  date: string;
  meta: string;
}

export interface Hit {
  title: string;
  url: string;
  excerpt: string; // may contain <mark> from Pagefind
  topic: string;
  meta: string;
}

const BASE = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '');

let pfPromise: Promise<any> | null = null;

function loadPagefind(): Promise<any> {
  if (!pfPromise) {
    pfPromise = (async () => {
      try {
        const pf = await import(/* @vite-ignore */ `${BASE}/pagefind/pagefind.js`);
        await pf.options?.({ baseUrl: BASE + '/', excerptLength: 22 });
        pf.init?.();
        return pf;
      } catch {
        return null; // no index (astro dev) → local fallback
      }
    })();
  }
  return pfPromise;
}

let local: LitePost[] | null = null;
export function localIndex(): LitePost[] {
  if (!local) {
    try {
      local = JSON.parse(document.getElementById('post-index')?.textContent || '[]');
    } catch {
      local = [];
    }
  }
  return local!;
}

const STOP = new Set('a an and are as at be by do does for from how i in is it of on or should the to what when where which why with vs my me can you your into about exactly really'.split(' '));

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

export function localSearch(q: string, limit = 6): Hit[] {
  const posts = localIndex();
  const terms = q.toLowerCase().replace(/[^\w\s-]/g, ' ').split(/\s+/).filter((t) => t && !STOP.has(t));
  if (!terms.length) return [];
  const scored = posts
    .map((p) => {
      const title = p.title.toLowerCase(), desc = p.desc.toLowerCase(), tags = p.tags.join(' ').toLowerCase(), topic = p.topic.toLowerCase();
      let s = 0;
      for (const t of terms) {
        const stem = t.length > 4 ? t.replace(/(ing|ers|er|es|s)$/, '') : t;
        if (title.includes(stem)) s += 3;
        if (tags.includes(stem)) s += 2;
        if (topic.includes(stem)) s += 2;
        if (desc.includes(stem)) s += 1;
      }
      return { p, s };
    })
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s);
  return scored.slice(0, limit).map(({ p }) => ({ title: p.title, url: p.url, excerpt: escapeHtml(p.desc), topic: p.topic, meta: p.meta }));
}

export async function search(q: string, limit = 6): Promise<{ hits: Hit[]; engine: 'pagefind' | 'local' }> {
  q = q.trim();
  if (!q) return { hits: [], engine: 'local' };
  const pf = await loadPagefind();
  if (pf) {
    try {
      const res = await pf.search(q);
      const data = await Promise.all(res.results.slice(0, limit).map((r: any) => r.data()));
      const byUrl = new Map(localIndex().map((p) => [p.url.replace(/\/$/, ''), p]));
      const hits: Hit[] = data.map((d: any) => {
        const lp = byUrl.get(String(d.url).replace(/\/$/, ''));
        return {
          title: d.meta?.title || lp?.title || d.url,
          url: d.url,
          excerpt: d.excerpt || '',
          topic: d.meta?.topic || lp?.topic || '',
          meta: lp?.meta || '',
        };
      });
      if (hits.length) return { hits, engine: 'pagefind' };
    } catch {
      /* fall through */
    }
  }
  return { hits: localSearch(q, limit), engine: 'local' };
}

/** Warm the Pagefind bundle (e.g. on first focus) so the first query is fast. */
export function preload() {
  loadPagefind();
}

export function stripTags(html: string) {
  const d = document.createElement('div');
  d.innerHTML = html;
  return d.textContent || '';
}
