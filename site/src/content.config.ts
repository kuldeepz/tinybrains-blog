import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';
import { SITE } from './config';

const posts = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/posts' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    date: z.coerce.date(),
    updated: z.coerce.date().optional(),
    topic: z.string(),
    level: z.enum(['Beginner', 'Practitioner', 'Expert']),
    type: z.enum(['Article', 'Tutorial', 'Deep dive']),
    tags: z.array(z.string()).default([]),
    tldr: z.string(),
    takeaways: z.array(z.string()).default([]),
    cover: z.string().optional(),
    sources: z.array(z.object({ title: z.string(), url: z.string() })).default([]),
    author: z.string().default(SITE.author.name),
    draft: z.boolean().default(false),
    version: z.number().default(1),
  }),
});

export const collections = { posts };
