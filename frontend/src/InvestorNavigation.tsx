import { useEffect, useRef } from "react";
import { menu, type View } from "./investorViews";

const HOVER_PRELOAD_DELAY_MS = 120;

type InvestorNavigationProps = {
  activeView: View;
  onPreload: (view: View) => void;
  onSelect: (view: View) => void;
};

export default function InvestorNavigation({
  activeView,
  onPreload,
  onSelect,
}: InvestorNavigationProps) {
  const hoverTimer = useRef<number | null>(null);

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
    }, HOVER_PRELOAD_DELAY_MS);
  }

  useEffect(() => cancelHoverPreload, []);

  return (
    <aside className="sidebar">
      <div className="brand">
        <span aria-hidden="true" className="brandMark">O</span>
        <div><strong>Otello</strong><small>Investorverktøy</small></div>
      </div>
      <nav aria-label="Hovedmeny">
        {menu.map((item) => (
          <button
            aria-current={item === activeView ? "page" : undefined}
            className={item === activeView ? "navItem active" : "navItem"}
            key={item}
            onClick={() => {
              cancelHoverPreload();
              onSelect(item);
            }}
            onFocus={() => onPreload(item)}
            onMouseEnter={() => scheduleHoverPreload(item)}
            onMouseLeave={cancelHoverPreload}
            type="button"
          >
            <span aria-hidden="true" className="navDot" />
            {item}
          </button>
        ))}
      </nav>
      <div className="sidebarFooter investorSidebarFooter">
        Teknisk status ligger under Datakvalitet
      </div>
    </aside>
  );
}
