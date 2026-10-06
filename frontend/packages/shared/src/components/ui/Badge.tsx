import type { ReactNode } from 'react';

interface BadgeProps {
  children: ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info';
  size?: 'sm' | 'md';
}

export function Badge({ children, variant = 'default', size = 'md' }: BadgeProps) {
  const sizeStyles = {
    sm: {
      padding: '2px 8px',
      fontSize: '11px',
    },
    md: {
      padding: '4px 12px',
      fontSize: '12px',
    },
  };

  const variantStyles = {
    default: {
      backgroundColor: '#f3f4f6',
      color: '#374151',
    },
    success: {
      backgroundColor: '#d1fae5',
      color: '#065f46',
    },
    warning: {
      backgroundColor: '#fef3c7',
      color: '#92400e',
    },
    error: {
      backgroundColor: '#fee2e2',
      color: '#991b1b',
    },
    info: {
      backgroundColor: '#dbeafe',
      color: '#1e40af',
    },
  };

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: '9999px',
        fontWeight: 500,
        ...sizeStyles[size],
        ...variantStyles[variant],
      }}
    >
      {children}
    </span>
  );
}