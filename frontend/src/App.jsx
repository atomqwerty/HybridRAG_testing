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
    const [sessionId, setSessionId] = useState(() => Math.random().toString(36).substr(2, 9));
    const [sessions, setSessions] = useState([]); // list of {session_id, title, last_at}
    const [lightboxImage, setLightboxImage] = useState(null);
    const [isCreative, setIsCreative] = useState(true);
    const [isDraftMode, setIsDraftMode] = useState(false); // Sandbox mode for Admins

    // View State ('chat' or 'settings')
    const [activeView, setActiveView] = useState('chat');

    // Config & Files
    const [config, setConfig] = useState({ strict_mode: true, rules: [], default_score: 0.5 });
    const [ragConfig, setRagConfig] = useState({ k: 10, k_keyword: 15, min_score: 0.5, top_k_rerank: 10, multi_query: true });
    const [ragConfigSaving, setRagConfigSaving] = useState(false);
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

    // Users Management State (superadmin)
    const [userList, setUserList] = useState([]);
    const [auditLog, setAuditLog] = useState([]);
    const [usersTab, setUsersTab] = useState('users'); // 'users' | 'audit'
    const [newUserForm, setNewUserForm] = useState({ username: '', password: '', role: 'user' });
    const [pwForm, setPwForm] = useState({ userId: '', password: '' });
    const [userMsg, setUserMsg] = useState({ text: '', ok: true });

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
            // History will be loaded by the currentUser useEffect
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

    // Note: LoginScreen, Sidebar, ChatView, SettingsView have been moved outside App to prevent focus loss.
    // Note: LoginScreen, Sidebar, ChatView, SettingsView, and UsersView have been moved outside App to prevent focus loss.

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

        const fetchSessions = async () => {
            try {
                const res = await authFetch('/api/chat/sessions');
                if (res.ok) {
                    const data = await res.json();
                    const list = data.sessions || [];
                    setSessions(list);
                    // Load the most recent session if any
                    if (list.length > 0) {
                        loadSessionMessages(list[0].session_id);
                        setSessionId(list[0].session_id);
                    }
                }
            } catch (e) { console.error('fetchSessions failed', e); }
        };

        const initSources = async () => {
            const res = await authFetch('/api/files');
            const data = await res.json();
            if (data.files) setSelectedSources(new Set(data.files));
        };
        initSources();
        fetchSessions();

        // Fetch RAG config. If admin, fetch draft (id=2) by default for editing.
        const configIdToEdit = isAdmin ? '2' : '1';
        authFetch(`/api/config/rag?id=${configIdToEdit}`)
            .then(r => r.ok ? r.json() : null)
            .then(d => d && setRagConfig(d))
            .catch(() => { });
    }, [currentUser, isAdmin]);

    const loadSessionMessages = async (sid) => {
        try {
            const res = await authFetch(`/api/chat/history?session_id=${encodeURIComponent(sid)}`);
            if (res.ok) {
                const data = await res.json();
                const loaded = (data.messages || []).map(m => ({
                    type: m.role,
                    content: m.content,
                    sources: m.sources || [],
                    images: [],
                }));
                setMessages(loaded);
            }
        } catch (e) { console.error('loadSessionMessages failed', e); }
    };

    const handleNewChat = () => {
        const newId = Math.random().toString(36).substr(2, 9);
        setSessionId(newId);
        setMessages([]);
        setActiveView('chat');
    };

    const handleLoadSession = async (sid) => {
        setSessionId(sid);
        setMessages([]);
        setActiveView('chat');
        await loadSessionMessages(sid);
    };

    const handleDeleteSession = async (sid) => {
        try {
            await authFetch(`/api/chat/history?session_id=${encodeURIComponent(sid)}`, { method: 'DELETE' });
            setSessions(prev => prev.filter(s => s.session_id !== sid));
            if (sid === sessionId) {
                // Switch to another session or start fresh
                const remaining = sessions.filter(s => s.session_id !== sid);
                if (remaining.length > 0) {
                    handleLoadSession(remaining[0].session_id);
                } else {
                    handleNewChat();
                }
            }
        } catch (e) { console.error('handleDeleteSession failed', e); }
    };

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

    // --- User Management Handlers (superadmin) ---
    const loadUsers = async () => {
        try {
            const r = await authFetch('/api/auth/users');
            const d = await r.json();
            setUserList(d.users || []);
        } catch (e) { console.error(e); }
    };

    const loadAudit = async () => {
        try {
            const r = await authFetch('/api/auth/audit?limit=50');
            const d = await r.json();
            setAuditLog(d.entries || []);
        } catch (e) { console.error(e); }
    };

    const showUserMsg = (text, ok = true) => {
        setUserMsg({ text, ok });
        setTimeout(() => setUserMsg({ text: '', ok: true }), 3000);
    };

    const handleCreateUser = async (e) => {
        e.preventDefault();
        try {
            const r = await authFetch('/api/auth/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(newUserForm),
            });
            const d = await r.json();
            if (!r.ok) { showUserMsg(d.error || 'Failed', false); return; }
            setNewUserForm({ username: '', password: '', role: 'user' });
            showUserMsg(`User "${d.user.username}" created!`);
            loadUsers();
        } catch (e) { showUserMsg('Network error', false); }
    };

    const handleDeleteUser = async (userId, username) => {
        if (!window.confirm(`Delete user "${username}"?`)) return;
        const r = await authFetch(`/api/auth/users/${userId}`, { method: 'DELETE' });
        if (r.ok) { showUserMsg(`Deleted "${username}"`); loadUsers(); }
        else { const d = await r.json(); showUserMsg(d.error || 'Failed', false); }
    };

    const handleChangeRole = async (userId, newRole) => {
        const r = await authFetch(`/api/auth/users/${userId}/role`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: newRole }),
        });
        if (r.ok) { showUserMsg('Role updated'); loadUsers(); }
        else { const d = await r.json(); showUserMsg(d.error || 'Failed', false); }
    };

    const handleChangePw = async (e) => {
        e.preventDefault();
        if (!pwForm.userId || !pwForm.password) { showUserMsg('Select user and enter password', false); return; }
        const r = await authFetch(`/api/auth/users/${pwForm.userId}/password`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwForm.password }),
        });
        if (r.ok) { setPwForm({ userId: '', password: '' }); showUserMsg('Password changed!'); }
        else { const d = await r.json(); showUserMsg(d.error || 'Failed', false); }
    };

    const handleSendMessage = async (e) => {
        e.preventDefault();
        if (!input.trim() || loading) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { type: 'user', content: userMessage }]);
        setMessages(prev => [...prev, { type: 'bot', content: '', sources: [], images: [] }]);
        setLoading(true);

        let accumulatedContent = "";
        let finalSources = [];

        try {
            const response = await authFetch('/api/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    temperature: isCreative ? 0.3 : 0.0,
                    selected_sources: Array.from(selectedSources),
                    is_draft: isDraftMode
                })
            });

            if (!response.ok) throw new Error(`Server error ${response.status}`);

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

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
                                finalSources = data.sources || [];
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
            if (accumulatedContent) {
                const isNew = messages.length === 0; // First message in this session
                authFetch('/api/chat/history', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: sessionId,
                        messages: [
                            { role: 'user', content: userMessage, sources: [] },
                            { role: 'bot', content: accumulatedContent, sources: finalSources },
                        ]
                    })
                }).then(() => {
                    // Refresh the sessions list to update sidebar
                    authFetch('/api/chat/sessions')
                        .then(r => r.ok ? r.json() : null)
                        .then(d => d && setSessions(d.sessions || []))
                        .catch(() => { });
                }).catch(() => { });
            }
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

    const handleUpdateRagConfig = async (patch) => {
        setRagConfigSaving(true);
        try {
            const res = await authFetch('/api/config/rag', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(patch),
            });
            if (res.ok) {
                const data = await res.json();
                setRagConfig(data.config);
            } else {
                alert('Failed to save draft settings');
            }
        } catch (e) {
            alert('Error saving config');
        } finally {
            setRagConfigSaving(false);
        }
    };

    const handlePublishRagConfig = async () => {
        if (!window.confirm('Publish draft settings to production? This will affect all users.')) return;
        setRagConfigSaving(true);
        try {
            const res = await authFetch('/api/config/rag/publish', { method: 'POST' });
            if (res.ok) {
                alert('Successfully published to production!');
            } else {
                alert('Publish failed');
            }
        } catch (e) {
            alert('Networking error during publish');
        } finally {
            setRagConfigSaving(false);
        }
    };

    const handleClearChat = async (sid) => {
        const targetId = sid || sessionId;
        try {
            await authFetch(`/api/chat/history?session_id=${encodeURIComponent(targetId)}`, { method: 'DELETE' });
            setSessions(prev => prev.filter(s => s.session_id !== targetId));
            if (targetId === sessionId) {
                setMessages([]);
            }
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

    // Markdown/Table helpers moved outside.

    // UsersView moved outside.

    return (!token || !currentUser) ? <LoginScreen handleLogin={handleLogin} authError={authError} /> : (
        <div className="app-container">
            <Sidebar
                activeView={activeView}
                setActiveView={setActiveView}
                isAdmin={isAdmin}
                isSuperAdmin={isSuperAdmin}
                loadUsers={loadUsers}
                currentUser={currentUser}
                handleNewChat={handleNewChat}
                handleLoadSession={handleLoadSession}
                handleDeleteSession={handleDeleteSession}
                sessions={sessions}
                activeSessionId={sessionId}
                handleLogout={handleLogout}
            />
            <main className="main-content">
                {activeView === 'chat' && (
                    <ChatView
                        isIngesting={isIngesting}
                        ingestStatus={ingestStatus}
                        isCreative={isCreative}
                        messages={messages}
                        loading={loading}
                        input={input}
                        setInput={setInput}
                        handleSendMessage={handleSendMessage}
                        setLightboxImage={setLightboxImage}
                        formatMessage={formatMessage}
                        isAdmin={isAdmin}
                        isDraftMode={isDraftMode}
                        setIsDraftMode={setIsDraftMode}
                    />
                )}
                {activeView === 'settings' && (
                    <SettingsView
                        isCreative={isCreative}
                        setIsCreative={setIsCreative}
                        handleToggleAllSources={handleToggleAllSources}
                        selectedSources={selectedSources}
                        availableFiles={availableFiles}
                        isSuperAdmin={isSuperAdmin}
                        handleDeleteAll={handleDeleteAll}
                        refreshData={refreshData}
                        authFetch={authFetch}
                        handleDeleteFile={handleDeleteFile}
                        handleToggleSource={handleToggleSource}
                        handleUpload={handleUploadFiles} // Assuming handleUploadFiles is the correct handler for file uploads
                        isAdmin={isAdmin} // Pass isAdmin for ingestion section
                        currUrl={currUrl} // Pass currUrl for website crawling
                        setCurrUrl={setCurrUrl} // Pass setCurrUrl for website crawling
                        handleAddUrl={handleAddUrl} // Pass handleAddUrl for website crawling
                        uploading={uploading} // Pass uploading state
                        config={config}
                        handleDeleteRule={handleDeleteRule}
                        setConfig={setConfig}
                        ragConfig={ragConfig}
                        ragConfigSaving={ragConfigSaving}
                        handleUpdateRagConfig={handleUpdateRagConfig}
                        handlePublish={handlePublishRagConfig}
                    />
                )}
                {activeView === 'users' && isSuperAdmin && (
                    <UsersView
                        userList={userList}
                        auditLog={auditLog}
                        usersTab={usersTab}
                        setUsersTab={setUsersTab}
                        userMsg={userMsg}
                        newUserForm={newUserForm}
                        setNewUserForm={setNewUserForm}
                        pwForm={pwForm}
                        setPwForm={setPwForm}
                        currentUser={currentUser}
                        loadAudit={loadAudit}
                        handleCreateUser={handleCreateUser}
                        handleDeleteUser={handleDeleteUser}
                        handleChangeRole={handleChangeRole}
                        handleChangePw={handleChangePw}
                    />
                )}
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

// ── Helpers ────────────────────────────────────────────────────────

const processInlineMarkdown = (text, setLightboxImage) => {
    if (!text) return null;
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

const renderTable = (rows, setLightboxImage) => {
    const tableData = rows.map(row => row.split('|').filter(cell => cell.trim()).map(cell => cell.trim()));
    if (tableData.length < 2) return null;
    const headers = tableData[0];
    const dataRows = tableData.slice(2);
    return (
        <table>
            <thead><tr>{headers.map((h, i) => <th key={i}>{processInlineMarkdown(h, setLightboxImage)}</th>)}</tr></thead>
            <tbody>{dataRows.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{processInlineMarkdown(c, setLightboxImage)}</td>)}</tr>)}</tbody>
        </table>
    );
};

const formatMessage = (content, setLightboxImage) => {
    const lines = typeof content === 'string' ? content.split('\n') : [];
    const formatted = [];
    let tableRows = [];

    lines.forEach((line, idx) => {
        if (line.trim().startsWith('|')) {
            tableRows.push(line);
        } else {
            if (tableRows.length > 0) {
                formatted.push(<div key={`table-${idx}`} className="markdown-table">{renderTable(tableRows, setLightboxImage)}</div>);
                tableRows = [];
            }
            if (line.trim()) {
                if (line.startsWith('###')) formatted.push(<h3 key={idx}>{processInlineMarkdown(line.replace(/^###\s*/, ''), setLightboxImage)}</h3>);
                else if (line.trim().startsWith('-')) formatted.push(<li key={idx}>{processInlineMarkdown(line.trim().substring(1).trim(), setLightboxImage)}</li>);
                else formatted.push(<p key={idx}>{processInlineMarkdown(line, setLightboxImage)}</p>);
            }
        }
    });
    if (tableRows.length > 0) formatted.push(<div key="table-final" className="markdown-table">{renderTable(tableRows, setLightboxImage)}</div>);
    return formatted;
};

// ── Components ──────────────────────────────────────────────────────

const LoginScreen = ({ handleLogin, authError }) => (
    <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'linear-gradient(135deg, #0f0c29, #302b63, #24243e)'
    }}>
        <div style={{
            background: 'rgba(255,255,255,0.05)', backdropFilter: 'blur(16px)', borderRadius: '20px',
            border: '1px solid rgba(255,255,255,0.12)', padding: '48px', width: '380px',
            boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)'
        }}>
            <div style={{ textAlign: 'center', marginBottom: '32px' }}>
                <div style={{ fontSize: '3rem', marginBottom: '16px' }}>🌌</div>
                <h2 style={{ color: 'white', fontSize: '1.75rem', fontWeight: 800 }}>Hybrid RAG</h2>
                <p style={{ color: '#9ca3af', fontSize: '0.9rem' }}>Secure and Private Intelligence</p>
            </div>
            <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div>
                    <input name="username" placeholder="Username" required
                        style={{ width: '100%', padding: '14px 16px', borderRadius: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', outline: 'none' }} />
                </div>
                <div>
                    <input name="password" type="password" placeholder="Password" required
                        style={{ width: '100%', padding: '14px 16px', borderRadius: '12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', outline: 'none' }} />
                </div>
                {authError && <div style={{ color: '#f87171', fontSize: '0.85rem', textAlign: 'center' }}>{authError}</div>}
                <button type="submit" style={{ padding: '14px', borderRadius: '12px', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: 'white', fontWeight: 700, border: 'none', cursor: 'pointer', fontSize: '1rem', marginTop: '8px' }}>Sign In</button>
            </form>
        </div>
    </div>
);

const Sidebar = ({ activeView, setActiveView, isAdmin, isSuperAdmin, loadUsers, currentUser, handleNewChat, handleLoadSession, handleDeleteSession, sessions, activeSessionId, handleLogout }) => (
    <div className="sidebar">
        <div className="sidebar-logo">
            <span style={{ fontSize: '1.4rem' }}>🌌</span>
            <span>Hybrid RAG</span>
        </div>

        <button className="new-chat-btn" onClick={handleNewChat}>
            <span>✏️</span> New Chat
        </button>

        <div className="sidebar-section-label">Recent Chats</div>
        <div className="chat-list">
            {sessions.length === 0 ? (
                <div className="chat-list-empty">No chats yet. Start one above!</div>
            ) : sessions.map(s => (
                <div
                    key={s.session_id}
                    className={`chat-list-item ${s.session_id === activeSessionId ? 'active' : ''}`}
                    onClick={() => handleLoadSession(s.session_id)}
                >
                    <div className="chat-list-title">{s.title || 'New Conversation'}</div>
                    <div className="chat-list-meta">
                        <span>{s.last_at ? new Date(s.last_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : ''}</span>
                        <button
                            className="chat-list-delete"
                            title="Delete chat"
                            onClick={(e) => { e.stopPropagation(); handleDeleteSession(s.session_id); }}
                        >🗑️</button>
                    </div>
                </div>
            ))}
        </div>

        <div className="sidebar-footer">
            {isAdmin && (
                <button className={`nav-item ${activeView === 'settings' ? 'active' : ''}`} onClick={() => setActiveView('settings')}>
                    <span>⚙️</span> Settings & Data
                </button>
            )}
            {isSuperAdmin && (
                <button className={`nav-item ${activeView === 'users' ? 'active' : ''}`} onClick={() => { setActiveView('users'); loadUsers(); }}>
                    <span>👥</span> User Management
                </button>
            )}
            <div className="user-pill">
                <div className="user-avatar">{currentUser?.username?.[0] || 'U'}</div>
                <div className="user-info">
                    <span className="user-name">{currentUser?.username}</span>
                    <span className="user-role">{ROLE_BADGE[currentUser?.role] || currentUser?.role}</span>
                </div>
            </div>
            <button className="nav-item" onClick={handleLogout} style={{ color: '#f87171' }}>
                <span>🚪</span> Sign Out
            </button>
        </div>
    </div>
)

const ChatView = ({ isIngesting, ingestStatus, isCreative, messages, loading, input, setInput, handleSendMessage, setLightboxImage, messagesEndRef, formatMessage, isAdmin, isDraftMode, setIsDraftMode }) => (
    <div className="chat-root" style={{ position: 'relative' }}>
        <header className="chat-header">
            <div style={{ display: 'flex', flexDirection: 'column' }}>
                <h1 style={{ margin: 0 }}>AI Assistant</h1>
                {isAdmin && (
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '4px' }}>
                        <div className={`toggle-switch small ${isDraftMode ? 'draft' : ''}`}>
                            <input type="checkbox" checked={isDraftMode} onChange={e => setIsDraftMode(e.target.checked)} />
                            <span className="slider"></span>
                        </div>
                        <span style={{ fontSize: '0.75rem', fontWeight: 600, color: isDraftMode ? '#f59e0b' : '#6b7280' }}>
                            {isDraftMode ? '🧪 SANDBOX MODE' : '🌐 PRODUCTION'}
                        </span>
                    </div>
                )}
            </div>
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
                <div className="welcome-screen">
                    <div style={{ fontSize: '2.5rem' }}>🌌</div>
                    <h2>How can I help you today?</h2>
                    <p>Ask about documents, images, or data — I'll find the answer.</p>
                    <div className="welcome-chips">
                        {['Summarize the latest uploads', 'Compare two documents', 'Extract key data from tables', 'Find references to a topic'].map(q => (
                            <div key={q} className="welcome-chip" onClick={() => setInput(q)}>{q}</div>
                        ))}
                    </div>
                </div>
            )}
            {messages.map((msg, idx) => (
                <div key={idx} className={`message ${msg.type}`}>
                    <div className="message-inner">
                        <div className="avatar">
                            {msg.type === 'user'
                                ? 'U'
                                : (msg.agent === 'visual' || msg.agent === 'image' ? '📸'
                                    : msg.agent === 'table' ? '📊' : '✦')}
                        </div>
                        <div className="message-body">
                            {msg.type === 'bot' && msg.agent && (
                                <div className="agent-badge">
                                    {msg.agent === 'visual' || msg.agent === 'image' ? 'Image Agent'
                                        : msg.agent === 'table' ? 'Table Agent' : 'Text Assistant'}
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
                                    msg.content ? formatMessage(msg.content, setLightboxImage) :
                                        (msg.thought ? null : <div className="typing-indicator"><span></span><span></span><span></span></div>)
                                ) : msg.content}
                            </div>
                            {msg.sources?.length > 0 && (
                                <div className="sources-section">
                                    <div className="sources-label">Sources</div>
                                    <div className="source-chips">
                                        {msg.sources.map((s, i) => (
                                            <span key={i} className="source-chip" title={s.file}>
                                                📄 {s.file?.length > 18 ? s.file.substring(0, 15) + '…' : s.file} p.{s.page}
                                            </span>
                                        ))}
                                    </div>
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
                </div>
            ))}
            {loading && messages.length > 0 && messages[messages.length - 1]?.content === '' && (
                <div className="message bot">
                    <div className="message-inner">
                        <div className="avatar">✦</div>
                        <div className="message-body">
                            <div className="typing-indicator"><span></span><span></span><span></span></div>
                        </div>
                    </div>
                </div>
            )}
            <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
            <div className="input-wrapper">
                <form className="input-box" onSubmit={handleSendMessage}>
                    <textarea
                        rows="1"
                        placeholder="Message Hybrid RAG…"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                                e.preventDefault();
                                handleSendMessage(e);
                            }
                        }}
                    />
                    <button type="submit" className="send-btn" disabled={!input.trim() || loading}
                        title={loading ? 'Generating…' : 'Send'}>
                        {loading ? '⏳' : '↑'}
                    </button>
                </form>
                <div className="input-hint">Hybrid RAG can make mistakes. Check important info. · Shift+Enter for new line</div>
            </div>
        </div>
    </div>
);

