import { QueryProvider } from "@/components/query-provider";
import { SidebarNav } from "@/components/sidebar-nav";
import { DotMatrixWordmark } from "@/components/dot-matrix-wordmark";
import { ThemeProvider } from "@/components/theme-provider";
import { WorkspaceProvider } from "@/components/workspace-context";
import { WorkspaceMain } from "@/components/workspace-main";
import Link from "next/link";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <WorkspaceProvider>
          <div className="memoryos-shell">
            <div className="footer-curtain-stage">
              <DotMatrixWordmark />
              <div className="curtain-footer">
                <span>
                  © 2026 MemoryOS, made with{" "}
                  <span
                    className="curtain-lizard"
                    role="img"
                    aria-label="lizard"
                  >
                    🦎
                  </span>{" "}
                  in India
                </span>
                <nav className="curtain-footer-links" aria-label="Legal">
                  <span className="curtain-link-wrap">
                    <Link
                      href="/legal#terms-of-use"
                      title="Built by Dumpydon"
                      aria-describedby="curtain-tooltip-terms"
                      aria-label="Terms of use — Built by Dumpydon"
                    >
                      Terms of use
                    </Link>
                    <span
                      id="curtain-tooltip-terms"
                      className="curtain-link-tooltip"
                      role="tooltip"
                    >
                      <strong>Built by Dumpydon</strong>
                      <a href="mailto:apiyush171@gmail.com">
                        apiyush171@gmail.com
                      </a>
                    </span>
                  </span>
                  <span className="curtain-footer-divider" aria-hidden="true">
                    |
                  </span>
                  <span className="curtain-link-wrap">
                    <Link
                      href="/legal#privacy-policy"
                      title="Built by Dumpydon"
                      aria-describedby="curtain-tooltip-privacy"
                      aria-label="Privacy policy — Built by Dumpydon"
                    >
                      Privacy policy
                    </Link>
                    <span
                      id="curtain-tooltip-privacy"
                      className="curtain-link-tooltip"
                      role="tooltip"
                    >
                      <strong>Built by Dumpydon</strong>
                      <a href="mailto:apiyush171@gmail.com">
                        apiyush171@gmail.com
                      </a>
                    </span>
                  </span>
                </nav>
              </div>
            </div>
            <div className="footer-curtain-content">
              <div className="app-frame">
                <aside className="sidebar">
                  <div className="brand-lockup">
                    <div className="brand-mark" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </div>
                    <div>
                      <div className="brand-name">MemoryOS</div>
                      <div className="brand-caption">agent memory layer</div>
                    </div>
                  </div>

                  <SidebarNav />
                </aside>

                <WorkspaceMain>{children}</WorkspaceMain>
              </div>
            </div>
            <div className="footer-curtain-spacer" aria-hidden="true" />
          </div>
        </WorkspaceProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
