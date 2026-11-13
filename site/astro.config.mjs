// @ts-check
import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import { tinybrainsTheme, codeMetaTransformer } from './src/lib/shiki.mjs';

export default defineConfig({
  site: 'https://kuldeepz.github.io',
  base: '/tinybrains-blog',
  trailingSlash: 'ignore',
  output: 'static',
  integrations: [mdx(), sitemap()],
  markdown: {
    syntaxHighlight: 'shiki',
    shikiConfig: {
      theme: tinybrainsTheme,
      wrap: false,
      transformers: [codeMetaTransformer()],
    },
  },
  build: { format: 'directory' },
});
