import { Link } from 'react-router-dom';

export function NotFound() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh', gap: '16px' }}>
      <h1 style={{ fontSize: '48px', margin: 0, color: '#1f2937' }}>404</h1>
      <p style={{ fontSize: '18px', color: '#6b7280' }}>页面未找到</p>
      <Link
        to="/dashboard"
        style={{ padding: '8px 16px', backgroundColor: '#6366f1', color: '#ffffff', borderRadius: '8px', textDecoration: 'none' }}
      >
        返回首页
      </Link>
    </div>
  );
}