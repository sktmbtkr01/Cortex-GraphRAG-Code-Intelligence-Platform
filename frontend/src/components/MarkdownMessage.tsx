"use client";

import React, { useEffect, useState } from "react";
import { createHighlighter, Highlighter } from "shiki";

let highlighter: Highlighter | null = null;
const initShiki = async () => {
  if (!highlighter) {
    highlighter = await createHighlighter({
      themes: ["github-dark"],
      langs: ["python", "javascript", "typescript", "json", "bash", "go", "sql"]
    });
  }
  return highlighter;
};

function renderInline(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function renderMarkdownText(text: string, keyPrefix: string) {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = () => {
    if (listItems.length === 0) return;
    const listKey = `${keyPrefix}-list-${nodes.length}`;
    nodes.push(
      <ul key={listKey}>
        {listItems.map((item, index) => (
          <li key={`${listKey}-${index}`}>{renderInline(item)}</li>
        ))}
      </ul>
    );
    listItems = [];
  };

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    const bullet = trimmed.match(/^[-*]\s+(.+)$/);

    if (bullet) {
      listItems.push(bullet[1]);
      return;
    }

    flushList();

    if (!trimmed) {
      nodes.push(<div key={`${keyPrefix}-space-${index}`} className="markdown-gap" />);
      return;
    }

    if (trimmed.startsWith("### ")) {
      nodes.push(<h3 key={`${keyPrefix}-h3-${index}`}>{renderInline(trimmed.slice(4))}</h3>);
    } else if (trimmed.startsWith("## ")) {
      nodes.push(<h2 key={`${keyPrefix}-h2-${index}`}>{renderInline(trimmed.slice(3))}</h2>);
    } else if (trimmed.startsWith("# ")) {
      nodes.push(<h2 key={`${keyPrefix}-h1-${index}`}>{renderInline(trimmed.slice(2))}</h2>);
    } else {
      nodes.push(<p key={`${keyPrefix}-p-${index}`}>{renderInline(trimmed)}</p>);
    }
  });

  flushList();
  return nodes;
}

// Lightweight Markdown renderer with Shiki-powered fenced code blocks.
export default function MarkdownMessage({ content }: { content: string }) {
  const [htmlContent, setHtmlContent] = useState<React.ReactNode[]>([]);

  useEffect(() => {
    let active = true;

    async function parseMarkdown() {
      const parts = content.split(/(```[\s\S]*?```)/g);
      const hl = await initShiki();

      if (!active) return;

      const renderedParts = parts.map((part, index) => {
        if (part.startsWith("```") && part.endsWith("```")) {
          const lines = part.slice(3, -3).trim().split('\n');
          const lang = lines[0].trim() || "text";
          const code = lines.slice(1).join('\n');
          
          if (hl) {
            try {
              const html = hl.codeToHtml(code, { lang: lang === "text" ? "javascript" : lang, theme: "github-dark" });
              return <div key={index} dangerouslySetInnerHTML={{ __html: html }} className="code-block-wrapper" />;
            } catch (e) {
              return <pre key={index} className="fallback-code"><code>{code}</code></pre>;
            }
          }
          return <pre key={index} className="fallback-code"><code>{code}</code></pre>;
        }
        
        return <React.Fragment key={index}>{renderMarkdownText(part, `md-${index}`)}</React.Fragment>;
      });

      setHtmlContent(renderedParts);
    }

    parseMarkdown();

    return () => { active = false; };
  }, [content]);

  return <div className="markdown-prose">{htmlContent.length > 0 ? htmlContent : content}</div>;
}
