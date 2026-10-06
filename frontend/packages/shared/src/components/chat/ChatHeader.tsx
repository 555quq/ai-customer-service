import type { Contact, Agent } from '../../types';
import { getStatusColor } from '../../utils';

interface ChatHeaderProps {
  title?: string;
  contact?: Contact;
  agent?: Agent;
  onClose?: () => void;
  isOnline?: boolean;
}

export function ChatHeader({
  title = '在线客服',
  contact,
  agent,
  onClose,
  isOnline = true,
}: ChatHeaderProps) {
  const displayName = contact?.name || agent?.name || title;

  return (
    <div
      className="flex items-center justify-between px-4 py-3 bg-white border-b"
      style={{ borderColor: '#e5e7eb' }}
    >
      <div className="flex items-center gap-3">
        <div
          className="relative w-10 h-10 rounded-full flex items-center justify-center text-white font-medium"
          style={{
            backgroundColor: contact ? '#10b981' : '#6366f1',
          }}
        >
          {displayName.charAt(0)}
          {isOnline && (
            <span
              className="absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-white"
              style={{ backgroundColor: '#22c55e' }}
            />
          )}
        </div>

        <div>
          <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#1f2937' }}>
            {displayName}
          </h3>
          <p
            className="text-sm"
            style={{
              margin: 0,
              color: isOnline ? '#22c55e' : '#6b7280',
            }}
          >
            {isOnline ? '在线' : '离线'}
            {agent?.status && (
              <span
                className="ml-2 px-2 py-0.5 rounded-full text-xs"
                style={{
                  backgroundColor: `${getStatusColor(agent.status)}20`,
                  color: getStatusColor(agent.status),
                }}
              >
                {agent.status === 'online' && '空闲'}
                {agent.status === 'busy' && '忙碌'}
                {agent.status === 'away' && '离开'}
                {agent.status === 'offline' && '离线'}
              </span>
            )}
          </p>
        </div>
      </div>

      {onClose && (
        <button
          onClick={onClose}
          className="p-2 rounded-full hover:bg-gray-100 transition-colors"
          style={{ border: 'none', background: 'none', cursor: 'pointer' }}
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
            style={{ color: '#6b7280' }}
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}
    </div>
  );
}