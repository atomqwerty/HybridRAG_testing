import React, { useState, useRef, useEffect, useCallback } from 'react';
import './App.css';

const ROLE_BADGE = { superadmin: '🔑 Super Admin', admin: '⚙️ Admin', user: '👤 User' };

function App() {
    // ---- Auth State ----
    const [token, setToken] = useState(() => localStorage.getItem('rag_token'));
    const [currentUser, setCurrentUser] = useState(null);
    const [authError, setAuthError] = useState('');
    // ---- App State ----
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [sessionId] = useState(() => Math.random().toString(36).substr(2, 9));
    const [lightboxImage, setLightboxImage] = useState(null);
    const [isCreative, setIsCreative] = useState(true);

    // View State ('chat' or 'settings')
    const [activeView, setActiveView] = useState('chat');

    // Config & Files
    const [config, setConfig] = useState({ strict_mode: true, rules: [], default_score: 0.5 });
    const [availableFiles, setAvailableFiles] = useState([]);
    const [selectedSources, setSelectedSources] = useState(new Set());

    // New Rule State
    const [newRulePattern, setNewRulePattern] = useState('');
    const [newRuleScore, setNewRuleScore] = useState(1.0);

    const [currUrl, setCurrUrl] = useState('');
    const [uploading, setUploading] = useState(false);
    const [isIngesting, setIsIngesting] = useState(false);
    const [ingestStatus, setIngestStatus] = useState({ percent: 0, message: '' });

    const [uploadStatus, setUploadStatus] = useState(null);
    const [isDragging, setIsDragging] = useState(false);

    const [messages, setMessages] = useState([]);
    const messagesEndRef = useRef(null);

    // Derived
    const isAdmin = currentUser?.role === 'admin' || currentUser?.role === 'superadmin';
    const isSuperAdmin = currentUser?.role === 'superadmin';

    // ---- Auth helpers ----
    const authFetch = useCallback((url, options = {}) => {
        const headers = { ...(options.headers || {}), 'Authorization': `Bearer ${token}` };
        return fetch(url, { ...options, headers });
    }, [token]);

    // On mount / token change: verify token and get current user
    useEffect(() => {
        if (!token) { setCurrentUser(null); return; }
        fetch('/api/auth/me', { headers: { 'Authorization': `Bearer ${token}` } })
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(setCurrentUser)
            .catch(() => { localStorage.removeItem('rag_token'); setToken(null); setCurrentUser(null); });
    }, [token]);

    const handleLogin = async (e) => {
        e.preventDefault();
        const form = e.target;
        const username = form.username.value.trim();
        const password = form.password.value;
        setAuthError('');
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json();
            if (!res.ok) { setAuthError(data.error || 'Login failed'); return; }
            localStorage.setItem('rag_token', data.token);
            setToken(data.token);
            setCurrentUser(data.user);
        } catch (e) {
            setAuthError('Cannot connect to server');
        }
    };

    const handleLogout = () => {
        localStorage.removeItem('rag_token');
        setToken(null);
        setCurrentUser(null);
        setMessages([]);
    };

    // Login screen rendered via main return (not early return, to satisfy hooks rules)
    const LoginScreen = () => (
        <div style={{
            minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'linear-gradient(135deg, #0f0c29, #302b63, #24243e)'
        }}>
            <div style={{
                background: 'rgba(255,255,255,0.05)', backdropFilter: 'blur(16px)', borderRadius: '20px',
                border: '1px solid rgba(255,255,255,0.12)', padding: '48px', width: '380px',
                boxShadow: '0 24px 64px rgba(0,0,0,0.5)'
            }}>
                <div style={{ textAlign: 'center', marginBottom: '32px' }}>
                    <div style={{ fontSize: '3rem', marginBottom: '12px' }}>🌌</div>
                    <h1 style={{ margin: 0, fontSize: '1.6rem', color: '#fff', fontWeight: 700 }}>Hybrid RAG</h1>
                    <p style={{ color: '#9ca3af', fontSize: '0.9rem', marginTop: '8px' }}>Sign in to continue</p>
                </div>
                <form onSubmit={handleLogin}>
                    <div style={{ marginBottom: '16px' }}>
                        <label style={{ display: 'block', color: '#d1d5db', fontSize: '0.85rem', marginBottom: '6px' }}>Username</label>
                        <input id="login-username" name="username" type="text" required autoFocus
                            style={{
                                width: '100%', padding: '10px 14px', borderRadius: '10px',
                                border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.08)',
                                color: '#fff', fontSize: '0.95rem', boxSizing: 'border-box', outline: 'none'
                            }}
                        />
                    </div>
                    <div style={{ marginBottom: '24px' }}>
                        <label style={{ display: 'block', color: '#d1d5db', fontSize: '0.85rem', marginBottom: '6px' }}>Password</label>
                        <input id="login-password" name="password" type="password" required
                            style={{
                                width: '100%', padding: '10px 14px', borderRadius: '10px',
                                border: '1px solid rgba(255,255,255,0.15)', background: 'rgba(255,255,255,0.08)',
                                color: '#fff', fontSize: '0.95rem', boxSizing: 'border-box', outline: 'none'
                            }}
                        />
                    </div>
                    {authError && <p style={{ color: '#f87171', fontSize: '0.85rem', marginBottom: '16px', textAlign: 'center' }}>{authError}</p>}
                    <button id="login-submit" type="submit"
                        style={{
                            width: '100%', padding: '12px', borderRadius: '10px', border: 'none',
                            background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                            color: '#fff', fontWeight: 700, fontSize: '1rem', cursor: 'pointer'
                        }}
                    >Sign In</button>
                </form>
            </div>
        </div>
    );

    // --- Core Logic ---

    const refreshData = async () => {
        try {
            const [configRes, filesRes] = await Promise.all([
                authFetch('/api/config/trust?_t=' + Date.now()),
                authFetch('/api/files?_t=' + Date.now())
            ]);
            const configData = await configRes.json();
            const filesData = await filesRes.json();
            setConfig(configData);
            setAvailableFiles(filesData.files || []);
        } catch (err) {
            console.error("Failed to refresh data", err);
        }
    };

    useEffect(() => {
        if (!currentUser) return;
        refreshData();
        const initSources = async () => {
            const res = await authFetch('/api/files');
            const data = await res.json();
            if (data.files) setSelectedSources(new Set(data.files));
        };
        initSources();
    }, [currentUser]);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Polling for ingestion
    useEffect(() => {
        let interval;
        if (isIngesting) {
            interval = setInterval(async () => {
                try {
                    const res = await authFetch('/api/ingest/status');
                    const data = await res.json();
                    setIngestStatus(data);
                    if (data.percent >= 100) {
                        setIsIngesting(false);
                        setUploading(false);
                        refreshData();
                    }
                } catch (e) { }
            }, 1000);
        }
        return () => clearInterval(interval);
    }, [isIngesting]);

    // --- Handlers ---

    const handleSendMessage = async (e) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { type: 'user', content: userMessage }]);
        setMessages(prev => [...prev, { type: 'bot', content: '', sources: [], images: [] }]);
        setLoading(true);

        try {
            const response = await authFetch('/api/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    temperature: isCreative ? 0.3 : 0.0,
                    selected_sources: Array.from(selectedSources)
                })
            });

            if (!response.ok) throw new Error(`Server error ${response.status}`);

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let accumulatedContent = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n');

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const data = JSON.parse(line);
                        setMessages(prev => {
                            const newMsgs = [...prev];
                            const last = { ...newMsgs[newMsgs.length - 1] };
                            if (data.type === 'thought') {
                                last.thought = data.content;
                            } else if (data.type === 'meta') {
                                last.sources = data.sources || [];
                                last.images = data.images || [];
                                last.agent = data.agent || 'text';
                                // Clear thought once content or meta arrives, 
                                // or keep it as a status? Let's keep it until 'token' arrives.
                            } else if (data.type === 'token') {
                                last.thought = null; // Clear thought once we start getting answer tokens
                                accumulatedContent += data.content;
                                last.content = accumulatedContent;
                            } else if (data.type === 'error') {
                                last.type = 'error';
                                last.content = data.content;
                                last.thought = null;
                            }
                            newMsgs[newMsgs.length - 1] = last;
                            return newMsgs;
                        });
                    } catch (e) { }
                }
            }
        } catch (error) {
            setMessages(prev => {
                const newMsgs = [...prev];
                newMsgs[newMsgs.length - 1] = { type: 'error', content: error.message };
                return newMsgs;
            });
        } finally {
            setLoading(false);
        }
    };

    const handleToggleSource = (filename) => {
        const newSet = new Set(selectedSources);
        if (newSet.has(filename)) newSet.delete(filename);
        else newSet.add(filename);
        setSelectedSources(newSet);
    };

    const handleToggleAllSources = () => {
        if (selectedSources.size === availableFiles.length) {
            setSelectedSources(new Set());
        } else {
            setSelectedSources(new Set(availableFiles));
        }
    };

    const handleDeleteFile = async (filename) => {
        if (!window.confirm(`Delete ${filename}?`)) return;
        try {
            const res = await authFetch('/api/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename })
            });
            if (res.ok) {
                const newSet = new Set(selectedSources);
                newSet.delete(filename);
                setSelectedSources(newSet);
                refreshData();
            }
        } catch (e) { alert("Delete failed"); }
    };

    const handleDeleteAll = async () => {
        if (!window.confirm('Delete ALL uploaded data and clear the knowledge DB? This will remove all files and Neo4j data.')) return;
        try {
            const res = await authFetch('/api/admin/clear_db', { method: 'POST' });
            if (res.ok) {
                setSelectedSources(new Set());
                refreshData();
                alert('All data cleared successfully.');
            } else {
                const data = await res.json();
                alert(data.error || 'Failed to clear data');
            }
        } catch (e) { alert('Failed to clear data'); }
    };

    const handleClearChat = async () => {
        try {
            await authFetch('/api/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });
            setMessages([]);
        } catch (e) { }
    };

    const handleDeleteRule = async (index) => {
        const newRules = config.rules.filter((_, i) => i !== index);
        const newConfig = { ...config, rules: newRules };
        try {
            const res = await authFetch('/api/config/trust', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newConfig)
            });
            if (res.ok) setConfig(newConfig);
        } catch (e) { alert("Delete failed"); }
    };

    const handleAddUrl = async () => {
        if (!currUrl) return;
        setUploading(true);
        try {
            const res = await authFetch('/api/ingest/url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: currUrl })
            });
            if (res.ok) {
                setCurrUrl('');
                setIsIngesting(true);
            } else {
                const data = await res.json();
                alert(data.error);
                setUploading(false);
            }
        } catch (e) { setUploading(false); }
    };

    const handleUploadFiles = async (e, isFolder = false) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;
        setUploading(true);
        const formData = new FormData();

        for (let f of files) {
            formData.append('file', f);
            if (isFolder && f.webkitRelativePath) {
                formData.append('paths', f.webkitRelativePath);
            }
        }

        try {
            const res = await authFetch('/api/ingest/upload', { method: 'POST', body: formData });
            if (res.ok) {
                setIsIngesting(true);
                refreshData();
            } else {
                const data = await res.json();
                alert(data.error);
                setUploading(false);
            }
        } catch (e) { setUploading(false); }
    };

    // --- Render Helpers ---

    const processInlineMarkdown = (text) => {
        const parts = text.split(/(\*\*.*?\*\*)|(!\[.*?\]\(.*?\))/g);
        return parts.map((part, index) => {
            if (!part) return null;
            if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
            if (part.match(/^!\[(.*?)\]\((.*?)\)$/)) {
                const match = part.match(/^!\[(.*?)\]\((.*?)\)$/);
                return (
                    <img key={index} src={match[2]} alt={match[1]} onClick={() => setLightboxImage(match[2])} className="message-inline-img" />
                );
            }
            return part;
        });
    };

    const formatMessage = (content) => {
        const lines = content.split('\n');
        const formatted = [];
        let tableRows = [];

        lines.forEach((line, idx) => {
            if (line.trim().startsWith('|')) {
                tableRows.push(line);
            } else {
                if (tableRows.length > 0) {
                    formatted.push(<div key={`table-${idx}`} className="markdown-table">{renderTable(tableRows)}</div>);
                    tableRows = [];
                }
                if (line.trim()) {
                    if (line.startsWith('###')) formatted.push(<h3 key={idx}>{processInlineMarkdown(line.replace(/^###\s*/, ''))}</h3>);
                    else if (line.trim().startsWith('-')) formatted.push(<li key={idx}>{processInlineMarkdown(line.trim().substring(1).trim())}</li>);
                    else formatted.push(<p key={idx}>{processInlineMarkdown(line)}</p>);
                }
            }
        });
        if (tableRows.length > 0) formatted.push(<div key="table-final" className="markdown-table">{renderTable(tableRows)}</div>);
        return formatted;
    };

    const renderTable = (rows) => {
        const tableData = rows.map(row => row.split('|').filter(cell => cell.trim()).map(cell => cell.trim()));
        if (tableData.length < 2) return null;
        const headers = tableData[0];
        const dataRows = tableData.slice(2);
        return (
            <table>
                <thead><tr>{headers.map((h, i) => <th key={i}>{processInlineMarkdown(h)}</th>)}</tr></thead>
                <tbody>{dataRows.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{processInlineMarkdown(c)}</td>)}</tr>)}</tbody>
            </table>
        );
    };

    // --- Layout Components ---

    const Sidebar = () => (
        <div className="sidebar">
            <div className="sidebar-logo">
                <span style={{ fontSize: '1.5rem' }}>🌌</span>
                <span>Hybrid RAG</span>
            </div>
            <div className="sidebar-nav">
                <button className={`nav-item ${activeView === 'chat' ? 'active' : ''}`} onClick={() => setActiveView('chat')}>
                    <span>💬</span> Chat Assistant
                </button>
                {isAdmin && (
                    <button className={`nav-item ${activeView === 'settings' ? 'active' : ''}`} onClick={() => setActiveView('settings')}>
                        <span>⚙️</span> Settings &amp; Data
                    </button>
                )}
            </div>
            <div className="sidebar-footer">
                <div style={{ padding: '8px 16px', fontSize: '0.8rem', color: '#9ca3af', marginBottom: '4px' }}>
                    <div style={{ fontWeight: 600, color: '#e5e7eb' }}>{currentUser?.username}</div>
                    <div style={{ marginTop: '2px' }}>{ROLE_BADGE[currentUser?.role] || currentUser?.role}</div>
                </div>
                <button className="nav-item" onClick={handleClearChat}>
                    <span>🗑️</span> Clear History
                </button>
                <button className="nav-item" onClick={handleLogout} style={{ color: '#f87171' }}>
                    <span>🚪</span> Sign Out
                </button>
            </div>
        </div>
    );

    const ChatView = () => (
        <div className="chat-root" style={{ position: 'relative' }}>
            <header className="chat-header">
                <h1>AI Assistant</h1>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                    {isIngesting && (
                        <div className="ingest-indicator">
                            <div className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }}></div>
                            <span>{ingestStatus.message || 'Ingesting...'}</span>
                        </div>
                    )}
                    <span style={{ fontSize: '0.85rem', color: '#6b7280' }}>
                        {isCreative ? 'Creative' : 'Precise'} Mode
                    </span>
                </div>
            </header>

            {isIngesting && (
                <div className="progress-wrapper">
                    <div className="progress-container">
                        <div
                            className="progress-bar-fill"
                            style={{ width: `${ingestStatus.percent || 0}%` }}
                        ></div>
                    </div>
                </div>
            )}

            <div className="messages-container">
                {messages.length === 0 && (
                    <div style={{ textAlign: 'center', marginTop: '100px', color: '#9ca3af' }}>
                        <div style={{ fontSize: '3rem', marginBottom: '16px' }}>👋</div>
                        <h2>How can I help you today?</h2>
                        <p>Ask about cars, specs, or upload documents to get started.</p>
                    </div>
                )}
                {messages.map((msg, idx) => (
                    <div key={idx} className={`message ${msg.type}`}>
                        <div className="avatar">
                            {msg.type === 'user' ? 'U' : (
                                <span title={msg.agent}>
                                    {msg.agent === 'visual' || msg.agent === 'image' ? '📸' :
                                        msg.agent === 'table' ? '📊' : '🤖'}
                                </span>
                            )}
                        </div>
                        <div className="message-body">
                            {msg.type === 'bot' && msg.agent && (
                                <div className="agent-badge">
                                    {msg.agent === 'visual' || msg.agent === 'image' ? 'Image Agent' :
                                        msg.agent === 'table' ? 'Table Agent' : 'Text Assistant'}
                                </div>
                            )}
                            <div className="message-content">
                                {msg.thought && (
                                    <div className="thought-block">
                                        <div className="thought-icon">🧠</div>
                                        <div className="thought-text">{msg.thought}</div>
                                    </div>
                                )}
                                {typeof msg.content === 'string' ? (
                                    msg.content ? formatMessage(msg.content) :
                                        (msg.thought ? null : <div className="typing-indicator"><span></span><span></span><span></span></div>)
                                ) : msg.content}
                            </div>
                            {msg.sources?.length > 0 && (
                                <div className="sources-chips">
                                    {msg.sources.map((s, i) => (
                                        <span key={i} className="source-chip" title={s.file}>
                                            📄 {s.file.length > 15 ? s.file.substring(0, 12) + '...' : s.file} (p.{s.page})
                                        </span>
                                    ))}
                                </div>
                            )}
                            {msg.images?.length > 0 && (
                                <div className="image-grid">
                                    {msg.images.map((img, i) => {
                                        const src = img.startsWith('/api/images/') ? img : `/api/images/${img}`;
                                        return (
                                            <div key={i} className="image-card">
                                                <img src={src} alt="Ref" onClick={() => setLightboxImage(src)} />
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
                {loading && (
                    <div className="message bot">
                        <div className="avatar">AI</div>
                        <div className="message-body">
                            <div className="typing-indicator"><span></span><span></span><span></span></div>
                        </div>
                    </div>
                )}
                <div ref={messagesEndRef} />
            </div>

            <div className="input-area">
                <form className="input-box" onSubmit={handleSendMessage}>
                    <textarea
                        rows="1"
                        placeholder="Ask anything..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                handleSendMessage(e);
                            }
                        }}
                    />
                    <button type="submit" className="send-btn" disabled={!input.trim() || loading}>
                        ➜
                    </button>
                </form>
            </div>
        </div>
    );

    const SettingsView = () => (
        <div className="settings-view">
            <div className="settings-container">
                <h2 style={{ marginBottom: '32px', fontSize: '1.875rem' }}>System Settings</h2>

                <div className="settings-grid">
                    {/* Model Config */}
                    <div className="settings-card">
                        <h3>🧠 AI Configuration</h3>
                        <div className="form-group">
                            <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }}>
                                <div className="toggle-switch">
                                    <input type="checkbox" checked={isCreative} onChange={(e) => setIsCreative(e.target.checked)} />
                                    <span className="slider"></span>
                                </div>
                                <div>
                                    <div style={{ fontWeight: 600 }}>Creative Mode</div>
                                    <div style={{ fontSize: '0.8rem', color: '#6b7280' }}>Uncheck for more precise/literal answers.</div>
                                </div>
                            </label>
                        </div>
                    </div>

                    {/* Dataset Toggles */}
                    <div className="settings-card" style={{ gridRow: 'span 2' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                            <h3 style={{ margin: 0 }}>📂 Dataset Selection</h3>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <button className="btn-modern secondary" style={{ padding: '4px 8px', fontSize: '0.8rem' }} onClick={handleToggleAllSources}>
                                    {selectedSources.size === availableFiles.length ? 'Deselect All' : 'Select All'}
                                </button>
                                {isSuperAdmin && (
                                    <button className="btn-modern danger" style={{ padding: '4px 8px', fontSize: '0.8rem' }} onClick={handleDeleteAll}>
                                        🗑️ Delete All
                                    </button>
                                )}
                            </div>
                        </div>
                        <div className="data-list">
                            {availableFiles.length === 0 ? (
                                <p style={{ color: '#9ca3af', fontStyle: 'italic' }}>No data uploaded yet.</p>
                            ) : availableFiles.map((file, i) => (
                                <div key={i} className="data-item">
                                    <div className="data-info">
                                        <span className="data-icon">{file.match(/\.(jpg|jpeg|png)$/i) ? '🖼️' : '📄'}</span>
                                        <span className="data-name">{file}</span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <div className="toggle-switch">
                                            <input type="checkbox" checked={selectedSources.has(file)} onChange={() => handleToggleSource(file)} />
                                            <span className="slider"></span>
                                        </div>
                                        <button className="btn-delete-small" onClick={() => handleDeleteFile(file)}>🗑️</button>
                                    </div>
                                </div>
                            ))}
                        </div>
                        <div style={{ marginTop: '20px', fontSize: '0.85rem', color: '#6b7280', background: '#fef3c7', padding: '12px', borderRadius: '8px' }}>
                            💡 <strong>Tip:</strong> Toggle sources to restrict the AI to only specific documents.
                        </div>
                    </div>

                    {/* Ingestion — admin only */}
                    {isAdmin && (
                        <div className="settings-card">
                            <h3>📤 Add New Knowledge</h3>
                            <div className="form-group">
                                <label className="form-label">Crawl Website</label>
                                <div style={{ display: 'flex', gap: '8px' }}>
                                    <input className="input-dark" type="text" placeholder="https://..." value={currUrl} onChange={e => setCurrUrl(e.target.value)} />
                                    <button className="btn-modern primary" onClick={handleAddUrl} disabled={uploading}>Crawl</button>
                                </div>
                            </div>
                            <div className="form-group">
                                <label className="form-label">Upload Knowledge</label>
                                <div style={{ display: 'flex', gap: '8px', flexDirection: 'column' }}>
                                    <input type="file" multiple onChange={(e) => handleUploadFiles(e)} style={{ fontSize: '0.85rem' }} disabled={uploading} />
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button
                                            className="btn-modern secondary"
                                            style={{ flex: 1, fontSize: '0.85rem' }}
                                            onClick={() => document.getElementById('folder-upload').click()}
                                            disabled={uploading}
                                        >
                                            📁 Upload Folder
                                        </button>
                                        <input
                                            type="file"
                                            id="folder-upload"
                                            style={{ display: 'none' }}
                                            webkitdirectory="true"
                                            directory="true"
                                            multiple
                                            onChange={(e) => handleUploadFiles(e, true)}
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Trust Rules */}
                    <div className="settings-card" style={{ gridColumn: '1 / -1' }}>
                        <h3>⚖️ Trust & Scoring Rules</h3>
                        <table className="modern-table" style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <thead>
                                <tr>
                                    <th style={{ padding: '12px' }}>Pattern</th>
                                    <th>Trust Score</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {config.rules.map((rule, idx) => (
                                    <tr key={idx}>
                                        <td style={{ padding: '12px' }}>{rule.pattern}</td>
                                        <td>{rule.score}</td>
                                        <td>
                                            <button
                                                className="btn-delete-small"
                                                onClick={() => handleDeleteRule(idx)}
                                            >
                                                🗑️ Delete
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    );

    return (!token || !currentUser) ? <LoginScreen /> : (
        <div className="app-container">
            <Sidebar />
            <main className="main-content">
                {activeView === 'chat' ? <ChatView /> : <SettingsView />}
            </main>

            {lightboxImage && (
                <div className="lightbox-overlay" onClick={() => setLightboxImage(null)}>
                    <div className="lightbox-content">
                        <img src={lightboxImage} alt="Large" />
                    </div>
                </div>
            )}
        </div>
    );
}

export default App;
