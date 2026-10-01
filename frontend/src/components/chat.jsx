import { useEffect, useRef, useState } from 'react';
import { docsAPI, errorMessage } from '../api/client';
import Dialog from './Dialog';
import Icon from './Icon';
import Markdown from './Markdown';
import { citationLabel } from '../lib/markdown';


export function CitationList({ citations, onOpen }) {
  if (!citations?.length) return null;
  return (
    <div className="citations">
      <p className="citations-title">
        <Icon name="quote" size={14} /> Sources
      </p>
      <ol className="citation-chips">
        {citations.map((c, i) => (
          <li key={`${c.chunk_id ?? i}-${i}`}>
            <button type="button" className="citation-chip" onClick={() => onOpen(c)}>
              <span className="citation-num">{c.index ?? i + 1}</span>
              <span className="citation-file">{citationLabel(c)}</span>
              {typeof c.similarity === 'number' && (
                <span className="citation-score" title="Similarity to your question">
                  {Math.round(c.similarity * 100)}%
                </span>
              )}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Shows the exact retrieved passage behind a citation (fetched with ownership checks server-side). */
export function CitationDialog({ citation, onClose }) {
  const [state, setState] = useState({ loading: true, chunk: null, error: '' });
  const id = citation ? `${citation.document_id}:${citation.chunk_id}` : null;

  useEffect(() => {
    if (!citation) return undefined;
    let active = true;
    // Old messages may lack ids; then only the stored snippet can be shown.
    if (citation.document_id == null || citation.chunk_id == null) {
      Promise.resolve().then(() => active && setState({ loading: false, chunk: null, error: '' }));
      return () => {
        active = false;
      };
    }
    Promise.resolve().then(() => active && setState({ loading: true, chunk: null, error: '' }));
    docsAPI
      .chunk(citation.document_id, citation.chunk_id)
      .then((res) => active && setState({ loading: false, chunk: res.data, error: '' }))
      .catch((err) =>
        active &&
        setState({
          loading: false,
          chunk: null,
          error: err.response?.status === 404 ? 'This passage is no longer available (the document was deleted).' : errorMessage(err),
        }),
      );
    return () => {
      active = false;
    };
  }, [id, citation]);

  const snippet = citation?.snippet || citation?.content;
  return (
    <Dialog open={Boolean(citation)} onClose={onClose} title={citation ? `Source ${citation.index ?? ''}` : ''} className="citation-dialog">
      {citation && (
        <>
          <p className="citation-dialog-meta">
            <span className="file-tile mini" aria-hidden="true">
              {(citation.filename || '').split('.').pop()?.toUpperCase()}
            </span>
            <span>
              <strong>{citation.filename}</strong>
              <span className="muted">
                {citation.page_number ? ` · Page ${citation.page_number}` : ' · No page numbers in this format'}
                {typeof citation.similarity === 'number' ? ` · ${Math.round(citation.similarity * 100)}% match` : ''}
              </span>
            </span>
          </p>
          {state.loading ? (
            <div className="skeleton-block" aria-busy="true" aria-label="Loading passage" />
          ) : state.chunk ? (
            <blockquote className="passage">{state.chunk.content}</blockquote>
          ) : (
            <>
              {state.error && <p className="inline-error">{state.error}</p>}
              {snippet && <blockquote className="passage">{snippet}</blockquote>}
            </>
          )}
        </>
      )}
    </Dialog>
  );
}

const STAGE_TEXT = {
  sending: 'Sending your question…',
  searching: 'Searching your documents…',
  generating: 'Generating answer…',
};

/** Progress line driven only by real backend `status` events. */
export function RagStatus({ stream }) {
  if (!stream || stream.stage === 'streaming') return null;
  let text = STAGE_TEXT[stream.stage];
  if (stream.stage === 'retrieved') {
    text = stream.count ? `${stream.count} relevant passage${stream.count === 1 ? '' : 's'} found` : 'No relevant passages found';
  }
  if (stream.stage === 'generating' && stream.count) {
    text = `${stream.count} passage${stream.count === 1 ? '' : 's'} found · Generating answer…`;
  }
  return (
    <p className="rag-status" role="status" aria-live="polite">
      <span className="rag-pulse" aria-hidden="true" />
      {text}
    </p>
  );
}

export function Message({ message, onCite }) {
  const isUser = message.role === 'user';
  const incomplete = !isUser && message.status && message.status !== 'complete';
  return (
    <article className={`msg ${isUser ? 'msg-user' : 'msg-ai'} ${incomplete ? 'msg-incomplete' : ''}`}>
      {!isUser && (
        <span className="msg-avatar" aria-hidden="true">
          <Icon name="spark" size={16} />
        </span>
      )}
      <div className="msg-body">
        <h3 className="visually-hidden">{isUser ? 'You asked' : 'DocuMind answered'}</h3>
        {isUser ? (
          <p className="msg-text">{message.content}</p>
        ) : (
          <Markdown text={message.content} citations={message.citations} onCite={onCite} />
        )}
        {incomplete && (
          <p className="msg-flag">
            <Icon name="alert" size={14} />
            {message.status === 'partial' ? 'This answer was interrupted and may be incomplete.' : 'This answer could not be generated.'}
          </p>
        )}
        {!isUser && <CitationList citations={message.citations} onOpen={onCite} />}
      </div>
    </article>
  );
}

export function StreamingMessage({ stream, onCite }) {
  return (
    <>
      <article className="msg msg-user">
        <div className="msg-body">
          <p className="msg-text">{stream.question}</p>
        </div>
      </article>
      <article className="msg msg-ai" aria-busy="true">
        <span className="msg-avatar is-thinking" aria-hidden="true">
          <Icon name="spark" size={16} />
        </span>
        <div className="msg-body">
          <RagStatus stream={stream} />
          {stream.text && (
            <div className="streaming-text">
              <Markdown text={stream.text} citations={stream.citations} onCite={onCite} />
              <span className="caret" aria-hidden="true" />
            </div>
          )}
          {stream.stage === 'streaming' && <CitationList citations={stream.citations} onOpen={onCite} />}
        </div>
      </article>
    </>
  );
}

const MAX_CHARS = 2000;

export function Composer({ onSend, onStop, streaming, disabled, placeholder }) {
  const [value, setValue] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const submit = (e) => {
    e?.preventDefault();
    const q = value.trim();
    if (!q || streaming || disabled || q.length > MAX_CHARS) return;
    onSend(q);
    setValue('');
  };

  const over = value.length > MAX_CHARS;
  return (
    <form className="composer" onSubmit={submit}>
      <label htmlFor="question" className="visually-hidden">
        Ask a question about your documents
      </label>
      <textarea
        id="question"
        ref={ref}
        rows={1}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={over || undefined}
        aria-describedby="composer-help"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) submit(e);
        }}
      />
      <div className="composer-side">
        <span id="composer-help" className={`composer-count ${over ? 'over' : ''}`}>
          {value.length > MAX_CHARS * 0.8 ? `${value.length}/${MAX_CHARS}` : ''}
        </span>
        {streaming ? (
          <button type="button" className="send-btn stop" onClick={onStop} aria-label="Stop generating">
            <Icon name="stop" size={16} />
          </button>
        ) : (
          <button type="submit" className="send-btn" disabled={disabled || !value.trim() || over} aria-label="Send question">
            <Icon name="send" size={18} strokeWidth={2.2} />
          </button>
        )}
      </div>
    </form>
  );
}
