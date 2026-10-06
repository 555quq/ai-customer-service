import type { CSSProperties, ReactNode } from 'react';

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  loading?: boolean;
  type?: 'button' | 'submit' | 'reset';
  /** 附加样式（覆盖默认样式） */
  style?: CSSProperties;
  className?: string;
  title?: string;
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  type = 'button',
  style: styleProp,
  className,
  title,
}: ButtonProps) {
  const baseStyles = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    border: 'none',
    borderRadius: '8px',
    cursor: disabled || loading ? 'not-allowed' : 'pointer',
    transition: 'all 0.2s ease',
    fontWeight: 500,
    fontFamily: 'inherit',
  };

  const sizeStyles = {
    sm: {
      padding: '6px 12px',
      fontSize: '12px',
    },
    md: {
      padding: '8px 16px',
      fontSize: '14px',
    },
    lg: {
      padding: '12px 24px',
      fontSize: '16px',
    },
  };

  const variantStyles = {
    primary: {
      backgroundColor: '#6366f1',
      color: '#ffffff',
      hover: { backgroundColor: '#4f46e5' },
      active: { backgroundColor: '#4338ca' },
    },
    secondary: {
      backgroundColor: '#64748b',
      color: '#ffffff',
      hover: { backgroundColor: '#475569' },
      active: { backgroundColor: '#334155' },
    },
    outline: {
      backgroundColor: 'transparent',
      color: '#6366f1',
      border: '1px solid #6366f1',
      hover: { backgroundColor: '#eef2ff' },
      active: { backgroundColor: '#e0e7ff' },
    },
    ghost: {
      backgroundColor: 'transparent',
      color: '#64748b',
      hover: { backgroundColor: '#f1f5f9' },
      active: { backgroundColor: '#e2e8f0' },
    },
    danger: {
      backgroundColor: '#ef4444',
      color: '#ffffff',
      hover: { backgroundColor: '#dc2626' },
      active: { backgroundColor: '#b91c1c' },
    },
  };

  const style = {
    ...baseStyles,
    ...sizeStyles[size],
    ...variantStyles[variant],
    opacity: disabled || loading ? 0.7 : 1,
    ...styleProp,
  };

  const handleClick = () => {
    if (!disabled && !loading) {
      onClick?.();
    }
  };

  return (
    <button
      type={type}
      onClick={handleClick}
      disabled={disabled || loading}
      style={style}
      className={className}
      title={title}
      onMouseEnter={(e) => {
        if (!disabled && !loading) {
          e.currentTarget.style.backgroundColor = variantStyles[variant].hover.backgroundColor;
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled && !loading) {
          e.currentTarget.style.backgroundColor = variantStyles[variant].backgroundColor;
        }
      }}
      onMouseDown={(e) => {
        if (!disabled && !loading) {
          e.currentTarget.style.backgroundColor = variantStyles[variant].active.backgroundColor;
        }
      }}
      onMouseUp={(e) => {
        if (!disabled && !loading) {
          e.currentTarget.style.backgroundColor = variantStyles[variant].hover.backgroundColor;
        }
      }}
    >
      {loading && (
        <svg
          className="animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          width={size === 'sm' ? 14 : size === 'lg' ? 20 : 16}
          height={size === 'sm' ? 14 : size === 'lg' ? 20 : 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {children}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .animate-spin {
          animation: spin 1s linear infinite;
        }
      `}</style>
    </button>
  );
}