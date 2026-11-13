import { getCollection, type CollectionEntry } from 'astro:content';
import { SITE } from '../config';
import { url } from './url';

export type Post = CollectionEntry<'posts'>;

export interface PostView {
  id: string;
  href: string;
  data: Post['data'];
  body: string;
  words: number;
  readMin: number;
  tokens: number;
  tokensLabel: string; // "~3.4k"
  meta: string; // "14 min read"
  dateLabel: string; // "13 Nov 2026"
  shortDate: string; // "13 Nov"
  coverSrc?: string;
  coverBg: string; // CSS background fallback / underlay
  fig: string; // "fig.01 · agents"
  index: number;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function fmtDate(d: Date): string {
  return `${String(d.getUTCDate()).padStart(2, '0')} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function fmtK(n: number): string {
  if (n < 1000) return String(Math.round(n));
  const k = n / 1000;
  return (k >= 100 ? Math.round(k) : k.toFixed(1).replace(/\.0$/, '')) + 'k';
}

export function countWords(body = ''): number {
  const text = body
    .replace(/^\s*(import|export)\s.*$/gm, ' ')
    .replace(/<\/?[A-Za-z][^>]*>/g, ' ')
    .replace(/[#>*_`|[\]()-]+/g, ' ');
  return (text.match(/\S+/g) || []).length;
}

/** Deterministic PRNG (same as the design file) so covers are stable between builds. */
export function rnd(seed: number) {
  let s = seed;
  return () => (s = (s * 9301 + 49297) % 233280) / 233280;
}

export function hash(str: string): number {
  let h = 7;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 100000;
  return h;
}

export function coverGradient(seed: number): string {
  const r = rnd(seed * 7 + 3);
  const x1 = 20 + r() * 60, y1 = 20 + r() * 60, x2 = 10 + r() * 80, y2 = 10 + r() * 80;
  return `radial-gradient(circle at ${x1.toFixed(1)}% ${y1.toFixed(1)}%,rgba(124,92,255,.42),transparent 42%),radial-gradient(circle at ${x2.toFixed(1)}% ${y2.toFixed(1)}%,rgba(34,211,238,.22),transparent 38%),linear-gradient(rgba(255,255,255,.055) 1px,transparent 1px) 0 0/22px 22px,linear-gradient(90deg,rgba(255,255,255,.055) 1px,transparent 1px) 0 0/22px 22px,#0B0C11`;
}

/** Days between two dates, rendered as "today" / "2 days ago" / "13 Nov 2026". */
export function relDays(d: Date, now = new Date()): string {
  const days = Math.floor((now.getTime() - d.getTime()) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  return fmtDate(d);
}

let cache: PostView[] | null = null;

/** All published posts, newest first, with computed read-time and token estimates. */
export async function getPosts(): Promise<PostView[]> {
  if (cache) return cache;
  const entries = await getCollection('posts', ({ data }) => !data.draft);
  entries.sort((a, b) => b.data.date.getTime() - a.data.date.getTime());
  const total = entries.length;
  cache = entries.map((p, i) => {
    const words = countWords(p.body);
    const readMin = Math.max(1, Math.round(words / 230));
    const tokens = Math.round(words * 1.33);
    const tokensLabel = '~' + fmtK(tokens);
    const n = total - i; // oldest post is fig.01
    return {
      id: p.id,
      href: url(`posts/${p.id}/`),
      data: p.data,
      body: p.body ?? '',
      words,
      readMin,
      tokens,
      tokensLabel,
      meta: `${readMin} min read`,
      dateLabel: fmtDate(p.data.date),
      shortDate: fmtDate(p.data.date).slice(0, 6),
      coverSrc: p.data.cover ? url(p.data.cover) : undefined,
      coverBg: coverGradient(hash(p.id)),
      fig: `fig.${String(n).padStart(2, '0')} · ${p.data.topic.toLowerCase()}`,
      index: i,
    };
  });
  return cache;
}

export async function getEntry(id: string): Promise<Post | undefined> {
  const all = await getCollection('posts');
  return all.find((p) => p.id === id);
}

/** Configured topics first (in order), then any extra topics used by posts. */
export function allTopics(posts: PostView[]): string[] {
  const set = new Set<string>(SITE.topics);
  posts.forEach((p) => set.add(p.data.topic));
  return [...set];
}

export function topicCounts(posts: PostView[]): Record<string, number> {
  const c: Record<string, number> = {};
  posts.forEach((p) => (c[p.data.topic] = (c[p.data.topic] || 0) + 1));
  return c;
}

/** Same topic first, then shared tags, then most recent. */
export function related(posts: PostView[], current: PostView, n = 3): PostView[] {
  const others = posts.filter((p) => p.id !== current.id);
  const score = (p: PostView) =>
    (p.data.topic === current.data.topic ? 100 : 0) +
    p.data.tags.filter((t) => current.data.tags.includes(t)).length * 10 -
    p.index * 0.01;
  return [...others].sort((a, b) => score(b) - score(a)).slice(0, n);
}

/** First fenced code block of a post body, for "From the lab" previews. */
export function firstCodeBlock(body = ''): { lang: string; code: string } | null {
  const re = /^```([\w+-]*)[^\n]*\n([\s\S]*?)^```/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(body))) {
    const lang = m[1] || 'text';
    if (['text', 'txt', 'plaintext'].includes(lang)) continue;
    return { lang, code: m[2].replace(/\n$/, '') };
  }
  return null;
}

export function archiveHref(params: Record<string, string> = {}): string {
  const q = new URLSearchParams(params).toString();
  return url('archive/') + (q ? `?${q}` : '');
}
