import type { Message } from '../../types';
import { formatTime, truncateText } from '../../utils';

interface ChatBubbleProps {
  message: Message;
  showAvatar?: boolean;
}

export function ChatBubble({ message, showAvatar = true }: ChatBubbleProps) {
  const isUser = message.senderType === 'user';
  const isAI = message.senderType === 'ai';

  return (
    <div
      className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}
      style={{ gap: '8px' }}
    >
      {showAvatar && !isUser && (
        <div
          className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-medium"
          style={{
            backgroundColor: isAI ? '#6366f1' : '#64748b',
          }}
        >
          {message.senderName?.charAt(0) || '?'}
        </div>
      )}

      <div
        className={`max-w-[70%] ${isUser ? 'items-end' : 'items-start'}`}
        style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}
      >
        {!isUser && (
          <span
            className="text-xs text-gray-500"
            style={{ fontWeight: 500 }}
          >
            {message.senderName}
          </span>
        )}

        <div
          className={`px-4 py-2.5 rounded-2xl ${
            isUser
              ? 'bg-indigo-600 text-white rounded-br-md'
              : 'bg-gray-100 text-gray-800 rounded-bl-md'
          }`}
          style={{ wordBreak: 'break-word' }}
        >
          {message.contentType === 'text' ? (
            <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5' }}>
              {truncateText(message.content, 500)}
            </p>
          ) : (
            <div style={{ fontSize: '14px' }}>
              {message.attachment?.name && (
                <div
                  className="flex items-center gap-2 p-2 bg-gray-50 rounded-lg"
                  style={{ borderRadius: '8px' }}
                >
                  <span>📎</span>
                  <span>{message.attachment.name}</span>
                </div>
              )}
            </div>
          )}

          {message.confidence !== undefined && isAI && (
            <div
              className="mt-2 flex items-center gap-2"
              style={{ fontSize: '11px', color: '#9ca3af' }}
            >
              <span>置信度:</span>
              <div
                className="flex-1 h-1 bg-gray-200 rounded-full"
                style={{ width: '60px' }}
              >
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${message.confidence * 100}%`,
                    backgroundColor:
                      message.confidence >= 0.7
                        ? '#22c55e'
                        : message.confidence >= 0.4
                        ? '#eab308'
                        : '#ef4444',
                  }}
                />
              </div>
              <span>{Math.round(message.confidence * 100)}%</span>
            </div>
          )}

          {message.quickReplies && message.quickReplies.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {message.quickReplies.map((reply) => (
                <button
                  key={reply.id}
                  className="px-3 py-1 rounded-full text-xs bg-indigo-100 text-indigo-700 hover:bg-indigo-200 transition-colors"
                  style={{ border: 'none', cursor: 'pointer' }}
                >
                  {reply.label}
                </button>
              ))}
            </div>
          )}
        </div>

        <span
          className="text-xs text-gray-400"
          style={{ marginLeft: isUser ? 'auto' : 0 }}
        >
          {formatTime(message.createdAt)}
        </span>
      </div>

      {showAvatar && isUser && (
        <div
          className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-medium"
          style={{ backgroundColor: '#10b981' }}
        >
          {message.senderName?.charAt(0) || 'U'}
        </div>
      )}
    </div>
  );
}