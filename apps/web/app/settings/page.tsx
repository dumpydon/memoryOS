"use client";

import {
  KeyRound,
  LockKeyhole,
  Radio,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useState } from "react";

import { InlineNotice } from "@/components/status-state";
import { useWorkspace } from "@/components/workspace-context";

export default function SettingsPage() {
  const { token, mode, scopeId, isOwner, setToken, clearToken, setMode } =
    useWorkspace();
  const [draftToken, setDraftToken] = useState(token);
  const [saved, setSaved] = useState(false);

  function saveToken() {
    setToken(draftToken.trim());
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2200);
  }

  function clear() {
    setDraftToken("");
    clearToken();
    setSaved(false);
  }

  return (
    <div className="page-wrap narrow-page">
      <header className="page-header">
        <div>
          <div className="breadcrumb">
            <span>Workspace</span>
            <span>/</span>
            <strong>Settings</strong>
          </div>
          <h1>Workspace settings</h1>
          <p className="page-subtitle">
            Choose a scope and keep the owner token in this browser session
            only.
          </p>
        </div>
      </header>

      {saved ? (
        <InlineNotice tone="success">
          <ShieldCheck size={15} /> Owner token is available for this session.
        </InlineNotice>
      ) : null}

      <section className="settings-grid">
        <article className="panel settings-card">
          <div className="settings-heading">
            <div className="settings-icon">
              <Radio size={17} />
            </div>
            <div>
              <h2>Execution scope</h2>
              <p>Demo is safe to share. Live uses the private owner scope.</p>
            </div>
          </div>
          <div
            className="mode-switch"
            role="radiogroup"
            aria-label="Execution scope"
          >
            <button
              className={mode === "demo" ? "mode-option active" : "mode-option"}
              type="button"
              role="radio"
              aria-checked={mode === "demo"}
              onClick={() => setMode("demo")}
            >
              <span className="mode-option-title">Demo scope</span>
              <span className="mode-option-detail">
                Seeded, fixture embeddings, no paid calls
              </span>
            </button>
            <button
              className={mode === "live" ? "mode-option active" : "mode-option"}
              type="button"
              role="radio"
              aria-checked={mode === "live"}
              onClick={() => setMode("live")}
            >
              <span className="mode-option-title">Live scope</span>
              <span className="mode-option-detail">
                Owner token, OpenAI providers, private scope
              </span>
            </button>
          </div>
          <div className="scope-readout">
            <span>Current scope</span>
            <code>{scopeId}</code>
          </div>
        </article>

        <article className="panel settings-card">
          <div className="settings-heading">
            <div className="settings-icon">
              <KeyRound size={17} />
            </div>
            <div>
              <h2>Owner access</h2>
              <p>Required for commits, live recall, and non-demo scopes.</p>
            </div>
          </div>
          <label className="field-label" htmlFor="owner-token">
            Owner API token
          </label>
          <div className="token-field">
            <input
              id="owner-token"
              type="password"
              value={draftToken}
              onChange={(event) => setDraftToken(event.target.value)}
              placeholder="Paste token for this session"
              autoComplete="off"
            />
            <button
              className="primary-button"
              type="button"
              onClick={saveToken}
            >
              Save in memory
            </button>
          </div>
          <div className="token-status">
            <span className={isOwner ? "status-dot" : "status-dot idle-dot"} />
            {isOwner ? "Owner token active in memory" : "Public demo access"}
          </div>
          <button className="danger-text-button" type="button" onClick={clear}>
            <Trash2 size={14} />
            Clear token
          </button>
        </article>
      </section>

      <section className="security-note">
        <LockKeyhole size={17} />
        <div>
          <strong>Session-only by design</strong>
          <p>
            The token is held in React memory, never localStorage, cookies, or a
            public environment variable. Reloading the page clears it.
          </p>
        </div>
      </section>
    </div>
  );
}
