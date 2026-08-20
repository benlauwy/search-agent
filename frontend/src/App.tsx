import { useCallback, useEffect, useState } from 'react'
import { api, type Session, type User } from './api'
import { useChat } from './useChat'
import { MessageList } from './components/MessageList'
import { FilesPanel } from './components/FilesPanel'
import { SettingsModal } from './components/SettingsModal'

function LoginScreen() {
  return (
    <div className="login-screen">
      <h1>search-agent</h1>
      <p>An agent that searches the web, reads your files, and writes reports.</p>
      <a className="login-button" href="/api/auth/login">
        Sign in
      </a>
    </div>
  )
}

function Composer({
  onSend,
  onCancel,
  running,
}: {
  onSend: (text: string) => void
  onCancel: () => void
  running: boolean
}) {
  const [text, setText] = useState('')
  const submit = () => {
    const t = text.trim()
    if (!t || running) return
    setText('')
    onSend(t)
  }
  return (
    <div className="composer">
      <textarea
        value={text}
        placeholder="Send a message…"
        rows={3}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      {running ? (
        <button className="danger" onClick={onCancel}>
          Stop
        </button>
      ) : (
        <button className="primary" onClick={submit} disabled={!text.trim()}>
          Send
        </button>
      )}
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const chat = useChat(activeId)

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true))
  }, [])

  const loadSessions = useCallback(async () => {
    const list = await api.listSessions()
    setSessions(list)
    return list
  }, [])

  useEffect(() => {
    if (user) void loadSessions()
  }, [user, loadSessions])

  const newSession = async () => {
    const s = await api.createSession()
    await loadSessions()
    setActiveId(s.id)
  }

  const deleteSession = async (id: string) => {
    try {
      await api.deleteSession(id)
    } catch (e) {
      alert(`Failed to delete session: ${e instanceof Error ? e.message : e}`)
      return
    }
    const list = await loadSessions()
    if (activeId === id) setActiveId(list[0]?.id ?? null)
  }

  const send = async (text: string) => {
    await chat.send(text)
    void loadSessions() // refresh titles
  }

  if (!authChecked) return null
  if (!user) return <LoginScreen />

  const active = sessions.find((s) => s.id === activeId) ?? null

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="brand">search-agent</span>
          <button onClick={() => void newSession()}>+ New</button>
        </div>
        <nav className="session-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${s.id === activeId ? 'active' : ''}`}
              onClick={() => setActiveId(s.id)}
            >
              <span className="session-title">{s.title}</span>
              <button
                className="session-delete"
                title="Delete"
                onClick={(e) => {
                  e.stopPropagation()
                  void deleteSession(s.id)
                }}
              >
                ×
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <span className="user-name" title={user.email}>
            {user.name || user.email}
          </span>
          <button onClick={() => setShowSettings(true)}>Settings</button>
          <button
            onClick={() => {
              void api.logout().then(() => setUser(null))
            }}
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="chat-pane">
        {active ? (
          <>
            <header className="chat-header">
              <span className="chat-title">{active.title}</span>
              <span className="chat-provider">
                {active.provider}
                {active.model ? ` · ${active.model}` : ''}
              </span>
            </header>
            <MessageList
              messages={chat.messages}
              draft={chat.draft}
              running={chat.running}
              error={chat.error}
            />
            <Composer onSend={(t) => void send(t)} onCancel={() => void chat.cancel()} running={chat.running} />
          </>
        ) : (
          <div className="empty-state center">
            <p>Create a new chat to get started.</p>
            <button className="primary" onClick={() => void newSession()}>
              + New chat
            </button>
          </div>
        )}
      </main>

      {active && <FilesPanel files={chat.files} onUpload={chat.upload} />}
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </div>
  )
}
