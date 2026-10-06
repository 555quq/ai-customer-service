import type { WidgetConfig } from '@ai-cs/shared/types';

interface WidgetLauncherProps {
  config: WidgetConfig;
  isOpen: boolean;
  onClick: () => void;
}

/** 腾讯云 Kiki 风格：圆形头像启动按钮 */
export function WidgetLauncher({ config, isOpen, onClick }: WidgetLauncherProps) {
  return (
    <button
      onClick={onClick}
      className={`kiki-launcher ${isOpen ? 'kiki-launcher--open' : ''}`}
      style={{
        [config.position === 'left' ? 'left' : 'right']: '24px',
        zIndex: config.zIndex,
      }}
      aria-label={isOpen ? '关闭 AI 助手' : '打开 AI 助手'}
    >
      <span className="kiki-launcher-avatar">
        {isOpen ? (
          /* 关闭图标 */
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{ color: '#0052d9' }}
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        ) : (
          /* 机器人头像 */
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="28"
            height="28"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="4" y="8" width="16" height="12" rx="3" />
            <path d="M12 4v4" />
            <circle cx="12" cy="2.8" r="1.2" fill="currentColor" stroke="none" />
            <path d="M2 13h2M20 13h2" />
            <line x1="8" y1="13" x2="8" y2="15.5" />
            <line x1="16" y1="13" x2="16" y2="15.5" />
          </svg>
        )}
      </span>
    </button>
  );
}
