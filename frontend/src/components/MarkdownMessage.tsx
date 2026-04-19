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

// Extremely simple Markdown parser that extracts code blocks
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
        
        // Simple line breaks for prose
        return (
          <span key={index}>
            {part.split('\n').map((line, i) => (
              <React.Fragment key={i}>
                {line}
                {i < part.split('\n').length - 1 && <br />}
              </React.Fragment>
            ))}
          </span>
        );
      });

      setHtmlContent(renderedParts);
    }

    parseMarkdown();

    return () => { active = false; };
  }, [content]);

  return <div className="markdown-prose">{htmlContent.length > 0 ? htmlContent : content}</div>;
}
