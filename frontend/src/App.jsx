import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [sessionId] = useState(() => Math.random().toString(36).substr(2, 9));
    const [lightboxImage, setLightboxImage] = useState(null);
    const [isCreative, setIsCreative] = useState(true); // Default to Creative (0.3)
    const messagesEndRef = useRef(null);

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
        <div className="App">
            <div className="chat-container">
                <div className="chat-header">
                    <h1>🧠 EV Charger Expert AI</h1>
                    <div className="controls">
                        <label className="mode-toggle">
                            <input
                                type="checkbox"
                                checked={isCreative}
                                onChange={(e) => setIsCreative(e.target.checked)}
                            />
                            <span className="slider"></span>
                            <span className="label-text">{isCreative ? 'Creative (0.3)' : 'Strict (0.0)'}</span>
                        </label>
                        <button onClick={clearChat} className="clear-btn">Clear Chat</button>
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
                                    <strong>📚 Sources:</strong>
                                    <ul>
                                        {msg.sources.map((src, i) => (
                                            <li key={i}>{src.file} (Page {src.page})</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {msg.images && msg.images.length > 0 && (
                                <div className="images">
                                    <strong>🖼️ Images:</strong>
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
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Ask me anything about F1..."
                        disabled={loading}
                    />
                    <button type="submit" disabled={loading || !input.trim()}>
                        Send
                    </button>
                </form>
            </div>

            {lightboxImage && (
                <div className="lightbox-overlay" onClick={closeLightbox}>
                    <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
                        <button className="lightbox-close" onClick={closeLightbox}>×</button>
                        <img src={lightboxImage} alt="Full size" />
                    </div>
                </div>
            )}
        </div>
    );
}

export default App;
