import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createSSEParser, streamAnswer, StreamError } from '../api/sse';

function collect() {
  const events = [];
  const parser = createSSEParser((e) => events.push(e));
  return { events, parser };
}

describe('SSE parser', () => {
  it('reassembles events split across arbitrary network chunks', () => {
    const { events, parser } = collect();
    const wire = 'data: {"type":"token","data":"Hel"}\n\ndata: {"type":"token","data":"lo"}\n\ndata: {"type":"done","message_id":7}\n\n';
    for (const ch of wire) parser.push(ch); // worst case: one byte at a time
    parser.end();
    expect(events.map((e) => e.data ?? e.type)).toEqual(['Hel', 'lo', 'done']);
  });

  it('handles CRLF, comments, unknown fields and a trailing event without blank line', () => {
    const { events, parser } = collect();
    parser.push(': keep-alive\r\nevent: ignored\r\ndata: {"type":"status","stage":"searching"}\r\n\r\n');
    parser.push('data: {"type":"done"}');
    parser.end();
    expect(events).toEqual([{ type: 'status', stage: 'searching' }, { type: 'done' }]);
  });

  it('skips malformed or untyped events without throwing', () => {
    const { events, parser } = collect();
    parser.push('data: {not json\n\ndata: [1,2]\n\ndata: {"type":"token","data":"ok"}\n\n');
    expect(events).toEqual([{ type: 'token', data: 'ok' }]);
  });

  it('keeps newlines inside JSON strings as data, not as new events', () => {
    const { events, parser } = collect();
    parser.push(`data: ${JSON.stringify({ type: 'token', data: 'a\n\ndata: {"type":"done"}' })}\n\n`);
    expect(events).toHaveLength(1);
    expect(events[0].data).toContain('data: {"type":"done"}');
  });
});

function streamResponse(chunks, init = {}) {
  const enc = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      chunks.forEach((c) => controller.enqueue(enc.encode(c)));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' }, ...init });
}

describe('streamAnswer', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('streams events and reads data.data for tokens', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      streamResponse(['data: {"type":"citations","data":[{"index":1}]}\n\ndata: {"type":"to', 'ken","data":"Hi"}\n\ndata: {"type":"done","message_id":1}\n\n']),
    );
    const seen = [];
    await streamAnswer(1, 'q', { onEvent: (e) => seen.push(e) });
    expect(seen.map((e) => e.type)).toEqual(['citations', 'token', 'done']);
    expect(seen[1].data).toBe('Hi');
  });

  it('throws a safe error for HTTP failures instead of parsing them as a stream', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Conversation not found.' }), { status: 404 }),
    );
    await expect(streamAnswer(1, 'q', { onEvent: () => {} })).rejects.toMatchObject({ message: 'Conversation not found.', status: 404 });
  });

  it('hides 5xx details', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ detail: 'Traceback: secret' }), { status: 500 }));
    const err = await streamAnswer(1, 'q', { onEvent: () => {} }).catch((e) => e);
    expect(err).toBeInstanceOf(StreamError);
    expect(err.message).not.toContain('Traceback');
  });

  it('reports a stream that ends without done/error as interrupted (partial)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(streamResponse(['data: {"type":"token","data":"half"}\n\n']));
    await expect(streamAnswer(1, 'q', { onEvent: () => {} })).rejects.toThrow(/interrupted/);
  });

  it('reports network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(streamAnswer(1, 'q', { onEvent: () => {} })).rejects.toThrow(/reach the server/);
  });
});
