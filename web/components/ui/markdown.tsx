"use client";

import * as React from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

interface MarkdownViewProps {
  content: string;
  className?: string;
}

/**
 * Small dependency-light markdown renderer for chat / docs output.
 *
 * The component overrides below give us styling that matches the rest
 * of the app without pulling in `@tailwindcss/typography`. Code blocks
 * get highlight.js classes from `rehype-highlight`; we style the
 * `.hljs-*` tokens in `globals.css`.
 *
 * `react-markdown` does NOT render raw HTML by default, so this is
 * safe to point at untrusted LLM output.
 */
export function MarkdownView({ content, className }: MarkdownViewProps) {
  return (
    <div className={cn("markdown-body", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

const components: Components = {
  h1: ({ children, ...props }) => (
    <h1
      className="mb-2 mt-4 text-base font-semibold tracking-tight first:mt-0"
      {...props}
    >
      {children}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2
      className="mb-2 mt-4 text-sm font-semibold tracking-tight first:mt-0"
      {...props}
    >
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="mb-1.5 mt-3 text-sm font-semibold first:mt-0" {...props}>
      {children}
    </h3>
  ),
  h4: ({ children, ...props }) => (
    <h4
      className="mb-1 mt-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
      {...props}
    >
      {children}
    </h4>
  ),
  p: ({ children, ...props }) => (
    <p className="my-2 text-sm leading-relaxed first:mt-0 last:mb-0" {...props}>
      {children}
    </p>
  ),
  ul: ({ children, ...props }) => (
    <ul className="my-2 ml-5 list-disc space-y-1 text-sm" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }) => (
    <ol className="my-2 ml-5 list-decimal space-y-1 text-sm" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }) => (
    <li className="leading-relaxed" {...props}>
      {children}
    </li>
  ),
  a: ({ children, ...props }) => (
    <a
      className="text-foreground underline decoration-muted-foreground/40 underline-offset-2 hover:decoration-foreground"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    >
      {children}
    </a>
  ),
  blockquote: ({ children, ...props }) => (
    <blockquote
      className="my-2 border-l-2 border-muted-foreground/30 pl-3 text-sm italic text-muted-foreground"
      {...props}
    >
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }) => {
    // Inline code (no language class) vs fenced code (className like
    // ``language-tsx``). react-markdown routes both through here; we
    // distinguish by whether the parent is a <pre>.
    const isFenced =
      typeof className === "string" && className.startsWith("language-");
    if (isFenced) {
      return (
        <code className={cn("text-[12px]", className)} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="rounded bg-muted px-1.5 py-0.5 font-mono text-[12px]"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }) => (
    <pre
      className="my-2 overflow-x-auto rounded-md border bg-muted/40 p-3 text-[12px] leading-relaxed"
      {...props}
    >
      {children}
    </pre>
  ),
  table: ({ children, ...props }) => (
    <div className="my-2 overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="border-b bg-muted/30 text-xs font-medium" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, ...props }) => (
    <th className="px-2 py-1 text-left font-medium" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="border-t px-2 py-1" {...props}>
      {children}
    </td>
  ),
  hr: ({ ...props }) => <hr className="my-3 border-border" {...props} />,
  strong: ({ children, ...props }) => (
    <strong className="font-semibold" {...props}>
      {children}
    </strong>
  ),
  em: ({ children, ...props }) => (
    <em className="italic" {...props}>
      {children}
    </em>
  ),
};
