import { NavLink } from 'react-router-dom';

const links = [
  { to: '/', label: 'Dashboard', icon: '◉' },
  { to: '/analyze', label: 'Analyze', icon: '▶' },
  { to: '/atlas', label: 'Atlas', icon: '◈' },
  { to: '/system', label: 'System', icon: '⚡' },
];

export default function Sidebar() {
  return (
    <nav style={{
      width: 200, background: 'var(--surface)', borderRight: '1px solid var(--border)',
      position: 'fixed', top: 0, left: 0, height: '100vh', padding: '16px 0',
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{ padding: '0 16px 24px' }}>
        <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--accent)', letterSpacing: -0.5 }}>
          BioVoid
        </div>
        <div style={{ fontSize: 9, color: 'var(--text2)', letterSpacing: 2, textTransform: 'uppercase', marginTop: 2 }}>
          Pocket Discovery Engine
        </div>
      </div>
      {links.map(l => (
        <NavLink key={l.to} to={l.to} end={l.to === '/'}
          style={({ isActive }) => ({
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '10px 16px', color: isActive ? 'var(--accent)' : 'var(--text2)',
            background: isActive ? 'rgba(0,255,136,0.06)' : 'transparent',
            borderLeft: `3px solid ${isActive ? 'var(--accent)' : 'transparent'}`,
            textDecoration: 'none', fontSize: 13, fontWeight: 500, transition: '.15s',
          })}
        >
          <span style={{ fontSize: 14 }}>{l.icon}</span> {l.label}
        </NavLink>
      ))}
      <div style={{ marginTop: 'auto', padding: '12px 16px', borderTop: '1px solid var(--border)', fontSize: 10, color: 'var(--text2)' }}>
        v1.0.0 — MIT License
      </div>
    </nav>
  );
}
