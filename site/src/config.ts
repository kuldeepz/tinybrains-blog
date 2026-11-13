// Single source of truth for brand, author, links and site-wide copy.
// Everything user-facing that is not a post lives here.

export const SITE = {
  /** Full brand name. The part before the first "." is rendered bold, the rest muted. */
  name: 'tinybrains.ai',
  tagline: 'AI engineering, in practice',
  description:
    'Hands-on guides to LLMs, agents and RAG — with runnable code, real benchmarks and exact numbers.',
  /** Canonical public URL of the deployed site (including the GitHub Pages base path). */
  url: 'https://kuldeepz.github.io/tinybrains-blog',
  lang: 'en',

  /** Home hero headline. The last two words get the violet → cyan gradient. */
  heroHeadline: 'Build AI systems that hold up in production.',

  /** About page mission statement (streams in word by word). */
  mission:
    'tinybrains.ai is a field notebook for engineers building with language models. Every article ships with runnable code, measured results and the trade-offs we hit along the way — no hype, no hand-waving.',

  author: {
    name: 'Kuldeep Rao',
    initials: 'KR',
    role: 'AI Engineer',
    bio: 'Builds LLM applications, agents and retrieval systems, and writes up what actually worked — with the code and the numbers.',
  },

  socials: [
    { label: 'GitHub', href: 'https://github.com/kuldeepz' },
    { label: 'X', href: '#' },
    { label: 'LinkedIn', href: '#' },
    { label: 'YouTube', href: '#' },
  ],

  /**
   * Newsletter form action (e.g. a Buttondown / ConvertKit / Formspree endpoint).
   * Leave empty to show a "coming soon" message on submit instead of posting.
   * The form posts a single field named `email`.
   */
  newsletterAction: '',
  newsletterCadence: 'weekly, Friday',

  /** Known topics, in topic-map order. Posts may use other topics; they are appended automatically. */
  topics: ['LLMs', 'Agents', 'RAG', 'MLOps', 'Evals', 'Infra', 'Research', 'Tools'],
  levels: ['Beginner', 'Practitioner', 'Expert'] as const,
  types: ['Article', 'Tutorial', 'Deep dive'] as const,

  /** Cycling placeholders for the "Ask the blog" box; the first three become suggestion chips. */
  askPrompts: [
    'How does a tool-calling agent loop work?',
    'Why combine BM25 with vector search?',
    'What is a token, exactly?',
    'How do I rerank retrieval results?',
    'How big is a context window really?',
  ],

  /** Extra items appended to the home ticker (posts are added automatically). */
  tickerNotes: [
    { k: 'NOTE', t: 'new deep-dives land on Fridays' },
    { k: 'LAB', t: 'every code sample is runnable — copy and go' },
  ],

  stack: [
    { group: 'Languages', items: ['Python', 'TypeScript'] },
    { group: 'Models', items: ['Claude', 'GPT', 'Llama', 'Mistral'] },
    { group: 'Retrieval', items: ['pgvector', 'BM25', 'Cross-encoders'] },
    { group: 'Site', items: ['Astro', 'MDX', 'Shiki', 'Pagefind'] },
  ],
} as const;

export type Level = (typeof SITE.levels)[number];
export type PostType = (typeof SITE.types)[number];
