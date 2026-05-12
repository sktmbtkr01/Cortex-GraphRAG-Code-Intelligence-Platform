"use client";

import Link from "next/link";
import { ArrowRight, Brain, ExternalLink, GitBranch as GitHubIcon } from "lucide-react";
import { ShaderAnimation } from "@/components/ui/shader-lines";
import { useAuth } from "@/context/AuthContext";

export default function LandingPage() {
  const { loginWithGitHub, isAuthenticated } = useAuth();

  return (
    <main className="landing-page landing-page-minimal">
      <section className="landing-hero">
        <ShaderAnimation />
        <div className="landing-hero-scrim" />

        <div className="landing-hero-inner">
          <div className="cortex-orb" aria-hidden="true">
            <div className="cortex-orb-ring" />
            <Brain size={74} strokeWidth={1.25} />
          </div>

          <h1>Cortex</h1>
          <p className="landing-hero-copy">GitHub Codebase Intelligence</p>

          <div className="landing-actions">
            {isAuthenticated ? (
              <Link className="landing-primary-action" href="/repos">
                Open dashboard <ArrowRight size={17} />
              </Link>
            ) : (
              <button type="button" className="landing-primary-action" onClick={loginWithGitHub}>
                <GitHubIcon size={18} /> Sign in with GitHub
              </button>
            )}
            {!isAuthenticated && (
              <a
                className="landing-secondary-action"
                href="https://github.com/logout"
                target="_blank"
                rel="noreferrer"
                title="GitHub controls account switching. Sign out on github.com, then return to Cortex and sign in again."
              >
                Use another GitHub account <ExternalLink size={14} />
              </a>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
