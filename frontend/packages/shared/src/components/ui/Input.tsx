import { useId } from 'react';
import type { InputHTMLAttributes, ReactNode } from 'react';

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'prefix'> {
  label?: string;
  error?: string;
  prefix?: ReactNode;
  suffix?: ReactNode;
}

export function Input({
  label,
  error,
  prefix,
  suffix,
  className,
  ...props
}: InputProps) {
  const generatedId = useId();
  const inputId = props.id ?? generatedId;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {label && (
        <label
          htmlFor={inputId}
          style={{
            fontSize: '14px',
            fontWeight: 500,
            color: '#374151',
          }}
        >
          {label}
        </label>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          border: `1px solid ${error ? '#ef4444' : '#d1d5db'}`,
          borderRadius: '8px',
          backgroundColor: '#ffffff',
          transition: 'all 0.2s ease',
        }}
      >
        {prefix && (
          <span
            style={{
              padding: '0 12px',
              color: '#9ca3af',
            }}
          >
            {prefix}
          </span>
        )}

        <input
          {...props}
          id={inputId}
          style={{
            flex: 1,
            padding: '10px 12px',
            border: 'none',
            outline: 'none',
            fontSize: '14px',
            color: '#1f2937',
            backgroundColor: 'transparent',
          }}
          onFocus={(e) => {
            e.currentTarget.parentElement?.style.setProperty('border-color', '#6366f1');
            e.currentTarget.parentElement?.style.setProperty('box-shadow', '0 0 0 3px rgba(99, 102, 241, 0.1)');
          }}
          onBlur={(e) => {
            e.currentTarget.parentElement?.style.setProperty('border-color', error ? '#ef4444' : '#d1d5db');
            e.currentTarget.parentElement?.style.setProperty('box-shadow', 'none');
          }}
        />

        {suffix && (
          <span
            style={{
              padding: '0 12px',
              color: '#9ca3af',
            }}
          >
            {suffix}
          </span>
        )}
      </div>

      {error && (
        <span style={{ fontSize: '12px', color: '#ef4444' }}>{error}</span>
      )}
    </div>
  );
}
