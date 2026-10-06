import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../shared/AuthProvider';
import { Button } from '@ai-cs/shared/components';
import { Input } from '@ai-cs/shared/components';
import { Card } from '@ai-cs/shared/components';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const { login, errorCode } = useAuth();

  useEffect(() => {
    if (errorCode === 'AGENT_CREDENTIALS_NOT_CONFIGURED') {
      setError('请联系管理员先配置客服账号');
    }
  }, [errorCode]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    const success = await login(username, password);

    if (success) {
      navigate('/workspace');
    } else {
      setError('用户名或密码错误');
    }

    setIsLoading(false);
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', backgroundColor: '#f3f4f6' }}>
      <Card padding="lg">
        <div style={{ width: '360px' }}>
          <div style={{ textAlign: 'center', marginBottom: '32px' }}>
            <div
              style={{
                width: '64px',
                height: '64px',
                borderRadius: '16px',
                backgroundColor: '#6366f1',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
              }}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h1 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#1f2937' }}>客服工作台</h1>
            <p style={{ margin: '8px 0 0', fontSize: '14px', color: '#6b7280' }}>欢迎回来，请登录</p>
          </div>

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: '16px' }}>
              <Input
                label="用户名"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                error={error ? ' ' : undefined}
              />
            </div>

            <div style={{ marginBottom: '24px' }}>
              <Input
                label="密码"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                error={error}
              />
            </div>

            <Button type="submit" variant="primary" size="lg" loading={isLoading} style={{ width: '100%' }}>
              登录
            </Button>
          </form>
        </div>
      </Card>
    </div>
  );
}
