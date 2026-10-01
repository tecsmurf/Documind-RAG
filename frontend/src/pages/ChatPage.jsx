import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { errorMessage } from '../api/client';
import { CitationDialog, Composer, Message, StreamingMessage } from '../components/chat';
import Dialog from '../components/Dialog';
import DocumentCard, { UploadingCard } from '../components/DocumentCard';
import Icon from '../components/Icon';
import Logo from '../components/Logo';
import UploadZone from '../components/UploadZone';
import { Scene } from '../components/three-d';
import { useAuth } from '../hooks/authContext';
import { useChat } from '../hooks/useChat';
import { useDocuments } from '../hooks/useDocuments';
import { formatDate, precheckFile } from '../lib/format';

const HERO_SCENE = [
  { id: 'h-pdf', type: 'document', x: 6, y: 10, depth: 0.7, rotate: -12, props: { label: 'PDF', size: 0.75 }, hideBelow: 'md' },
  { id: 'h-ai', type: 'ai', x: 84, y: 8, depth: 0.6, delay: 1, props: { size: 0.75 }, hideBelow: 'md' },
  { id: 'h-vec', type: 'vector', x: 86, y: 70, depth: 0.5, rotate: 8, delay: 2, props: { size: 0.7 }, hideBelow: 'lg' },
  { id: 'h-orb', type: 'orb', x: 4, y: 74, depth: 0.4, delay: 1.5, props: { label: 'Search', tone: 'cyan', size: 0.6 }, hideBelow: 'lg' },
];

const SUGGESTIONS = ['Summarize the key points of my documents', 'What are the main conclusions?', 'List the important dates and numbers'];

