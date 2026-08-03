const links = [
  { to: '/', label: 'Dashboard', icon: '◉' },
  { to: '/analyze', label: 'Analyze', icon: '▶' },
  { to: '/atlas', label: 'Atlas', icon: '◈' },
  { to: '/system', label: 'System', icon: '⚡' },
];

interface SidebarProps {
  currentPath: string;
  onNavigate: (path: string) => void;
}

export default function Sidebar({ currentPath, onNavigate }: SidebarProps) {
  return (
    <nav className="app-sidebar" aria-label="Primary navigation">
      <div className="sidebar-brand">
        <div className="sidebar-title">
          BioVoid
        </div>
        <div className="sidebar-subtitle">
          Pocket Analysis Prototype
        </div>
      </div>
      {links.map(l => (
        <a
          key={l.to}
          href={l.to}
          aria-current={currentPath === l.to ? 'page' : undefined}
          className={`nav-link${currentPath === l.to ? ' active' : ''}`}
          onClick={(event) => {
            event.preventDefault();
            onNavigate(l.to);
          }}
        >
          <span style={{ fontSize: 14 }}>{l.icon}</span> {l.label}
        </a>
      ))}
      <div className="sidebar-footer">
        v0.1.0 | MIT License
      </div>
    </nav>
  );
}
