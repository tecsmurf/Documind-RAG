import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { docsAPI, chatAPI } from '../api';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function ChatPage() {
  const { user, logout } = useAuth();

  // Documents state
  const [documents, setDocuments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');

  // Conversations state
  const [conversations, setConversations] = useState([]);
  const [activeConv, setActiveConv] = useState(null);
  const [messages, setMessages] = useState([]);

  // Chat input
  const [question, setQuestion] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [streamText, setStreamText] = useState('');
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);

  // Sidebar toggle
  const [showSidebar, setShowSidebar] = useState(true);

  useEffect(() => {
    fetchDocuments();
    fetchConversations();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamText]);

  const fetchDocuments = async () => {
    try {
      const res = await docsAPI.list();
      setDocuments(res.data);
    } catch (err) { console.error(err); }
  };

  const fetchConversations = async () => {
    try {
      const res = await chatAPI.listConversations();
      setConversations(res.data);
    } catch (err) { console.error(err); }
  };

  const loadConversation = async (conv) => {
    setActiveConv(conv);
    try {
      const res = await chatAPI.getMessages(conv.id);
      setMessages(res.data);
    } catch (err) { console.error(err); }
  };

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    setUploadError('');
    try {
      await docsAPI.upload(file);
      fetchDocuments();
    } catch (err) {
      setUploadError(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this document?')) return;
    try {
      await docsAPI.delete(id);
      fetchDocuments();
    } catch (err) { console.error(err); }
  };

  const handleNewChat = async () => {
    try {
      const res = await chatAPI.createConversation('New Chat');
      setConversations(prev => [res.data, ...prev]);
      setActiveConv(res.data);
      setMessages([]);
    } catch (err) { console.error(err); }
  };

  const handleAsk = async (e) => {
    e.preventDefault();
    if (!question.trim() || !activeConv || streaming) return;

    const userMsg = { role: 'user', content: question, id: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setQuestion('');
    setStreaming(true);
    setStreamText('');

    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_URL}/api/chat/conversations/${activeConv.id}/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ question: userMsg.content }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let fullText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === 'token') {
                fullText += data.content;
                setStreamText(fullText);
              } else if (data.type === 'citations') {
                // Store citations
              } else if (data.type === 'done') {
                setMessages(prev => [...prev, {
                  role: 'assistant', content: fullText,
                  citations: data.citations || [], id: Date.now() + 1,
                }]);
                setStreamText('');
              } else if (data.type === 'error') {
                setMessages(prev => [...prev, {
                  role: 'assistant', content: `Error: ${data.message}`, id: Date.now() + 1,
                }]);
                setStreamText('');
              }
            } catch {}
          }
        }
      }

      if (fullText && !streamText) {
        setMessages(prev => [...prev, {
          role: 'assistant', content: fullText, id: Date.now() + 1,
        }]);
        setStreamText('');
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: `Error: ${err.message}`, id: Date.now() + 1,
      }]);
    } finally {
      setStreaming(false);
      setStreamText('');
    }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  };

  const readyDocs = documents.filter(d => d.status === 'ready');

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className={`sidebar ${showSidebar ? '' : 'sidebar-hidden'}`}>
        <div className="sidebar-header">
          <h2>📄 DocuMind</h2>
          <button onClick={() => setShowSidebar(false)} className="btn-icon" title="Close sidebar">✕</button>
        </div>

        {/* Documents Section */}
        <div className="sidebar-section">
          <div className="section-header">
            <h3>Documents</h3>
            <label className="btn-upload" title="Upload document">
              {uploading ? '⏳' : '＋'}
              <input type="file" ref={fileInputRef} accept=".pdf,.txt,.md"
                onChange={handleUpload} hidden />
            </label>
          </div>
          {uploadError && <div className="error-msg">{uploadError}</div>}
          <div className="doc-list">
            {documents.length === 0 ? (
              <p className="empty-hint">Upload a PDF, TXT, or MD file to get started</p>
            ) : documents.map(doc => (
              <div key={doc.id} className={`doc-item ${doc.status}`}>
                <div className="doc-info">
                  <span className="doc-icon">
                    {doc.status === 'ready' ? '✅' : doc.status === 'processing' ? '⏳' : '❌'}
                  </span>
                  <div>
                    <div className="doc-name" title={doc.filename}>{doc.filename}</div>
                    <div className="doc-meta">
                      {formatSize(doc.file_size)} · {doc.total_chunks} chunks
                    </div>
                  </div>
                </div>
                <button onClick={() => handleDelete(doc.id)} className="btn-icon btn-delete" title="Delete">🗑</button>
              </div>
            ))}
          </div>
        </div>

        {/* Conversations Section */}
        <div className="sidebar-section">
          <div className="section-header">
            <h3>Chats</h3>
            <button onClick={handleNewChat} className="btn-upload" title="New chat">＋</button>
          </div>
          <div className="conv-list">
            {conversations.map(c => (
              <button key={c.id}
                className={`conv-item ${activeConv?.id === c.id ? 'active' : ''}`}
                onClick={() => loadConversation(c)}>
                💬 {c.title}
              </button>
            ))}
          </div>
        </div>

        {/* User */}
        <div className="sidebar-footer">
          <span className="user-label">{user?.full_name}</span>
          <button onClick={logout} className="btn-ghost-sm">Logout</button>
        </div>
      </aside>

      {/* Main Chat Area */}
      <main className="chat-main">
        {!showSidebar && (
          <button onClick={() => setShowSidebar(true)} className="btn-sidebar-toggle">☰</button>
        )}

        {!activeConv ? (
          <div className="chat-empty">
            <div className="chat-empty-icon">📄</div>
            <h2>DocuMind</h2>
            <p>Upload documents and ask questions. AI answers with citations from your files.</p>
            <div className="chat-empty-steps">
              <div className="step">
                <span className="step-num">1</span>
                <span>Upload a PDF, TXT, or MD file</span>
              </div>
              <div className="step">
                <span className="step-num">2</span>
                <span>Start a new chat</span>
              </div>
              <div className="step">
                <span className="step-num">3</span>
                <span>Ask anything about your documents</span>
              </div>
            </div>
            {readyDocs.length > 0 && (
              <button onClick={handleNewChat} className="btn btn-primary">Start a Chat</button>
            )}
          </div>
        ) : (
          <>
            {/* Messages */}
            <div className="messages-area">
              {messages.length === 0 && !streamText && (
                <div className="chat-hint">
                  <p>Ask a question about your {readyDocs.length} uploaded document{readyDocs.length !== 1 ? 's' : ''}.</p>
                </div>
              )}
              {messages.map((msg) => (
                <div key={msg.id} className={`message ${msg.role}`}>
                  <div className="message-avatar">{msg.role === 'user' ? '👤' : '🤖'}</div>
                  <div className="message-content">
                    <div className="message-text">{msg.content}</div>
                    {msg.citations?.length > 0 && (
                      <div className="citations">
                        <div className="citations-label">Sources:</div>
                        {msg.citations.map((c, i) => (
                          <div key={i} className="citation-item">
                            📎 {c.document || 'Document'} — chunk {c.chunk_index || i + 1}
                            {c.similarity && <span className="similarity">{(c.similarity * 100).toFixed(0)}% match</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {streamText && (
                <div className="message assistant">
                  <div className="message-avatar">🤖</div>
                  <div className="message-content">
                    <div className="message-text">{streamText}<span className="cursor-blink">▌</span></div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input */}
            <form className="chat-input-area" onSubmit={handleAsk}>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={readyDocs.length === 0 ? 'Upload a document first...' : 'Ask about your documents...'}
                disabled={streaming || readyDocs.length === 0}
                className="chat-input"
              />
              <button type="submit" className="btn btn-primary btn-send"
                disabled={streaming || !question.trim() || readyDocs.length === 0}>
                {streaming ? '...' : '→'}
              </button>
            </form>
          </>
        )}
      </main>
    </div>
  );
}