export default function ChatPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const docs = useDocuments();
  const chat = useChat();
  const { openConversation, activeId } = chat;

  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [citation, setCitation] = useState(null);
  const [confirm, setConfirm] = useState(null); // {kind, item}
  const [actionError, setActionError] = useState('');
  const [dragging, setDragging] = useState(false);
  const retryInput = useRef(null);
  const retryTarget = useRef(null);
  const scrollRef = useRef(null);
  const dragDepth = useRef(0);

  // URL is the source of truth for the open conversation (survives refresh / back / forward).
  const routeId = conversationId ? Number(conversationId) : null;
  useEffect(() => {
    if (routeId !== activeId && (routeId == null || Number.isInteger(routeId))) openConversation(routeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId]);
  useEffect(() => {
    if (activeId != null && activeId !== routeId) navigate(`/chat/${activeId}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.messages, chat.stream]);

  const readyDocs = docs.documents.filter((d) => d.status === 'ready');
  const hasDocs = docs.documents.length > 0 || docs.uploads.length > 0;
  const activeConv = chat.conversations.find((c) => c.id === chat.activeId);
  const streaming = Boolean(chat.stream);

  const uploadFiles = useCallback(
    (files, replaces) => {
      files.forEach((f) => docs.upload(f, { replaces }));
    },
    [docs],
  );

  const onRetry = (doc) => {
    retryTarget.current = doc.id;
    retryInput.current?.click();
  };

  const confirmDelete = async () => {
    const { kind, item } = confirm;
    setConfirm(null);
    try {
      if (kind === 'document') await docs.remove(item.id);
      else {
        await chat.deleteConversation(item.id);
        if (item.id === routeId) navigate('/chat');
      }
    } catch (err) {
      setActionError(errorMessage(err, 'Could not delete. Please try again.'));
    }
  };

  const startNewChat = () => {
    setSidebarOpen(false);
    navigate('/chat');
  };

  return (
    <div
      className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}
      onDragEnter={(e) => {
        if (!e.dataTransfer?.types?.includes('Files')) return;
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragLeave={() => {
        dragDepth.current -= 1;
        if (dragDepth.current <= 0) setDragging(false);
      }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
        const files = Array.from(e.dataTransfer.files || []).filter((f) => !precheckFile(f));
        if (files.length) uploadFiles(files);
      }}
    >
      <a href="#question" className="skip-link">
        Skip to question box
      </a>

      <aside className="sidebar" aria-label="Library and conversations">
        <div className="sidebar-head">
          <Logo />
          <button type="button" className="icon-btn only-mobile" onClick={() => setSidebarOpen(false)} aria-label="Close menu">
            <Icon name="close" />
          </button>
        </div>

        <button type="button" className="btn btn-primary btn-block new-chat" onClick={startNewChat}>
          <Icon name="plus" size={16} strokeWidth={2.2} /> New chat
        </button>

        <section className="side-section" aria-labelledby="lib-title">
          <div className="side-title">
            <h2 id="lib-title">Library</h2>
            <span className="count">{readyDocs.length} ready</span>
          </div>
          <UploadZone variant="compact" onFiles={uploadFiles} />
          {docs.loadError && <p className="inline-error">{docs.loadError}</p>}
          <ul className="doc-list">
            {docs.uploads.map((u) => (
              <UploadingCard key={u.key} upload={u} onDismiss={docs.dismissUpload} />
            ))}
            {docs.documents.map((d) => (
              <DocumentCard key={d.id} doc={d} onDelete={(item) => setConfirm({ kind: 'document', item })} onRetry={onRetry} />
            ))}
          </ul>
          {docs.loaded && !hasDocs && <p className="empty-note">No documents yet.</p>}
        </section>

        <section className="side-section grow" aria-labelledby="conv-title">
          <div className="side-title">
            <h2 id="conv-title">Conversations</h2>
          </div>
          <ul className="conv-list">
            {chat.conversations.map((c) => (
              <li key={c.id} className={`conv-item ${c.id === chat.activeId ? 'active' : ''}`}>
                <button type="button" className="conv-open" onClick={() => { setSidebarOpen(false); navigate(`/chat/${c.id}`); }}
                  aria-current={c.id === chat.activeId ? 'page' : undefined}>
                  <Icon name="chat" size={15} />
                  <span className="conv-title">{c.title}</span>
                  <time className="conv-time" dateTime={c.updated_at}>{formatDate(c.updated_at)}</time>
                </button>
                <button type="button" className="icon-btn danger conv-del" onClick={() => setConfirm({ kind: 'conversation', item: c })}
                  aria-label={`Delete conversation ${c.title}`}>
                  <Icon name="trash" size={14} />
                </button>
              </li>
            ))}
          </ul>
          {chat.conversations.length === 0 && <p className="empty-note">Your conversations will appear here.</p>}
        </section>

        <footer className="user-bar">
          <span className="avatar" aria-hidden="true">
            {(user?.full_name || '?').trim().charAt(0).toUpperCase()}
          </span>
          <span className="user-text">
            <span className="user-name">{user?.full_name}</span>
            <span className="user-email">{user?.email}</span>
          </span>
          <button type="button" className="icon-btn" onClick={logout} aria-label="Sign out" title="Sign out">
            <Icon name="logout" />
          </button>
        </footer>
      </aside>
      <button type="button" className="scrim" aria-label="Close menu" tabIndex={sidebarOpen ? 0 : -1} onClick={() => setSidebarOpen(false)} />

      <main className="workspace">
        <header className="topbar">
          <button type="button" className="icon-btn only-mobile" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
            <Icon name="menu" />
          </button>
          <h1 className="topbar-title">{activeConv?.title || 'New conversation'}</h1>
          <span className="topbar-chip" title="Documents available for answers">
            <span className="chip-dot" aria-hidden="true" />
            {readyDocs.length} {readyDocs.length === 1 ? 'document' : 'documents'} ready
          </span>
        </header>

        <div className="conversation" ref={scrollRef}>
          {!docs.loaded ? (
            <div className="loading-block" aria-busy="true" aria-label="Loading your workspace">
              <div className="skeleton-block" />
            </div>
          ) : !hasDocs ? (
            <section className="hero">
              <Scene items={HERO_SCENE} className="hero-scene" />
              <div className="hero-copy">
                <p className="eyebrow">Step 1 of 2</p>
                <h2>Bring your documents to life</h2>
                <p>Upload a PDF, text or Markdown file. DocuMind reads it, splits it into passages and indexes them for cited answers.</p>
              </div>
              <UploadZone variant="hero" onFiles={uploadFiles} />
            </section>
          ) : chat.messages.length === 0 && !chat.stream ? (
            <section className="welcome">
              <div className="welcome-orb" aria-hidden="true">
                <span className="faio-ring r1" />
                <span className="faio-ring r2" />
                <span className="faio-core">
                  <Icon name="spark" size={26} />
                </span>
              </div>
              <h2>{chat.loadingMessages ? 'Loading conversation…' : `Ask anything about your ${readyDocs.length || ''} document${readyDocs.length === 1 ? '' : 's'}`}</h2>
              <p>Answers come only from your files, with numbered citations you can open.</p>
              {readyDocs.length > 0 && (
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" className="suggestion" onClick={() => chat.ask(s)} disabled={streaming}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {readyDocs.length === 0 && hasDocs && <p className="notice">Your documents are still processing. You can ask once one is ready.</p>}
            </section>
          ) : (
            <div className="thread" aria-live="polite">
              {chat.messages.map((m) => (
                <Message key={m.id} message={m} onCite={setCitation} />
              ))}
              {chat.stream && <StreamingMessage stream={chat.stream} onCite={setCitation} />}
            </div>
          )}
        </div>

        <div className="composer-wrap">
          {(chat.error || actionError) && (
            <div className="toast" role="alert">
              <Icon name="alert" size={16} />
              <span>{chat.error || actionError}</span>
              <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => { chat.setError(''); setActionError(''); }}>
                <Icon name="close" size={14} />
              </button>
            </div>
          )}
          <Composer
            onSend={chat.ask}
            onStop={chat.stop}
            streaming={streaming}
            disabled={readyDocs.length === 0}
            placeholder={readyDocs.length === 0 ? 'Upload a document to start asking questions' : 'Ask a question about your documents…'}
          />
          <p className="composer-note">DocuMind answers from your documents only. Check citations for important decisions.</p>
        </div>
      </main>

      {dragging && (
        <div className="drop-overlay" aria-hidden="true">
          <div className="drop-overlay-card">
            <Icon name="upload" size={28} />
            Drop to upload
          </div>
        </div>
      )}

      <input
        ref={retryInput}
        type="file"
        hidden
        accept=".pdf,.txt,.md"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (!file) return;
          const problem = precheckFile(file);
          if (problem) return setActionError(problem);
          uploadFiles([file], retryTarget.current);
        }}
      />

      <CitationDialog citation={citation} onClose={() => setCitation(null)} />
      <Dialog
        open={Boolean(confirm)}
        onClose={() => setConfirm(null)}
        title={confirm?.kind === 'document' ? 'Delete document?' : 'Delete conversation?'}
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setConfirm(null)}>
              Cancel
            </button>
            <button type="button" className="btn btn-danger" onClick={confirmDelete}>
              Delete
            </button>
          </>
        }
      >
        <p>
          {confirm?.kind === 'document'
            ? `“${confirm?.item.filename}” and all of its indexed passages will be removed. Existing answers keep their citation text.`
            : `“${confirm?.item.title}” and its messages will be removed.`}
        </p>
      </Dialog>
    </div>
  );
}
