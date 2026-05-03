"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { QUICK_PROMPTS } from "@/app/utils/quickPrompts";

export default function QuickPrompts({ repo }: { repo: string }) {
  const router = useRouter();

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {QUICK_PROMPTS.map((item) => {
        const q = item.buildPrompt(repo);
        const href = `/query?repo=${encodeURIComponent(repo)}&q=${encodeURIComponent(q)}&autorun=1`;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => router.push(href)}
            style={{
              minHeight: 32,
              background: "rgba(119, 200, 107, 0.08)",
              border: "1px solid var(--line)",
              color: "var(--foreground)",
              borderRadius: 8,
              fontSize: 12,
              fontWeight: 600,
              padding: "0 10px",
            }}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
