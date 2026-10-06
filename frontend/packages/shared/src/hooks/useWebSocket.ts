import { useState, useCallback, useEffect, useRef } from 'react';

interface UseWebSocketOptions {
  url: string;
  onMessage?: (data: unknown) => void;
  onError?: (error: Event) => void;
  onClose?: (event: CloseEvent) => void;
  reconnectDelay?: number;
  queryParams?: Record<string, string>;
  authToken?: string | null;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  send: (data: unknown) => void;
  disconnect: () => void;
  connect: () => void;
}

export function useWebSocket({
  url,
  onMessage,
  onError,
  onClose,
  reconnectDelay = 3000,
  queryParams,
  authToken,
}: UseWebSocketOptions): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
    onCloseRef.current = onClose;
  }, [onMessage, onError, onClose]);

  const buildUrl = useCallback(() => {
    const baseUrl = url.replace(/^http/, 'ws');
    if (!queryParams) return baseUrl;
    const params = new URLSearchParams(queryParams);
    return `${baseUrl}?${params.toString()}`;
  }, [url, queryParams]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const fullUrl = buildUrl();
    const ws = new WebSocket(fullUrl);

    ws.onopen = () => {
      if (authToken) {
        ws.send(JSON.stringify({ type: 'auth', token: authToken }));
      }
      setIsConnected(true);
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessageRef.current?.(data);
      } catch {
        onMessageRef.current?.(event.data);
      }
    };

    ws.onerror = (error) => {
      setIsConnected(false);
      onErrorRef.current?.(error);
    };

    ws.onclose = (event) => {
      setIsConnected(false);
      onCloseRef.current?.(event);

      if (event.code !== 1000 && event.code !== 4401) {
        reconnectTimerRef.current = setTimeout(() => {
          connect();
        }, reconnectDelay);
      }
    };

    wsRef.current = ws;
  }, [buildUrl, reconnectDelay, authToken]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Manual disconnect');
      wsRef.current = null;
    }

    setIsConnected(false);
  }, []);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(typeof data === 'string' ? data : JSON.stringify(data));
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    isConnected,
    send,
    disconnect,
    connect,
  };
}
