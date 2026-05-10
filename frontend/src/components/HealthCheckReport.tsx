"use client";

import React from "react";
import MarkdownMessage from "@/components/MarkdownMessage";

type Section = {
  title: string;
  body: string;
};

const SECTION_RE = /^(?:#{1,3}\s*)?(?:\d+\.\s+)?(Overall Summary|Architecture And Coupling Signals|Security-Sensitive Areas To Review|Secret Exposure Signals|Dependency Surface|Testing And Maintainability Signals|Recommended Next Actions|Evidence Reviewed)\s*$/i;

function splitHealthReport(content: string): { intro: string; sections: Section[] } {
  const lines = content.split(/\r?\n/);
  const intro: string[] = [];
  const sections: Section[] = [];
  let current: Section | null = null;

  for (const line of lines) {
    const match = line.trim().match(SECTION_RE);
    if (match) {
      if (current) sections.push(current);
      current = { title: match[1], body: "" };
      continue;
    }

    if (current) {
      current.body += `${line}\n`;
    } else {
      intro.push(line);
    }
  }

  if (current) sections.push(current);
  return { intro: intro.join("\n").trim(), sections };
}

export default function HealthCheckReport({ content }: { content: string }) {
  const { intro, sections } = splitHealthReport(content);

  if (sections.length === 0) {
    return <MarkdownMessage content={content} />;
  }

  return (
    <div className="health-report">
      {intro && <MarkdownMessage content={intro} />}
      <div className="health-report-sections">
        {sections.map((section, index) => {
          const defaultOpen = index === 0 || section.title === "Recommended Next Actions";
          return (
            <details key={section.title} className="health-section" open={defaultOpen}>
              <summary>
                <span>{section.title}</span>
              </summary>
              <div className="health-section-body">
                <MarkdownMessage content={section.body.trim()} />
              </div>
            </details>
          );
        })}
      </div>
    </div>
  );
}
