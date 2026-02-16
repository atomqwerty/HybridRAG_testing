import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [sessionId] = useState(() => Math.random().toString(36).substr(2, 9));
    const [lightboxImage, setLightboxImage] = useState(null);
    const [isCreative, setIsCreative] = useState(true); // Default to Creative (0.3)

    // View State ('chat' or 'settings')
    const [view, setView] = useState('chat');
    const [config, setConfig] = useState({ strict_mode: true, rules: [], default_score: 0.5 });
    const [availableFiles, setAvailableFiles] = useState([]);

    const [currUrl, setCurrUrl] = useState('');
    const [uploading, setUploading] = useState(false);
    const [isIngesting, setIsIngesting] = useState(false);
    const [ingestStatus, setIngestStatus] = useState({ percent: 0, message: '' });

    // --- Status & Notification State ---
    const [uploadStatus, setUploadStatus] = useState(null); // { type: 'success'|'error', msg: '' }

    // Helper: Clear status after 3 seconds
    const showStatus = (type, msg) => {
        setUploadStatus({ type, msg });
        setTimeout(() => setUploadStatus(null), 5000);
    };

    // --- Drag and Drop Logic ---
    const [isDragging, setIsDragging] = useState(false);

    const handleDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setIsDragging(true);
        } else if (e.type === 'dragleave') {
            setIsDragging(false);
        }
    };

    const traverseFileTree = (item, path = "") => {
        return new Promise((resolve) => {
            if (item.isFile) {
                item.file((file) => {
                    resolve([file]);
                });
            } else if (item.isDirectory) {
                const dirReader = item.createReader();
                dirReader.readEntries(async (entries) => {
                    let files = [];
                    for (let i = 0; i < entries.length; i++) {
                        const subFiles = await traverseFileTree(entries[i], path + item.name + "/");
                        files = files.concat(subFiles);
                    }
                    resolve(files);
                });
            } else {
                resolve([]);
            }
        });
    };

    // Helper to refresh data without changing view
    const refreshSettingsData = async () => {
        try {
            const [configRes, filesRes] = await Promise.all([
                fetch('/api/config/trust?_t=' + Date.now()),
                fetch('/api/files?_t=' + Date.now())
            ]);
            const configData = await configRes.json();
            const filesData = await filesRes.json();
            setConfig(configData);
            setAvailableFiles(filesData.files || []);
        } catch (err) {
            console.error("Failed to refresh settings data", err);
        }
    };

    const handleDrop = async (e) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragging(false);

        const items = e.dataTransfer.items;
        if (!items || items.length === 0) return;

        setUploading(true);
        const formData = new FormData();
        let fileCount = 0;

        try {
            const filePromises = [];
            for (let i = 0; i < items.length; i++) {
                const item = items[i].webkitGetAsEntry();
                if (item) {
                    filePromises.push(traverseFileTree(item));
                }
            }

            const results = await Promise.all(filePromises);
            const flatFiles = results.flat();

            if (flatFiles.length === 0) {
                showStatus('error', "No valid files found in drop.");
                setUploading(false);
                return;
            }

            for (const file of flatFiles) {
                formData.append('file', file);
                fileCount++;
            }

            // Reuse the existing fetch logic
            const res = await fetch('/api/ingest/upload', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (res.ok) {
                showStatus('success', `Success: Processed ${fileCount} files.`);
                await refreshSettingsData(); // Refresh immediately
                setIsIngesting(true);
            } else {
                showStatus('error', 'Error: ' + data.error);
            }
        } catch (error) {
            console.error(error);
            showStatus('error', "Drag and drop failed");
        } finally {
            setUploading(false);
        }
    };

    const messagesEndRef = useRef(null);
    const viewRef = useRef(view);

    useEffect(() => { viewRef.current = view; }, [view]);

    // Fetch Config on open settings
    const openSettings = async () => {
        await refreshSettingsData();
        setView('settings');
    };

    const saveSettings = async () => {
        try {
            await fetch('/api/config/trust', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            setView('chat');
            alert("Settings Saved!");
        } catch (err) {
            alert("Failed to save settings: " + err);
        }
    };

    const removeRule = async (idx) => {
        const ruleToRemove = config.rules[idx];
        if (!window.confirm(`⚠️ DANGER: This will PERMANENTLY DELETE all data from "${ruleToRemove.pattern}" from the database.\n\nAre you sure you want to proceed?`)) {
            return;
        }

        try {
            const newRules = config.rules.filter((_, i) => i !== idx);
            setConfig({ ...config, rules: newRules });

            const res = await fetch('/api/source', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pattern: ruleToRemove.pattern })
            });
            const data = await res.json();
            if (data.status === 'success') {
                alert("✅ Data purged successfully: " + data.message);
            } else {
                alert("⚠️ Error purging data: " + (data.error || "Unknown"));
            }
        } catch (err) {
            alert("❌ Network Error during purge: " + err);
        }
    };

    const updateRuleScore = (idx, val) => {
        const newScore = parseFloat(val);
        const newRules = [...config.rules];
        newRules[idx].score = isNaN(newScore) ? 0 : newScore;
        setConfig({ ...config, rules: newRules });
    };

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Check status on load (in case user refreshed during ingestion)
    useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await fetch('/api/ingest/status');
                const data = await res.json();
                if (data.status === 'running') {
                    setIsIngesting(true);
                    setIngestStatus(data);
                }
            } catch (e) { }
        };
        checkStatus();
    }, []);

    useEffect(() => {
        let interval;
        if (isIngesting) {
            interval = setInterval(async () => {
                try {
                    const res = await fetch('/api/ingest/status');
                    const data = await res.json();
                    setIngestStatus(data);

                    if (data.percent >= 100) {
                        setIsIngesting(false);
                        setUploading(false); // Ensure button enables
                        // FIX: Refresh Settings (Trust Rules) automatically when done
                        const refreshData = async () => {
                            try {
                                const [configRes, filesRes] = await Promise.all([
                                    fetch('/api/config/trust?_t=' + Date.now()),
                                    fetch('/api/files?_t=' + Date.now())
                                ]);
                                const configData = await configRes.json();
                                const filesData = await filesRes.json();
                                setConfig(configData);
                                setAvailableFiles(filesData.files || []);
                            } catch (err) { console.error(err); }
                        };

                        // Refresh data if in settings view
                        if (viewRef.current === 'settings') {
                            refreshData();
                        }

                        // Optional: Alert or toast notification? 
                        // For now silent completion is preferred by user.
                    }
                } catch (e) { }
            }, 1000);
        }
        return () => clearInterval(interval);
    }, [isIngesting]);

    // Helper to parse bold (**text**) AND images (![alt](src))
    const processInlineMarkdown = (text) => {
        // Regex to split by bold OR image
        // Group 1: **bold**
        // Group 2: ![alt](src)
        const parts = text.split(/(\*\*.*?\*\*)|(!\[.*?\]\(.*?\))/g);

        return parts.map((part, index) => {
            if (!part) return null;

            // Bold
            if (part.startsWith('**') && part.endsWith('**')) {
                return <strong key={index}>{part.slice(2, -2)}</strong>;
            }

            // Image
            if (part.match(/^!\[(.*?)\]\((.*?)\)$/)) {
                const match = part.match(/^!\[(.*?)\]\((.*?)\)$/);
                const alt = match[1];
                const src = match[2];
                return (
                    <img
                        key={index}
                        src={src}
                        alt={alt}
                        onClick={() => openLightbox(src)}
                        style={{
                            maxWidth: '100%',
                            borderRadius: '8px',
                            cursor: 'pointer',
                            margin: '5px 0',
                            display: 'block'
                        }}
                    />
                );
            }

            return part;
        });
    };

    // Format message content to preserve tables, headers, and bold
    const formatMessage = (content) => {
        // Split by code blocks and tables
        const lines = content.split('\n');
        const formatted = [];
        let inTable = false;
        let tableRows = [];

        lines.forEach((line, idx) => {
            // Detect markdown table
            if (line.trim().startsWith('|')) {
                inTable = true;
                tableRows.push(line);
            } else {
                if (inTable && tableRows.length > 0) {
                    // End of table, render it
                    formatted.push(
                        <div key={`table-${idx}`} className="markdown-table">
                            {renderTable(tableRows)}
                        </div>
                    );
                    tableRows = [];
                    inTable = false;
                }
                if (line.trim()) {
                    // Check for Headers (###)
                    if (line.startsWith('###')) {
                        const headerText = line.replace(/^###\s*/, '');
                        formatted.push(<h3 key={idx}>{processInlineMarkdown(headerText)}</h3>);
                    }
                    // Check for Bullet Points
                    else if (line.trim().startsWith('-')) {
                        const liText = line.trim().substring(1).trim();
                        formatted.push(<li key={idx}>{processInlineMarkdown(liText)}</li>);
                    }
                    // Normal text + Inline Images
                    else {
                        formatted.push(<div key={idx}>{processInlineMarkdown(line)}</div>);
                    }
                }
            }
        });

        // Handle remaining table
        if (tableRows.length > 0) {
            formatted.push(
                <div key="table-final" className="markdown-table">
                    {renderTable(tableRows)}
                </div>
            );
        }

        return formatted.length > 0 ? formatted : content;
    };

    const renderTable = (rows) => {
        const tableData = rows.map(row =>
            row.split('|').filter(cell => cell.trim()).map(cell => cell.trim())
        );

        if (tableData.length < 2) return rows.join('\n');

        const headers = tableData[0];
        const dataRows = tableData.slice(2); // Skip header separator

        return (
            <table>
                <thead>
                    <tr>
                        {headers.map((header, i) => <th key={i}>{processInlineMarkdown(header)}</th>)}
                    </tr>
                </thead>
                <tbody>
                    {dataRows.map((row, i) => (
                        <tr key={i}>
                            {row.map((cell, j) => <td key={j}>{processInlineMarkdown(cell)}</td>)}
                        </tr>
                    ))}
                </tbody>
            </table>
        );
    };

    const sendMessage = async (e) => {
        e.preventDefault();
        if (!input.trim()) return;

        const userMessage = input.trim();
        setInput('');

        // 1. Add User Message
        setMessages(prev => [...prev, { type: 'user', content: userMessage }]);

        // 2. Add Bot Placeholder (Empty content initially)
        setMessages(prev => [...prev, { type: 'bot', content: '', sources: [], images: [] }]);
        setLoading(true);

        try {
            // Use STREAMING endpoint
            const response = await fetch('/api/chat/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    temperature: isCreative ? 0.3 : 0.0,
                    history: messages.map(m => `${m.type === 'user' ? 'User' : 'Bot'}: ${m.content}`).join('\n')
                })
            });

            if (!response.ok) {
                const data = await response.json();
                throw new Error(data.error || 'Failed to fetch');
            }

            // 3. Read Stream
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
                            const lastMsgIndex = newMsgs.length - 1;
                            const lastMsg = { ...newMsgs[lastMsgIndex] }; // Copy object

                            if (data.type === 'meta') {
                                // Received Sources/Images
                                lastMsg.sources = data.sources || [];
                                lastMsg.images = data.images || [];
                            } else if (data.type === 'token') {
                                // Received Text Token
                                accumulatedContent += data.content;
                                lastMsg.content = accumulatedContent;
                            }

                            newMsgs[lastMsgIndex] = lastMsg;
                            return newMsgs;
                        });
                    } catch (e) {
                        // console.error("Stream parse error:", e); 
                    }
                }
            }

        } catch (error) {
            console.error(error);
            setMessages(prev => {
                const newMsgs = [...prev];
                newMsgs[newMsgs.length - 1] = {
                    type: 'error',
                    content: `Connection error: ${error.message}`
                };
                return newMsgs;
            });
        } finally {
            setLoading(false);
        }
    };

    // Ingestion Handlers
    const handleAddUrl = async () => {
        if (!currUrl) return;
        setUploading(true);
        try {
            const res = await fetch('/api/ingest/url', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: currUrl })
            });
            const data = await res.json();
            if (res.ok) {
                alert('Success: ' + data.message);
                setCurrUrl('');
                setIsIngesting(true); // Start polling
            } else {
                alert('Error: ' + data.error);
                setUploading(false);
            }
        } catch (e) {
            alert('Failed to add URL');
        } finally {
            setUploading(false);
        }
    };

    const handleFileUpload = async (e) => {
        const files = e.target.files;
        if (!files || files.length === 0) return;

        setUploading(true);
        const formData = new FormData();

        // Append all files
        for (let i = 0; i < files.length; i++) {
            formData.append('file', files[i]);
        }

        try {
            const res = await fetch('/api/ingest/upload', {
                method: 'POST',
                body: formData // No Content-Type header needed, browser adds it with boundary
            });
            const data = await res.json();
            if (res.ok) {
                alert('Success: ' + data.message);
                openSettings(); // Refresh Trust Rules immediately
                setIsIngesting(true); // Start polling
            } else {
                alert('Error: ' + data.error);
                setUploading(false);
            }
        } catch (e) {
            alert('Failed to upload file');
            setUploading(false);
        } finally {
            e.target.value = null; // Reset input
        }
    };

    const clearDatabase = async () => {
        if (!window.confirm("ARE YOU SURE? This will delete ALL ingested data (Nodes, Text, Images) from the database. This cannot be undone.")) return;

        try {
            const res = await fetch('/api/admin/clear_db', { method: 'POST' });
            const data = await res.json();
            if (res.ok) {
                showStatus('success', "Database Cleared: " + data.message);
                await refreshSettingsData(); // Refresh immediately
            } else {
                showStatus('error', "Error: " + data.error);
            }
        } catch (e) {
            showStatus('error', "Failed to clear database");
        }
    };

    const clearChat = async () => {
        try {
            await fetch('/api/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });
            setMessages([]);
        } catch (error) {
            console.error('Failed to clear chat:', error);
        }
    };

    const openLightbox = (imageSrc) => {
        setLightboxImage(imageSrc);
    };

    const closeLightbox = () => {
        setLightboxImage(null);
    };

    return (
        <div className="app-container">
            {view === 'settings' ? (
                <div className="settings-page">
                    <div className="settings-container-full">
                        <div className="settings-header">
                            <h2>⚙️ Settings & Data</h2>
                            <button onClick={() => setView('chat')} className="btn-secondary">
                                ← Back to Chat
                            </button>
                        </div>

                        <div className="settings-content">
                            <div className="setting-group">
                                <label className="checkbox-label">
                                    <input
                                        type="checkbox"
                                        checked={isCreative}
                                        onChange={(e) => setIsCreative(e.target.checked)}
                                    />
                                    Creative Mode (Temp 0.3)
                                </label>
                                <p className="setting-desc">
                                    Creative mode gives more natural answers. Uncheck for Precise Mode (0.0).
                                </p>
                            </div>

                            <h3>Add Data Source</h3>
                            <div className="ingest-section">
                                <div className="ingest-row">
                                    <input
                                        type="text"
                                        placeholder="Enter Website URL (e.g. https://example.com/spec)"
                                        value={currUrl}
                                        onChange={(e) => setCurrUrl(e.target.value)}
                                        className="input-dark"
                                    />
                                    <button
                                        onClick={handleAddUrl}
                                        disabled={uploading}
                                        className="btn-primary"
                                    >
                                        {uploading ? 'Processing...' : 'Crawl URL'}
                                    </button>
                                </div>

                                <div
                                    className={`ingest-row upload-row drop-zone ${isDragging ? 'drag-active' : ''}`}
                                    onDragEnter={handleDrag}
                                    onDragOver={handleDrag}
                                    onDragLeave={handleDrag}
                                    onDrop={handleDrop}
                                    style={{
                                        flexDirection: 'column',
                                        alignItems: 'center',
                                        gap: '15px',
                                        border: isDragging ? '2px dashed #4299e1' : '2px dashed #4a5568',
                                        backgroundColor: isDragging ? 'rgba(66, 153, 225, 0.1)' : 'rgba(0, 0, 0, 0.2)',
                                        padding: '30px',
                                        borderRadius: '10px',
                                        transition: 'all 0.2s ease',
                                        cursor: 'default'
                                    }}
                                >
                                    <div style={{ fontSize: '2rem' }}>📂</div>
                                    <span style={{ color: '#a0aec0', fontWeight: 'bold' }}>Drag & Drop Files or Folders Here</span>
                                    <span style={{ color: '#718096', fontSize: '0.9rem' }}>-- OR --</span>

                                    <div style={{ display: 'flex', gap: '10px' }}>
                                        {/* File Upload Button */}
                                        <label className="btn-primary" style={{ cursor: 'pointer', margin: 0, fontSize: '0.9rem', padding: '8px 16px' }}>
                                            Select Files manually
                                            <input
                                                type="file"
                                                multiple
                                                onChange={handleFileUpload}
                                                disabled={uploading}
                                                style={{ display: 'none' }}
                                            />
                                        </label>
                                    </div>

                                    {uploadStatus && (
                                        <div style={{
                                            padding: '8px 12px',
                                            borderRadius: '6px',
                                            fontSize: '0.9rem',
                                            marginBottom: '8px',
                                            width: '100%',
                                            textAlign: 'center',
                                            background: uploadStatus.type === 'success' ? '#d1fae5' : '#fee2e2',
                                            color: uploadStatus.type === 'success' ? '#065f46' : '#991b1b',
                                            border: uploadStatus.type === 'success' ? '1px solid #34d399' : '1px solid #f87171'
                                        }}>
                                            {uploadStatus.type === 'success' ? '✅ ' : '⚠️ '} {uploadStatus.msg}
                                        </div>
                                    )}
                                    {uploading && <span className="status-text" style={{ color: '#48bb78' }}>Processing Upload...</span>}
                                </div>
                            </div>



                            <h3>Trust Rules Configuration</h3>
                            <div className="rules-table-container">
                                <table className="rules-table">
                                    <thead>
                                        <tr>
                                            <th>Data Source Pattern</th>
                                            <th>Trust Score</th>
                                            <th>Action</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {config.rules.map((rule, idx) => (
                                            <tr key={idx}>
                                                <td>{rule.pattern}</td>
                                                <td>
                                                    <input
                                                        type="number"
                                                        step="0.1" max="1.5" min="0"
                                                        value={rule.score}
                                                        onChange={(e) => updateRuleScore(idx, e.target.value)}
                                                        className="score-input"
                                                    />
                                                </td>
                                                <td>
                                                    <button onClick={() => removeRule(idx)} className="btn-icon delete" title="Remove">×</button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            <div className="danger-zone" style={{ marginTop: '40px', paddingTop: '20px', borderTop: '1px solid #e53e3e' }}>
                                <h3 style={{ color: '#e53e3e', borderBottom: 'none' }}>⚠️ Danger Zone</h3>
                                <button onClick={clearDatabase} style={{ background: '#e53e3e', color: 'white', border: 'none', padding: '10px 20px', borderRadius: '8px', cursor: 'pointer' }}>
                                    Clear Database (Purge All Data)
                                </button>
                                <p style={{ color: '#a0aec0', fontSize: '0.9rem', marginTop: '10px' }}>
                                    Use this if ingestion extracted too much "trash" and you want to start fresh with the new filters.
                                </p>
                            </div>
                        </div>
                        <div className="modal-actions">
                            <button onClick={() => setView('chat')} className="btn-secondary">Close</button>
                            <button onClick={saveSettings} className="btn-primary">Save Changes</button>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="chat-container">
                    <div className="chat-header">
                        <div className="header-title">
                            <h1>Hybrid RAG Assistant</h1>
                        </div>
                        <div className="header-controls">
                            <button onClick={openSettings} className="icon-btn" title="Settings">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                            </button>
                            <button onClick={clearChat} className="icon-btn" title="Clear Chat">
                                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                            </button>
                        </div>
                    </div>

                    {isIngesting && (
                        <div style={{ background: '#ebf8ff', padding: '12px 20px', borderBottom: '1px solid #e0e4e8' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '0.9rem', color: '#2b6cb0' }}>
                                <span><strong>Processing Data...</strong> {ingestStatus.message}</span>
                                <span>{ingestStatus.percent}%</span>
                            </div>
                            <div style={{ width: '100%', height: '8px', background: '#bee3f8', borderRadius: '4px', overflow: 'hidden' }}>
                                <div style={{ width: `${ingestStatus.percent}%`, height: '100%', background: '#3182ce', transition: 'width 0.5s ease' }}></div>
                            </div>
                        </div>
                    )}

                    <div className="messages-container">
                        {messages.map((msg, idx) => (
                            <div key={idx} className={`message ${msg.type}`}>
                                <div className="message-content">
                                    {typeof msg.content === 'string' ? formatMessage(msg.content) : msg.content}
                                </div>

                                {msg.sources && msg.sources.length > 0 && (
                                    <div className="sources">
                                        <strong>Sources:</strong>
                                        <ul>
                                            {msg.sources.map((src, i) => (
                                                <li key={i}>{src.file} (Page {src.page})</li>
                                            ))}
                                        </ul>
                                    </div>
                                )}

                                {msg.images && msg.images.length > 0 && (
                                    <div className="images">
                                        <strong>Images:</strong>
                                        <div className="image-grid">
                                            {msg.images.map((img, i) => (
                                                <div key={i} className="image-item">
                                                    <img
                                                        src={`/images/${img}`}
                                                        alt={`Reference ${i + 1}`}
                                                        onClick={() => openLightbox(`/images/${img}`)}
                                                    />
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}

                        {loading && (
                            <div className="message bot loading">
                                <div className="typing-indicator">
                                    <span></span>
                                    <span></span>
                                    <span></span>
                                </div>
                            </div>
                        )}

                        <div ref={messagesEndRef} />
                    </div>

                    <form onSubmit={sendMessage} className="input-container">
                        <div className="input-wrapper">
                            <input
                                type="text"
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                placeholder="Ask me anything..."
                                disabled={loading}
                            />
                        </div>
                        <button type="submit" disabled={loading || !input.trim()}>
                            ➜
                        </button>
                    </form>
                </div>
            )}

            {
                lightboxImage && (
                    <div className="lightbox-overlay" onClick={closeLightbox}>
                        <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
                            <button className="lightbox-close" onClick={closeLightbox}>×</button>
                            <img src={lightboxImage} alt="Full size" />
                        </div>
                    </div>
                )
            }
        </div >
    );
}

export default App;
