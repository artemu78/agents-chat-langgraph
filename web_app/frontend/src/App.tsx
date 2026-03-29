import React, { useState, useEffect, useRef } from 'react'
import { Sun, Moon, MessageSquare, Send, Pause, Play, User, LogOut, Terminal, ShieldAlert, Paperclip } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// --- Helper Component ---
const FormattedMessage = ({ text, role }: { text: string, role: string }) => {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

  const renderMarkdown = (content: string) => (
    <ReactMarkdown 
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({node, ...props}) => <p style={{ margin: '0 0 12px 0', lineHeight: '1.6' }} {...props} />,
        code: ({node, ...props}) => (
          <code 
            style={{ 
              background: 'rgba(0, 0, 0, 0.2)', 
              padding: '2px 4px', 
              borderRadius: '4px', 
              fontFamily: 'monospace',
              fontSize: '0.9em'
            }} 
            {...props} 
          />
        ),
        pre: ({node, ...props}) => (
          <pre 
            style={{ 
              background: 'rgba(0, 0, 0, 0.3)', 
              padding: '16px', 
              borderRadius: '12px', 
              overflowX: 'auto',
              marginBottom: '16px',
              border: '1px solid var(--glass-border)'
            }} 
            {...props} 
          />
        ),
        ul: ({node, ...props}) => <ul style={{ marginLeft: '20px', marginBottom: '16px' }} {...props} />,
        ol: ({node, ...props}) => <ol style={{ marginLeft: '20px', marginBottom: '16px' }} {...props} />,
        li: ({node, ...props}) => <li style={{ marginBottom: '4px' }} {...props} />,
        blockquote: ({node, ...props}) => (
          <blockquote 
            style={{ 
              borderLeft: '4px solid var(--accent)', 
              paddingLeft: '16px', 
              margin: '0 0 16px 0',
              color: 'var(--text-secondary)'
            }} 
            {...props} 
          />
        ),
        a: ({node, ...props}) => <a style={{ color: 'var(--accent)', textDecoration: 'underline' }} {...props} />,
      }}
    >
      {content}
    </ReactMarkdown>
  )

  if (role !== 'OpenAI') return <div style={{ whiteSpace: 'pre-wrap' }}>{renderMarkdown(text)}</div>

  const auditMatch = text.match(/<audit>([\s\S]*?)<\/audit>/);
  if (!auditMatch) return <div style={{ whiteSpace: 'pre-wrap' }}>{renderMarkdown(text)}</div>

  const auditContent = auditMatch[1].trim();
  const remainingText = text.replace(/<audit>[\s\S]*?<\/audit>/, '').trim();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {remainingText && <div style={{ whiteSpace: 'pre-wrap' }}>{renderMarkdown(remainingText)}</div>}
      <div 
        className="audit-block"
        style={{
          background: 'rgba(0, 0, 0, 0.2)',
          borderLeft: '4px solid #f59e0b',
          padding: '12px 16px',
          borderRadius: '4px',
          fontFamily: 'monospace',
          fontSize: '0.85rem',
          color: '#fcd34d'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px', fontWeight: 'bold', color: '#f59e0b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          <ShieldAlert size={16} /> Audit & Optimization Log
        </div>
        <div style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{renderMarkdown(auditContent)}</div>
      </div>
    </div>
  )
}
// --- End Helper ---
import { useSSE } from './hooks/useSSE'

import { auth, googleProvider, devFirebaseDisabled } from './firebase'
import { signInWithPopup, signOut, onAuthStateChanged, User as FirebaseUser } from 'firebase/auth'

const isDevAuthBypass = devFirebaseDisabled
/** Stand-in user when running `vite` without Firebase sign-in */
const DEV_USER = { uid: 'dev', displayName: 'Dev user' } as FirebaseUser

