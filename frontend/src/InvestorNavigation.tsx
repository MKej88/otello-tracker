import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { navigationGroups, type View } from "./investorViews";

const INTENT_PRELOAD_DELAY_MS = 120;

type InvestorNavigationProps = {
  activeView: View;
  onPreload: (view: View) => void;
  onSelect: (view: View) => void;
};

const navigationIcons: Record<View, ReactNode> = {
  Oversikt: (
    <path d="M4 13h6V4H4zM14 20h6V9h-6zM4 20h6v-3H4zM14 5h6V4h-6z" />
  ),
  NAV: (
    <>
      <path d="m4 17 5-5 4 4 7-8" />
      <path d="M15 8h5v5" />
    </>
  ),
  "NAV-sensitivitet": (
    <>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </>
  ),
  Historikk: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </>
  ),
  Tilbakekjøpsprogram: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M6.1 8a7 7 0 0 1 11.2-2.1L20 8M4 16l2.7 2.1A7 7 0 0 0 17.9 16" />
    </>
  ),
  Cash: (
    <>
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <circle cx="12" cy="12" r="3" />
      <path d="M7 9H6v1M17 15h1v-1" />
    </>
  ),
  Bemobi: (
    <>
      <rect x="7" y="2" width="10" height="20" rx="2" />
      <path d="M10 5h4M11 18h2" />
    </>
  ),
  "BRL/NOK": <path d="M7 7h11M15 4l3 3-3 3M17 17H6M9 14l-3 3 3 3" />,
  Brasil: (
    <>
      <path d="m12 3 9 9-9 9-9-9z" />
      <circle cx="12" cy="12" r="4" />
    </>
  ),
  Konsensus: <path d="M4 20v-6M10 20V9M16 20V4M22 20H2" />,
  Nyheter: (
    <>
      <path d="M5 4h14v16H5z" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </>
  ),
  Datakvalitet: (
    <>
      <path d="M12 3 4 6v6c0 4.5 3.2 7.4 8 9 4.8-1.6 8-4.5 8-9V6z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
};

export default function InvestorNavigation({
  activeView,
  onPreload,
  onSelect,
}: InvestorNavigationProps) {
  const hoverTimer = useRef<number | null>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const mobileMenuId = useId();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  function cancelHoverPreload() {
    if (hoverTimer.current == null) return;
    window.clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
  }

  function scheduleHoverPreload(view: View) {
    cancelHoverPreload();
    hoverTimer.current = window.setTimeout(() => {
      onPreload(view);
      hoverTimer.current = null;
    }, INTENT_PRELOAD_DELAY_MS);
  }

  useEffect(() => cancelHoverPreload, []);

  useEffect(() => {
    if (!mobileMenuOpen) return;

    closeButton.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setMobileMenuOpen(false);
      menuButton.current?.focus();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileMenuOpen]);

  function closeMobileMenu() {
    setMobileMenuOpen(false);
    menuButton.current?.focus();
  }

  function navigationItems(selectView: (view: View) => void) {
    return navigationGroups.map((group) => (
      <div className="navGroup" key={group.label}>
        <span className="navGroupLabel">{group.label}</span>
        <div className="navGroupItems">
          {group.items.map((item) => (
            <button
              aria-current={item === activeView ? "page" : undefined}
              className={item === activeView ? "navItem active" : "navItem"}
              key={item}
              onClick={() => selectView(item)}
              onBlur={cancelHoverPreload}
              onFocus={() => scheduleHoverPreload(item)}
              onMouseEnter={() => scheduleHoverPreload(item)}
              onMouseLeave={cancelHoverPreload}
              type="button"
            >
              <svg
                aria-hidden="true"
                className="navIcon"
                fill="none"
                viewBox="0 0 24 24"
              >
                {navigationIcons[item]}
              </svg>
              <span className="navItemLabel">{item}</span>
            </button>
          ))}
        </div>
      </div>
    ));
  }

  return (
    <>
      <aside className="sidebar desktopSidebar">
        <div className="brand">
          <div>
            <img className="brandLogo" src="/otello-logo.png" alt="Otello" width="350" height="100" />
            <small>Investorverktøy</small>
          </div>
        </div>
        <nav className="investorNav" aria-label="Hovedmeny">
          {navigationItems((view) => {
            cancelHoverPreload();
            onSelect(view);
          })}
        </nav>
        <div className="sidebarFooter investorSidebarFooter">
          Teknisk status ligger under Datakvalitet
        </div>
      </aside>
      <div className="mobileNavigation">
        <div className="mobileNavigationBar">
          <div className="brand">
            <div>
              <img className="brandLogo" src="/otello-logo.png" alt="Otello" width="350" height="100" />
              <small>Investorverktøy</small>
            </div>
          </div>
          <div className="mobileActiveView">
            <span>Aktiv side</span>
            <strong>{activeView}</strong>
          </div>
          <button
            aria-controls={mobileMenuId}
            aria-expanded={mobileMenuOpen}
            className="mobileMenuButton"
            onClick={() => setMobileMenuOpen(true)}
            ref={menuButton}
            type="button"
          >
            <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
            Meny
          </button>
        </div>
        {mobileMenuOpen ? (
          <div
            aria-label="Hovedmeny"
            className="mobileMenuPanel"
            id={mobileMenuId}
            role="dialog"
          >
            <div className="mobileMenuPanelHeader">
              <strong>Navigasjon</strong>
              <button
                aria-label="Lukk meny"
                className="mobileMenuClose"
                onClick={closeMobileMenu}
                ref={closeButton}
                type="button"
              >
                <svg aria-hidden="true" fill="none" viewBox="0 0 24 24">
                  <path d="m6 6 12 12M18 6 6 18" />
                </svg>
                Lukk
              </button>
            </div>
            <nav className="investorNav mobileInvestorNav" aria-label="Sider">
              {navigationItems((view) => {
                cancelHoverPreload();
                onSelect(view);
                closeMobileMenu();
              })}
            </nav>
          </div>
        ) : null}
      </div>
    </>
  );
}
