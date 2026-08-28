import { menu, type View } from "./investorViews";

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
            onClick={() => onSelect(item)}
            onFocus={() => onPreload(item)}
            onMouseEnter={() => onPreload(item)}
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
