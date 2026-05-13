"use client";

import type React from "react";

interface AnimatedLetterTextProps {
  text: string;
  letterToReplace?: string;
  className?: string;
}

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function AnimatedLetterText({ text = "Portfolio", letterToReplace = "o", className }: AnimatedLetterTextProps) {
  const parts: React.ReactNode[] = [];
  let keyIndex = 0;

  const lowerText = text.toLowerCase();
  const lowerLetter = letterToReplace.toLowerCase();
  const replaceIndex = lowerText.indexOf(lowerLetter);

  if (replaceIndex === -1) {
    return <span className={cn("animated-letter-text", className)}>{text}</span>;
  }

  const before = text.slice(0, replaceIndex);
  const after = text.slice(replaceIndex + 1);

  return (
    <span className={cn("animated-letter-text", className)}>
      {before && <span key={keyIndex++}>{before}</span>}

      <span
        className="animated-letter-mark"
        style={{
          filter: "drop-shadow(0 4px 8px rgba(0,0,0,0.25)) drop-shadow(0 2px 4px rgba(0,0,0,0.15))",
        }}
      >
        <svg className="animated-letter-defs" aria-hidden="true">
          <defs>
            <filter id="innerShadow" x="-50%" y="-50%" width="200%" height="200%">
              <feComponentTransfer in="SourceAlpha">
                <feFuncA type="table" tableValues="1 0" />
              </feComponentTransfer>
              <feGaussianBlur stdDeviation="3" />
              <feOffset dx="0" dy="2" result="offsetblur" />
              <feFlood floodColor="rgba(255,255,255,0.15)" result="color" />
              <feComposite in2="offsetblur" operator="in" />
              <feComposite in2="SourceAlpha" operator="in" />
              <feMerge>
                <feMergeNode in="SourceGraphic" />
                <feMergeNode />
              </feMerge>
            </filter>

            <filter id="diamondGlow" x="-150%" y="-150%" width="400%" height="400%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="1.5" result="blur" />
              <feFlood floodColor="#d4ff4a" floodOpacity="0.3" />
              <feComposite in2="blur" operator="in" />
              <feMerge>
                <feMergeNode />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            <linearGradient id="diamondGradient" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#e2ff6a" />
              <stop offset="40%" stopColor="#d4ff4a" />
              <stop offset="60%" stopColor="#c4f934" />
              <stop offset="100%" stopColor="#b8ed28" />
            </linearGradient>

            <linearGradient id="diamondShine" x1="0%" y1="0%" x2="50%" y2="50%">
              <stop offset="0%" stopColor="rgba(255,255,255,0.6)" />
              <stop offset="100%" stopColor="rgba(255,255,255,0)" />
            </linearGradient>

            <radialGradient id="outerShapeGradient" cx="30%" cy="30%" r="70%">
              <stop offset="0%" stopColor="#2a2a2a" />
              <stop offset="100%" stopColor="#0f0f0f" />
            </radialGradient>
          </defs>
        </svg>

        <svg viewBox="0 0 100 100" className="animated-letter-outer">
          <path
            d="M50 0 C55 15, 65 15, 75 10 C70 25, 75 35, 90 35 C80 45, 80 55, 90 65 C75 65, 70 75, 75 90 C65 85, 55 85, 50 100 C45 85, 35 85, 25 90 C30 75, 25 65, 10 65 C20 55, 20 45, 10 35 C25 35, 30 25, 25 10 C35 15, 45 15, 50 0Z"
            fill="url(#outerShapeGradient)"
            filter="url(#innerShadow)"
          />
          <path
            d="M50 0 C55 15, 65 15, 75 10 C70 25, 75 35, 90 35 C80 45, 80 55, 90 65 C75 65, 70 75, 75 90 C65 85, 55 85, 50 100 C45 85, 35 85, 25 90 C30 75, 25 65, 10 65 C20 55, 20 45, 10 35 C25 35, 30 25, 25 10 C35 15, 45 15, 50 0Z"
            fill="none"
            stroke="rgba(255,255,255,0.05)"
            strokeWidth="1"
          />
        </svg>

        <span className="animated-letter-diamond-wrap">
          <svg viewBox="0 0 100 100" className="animated-letter-diamond" filter="url(#diamondGlow)">
            <path d="M50 8 L92 50 L50 92 L8 50 Z" fill="url(#diamondGradient)" />
            <path d="M50 8 L8 50 L50 50 Z" fill="url(#diamondShine)" />
            <path d="M50 18 L82 50 L50 82 L18 50 Z" fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1.5" />
          </svg>
        </span>
      </span>

      {after && <span key={keyIndex++}>{after}</span>}
    </span>
  );
}
