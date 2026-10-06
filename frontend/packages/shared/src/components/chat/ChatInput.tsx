import { useState, KeyboardEvent, FormEvent } from 'react';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ onSend, disabled = false, placeholder = '输入消息...' }: ChatInputProps) {
  const [value, setValue] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim() && !disabled) {
      onSend(value.trim());
      setValue('');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !disabled) {
        onSend(value.trim());
        setValue('');
      }
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <div
        className="flex items-end gap-2 p-3 bg-white border-t"
        style={{ borderColor: '#e5e7eb' }}
      >
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          className="flex-1 px-4 py-2.5 rounded-xl border resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
          style={{
            borderColor: '#e5e7eb',
            fontSize: '14px',
            minHeight: '44px',
            maxHeight: '120px',
            fontFamily: 'inherit',
          }}
          rows={1}
        />

        <button
          type="submit"
          disabled={!value.trim() || disabled}
          className="flex-shrink-0 w-10 h-10 rounded-full bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          style={{ border: 'none', cursor: value.trim() && !disabled ? 'pointer' : 'not-allowed' }}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </form>
  );
}