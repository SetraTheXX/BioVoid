import { useEffect, useState } from 'react';
import { api } from '../services/api';

export default function System() {
  const [health, setHealth] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .health()
      .then((r) => {
        if (!cancelled) {
          setHealth(
            r.status === 'ok'
              ? '● ONLINE — All systems operational'
              : '● OFFLINE'
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHealth('● OFFLINE — Cannot reach server');
          setError('Backend not reachable at http://127.0.0.1:8000');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: 'var(--accent)' }}>
          ⚡ System
        </h2>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 24,
            color: 'var(--text2)',
            fontSize: 14,
          }}
        >
          Checking backend status...
        </div>
      </div>
    );
  }

  const isOnline = health?.includes('ONLINE');

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: 'var(--accent)' }}>
        ⚡ System
      </h2>
      <div
        style={{
          background: 'var(--surface)',
          border: `1px solid ${isOnline ? 'var(--accent)' : 'var(--danger)'}`,
          borderRadius: 8,
          padding: 16,
        }}
      >
        <div
          style={{
            fontSize: 14,
            color: isOnline ? 'var(--accent)' : 'var(--danger)',
            fontWeight: 600,
          }}
        >
          {health}
        </div>
        {error && (
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color: 'var(--text2)',
            }}
          >
            {error}
          </div>
        )}
        {isOnline && (
          <div
            style={{
              marginTop: 8,
              fontSize: 11,
              color: 'var(--text2)',
              fontFamily: 'monospace',
            }}
          >
            API: http://127.0.0.1:8000 (proxied via Vite)
          </div>
        )}
      </div>
    </div>
  );
}
