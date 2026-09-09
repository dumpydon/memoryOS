import { QueryProvider } from "@/components/query-provider";
import { SidebarNav } from "@/components/sidebar-nav";
import { DotMatrixWordmark } from "@/components/dot-matrix-wordmark";
import { ThemeProvider } from "@/components/theme-provider";
import { WorkspaceProvider } from "@/components/workspace-context";
import { WorkspaceMain } from "@/components/workspace-main";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <QueryProvider>
        <WorkspaceProvider>
          <div className="memoryos-shell">
            <div className="footer-curtain-stage">
              <DotMatrixWordmark />
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
