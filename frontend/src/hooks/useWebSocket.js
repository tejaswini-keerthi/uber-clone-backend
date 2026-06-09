import { useEffect, useRef, useState } from "react";

// Generic WebSocket hook with auto-reconnect (capped backoff).
//
// Pass a null `url` to stay disconnected. `onMessage` receives each parsed JSON
// payload. Returns { connected, lastMessage }.
export function useWebSocket(url, onMessage) {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!url) return undefined;

    let ws;
    let closedByUs = false;
    let retry = 0;
    let reconnectTimer;

    const connect = () => {
      ws = new WebSocket(url);

      ws.onopen = () => {
        retry = 0;
        setConnected(true);
      };

      ws.onmessage = (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch {
          data = event.data;
        }
        setLastMessage(data);
        if (onMessageRef.current) onMessageRef.current(data);
      };

      ws.onclose = () => {
        setConnected(false);
        if (closedByUs) return;
        // Exponential backoff capped at 10s.
        const delay = Math.min(1000 * 2 ** retry, 10000);
        retry += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      closedByUs = true;
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [url]);

  return { connected, lastMessage };
}
