import { useCallback, useEffect, useRef, useState } from 'react';
import { chatAPI, errorMessage } from '../api/client';
import { streamAnswer } from '../api/sse';

/**
 * Conversations + streaming. Every visible state comes from a backend event:
 * `status` events drive the RAG progress line, `citations` are the real
 * retrieved chunks, tokens are appended as they arrive, and the final message
 * is reconciled with what the server saved.
 */
export function useChat() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [stream, setStream] = useState(null); // {question, text, citations, stage, count}
  const [error, setError] = useState('');
  const abortRef = useRef(null);
  const activeRef = useRef(null);

  const loadConversations = useCallback(async () => {
    try {
      const res = await chatAPI.list();
      setConversations(res.data);
    } catch (err) {
      setError(errorMessage(err, 'Could not load your conversations.'));
    }
  }, []);

  useEffect(() => {
    // initial fetch (async; state updates happen after the request resolves)
    void Promise.resolve().then(loadConversations);
    return () => abortRef.current?.abort();
  }, [loadConversations]);

  const openConversation = useCallback(async (id) => {
    abortRef.current?.abort();
    activeRef.current = id;
    setActiveId(id);
    setStream(null);
    setError('');
    if (id == null) {
      setMessages([]);
      return;
    }
    setLoadingMessages(true);
    try {
      const res = await chatAPI.messages(id);
      if (activeRef.current === id) setMessages(res.data);
    } catch (err) {
      if (activeRef.current === id) {
        setMessages([]);
        setError(errorMessage(err, 'Could not load this conversation.'));
      }
    } finally {
      if (activeRef.current === id) setLoadingMessages(false);
    }
  }, []);

  const newConversation = useCallback(async () => {
    const res = await chatAPI.create();
    setConversations((c) => [res.data, ...c]);
    await openConversation(res.data.id);
    return res.data.id;
  }, [openConversation]);

  const deleteConversation = useCallback(
    async (id) => {
      await chatAPI.remove(id);
      setConversations((c) => c.filter((x) => x.id !== id));
      if (activeRef.current === id) openConversation(null);
    },
    [openConversation],
  );

  const ask = useCallback(
    async (question) => {
      let conversationId = activeRef.current;
      if (stream) return;
      setError('');
      if (conversationId == null) {
        try {
          conversationId = await newConversation();
        } catch (err) {
          setError(errorMessage(err, 'Could not start a conversation.'));
          return;
        }
      }
      const controller = new AbortController();
      abortRef.current = controller;
      const local = { question, text: '', citations: [], stage: 'sending', count: null };
      setStream({ ...local });
      let outcome = null;

      try {
        await streamAnswer(conversationId, question, {
          signal: controller.signal,
          onEvent: (event) => {
            if (event.type === 'status') {
              local.stage = event.stage;
              if (event.count != null) local.count = event.count;
            } else if (event.type === 'citations') {
              local.citations = Array.isArray(event.data) ? event.data : [];
            } else if (event.type === 'token' && typeof event.data === 'string') {
              local.text += event.data;
              local.stage = 'streaming';
            } else if (event.type === 'done') {
              outcome = { status: 'complete' };
            } else if (event.type === 'error') {
              outcome = { status: 'error', message: event.message };
            }
            if (activeRef.current === conversationId) setStream({ ...local });
          },
        });
      } catch (err) {
        if (err.name === 'AbortError') {
          outcome = { status: 'aborted' };
          // The server saves the partial answer when it notices the disconnect.
          await new Promise((r) => setTimeout(r, 400));
        } else outcome = { status: 'error', message: err.message || 'Something went wrong while answering.' };
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }

      if (activeRef.current !== conversationId) return;
      // Reload from the server: what is shown is exactly what was saved (with its status).
      try {
        const res = await chatAPI.messages(conversationId);
        if (activeRef.current === conversationId) setMessages(res.data);
      } catch {
        setMessages((m) => [
          ...m,
          { id: `local-q-${Date.now()}`, role: 'user', content: question, status: 'complete' },
          {
            id: `local-a-${Date.now()}`,
            role: 'assistant',
            content: local.text,
            citations: local.citations,
            status: outcome?.status === 'complete' ? 'complete' : 'error',
          },
        ]);
      }
      if (outcome?.status === 'error') setError(outcome.message);
      setStream(null);
      loadConversations();
    },
    [stream, newConversation, loadConversations],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  return {
    conversations,
    activeId,
    messages,
    loadingMessages,
    stream,
    error,
    setError,
    openConversation,
    newConversation,
    deleteConversation,
    ask,
    stop,
  };
}