const SettingsView = ({
    isCreative, setIsCreative, handleToggleAllSources, selectedSources, availableFiles,
    isSuperAdmin, handleDeleteAll, refreshData, authFetch, handleDeleteFile, handleToggleSource, handleUpload,
    isAdmin, currUrl, setCurrUrl, handleAddUrl, uploading, config, handleDeleteRule, setConfig,
    ragConfig, ragConfigSaving, handleUpdateRagConfig, handlePublish
}) => {
    const [draft, setDraft] = React.useState(null);
    const rc = draft || ragConfig;
    const updateDraft = (k, v) => setDraft(prev => ({ ...(prev || ragConfig), [k]: v }));
    const saveDraft = () => { if (draft) handleUpdateRagConfig(draft).then ? handleUpdateRagConfig(draft).then(() => setDraft(null)) : (handleUpdateRagConfig(draft), setDraft(null)); };
    return (
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
                                    <input type="file" multiple onChange={(e) => handleUpload(e)} style={{ fontSize: '0.85rem' }} disabled={uploading} />
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
                                            onChange={(e) => handleUpload(e, true)}
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

                {/* Retrieval Settings — admin+ */}
                {isAdmin && (
                    <div className="settings-card">
                        <h3>⚙️ Retrieval Settings</h3>
                        <p style={{ fontSize: '0.82rem', color: '#6b7280', marginBottom: '16px' }}>
                            Update the global RAG draft — Changes are saved to a separate sandbox row. Use "Publish" to go live.
                        </p>

                        {/* Persona Management */}
                        <div className="form-group" style={{ marginBottom: '24px', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '16px' }}>
                            <label className="form-label" style={{ fontWeight: 700, color: '#4f46e5' }}>🤖 AI Persona & Personality</label>
                            
                            <div style={{ marginTop: '12px' }}>
                                <label className="form-label">Persona Name</label>
                                <input className="input-dark" type="text" placeholder="e.g. Technical Expert"
                                    value={rc?.persona_name || ''}
                                    onChange={e => updateDraft('persona_name', e.target.value)} />
                            </div>

                            <div style={{ marginTop: '12px' }}>
                                <label className="form-label">System Prompt (Persona Instructions)</label>
                                <textarea className="input-dark" rows="5" 
                                    placeholder="You are a helpful assistant..."
                                    style={{ width: '100%', resize: 'vertical', fontSize: '0.85rem' }}
                                    value={rc?.system_prompt || ''}
                                    onChange={e => updateDraft('system_prompt', e.target.value)} />
                                <div style={{ fontSize: '0.7rem', color: '#9ca3af', marginTop: '4px' }}>
                                    Use variable placeholders like <b>{"{context}"}</b>, <b>{"{question}"}</b>, and <b>{"{history}"}</b> if custom formatting is needed.
                                </div>
                            </div>
                        </div>

                        {/* Vector chunks (k) */}
                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <label className="form-label">Vector chunks (k)</label>
                                <span style={{ fontSize: '0.85rem', color: '#a78bfa' }}>{rc?.k}</span>
                            </div>
                            <input type="range" min="1" max="30" step="1" className="rag-slider"
                                value={rc?.k || 10}
                                onChange={e => updateDraft('k', Number(e.target.value))} />
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: '#6b7280' }}><span>1</span><span>30</span></div>
                        </div>

                        {/* Keyword chunks */}
                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <label className="form-label">Keyword chunks</label>
                                <span style={{ fontSize: '0.85rem', color: '#a78bfa' }}>{rc?.k_keyword}</span>
                            </div>
                            <input type="range" min="1" max="40" step="1" className="rag-slider"
                                value={rc?.k_keyword || 15}
                                onChange={e => updateDraft('k_keyword', Number(e.target.value))} />
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: '#6b7280' }}><span>1</span><span>40</span></div>
                        </div>

                        {/* Similarity threshold */}
                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <label className="form-label">Similarity threshold</label>
                                <span style={{ fontSize: '0.85rem', color: '#a78bfa' }}>{(rc?.min_score ?? 0.5).toFixed(2)}</span>
                            </div>
                            <input type="range" min="0" max="1" step="0.05" className="rag-slider"
                                value={rc?.min_score ?? 0.5}
                                onChange={e => updateDraft('min_score', Number(e.target.value))} />
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: '#6b7280' }}><span>0.0</span><span>1.0</span></div>
                        </div>

                        {/* Reranker top-k */}
                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                <label className="form-label">Reranker top-k</label>
                                <span style={{ fontSize: '0.85rem', color: '#a78bfa' }}>{rc?.top_k_rerank}</span>
                            </div>
                            <input type="range" min="1" max="20" step="1" className="rag-slider"
                                value={rc?.top_k_rerank || 10}
                                onChange={e => updateDraft('top_k_rerank', Number(e.target.value))} />
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: '#6b7280' }}><span>1</span><span>20</span></div>
                        </div>

                        {/* Query expansion */}
                        <div className="form-group">
                            <label className="checkbox-label" style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }}>
                                <div className="toggle-switch">
                                    <input type="checkbox" checked={rc?.multi_query ?? true}
                                        onChange={e => updateDraft('multi_query', e.target.checked)} />
                                    <span className="slider"></span>
                                </div>
                                <div>
                                    <div style={{ fontWeight: 600 }}>Query Expansion</div>
                                    <div style={{ fontSize: '0.8rem', color: '#6b7280' }}>Generate alternative queries to improve recall.</div>
                                </div>
                            </label>
                        </div>

                        <div style={{ display: 'flex', gap: '12px', marginTop: '16px' }}>
                            <button
                                className="btn-modern secondary"
                                style={{ flex: 1 }}
                                disabled={!draft || ragConfigSaving}
                                onClick={saveDraft}
                            >
                                {ragConfigSaving ? 'Saving…' : '💾 Save Draft'}
                            </button>
                            <button
                                className="btn-modern primary"
                                style={{ flex: 1.2, background: 'linear-gradient(135deg, #10b981, #059669)' }}
                                disabled={ragConfigSaving}
                                onClick={handlePublish}
                            >
                                🚀 Publish to Production
                            </button>
                        </div>
                    </div>
                )}

            </div>
        </div>
    );
};

