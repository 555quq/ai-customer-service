export function TypingIndicator() {
  return (
    <div className="flex justify-start mb-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-medium mr-2" style={{ backgroundColor: '#6366f1' }}>
        AI
      </div>
      <div className="bg-gray-100 px-4 py-3 rounded-2xl rounded-bl-md">
        <div className="flex gap-1">
          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
          <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
        </div>
        <style>{`
          @keyframes bounce {
            0%, 80%, 100% {
              transform: scale(0.8);
              opacity: 0.5;
            }
            40% {
              transform: scale(1);
              opacity: 1;
            }
          }
          .animate-bounce {
            animation: bounce 1.4s infinite ease-in-out;
          }
        `}</style>
      </div>
    </div>
  );
}