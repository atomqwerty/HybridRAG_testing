import React from 'react';

const ROLE_BADGE = { superadmin: '🔑 Super Admin', admin: '⚙️ Admin', user: '👤 User' };

export default function UsersView({
    userList, auditLog, usersTab, setUsersTab,
    userMsg, newUserForm, setNewUserForm, pwForm, setPwForm,
    currentUser,
    loadAudit, handleCreateUser, handleDeleteUser, handleChangeRole, handleChangePw,
}) {
    return (
        <div className="settings-view">
            <div className="settings-container" style={{ maxWidth: '900px' }}>
                <h2 style={{ marginBottom: '24px', fontSize: '1.875rem' }}>👥 User Management</h2>

                {/* Tabs */}
                <div style={{ display: 'flex', gap: '8px', marginBottom: '24px' }}>
                    {['users', 'audit'].map(t => (
                        <button key={t}
                            onClick={() => { setUsersTab(t); if (t === 'audit') loadAudit(); }}
                            style={{
                                padding: '8px 20px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontWeight: 600,
                                background: usersTab === t ? 'linear-gradient(135deg,#6366f1,#8b5cf6)' : 'rgba(255,255,255,0.06)',
                                color: usersTab === t ? '#fff' : '#9ca3af', transition: 'all 0.2s'
                            }}>
                            {t === 'users' ? '👤 Users' : '📋 Audit Log'}
                        </button>
                    ))}
                </div>

                {/* Status toast */}
                {userMsg.text && (
                    <div style={{
                        padding: '10px 16px', borderRadius: '8px', marginBottom: '16px', fontSize: '0.9rem', fontWeight: 500,
                        background: userMsg.ok ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)',
                        color: userMsg.ok ? '#34d399' : '#f87171',
                        border: `1px solid ${userMsg.ok ? 'rgba(52,211,153,0.3)' : 'rgba(248,113,113,0.3)'}`
                    }}>{userMsg.text}</div>
                )}

                {/* ─── USERS TAB ─── */}
                {usersTab === 'users' && (
                    <>
                        {/* User table */}
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
                                                {u.id === currentUser?.id && (
                                                    <span style={{ marginLeft: '6px', fontSize: '0.72rem', color: '#6b7280' }}>(you)</span>
                                                )}
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

                        {/* Create user form */}
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

                        {/* Change password form */}
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

                {/* ─── AUDIT TAB ─── */}
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
}
