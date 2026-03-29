import { useState, useEffect, useRef } from 'react';

export interface Message {
  role: string;
  content: string;
  node?: string;
}

export function useSSE(threadId: string | null) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isInterrupted, setIsInterrupted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const startStream = () => {
    if (!threadId) return;

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    setIsInterrupted(false);
    setError(null);

    // Using EventSource for SSE
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const url = `${apiUrl}/chat/stream?thread_id=${threadId}`;
    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      if (event.data === '[DONE]') {
        setIsStreaming(false);
        es.close();
        return;
      }

      try {
        const data = JSON.parse(event.data);
        
        if (data.type === 'message') {
          setMessages((prev) => {
            // Check if we should update the last message (e.g., if it's the same node)
            // Or just append if it's a new turn.
            // For now, let's append.
            return [...prev, { role: data.role, content: data.content, node: data.node }];
          });
        } else if (data.type === 'interrupt') {
          setIsInterrupted(true);
          setIsStreaming(false);
          es.close();
        } else if (data.type === 'error') {
          setError(data.content);
          setIsStreaming(false);
          es.close();
        }
      } catch (e) {
        console.error('Failed to parse SSE event', e);
      }
    };

    es.onerror = (e) => {
      console.error('SSE Error', e);
      setError('Connection to stream lost.');
      setIsStreaming(false);
      es.close();
    };
  };

  const stopStream = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      setIsStreaming(false);
    }
  };

  return { messages, isStreaming, isInterrupted, error, startStream, stopStream, setMessages };
}
