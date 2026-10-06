import type { CSSProperties, ReactNode } from 'react';

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  hover?: boolean;
  onClick?: () => void;
  /** 附加样式（覆盖默认样式） */
  style?: CSSProperties;
}

export function Card({
  children,
  padding = 'md',
  hover = false,
  onClick,
  className,
  style: styleProp,
}: CardProps) {
  const paddingStyles = {
    none: 0,
    sm: '12px',
    md: '16px',
    lg: '24px',
  };

  return (
    <div
      className={[hover ? 'cursor-pointer' : '', className].filter(Boolean).join(' ')}
      style={{
        backgroundColor: '#ffffff',
        borderRadius: '12px',
        padding: paddingStyles[padding],
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.06)',
        transition: hover ? 'all 0.2s ease' : 'none',
        cursor: onClick ? 'pointer' : undefined,
        ...styleProp,
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        if (hover) {
          e.currentTarget.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
          e.currentTarget.style.transform = 'translateY(-2px)';
        }
      }}
      onMouseLeave={(e) => {
        if (hover) {
          e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.06)';
          e.currentTarget.style.transform = 'translateY(0)';
        }
      }}
    >
      {children}
    </div>
  );
}