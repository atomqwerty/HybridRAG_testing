import React, { useState, useRef, useEffect } from 'react';
import './App.css';

function App() {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [sessionId] = useState(() => Math.random().toString(36).substr(2, 9));
    const [lightboxImage, setLightboxImage] = useState(null);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    // Format message content to preserve tables and line breaks
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
                    formatted.push(<div key={idx}>{line}</div>);
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
                        {headers.map((header, i) => <th key={i}>{header}</th>)}
                    </tr>
                </thead>
                <tbody>
                    {dataRows.map((row, i) => (
                        <tr key={i}>
                            {row.map((cell, j) => <td key={j}>{cell}</td>)}
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
            const response = await fetch('http://localhost:5000/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage,
                    session_id: sessionId
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
            await fetch('http://localhost:5000/api/clear', {
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
                    <h1>🧠 Hybrid RAG Chatbot</h1>
                    <button onClick={clearChat} className="clear-btn">Clear Chat</button>
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
                                                    src={`http://localhost:5000/images/${img}`}
                                                    alt={`Reference ${i + 1}`}
                                                    onClick={() => openLightbox(`http://localhost:5000/images/${img}`)}
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