const UsersView = ({
    userList, auditLog, usersTab, setUsersTab, userMsg, newUserForm, setNewUserForm,
    pwForm, setPwForm, currentUser, loadAudit, handleCreateUser, handleDeleteUser,
    handleChangeRole, handleChangePw
}) => (
    <div className="settings-view">
        <div className="settings-container" style={{ maxWidth: '900px' }}>
            <h2 style={{ marginBottom: '24px', fontSize: '1.875rem' }}>👥 User Management</h2>

            {/* Tabs */}
            <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
                {['users', 'audit'].map(t => (
                    <button key={t} onClick={() => { setUsersTab(t); if (t === 'audit') loadAudit(); }}
                        style={{
                            padding: '8px 20px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontWeight: 600,
                            background: usersTab === t ? 'linear-gradient(135deg,#6366f1,#8b5cf6)' : 'rgba(255,255,255,0.06)',
                            color: usersTab === t ? '#fff' : '#9ca3af', transition: 'all 0.2s'
                        }}>
                        {t === 'users' ? '👤 Users' : '📋 Audit Log'}
                    </button>
                ))}
            </div>

            {/* Status message */}
            {userMsg.text && (
                <div style={{
                    padding: '10px 16px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.9rem', fontWeight: 500,
                    background: userMsg.ok ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)',
                    color: userMsg.ok ? '#34d399' : '#f87171',
                    border: `1px solid ${userMsg.ok ? 'rgba(52,211,153,0.3)' : 'rgba(248,113,113,0.3)'}`
                }}>{userMsg.text}</div>
            )}

            {usersTab === 'users' && (
                <>
                    {/* User Table */}
                    <div className="settings-card" style={{ marginBottom: '24px' }}>
                        <h3 style={{ marginBottom: '16px' }}>All Users</h3>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
                            <thead>
                                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                                    {['Username', 'Role', 'Created', 'Change Role', 'Actions'].map(h => (
                                        <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#9ca3af', fontWeight: 600 }}>{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {userList.map(u => (
                                    <tr key={u.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                                        <td style={{ padding: '10px 12px', fontWeight: 600, color: '#e5e7eb' }}>
                                            {u.username}
                                            {u.id === currentUser?.id && <span style={{ marginLeft: '6px', fontSize: '0.72rem', color: '#6b7280' }}>(you)</span>}
                                        </td>
                                        <td style={{ padding: '10px 12px' }}>
                                            <span style={{
                                                padding: '2px 10px', borderRadius: '99px', fontSize: '0.78rem', fontWeight: 700,
                                                background: u.role === 'superadmin' ? 'rgba(251,191,36,0.15)' : u.role === 'admin' ? 'rgba(99,102,241,0.15)' : 'rgba(107,114,128,0.15)',
                                                color: u.role === 'superadmin' ? '#fbbf24' : u.role === 'admin' ? '#818cf8' : '#9ca3af'
                                            }}>{ROLE_BADGE[u.role] || u.role}</span>
                                        </td>
                                        <td style={{ padding: '10px 12px', color: '#6b7280', fontSize: '0.82rem' }}>
                                            {u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}
                                        </td>
                                        <td style={{ padding: '10px 12px' }}>
                                            {u.id !== currentUser?.id && (
                                                <select value={u.role} onChange={ev => handleChangeRole(u.id, ev.target.value)}
                                                    style={{ background: 'rgba(255,255,255,0.06)', color: '#e5e7eb', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', padding: '4px 8px', cursor: 'pointer', fontSize: '0.85rem' }}>
                                                    <option value="user">User</option>
                                                    <option value="admin">Admin</option>
                                                    <option value="superadmin">Super Admin</option>
                                                </select>
                                            )}
                                        </td>
                                        <td style={{ padding: '10px 12px' }}>
                                            {u.id !== currentUser?.id && (
                                                <button onClick={() => handleDeleteUser(u.id, u.username)}
                                                    style={{ padding: '4px 10px', borderRadius: '6px', border: 'none', background: 'rgba(248,113,113,0.15)', color: '#f87171', cursor: 'pointer', fontSize: '0.82rem', fontWeight: 600 }}>
                                                    🗑️ Delete
                                                </button>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                                {userList.length === 0 && (
                                    <tr><td colSpan={5} style={{ padding: '24px', textAlign: 'center', color: '#6b7280' }}>No users found</td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>

                    {/* Create User */}
                    <div className="settings-card" style={{ marginBottom: '24px' }}>
                        <h3 style={{ marginBottom: '16px' }}>➕ Create New User</h3>
                        <form onSubmit={handleCreateUser} style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                            <div style={{ flex: '1', minWidth: '140px' }}>
                                <label style={{ display: 'block', color: '#9ca3af', fontSize: '0.8rem', marginBottom: '6px' }}>Username</label>
                                <input id="new-username" value={newUserForm.username}
                                    onChange={e => setNewUserForm(f => ({ ...f, username: e.target.value }))}
                                    required placeholder="e.g. john"
                                    style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', boxSizing: 'border-box', border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#e5e7eb', fontSize: '0.9rem', outline: 'none' }} />
                            </div>
                            <div style={{ flex: '1', minWidth: '140px' }}>
                                <label style={{ display: 'block', color: '#9ca3af', fontSize: '0.8rem', marginBottom: '6px' }}>Password</label>
                                <input id="new-password" type="password" value={newUserForm.password}
                                    onChange={e => setNewUserForm(f => ({ ...f, password: e.target.value }))}
                                    required placeholder="Password"
                                    style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', boxSizing: 'border-box', border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#e5e7eb', fontSize: '0.9rem', outline: 'none' }} />
                            </div>
                            <div style={{ minWidth: '130px' }}>
                                <label style={{ display: 'block', color: '#9ca3af', fontSize: '0.8rem', marginBottom: '6px' }}>Role</label>
                                <select value={newUserForm.role} onChange={e => setNewUserForm(f => ({ ...f, role: e.target.value }))}
                                    style={{ padding: '9px 12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#e5e7eb', fontSize: '0.9rem', cursor: 'pointer' }}>
                                    <option value="user">User</option>
                                    <option value="admin">Admin</option>
                                    <option value="superadmin">Super Admin</option>
                                </select>
                            </div>
                            <button id="create-user-btn" type="submit"
                                style={{ padding: '9px 20px', borderRadius: '8px', border: 'none', background: 'linear-gradient(135deg,#6366f1,#8b5cf6)', color: '#fff', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem' }}>
                                Create User
                            </button>
                        </form>
                    </div>

                    {/* Change Password */}
                    <div className="settings-card">
                        <h3 style={{ marginBottom: '16px' }}>🔑 Change Password</h3>
                        <form onSubmit={handleChangePw} style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'flex-end' }}>
                            <div style={{ flex: '1', minWidth: '160px' }}>
                                <label style={{ display: 'block', color: '#9ca3af', fontSize: '0.8rem', marginBottom: '6px' }}>Select User</label>
                                <select value={pwForm.userId} onChange={e => setPwForm(f => ({ ...f, userId: e.target.value }))} required
                                    style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', boxSizing: 'border-box', border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#e5e7eb', fontSize: '0.9rem', cursor: 'pointer' }}>
                                    <option value="">— choose —</option>
                                    {userList.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
                                </select>
                            </div>
                            <div style={{ flex: '1', minWidth: '160px' }}>
                                <label style={{ display: 'block', color: '#9ca3af', fontSize: '0.8rem', marginBottom: '6px' }}>New Password</label>
                                <input id="change-pw" type="password" value={pwForm.password}
                                    onChange={e => setPwForm(f => ({ ...f, password: e.target.value }))}
                                    required placeholder="New password"
                                    style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', boxSizing: 'border-box', border: '1px solid rgba(255,255,255,0.12)', background: 'rgba(255,255,255,0.06)', color: '#e5e7eb', fontSize: '0.9rem', outline: 'none' }} />
                            </div>
                            <button id="change-pw-btn" type="submit"
                                style={{ padding: '9px 20px', borderRadius: '8px', border: 'none', background: 'linear-gradient(135deg,#f59e0b,#ef4444)', color: '#fff', fontWeight: 700, cursor: 'pointer', fontSize: '0.9rem' }}>
                                Change Password
                            </button>
                        </form>
                    </div>
                </>
            )}

            {usersTab === 'audit' && (
                <div className="settings-card">
                    <h3 style={{ marginBottom: '16px' }}>📋 Audit Log <span style={{ fontSize: '0.8rem', color: '#6b7280', fontWeight: 400 }}>(last 50)</span></h3>
                    <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                            <thead>
                                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)' }}>
                                    {['Time', 'Actor', 'Action', 'Detail'].map(h => (
                                        <th key={h} style={{ textAlign: 'left', padding: '8px 12px', color: '#9ca3af', fontWeight: 600 }}>{h}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {auditLog.map((entry, i) => (
                                    <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                                        <td style={{ padding: '8px 12px', color: '#6b7280', whiteSpace: 'nowrap' }}>
                                            {new Date(entry.timestamp).toLocaleString()}
                                        </td>
                                        <td style={{ padding: '8px 12px', fontWeight: 600, color: '#818cf8' }}>{entry.actor}</td>
                                        <td style={{ padding: '8px 12px' }}>
                                            <span style={{ padding: '2px 8px', borderRadius: '99px', fontSize: '0.78rem', background: 'rgba(99,102,241,0.1)', color: '#a5b4fc', fontWeight: 600 }}>
                                                {entry.action}
                                            </span>
                                        </td>
                                        <td style={{ padding: '8px 12px', color: '#d1d5db' }}>{entry.detail}</td>
                                    </tr>
                                ))}
                                {auditLog.length === 0 && (
                                    <tr><td colSpan={4} style={{ padding: '24px', textAlign: 'center', color: '#6b7280' }}>No audit entries yet</td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    </div>
);

export default App;
