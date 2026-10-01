/**
 * Streaming answers over SSE (POST + fetch, since EventSource cannot send a body or headers).
 *
 * The backend sends one JSON object per `data:` line:
 *   {type:"status", stage, count?} {type:"citations", data:[...]} {type:"token", data:"..."}
 *   {type:"done", message_id}      {type:"error", message, message_id}
 *
 * The parser buffers partial lines across network reads (the old one dropped them),
 * ignores comments/unknown fields, and skips malformed events instead of crashing.
 */
import { API_URL, AUTH_EXPIRED_EVENT, errorMessage, tokenStore } from './client';

export function createSSEParser(onEvent) {
  let buffer = '';
  let dataLines = [];

  const dispatch = () => {
    if (!dataLines.length) return;
    const payload = dataLines.join('\n');
    dataLines = [];
    try {
      const event = JSON.parse(payload);
      if (event && typeof event.type === 'string') onEvent(event);
    } catch {
      /* malformed event: ignore it, keep the stream alive */
    }
  };

  return {
    push(text) {
      buffer += text;
      let idx;
      while ((idx = buffer.search(/\r\n|\r|\n/)) !== -1) {
        const line = buffer.slice(0, idx);
        buffer = buffer.slice(buffer[idx] === '\r' && buffer[idx + 1] === '\n' ? idx + 2 : idx + 1);
        if (line === '') dispatch();
        else if (line.startsWith(':')) continue; // comment / heartbeat
        else if (line.startsWith('data:')) dataLines.push(line.slice(line[5] === ' ' ? 6 : 5));
        // other fields (event:, id:, retry:) are not used by this API
      }
    },
    end() {
      if (buffer.startsWith('data:')) dataLines.push(buffer.slice(buffer[5] === ' ' ? 6 : 5));
      buffer = '';
      dispatch();
    },
  };
}

export class StreamError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/**
 * POST a question and stream events to `onEvent`. Resolves when the stream ends.
 * Throws StreamError (safe message) for HTTP errors or a dropped connection.
 */
export async function streamAnswer(conversationId, question, { onEvent, signal, documentIds } = {}) {
  const token = tokenStore.get();
  let res;
  try {
    res = await fetch(`${API_URL}/api/chat/conversations/${encodeURIComponent(conversationId)}/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question, document_ids: documentIds?.length ? documentIds : undefined }),
      signal,
    });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new StreamError(errorMessage(null, 'Could not reach the server. Check your connection and try again.'));
  }

  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json())?.detail;
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 401) {
      tokenStore.clear();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    throw new StreamError(errorMessage({ response: { status: res.status, data: { detail } } }), res.status);
  }
  if (!res.body) throw new StreamError('Streaming is not supported by this browser.');

  let finished = false;
  const parser = createSSEParser((event) => {
    if (event.type === 'done' || event.type === 'error') finished = true;
    onEvent(event);
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true }));
    }
    parser.push(decoder.decode());
    parser.end();
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new StreamError('The connection was interrupted before the answer finished.');
  }
  if (!finished) throw new StreamError('The connection was interrupted before the answer finished.');
}
