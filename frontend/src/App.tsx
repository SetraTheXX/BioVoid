import { lazy, Suspense, useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const Analyze = lazy(() => import('./pages/Analyze'));
const Atlas = lazy(() => import('./pages/Atlas'));
const System = lazy(() => import('./pages/System'));

export default function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  function navigate(nextPath: string) {
    if (nextPath !== window.location.pathname) {
      window.history.pushState({}, '', nextPath);
    }
    setPath(nextPath);
  }

  const page = path === '/analyze'
    ? <Analyze />
    : path === '/atlas'
      ? <Atlas />
      : path === '/system'
        ? <System />
        : <Dashboard />;

  return (
    <div className="app-shell">
      <Sidebar currentPath={path} onNavigate={navigate} />
      <main className="app-main" aria-live="polite">
        <Suspense fallback={null}>{page}</Suspense>
      </main>
    </div>
  );
}
