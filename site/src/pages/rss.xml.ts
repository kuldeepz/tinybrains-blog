import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { SITE } from '../config';
import { getPosts } from '../lib/posts';
import { url } from '../lib/url';

export async function GET(context: APIContext) {
  const posts = await getPosts();
  return rss({
    title: SITE.name,
    description: `${SITE.tagline}. ${SITE.description}`,
    site: new URL(url(), context.site).href,
    items: posts.map((p) => ({
      title: p.data.title,
      description: p.data.description,
      pubDate: p.data.date,
      link: new URL(p.href, context.site).href,
      categories: [p.data.topic, p.data.type, p.data.level, ...p.data.tags],
      author: p.data.author,
    })),
    customData: `<language>${SITE.lang}</language>`,
  });
}
