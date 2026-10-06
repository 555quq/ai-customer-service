interface LoadingProps {
  size?: 'sm' | 'md' | 'lg';
  text?: string;
}

export function Loading({ size = 'md', text }: LoadingProps) {
  const sizeMap = {
    sm: 20,
    md: 32,
    lg: 48,
  };

  const strokeWidth = size === 'sm' ? 3 : size === 'lg' ? 4 : 3;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
      <svg
        className="animate-spin"
        xmlns="http://www.w3.org/2000/svg"
        width={sizeMap[size]}
        height={sizeMap[size]}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ color: '#6366f1' }}
      >
        <circle className="opacity-25" cx="12" cy="12" r="10" />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
      {text && (
        <span style={{ fontSize: '14px', color: '#6b7280' }}>{text}</span>
      )}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }
      `}</style>
    </div>
  );
}