import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [sessionId] = useState(() => Math.random().toString(36).substr(2, 9));
    const [lightboxImage, setLightboxImage] = useState(null);
    const [isCreative, setIsCreative] = useState(true); // Default to Creative (0.3)

    // Settings State
    const [showSettings, setShowSettings] = useState(false);
    const [config, setConfig] = useState({ strict_mode: true, rules: [], default_score: 0.5 }); // Default
    const [newPattern, setNewPattern] = useState('');
    const [newScore, setNewScore] = useState(1.0);
    const [availableFiles, setAvailableFiles] = useState([]);

    const messagesEndRef = useRef(null);

    // Fetch Config on open settings
    const openSettings = async () => {
        try {
            const [configRes, filesRes] = await Promise.all([
                fetch('http://localhost:8000/api/config/trust'),
                fetch('http://localhost:8000/api/files')
            ]);

            const configData = await configRes.json();
            const filesData = await filesRes.json();

            setConfig(configData);
            setAvailableFiles(filesData.files || []);
            setShowSettings(true);
        } catch (err) {
            console.error("Failed to load settings", err);
        }
    };

    const saveSettings = async () => {
        try {
            await fetch('http://localhost:8000/api/config/trust', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            setShowSettings(false);
            alert("Settings Saved!");
        } catch (err) {
            alert("Failed to save settings: " + err);
        }
    };

    const addRule = () => {
        if (!newPattern.trim()) return;
        const newRule = { pattern: newPattern, score: parseFloat(newScore), type: 'custom' };
        setConfig({ ...config, rules: [...config.rules, newRule] });
        setNewPattern('');
        setNewScore(1.0);
    };

    const removeRule = async (idx) => {
        const ruleToRemove = config.rules[idx];
        if (!window.confirm(`⚠️ DANGER: This will PERMANENTLY DELETE all data from "${ruleToRemove.pattern}" from the database.\n\nAre you sure you want to proceed?`)) {
            return;
        }

        try {
            // Optimistic update
            const newRules = config.rules.filter((_, i) => i !== idx);
            setConfig({ ...config, rules: newRules });

            const res = await fetch('http://localhost:8000/api/source', {
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

    // Helper to parse bold (**text**)
    const processInlineMarkdown = (text) => {
        const parts = text.split(/(\*\*.*?\*\*)/g);
        return parts.map((part, index) => {
            if (part.startsWith('**') && part.endsWith('**')) {
                return <strong key={index}>{part.slice(2, -2)}</strong>;
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
                    // Normal text
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

        setMessages(prev => [...prev, { type: 'user', content: userMessage }]);
        setLoading(true);

        try {
            // Use relative path for production (handled by proxy in dev)
            // Use absolute URL to force connection to backend
            const response = await fetch('http://localhost:8000/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId,
                    temperature: isCreative ? 0.3 : 0.0
                })
            });

            const data = await response.json();

            if (response.ok) {
                setMessages(prev => [...prev, {
                    type: 'bot',
                    content: data.response,
                    sources: data.sources || [],
                    images: data.images || []
                }]);
            } else {
                setMessages(prev => [...prev, {
                    type: 'error',
                    content: `Error: ${data.error}`
                }]);
            }
        } catch (error) {
            setMessages(prev => [...prev, {
                type: 'error',
                content: `Connection error: ${error.message}`
            }]);
        } finally {
            setLoading(false);
        }
    };

    const clearChat = async () => {
        try {
            await fetch('http://localhost:8000/api/clear', {
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
            <header className="app-header">
                <div className="header-title">
                    <h1>Hybrid RAG Assistant</h1>
                </div>
                <div className="header-controls">
                    <button onClick={openSettings} className="icon-btn" title="Settings">⚙️</button>
                    <button onClick={clearChat} className="icon-btn" title="Clear Chat">🗑️</button>
                </div>
            </header>

            {showSettings && config && (
                <div className="modal-overlay" onClick={() => setShowSettings(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <h2>System Settings</h2>

                        <div className="setting-group">
                            <label className="checkbox-label">
                                <input
                                    type="checkbox"
                                    checked={config.strict_mode}
                                    onChange={(e) => setConfig({ ...config, strict_mode: e.target.checked })}
                                />
                                Strict Image Filtering Mode
                            </label>
                            <p className="setting-desc">
                                Only show images that explicitly match keywords in the question.
                            </p>
                        </div>

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

                        <h3>Trust Rules</h3>
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




                        <div className="modal-actions">
                            <button onClick={() => setShowSettings(false)} className="btn-secondary">Close</button>
                            <button onClick={saveSettings} className="btn-primary">Save Changes</button>
                        </div>
                    </div>
                </div>
            )
            }

            <div className="chat-window">
                <div className="chat-header">
                    <div className="header-title">
                        <h1>Hybrid RAG Assistant</h1>
                    </div>
                    <div className="header-controls">
                        <button onClick={openSettings} className="icon-btn" title="Settings">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                        </button>
                        <button onClick={clearChat} className="icon-btn" title="Clear Chat">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
                        </button>
                    </div>
                </div>

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
                                                    src={`http://localhost:8000/images/${img}`}
                                                    alt={`Reference ${i + 1}`}
                                                    onClick={() => openLightbox(`http://localhost:8000/images/${img}`)}
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