function App() {
  const [theme, setTheme] = useState('dark')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [sessionName, setSessionName] = useState<string | null>(null)
  const [isPaused, setIsPaused] = useState(false)
  const [inputText, setInputText] = useState('')
  const [attachment, setAttachment] = useState<{ name: string, content: string, url: string } | null>(null)
  const [user, setUser] = useState<FirebaseUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [tokensUsed, setTokensUsed] = useState<number | null>(null)
  
  const { messages, isStreaming, isInterrupted, error, startStream, stopStream, setMessages } = useSSE(threadId)
  const scrollRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isStreaming])

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const ext = file.name.split('.').pop()?.toLowerCase()
    if (ext !== 'md' && ext !== 'mdc') {
      const confirmed = window.confirm(`Hint: Try to upload MD/MDC format only, as it saves context window drastically. Non-markdown files consume more tokens. Are you sure you want to attach "${file.name}"?`)
      if (!confirmed) {
        if (fileInputRef.current) fileInputRef.current.value = ''
        return
      }
    }

    const reader = new FileReader()
    reader.onload = (event) => {
      const content = event.target?.result as string
      const url = URL.createObjectURL(file)
      setAttachment({ name: file.name, content, url })
    }
    reader.readAsText(file)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  useEffect(() => {
    if (isDevAuthBypass) {
      setUser(DEV_USER)
      setLoading(false)
      setThreadId((tid) => tid ?? 'session_dev_' + Date.now().toString(36))
      return
    }
    if (!auth) {
      setLoading(false)
      return
    }
    const unsubscribe = onAuthStateChanged(auth, (u) => {
      setUser(u)
      setLoading(false)
      if (u && !threadId) {
        setThreadId('session_' + u.uid.slice(0, 8) + '_' + Date.now().toString(36))
      }
    })
    return () => unsubscribe()
  }, [])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark')
  }

  const handleLogin = async () => {
    if (!auth) return
    try {
      await signInWithPopup(auth, googleProvider)
    } catch (e) {
      console.error('Login failed', e)
    }
  }

  const handleLogout = async () => {
    if (isDevAuthBypass) {
      setThreadId('session_dev_' + Date.now().toString(36))
      setSessionName(null)
      setMessages([])
      return
    }
    if (!auth) return
    try {
      await signOut(auth)
      setThreadId(null)
      setSessionName(null)
      setMessages([])
    } catch (e) {
      console.error('Logout failed', e)
    }
  }

  
  const fetchTokens = async () => {
    if (!auth?.currentUser && !isDevAuthBypass) return
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    try {
      const headers = await getHeaders()
      const res = await fetch(`${apiUrl}/user/tokens`, { headers })
      const data = await res.json()
      if (data && typeof data.tokens_used === 'number') {
        setTokensUsed(data.tokens_used)
      }
    } catch (e) {
      console.error('Failed to fetch tokens', e)
    }
  }

  // Fetch tokens initially and when stream stops
  useEffect(() => {
    if (!loading && user) {
      fetchTokens()
    }
  }, [loading, user])

  useEffect(() => {
    if (!isStreaming) {
      fetchTokens()
    }
  }, [isStreaming])

  const getHeaders = async () => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (isDevAuthBypass) {
      return headers
    }
    const token = await auth?.currentUser?.getIdToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    return headers
  }

  const handleStartConversation = async () => {
    const textToSend = inputText + (attachment ? `\n\n[ATTACHED FILE: ${attachment.name}]\n${attachment.content}\n[END OF ATTACHMENT]\n` : '');
    if (!textToSend || !threadId) return
    
    setInputText('')
    if (attachment) {
      URL.revokeObjectURL(attachment.url);
      setAttachment(null);
    }

    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    try {
      const headers = await getHeaders()
      const response = await fetch(`${apiUrl}/chat/input`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ thread_id: threadId, seed_topic: textToSend })
      })
      const data = await response.json()
      if (data.session_name) {
        setSessionName(data.session_name)
      }
      startStream()
    } catch (e) {
      console.error('Failed to start conversation', e)
    }
  }

  const handleSendClarification = async () => {
    const textToSend = inputText + (attachment ? `\n\n[ATTACHED FILE: ${attachment.name}]\n${attachment.content}\n[END OF ATTACHMENT]\n` : '');
    if (!textToSend || !threadId) return
    setMessages(prev => [...prev, { role: 'Human', content: textToSend }])
    
    setInputText('')
    if (attachment) {
      URL.revokeObjectURL(attachment.url);
      setAttachment(null);
    }
    
    const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    try {
      const headers = await getHeaders()
      await fetch(`${apiUrl}/chat/input`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ thread_id: threadId, content: textToSend })
      })
      startStream()
    } catch (e) {
      console.error('Failed to send clarification', e)
    }
  }

  const handleTogglePause = async () => {
    const nextPauseState = !isPaused
    setIsPaused(nextPauseState)
    
    if (threadId) {
      const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const headers = await getHeaders()
      await fetch(`${apiUrl}/chat/input`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ thread_id: threadId, paused: nextPauseState })
      })
      
      if (!nextPauseState) {
        startStream()
      } else {
        stopStream()
      }
    }
  }

  if (loading) return null

  if (!user) {
    // ... (rest of the Login component)
    return (
      <div className="login-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div className="nebula-bg">
          <div className="nebula-blob" style={{ background: 'var(--accent)', top: '-10%', left: '-10%' }}></div>
          <div className="nebula-blob" style={{ background: '#ec4899', bottom: '-10%', right: '-10%' }}></div>
        </div>
        
        <div className="glass-panel" style={{ padding: '48px', width: '400px', textAlign: 'center' }}>
           <div style={{ width: '64px', height: '64px', background: 'var(--accent)', borderRadius: '20px', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px' }}>
              <Terminal color="white" size={32} />
           </div>
           <h1 style={{ marginBottom: '8px' }}>Nebula Glass</h1>
           <p style={{ color: 'var(--text-secondary)', marginBottom: '32px' }}>AI-to-AI Autonomous Conversations</p>
           
           <button 
             onClick={handleLogin}
             className="glass-card" 
             style={{ width: '100%', padding: '16px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '12px', fontSize: '1rem', fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px' }}
           >
             <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" width="20" alt="Google" />
             Sign in with Google
           </button>
        </div>
      </div>
    )
  }

  return (
    <div className="app-container" style={{ display: 'flex', height: '100vh', padding: '20px', gap: '20px' }}>
      <div className="nebula-bg">
        <div className="nebula-blob" style={{ background: 'var(--accent)', top: '-10%', left: '-10%' }}></div>
        <div className="nebula-blob" style={{ background: '#ec4899', bottom: '-10%', right: '-10%', animationDelay: '-5s' }}></div>
      </div>

      <aside className="glass-panel" style={{ width: '300px', display: 'flex', flexDirection: 'column', padding: '24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '32px' }}>
          <div style={{ width: '40px', height: '40px', background: 'var(--accent)', borderRadius: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <MessageSquare color="white" size={24} />
          </div>

          <h2 style={{ fontSize: '1.2rem' }}>Nebula Chat</h2>
        </div>
        
        {tokensUsed !== null && (
          <div style={{ marginBottom: '24px', padding: '8px 12px', background: 'var(--glass-bg)', border: '1px solid var(--glass-border)', borderRadius: '8px', fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Limit</span>
            <span style={{ fontWeight: 600, color: tokensUsed >= 500000 ? '#ef4444' : 'var(--text-primary)' }}>
              {Math.max(0, 500000 - tokensUsed) >= 1000 ? Math.round(Math.max(0, 500000 - tokensUsed)/1000) + 'k' : Math.max(0, 500000 - tokensUsed)} tokens left
            </span>
          </div>
        )}


        <nav style={{ flex: 1 }}>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '16px' }}>Current Session</p>
          <div className="glass-card" style={{ padding: '12px', background: 'var(--accent-glow)', border: '1px solid var(--accent)' }}>
            <p style={{ fontSize: '0.9rem', fontWeight: 500 }}>{sessionName || 'New Session'}</p>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>ID: {threadId}</p>
          </div>
        </nav>

        <div style={{ marginTop: 'auto', paddingTop: '24px', borderTop: '1px solid var(--glass-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <button onClick={toggleTheme} className="glass-card" style={{ padding: '8px', border: 'none', cursor: 'pointer', color: 'var(--text-primary)' }}>
            {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          <div style={{ display: 'flex', gap: '8px' }}>
            <div className="glass-card" style={{ padding: '8px', cursor: 'pointer' }} title={user?.displayName || 'User'}><User size={20} /></div>
            <div className="glass-card" style={{ padding: '8px', cursor: 'pointer' }} onClick={handleLogout} title="Logout"><LogOut size={20} /></div>
          </div>
        </div>
      </aside>

      <main className="glass-panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <header style={{ padding: '20px 32px', borderBottom: '1px solid var(--glass-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: '1.5rem' }}>AI Conversation</h1>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              {isStreaming ? 'Models are thinking...' : isInterrupted ? 'Waiting for your clarification' : 'Conversation ready'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
             <button 
              onClick={handleTogglePause}
              disabled={messages.length === 0}
              className="glass-card" 
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', border: 'none', cursor: 'pointer', color: 'var(--text-primary)', fontWeight: 600, opacity: messages.length === 0 ? 0.5 : 1 }}
            >
              {isPaused ? <Play size={18} fill="currentColor" /> : <Pause size={18} fill="currentColor" />}
              {isPaused ? 'Resume' : 'Pause'}
            </button>
          </div>
        </header>

        <section ref={scrollRef} style={{ flex: 1, padding: '32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
           {messages.length === 0 && (
             <div style={{ margin: 'auto', textAlign: 'center', maxWidth: '400px' }}>
                <Terminal size={48} color="var(--accent)" style={{ marginBottom: '16px', opacity: 0.5 }} />
                <h3>Start a New Thread</h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '8px' }}>Enter a topic below to seed the autonomous conversation between models.</p>
             </div>
           )}
           
           {messages.map((msg, i) => (
             <div key={i} style={{ alignSelf: msg.role === 'Human' || msg.role === 'OpenAI' ? 'flex-end' : 'flex-start', maxWidth: '80%' }}>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '4px', textAlign: msg.role === 'Human' || msg.role === 'OpenAI' ? 'right' : 'left' }}>
                  {msg.role}
                </p>
                <div 
                  className="glass-card" 
                  style={{ 
                    padding: '16px', 
                    borderRadius: msg.role === 'Human' || msg.role === 'OpenAI' ? '20px 20px 4px 20px' : '20px 20px 20px 4px',
                    background: msg.role === 'OpenAI' ? 'var(--accent)' : 'var(--glass-bg)',
                    color: msg.role === 'OpenAI' ? 'white' : 'var(--text-primary)',
                    border: msg.role === 'OpenAI' ? 'none' : '1px solid var(--glass-border)'
                  }}
                >
                  <FormattedMessage text={msg.content} role={msg.role} />
                </div>
             </div>
           ))}

           {isStreaming && (
             <div style={{ alignSelf: 'center', color: 'var(--text-secondary)', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <div className="typing-dot" style={{ width: '4px', height: '4px', background: 'currentColor', borderRadius: '50%' }}></div>
                <div className="typing-dot" style={{ width: '4px', height: '4px', background: 'currentColor', borderRadius: '50%', animationDelay: '0.2s' }}></div>
                <div className="typing-dot" style={{ width: '4px', height: '4px', background: 'currentColor', borderRadius: '50%', animationDelay: '0.4s' }}></div>
                Models are communicating...
             </div>
           )}

           {error && (
             <div className="glass-card" style={{ padding: '12px 24px', background: '#fee2e2', color: '#991b1b', border: '1px solid #ef4444', alignSelf: 'center' }}>
                {error}
             </div>
           )}
        </section>

        <footer style={{ padding: '24px 32px' }}>
          <div className="glass-card" style={{ display: 'flex', alignItems: 'center', padding: '8px 16px', gap: '12px', border: isInterrupted ? '2px solid var(--accent)' : '1px solid var(--glass-border)' }}>
            <button 
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming || (tokensUsed !== null && tokensUsed >= 500000)}
              style={{ 
                background: 'none', 
                border: 'none', 
                cursor: 'pointer', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center',
                opacity: (isStreaming || (tokensUsed !== null && tokensUsed >= 500000)) ? 0.5 : 1,
                color: 'var(--text-secondary)'
              }}
              title="Attach File (MD/MDC preferred)"
            >
              <Paperclip size={20} />
            </button>
            <input type="file" ref={fileInputRef} style={{ display: 'none' }} onChange={handleFileSelect} />
            
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
              <textarea 
                placeholder={(tokensUsed !== null && tokensUsed >= 500000) ? "Token limit reached" : messages.length === 0 ? "Enter a seed topic..." : isInterrupted ? "Type your clarification..." : "Steer the conversation..."} 
                value={inputText}
                rows={1}
                onChange={(e) => setInputText(e.target.value)}
                disabled={tokensUsed !== null && tokensUsed >= 500000}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if ((inputText || attachment) && !isStreaming && (tokensUsed === null || tokensUsed < 500000)) {
                      messages.length === 0 ? handleStartConversation() : handleSendClarification();
                    }
                  }
                }}
                style={{ 
                  flex: 1, 
                  background: 'none', 
                  border: 'none', 
                  outline: 'none', 
                  color: 'var(--text-primary)', 
                  fontSize: '1rem', 
                  padding: '8px 0',
                  resize: 'none',
                  fontFamily: 'inherit',
                  maxHeight: '150px'
                }}
              />
              
              {attachment && (
                <div style={{ marginTop: '4px', marginBottom: '4px', padding: '6px 12px', background: 'var(--glass-bg)', borderRadius: '8px', border: '1px solid var(--glass-border)', display: 'inline-flex', alignItems: 'center', gap: '8px', alignSelf: 'flex-start' }}>
                  <a href={attachment.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '0.85rem', color: 'var(--text-primary)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Paperclip size={14} />
                    {attachment.name}
                  </a>
                  <button 
                    onClick={() => {
                      URL.revokeObjectURL(attachment.url);
                      setAttachment(null);
                      if (fileInputRef.current) fileInputRef.current.value = '';
                    }}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', fontSize: '1.2rem', padding: '0 4px', lineHeight: 1 }}
                    title="Remove attachment"
                  >
                    &times;
                  </button>
                </div>
              )}
            </div>
            <button 
              onClick={() => messages.length === 0 ? handleStartConversation() : handleSendClarification()}
              disabled={isStreaming || (!inputText && !attachment) || (tokensUsed !== null && tokensUsed >= 500000)}
              style={{ 
                background: 'var(--accent)', 
                border: 'none', 
                borderRadius: '12px', 
                padding: '10px', 
                cursor: 'pointer', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center',
                opacity: (isStreaming || (!inputText && !attachment) || (tokensUsed !== null && tokensUsed >= 500000)) ? 0.5 : 1
              }}
            >
              <Send size={20} color="white" />
            </button>
          </div>
          <div style={{ marginTop: '8px', display: 'flex', justifyContent: 'center', gap: '20px' }}>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', opacity: 0.8 }}>
              <b>Tip:</b> Try to upload <b>.md/.mdc</b> format only, as it saves context window drastically.
            </p>
          </div>
          {isInterrupted && (
            <p style={{ fontSize: '0.75rem', color: 'var(--accent)', marginTop: '8px', textAlign: 'center', fontWeight: 600 }}>
              Action Required: An AI model needs your clarification to continue.
            </p>
          )}
        </footer>
      </main>

      <style>{`
        .typing-dot {
          animation: blink 1.4s infinite both;
        }
        @keyframes blink {
          0% { opacity: .2; }
          20% { opacity: 1; }
          100% { opacity: .2; }
        }
      `}</style>
    </div>
  )
}

export default App
