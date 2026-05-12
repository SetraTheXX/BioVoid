import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Analyze from './pages/Analyze';
import Atlas from './pages/Atlas';
import System from './pages/System';

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        <Sidebar />
        <main style={{ marginLeft: 200, padding: '20px 28px', flex: 1 }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/analyze" element={<Analyze />} />
            <Route path="/atlas" element={<Atlas />} />
            <Route path="/system" element={<System />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
