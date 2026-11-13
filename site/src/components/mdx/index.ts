import Callout from './Callout.astro';
import PullQuote from './PullQuote.astro';
import Terminal from './Terminal.astro';
import Diagram from './Diagram.astro';
import CodeBlock from './CodeBlock.astro';
import Table from './Table.astro';

/** Components auto-provided to every post body (no imports needed in .mdx files). */
export const mdxComponents = { Callout, PullQuote, Terminal, Diagram, pre: CodeBlock, table: Table };
