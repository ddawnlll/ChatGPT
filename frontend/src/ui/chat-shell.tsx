/**
 * ChatShell — fully reworked
 * ─────────────────────────────────────────────────────────
 * Features:
 *  • Enter to send (Shift+Enter = newline)
 *  • Inline rename in the sidebar chat row (pencil icon)
 *  • Markdown rendering via react-markdown + remark-gfm
 *  • Syntax-highlighted code blocks with copy button
 *  • File / artifact blocks with copy + download button
 *  • Richer dark palette — deep charcoal, blue + amber accents
 *  • Animated orb field, glass panels, staggered msg entrance
 *
 * Required dependencies (add to package.json if missing):
 *   react-markdown  remark-gfm
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useRouterState } from '@tanstack/react-router'
import clsx from 'clsx'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  createChat, deleteChat, getChat, listChats, renameChat, streamMessage,
  type ChatMessage, type SessionConfig,
} from '../lib/api'

/* ─── session persistence ─── */
const SESSION_STORAGE_KEY = 'gpt-fork-session-config'
type SessionFormState = SessionConfig

const defaultSessionConfig: SessionFormState = {
  session_id: 'web-session',
  cookies: '',
  authorization: '',
  thinking_mode: 'extended',
  model_name: 'auto',
}

function loadSessionConfig(): SessionFormState {
  const raw = window.localStorage.getItem(SESSION_STORAGE_KEY)
  if (!raw) return defaultSessionConfig
  try { return { ...defaultSessionConfig, ...JSON.parse(raw) } }
  catch { return defaultSessionConfig }
}

/* ─── auto-scroll ─── */
function useAutoScroll(dep: unknown) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' })
  }, [dep])
  return ref
}

/* ─── file-like language detection ─── */
const FILE_LANG_RE = /^([\w.-]+\.(tsx?|jsx?|py|rs|go|java|c|cpp|cs|rb|php|swift|kt|sh|bash|zsh|yaml|yml|toml|json|html?|css|scss|sql|md|txt))$/i

/* ─── helpers ─── */
async function copyText(text: string) {
  await navigator.clipboard.writeText(text)
}
function downloadText(filename: string, content: string) {
  const blob = new Blob([content], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}

/* ════════════════════════════════
   CODE / FILE BLOCK
═══════════════════════════════════ */
function CodeBlock({ language, filename, children }: { language?: string; filename?: string; children: string }) {
  const [copied, setCopied] = useState(false)
  const isFile = filename && FILE_LANG_RE.test(filename)

  const handleCopy = async () => {
    await copyText(children)
    setCopied(true)
    setTimeout(() => setCopied(false), 1800)
  }

  return (
    <div className="code-block">
      <div className="code-header">
        <div className="code-dots">
          <span className="dot dot-r" /><span className="dot dot-y" /><span className="dot dot-g" />
          {(filename || language) && <span className="code-lang">{filename ?? language}</span>}
        </div>
        <div className="code-actions">
          {isFile && (
            <button className="code-btn" onClick={() => downloadText(filename!, children)} title="Download">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              Download
            </button>
          )}
          <button className="code-btn" onClick={handleCopy} title="Copy">
            {copied
              ? <><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><polyline points="20 6 9 17 4 12"/></svg>Copied</>
              : <><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Copy</>
            }
          </button>
        </div>
      </div>
      <pre className="code-pre"><code className="code-inner">{children}</code></pre>
    </div>
  )
}

/* ════════════════════════════════
   MARKDOWN RENDERER
═══════════════════════════════════ */
function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="md-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\S+)/.exec(className || '')
            const raw = String(children).replace(/\n$/, '')
            if (!inline && match) {
              const lang = match[1]
              const isFilename = FILE_LANG_RE.test(lang)
              return (
                <CodeBlock
                  language={isFilename ? undefined : lang}
                  filename={isFilename ? lang : undefined}
                >{raw}</CodeBlock>
              )
            }
            if (!inline && raw.includes('\n')) return <CodeBlock>{raw}</CodeBlock>
            return <code className="inline-code" {...props}>{children}</code>
          },
          pre({ children }: any) { return <>{children}</> },
          p({ children }: any) { return <p className="md-p">{children}</p> },
          h1({ children }: any) { return <h1 className="md-h1">{children}</h1> },
          h2({ children }: any) { return <h2 className="md-h2">{children}</h2> },
          h3({ children }: any) { return <h3 className="md-h3">{children}</h3> },
          ul({ children }: any) { return <ul className="md-ul">{children}</ul> },
          ol({ children }: any) { return <ol className="md-ol">{children}</ol> },
          li({ children }: any) { return <li className="md-li">{children}</li> },
          blockquote({ children }: any) { return <blockquote className="md-bq">{children}</blockquote> },
          a({ children, href }: any) { return <a className="md-a" href={href} target="_blank" rel="noopener noreferrer">{children}</a> },
          table({ children }: any) { return <div className="md-table-wrap"><table className="md-table">{children}</table></div> },
          th({ children }: any) { return <th className="md-th">{children}</th> },
          td({ children }: any) { return <td className="md-td">{children}</td> },
          hr() { return <hr className="md-hr" /> },
          strong({ children }: any) { return <strong className="md-strong">{children}</strong> },
          em({ children }: any) { return <em className="md-em">{children}</em> },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

/* ════════════════════════════════
   SIDEBAR CHAT ROW (inline rename)
═══════════════════════════════════ */
function ChatRow({
  chat, active, onNavigate, onRename, onDelete,
}: {
  chat: { id: string; title: string; message_count: number }
  active: boolean
  onNavigate: () => void
  onRename: (t: string) => void
  onDelete: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(chat.title)
  const inputRef = useRef<HTMLInputElement>(null)

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation()
    setDraft(chat.title)
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 30)
  }
  const commitEdit = () => {
    const t = draft.trim()
    if (t && t !== chat.title) onRename(t)
    setEditing(false)
  }

  return (
    <div
      className={clsx('chat-row', active && 'chat-row-active')}
      onClick={!editing ? onNavigate : undefined}
    >
      {active && <div className="active-pip" />}

      {editing ? (
        <input
          ref={inputRef}
          className="rename-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') setEditing(false) }}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <div className="chat-row-body">
          <span className="chat-row-title">{chat.title}</span>
          <span className="chat-row-meta">{chat.message_count} messages</span>
        </div>
      )}

      {!editing && (
        <div className="chat-row-actions">
          <button className="icon-btn" onClick={startEdit} title="Rename">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button className="icon-btn icon-btn-danger" onClick={(e) => { e.stopPropagation(); onDelete() }} title="Delete">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/>
              <path d="M10 11v6M14 11v6"/><path d="M9 6V4h6v2"/>
            </svg>
          </button>
        </div>
      )}
    </div>
  )
}

/* ════════════════════════════════
   MESSAGE BUBBLE
═══════════════════════════════════ */
function MessageBubble({ item, index }: { item: ChatMessage; index: number }) {
  const isAI = item.role === 'assistant'
  const isStreaming = item.id === 'streaming-assistant'
  return (
    <div className="msg-enter" style={{ animationDelay: `${Math.min(index * 32, 220)}ms` }}>
      <div className={clsx('msg-row', isAI ? 'msg-row-ai' : 'msg-row-user')}>
        <div className={clsx('avatar', isAI ? 'avatar-ai' : 'avatar-user')}>{isAI ? 'AI' : 'ME'}</div>
        <div className={clsx('bubble', isAI ? 'bubble-ai' : 'bubble-user')}>
          {isAI
            ? <><MarkdownContent content={item.content} />{isStreaming && <span className="blink-cursor" />}</>
            : <span className="user-text">{item.content}</span>
          }
        </div>
      </div>
    </div>
  )
}

/* ════════════════════════════════
   FIELD
═══════════════════════════════════ */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="field">
      <label className="field-label">{label}</label>
      {children}
    </div>
  )
}

/* ════════════════════════════════════════════════
   MAIN COMPONENT
═══════════════════════════════════════════════════ */
export function ChatShell() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const params = useParams({ strict: false }) as { chatId?: string }
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  const [sessionConfig, setSessionConfig] = useState<SessionFormState>(() => loadSessionConfig())
  const [message, setMessage] = useState('')
  const [streamingAssistant, setStreamingAssistant] = useState('')
  const [pendingUserMessage, setPendingUserMessage] = useState<ChatMessage | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const chatsQuery = useQuery({ queryKey: ['chats'], queryFn: listChats, retry: false })
  const activeChatId = params.chatId
  const chatQuery = useQuery({
    queryKey: ['chat', activeChatId],
    queryFn: () => getChat(activeChatId!),
    enabled: Boolean(activeChatId),
    retry: false,
  })

  const createChatMutation = useMutation({
    mutationFn: () => createChat({ ...sessionConfig }),
    onSuccess: (chat) => {
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })
    },
  })

  const renameChatMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameChat(id, title),
    onSuccess: (chat) => {
      queryClient.setQueryData(['chat', chat.id], chat)
      queryClient.invalidateQueries({ queryKey: ['chats'] })
    },
  })

  const deleteChatMutation = useMutation({
    mutationFn: (id: string) => deleteChat(id),
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: ['chat', id] })
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      if (id === activeChatId) navigate({ to: '/' })
    },
  })

  const sendMessageMutation = useMutation({
    mutationFn: async () => {
      let chatId = activeChatId
      if (!chatId) {
        const created = await createChat({ ...sessionConfig })
        chatId = created.id
        queryClient.setQueryData(['chat', chatId], created)
        queryClient.invalidateQueries({ queryKey: ['chats'] })
        navigate({ to: '/chat/$chatId', params: { chatId } })
      }
      const optimisticUser: ChatMessage = {
        id: `pending-${Date.now()}`,
        role: 'user',
        content: message,
        created_at: new Date().toISOString(),
      }
      setPendingUserMessage(optimisticUser)
      setStreamingAssistant('')
      setStreamError(null)
      setIsStreaming(true)
      const finalChat = await streamMessage(chatId!, { message }, (event) => {
        if (event.type === 'chunk') setStreamingAssistant((p) => p + (event.content ?? ''))
      })
      return finalChat
    },
    onSuccess: (chat) => {
      queryClient.setQueryData(['chat', chat.id], chat)
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      setMessage('')
      setPendingUserMessage(null)
      setStreamingAssistant('')
      setStreamError(null)
      setIsStreaming(false)
    },
    onError: (error) => {
      setStreamError(String((error as Error).message))
      setPendingUserMessage(null)
      setStreamingAssistant('')
      setIsStreaming(false)
    },
  })

  const messages = useMemo(() => {
    const base = [...(chatQuery.data?.messages ?? [])]
    if (pendingUserMessage) base.push(pendingUserMessage)
    if (streamingAssistant) base.push({
      id: 'streaming-assistant',
      role: 'assistant',
      content: streamingAssistant,
      created_at: new Date().toISOString(),
    })
    return base
  }, [chatQuery.data, pendingUserMessage, streamingAssistant])

  const scrollRef = useAutoScroll(messages)

  /* auto-resize textarea */
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 220) + 'px'
  }, [message])

  const isBusy = sendMessageMutation.isPending || isStreaming

  const doSend = () => {
    if (!message.trim() || isBusy) return
    sendMessageMutation.mutate()
  }

  /* Enter = send, Shift+Enter = newline */
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend() }
  }

  useEffect(() => {
    if (!activeChatId || !chatQuery.error) return
    const m = String(chatQuery.error.message)
    if (m.includes('404') || m.includes('Chat not found')) navigate({ to: '/' })
  }, [activeChatId, chatQuery.error, navigate])

  useEffect(() => {
    if (pathname !== '/' || activeChatId || !chatsQuery.data?.length) return
    navigate({ to: '/chat/$chatId', params: { chatId: chatsQuery.data[0].id } })
  }, [activeChatId, chatsQuery.data, navigate, pathname])

  const saveSession = () => window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessionConfig))

  return (
    <>
      <style>{CSS}</style>
      <div className="shell">
        <div className="orb-field" aria-hidden>
          <div className="orb orb-1" /><div className="orb orb-2" /><div className="orb orb-3" />
        </div>
        <div className="noise" aria-hidden />

        {/* ══ SIDEBAR ══ */}
        <aside className={clsx('sidebar', !sidebarOpen && 'sidebar-closed')}>
          <div className="sidebar-brand">
            <div className="brand-icon">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
              </svg>
            </div>
            <span className="brand-name">GPT Fork</span>
          </div>

          <div className="px-new-chat">
            <button className="new-chat-btn" onClick={() => createChatMutation.mutate()}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <path d="M12 5v14M5 12h14"/>
              </svg>
              New conversation
            </button>
          </div>

          <div className="chat-list">
            {!chatsQuery.data?.length && <p className="empty-list">No conversations yet</p>}
            {chatsQuery.data?.map((chat, i) => (
              <div key={chat.id} style={{ animationDelay: `${i * 28}ms` }}>
                <ChatRow
                  chat={chat}
                  active={activeChatId === chat.id}
                  onNavigate={() => navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })}
                  onRename={(title) => renameChatMutation.mutate({ id: chat.id, title })}
                  onDelete={() => deleteChatMutation.mutate(chat.id)}
                />
              </div>
            ))}
          </div>

          <div className="settings-section">
            <button className="settings-toggle" onClick={() => setSettingsOpen((s) => !s)}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/>
              </svg>
              Session settings
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
                style={{ marginLeft: 'auto', transform: settingsOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
                <polyline points="6 9 12 15 18 9"/>
              </svg>
            </button>

            {settingsOpen && (
              <div className="settings-body settings-anim">
                <Field label="Session ID">
                  <input className="s-input" value={sessionConfig.session_id ?? ''} onChange={(e) => setSessionConfig((s) => ({ ...s, session_id: e.target.value }))} />
                </Field>
                <Field label="Model">
                  <input className="s-input" value={sessionConfig.model_name} onChange={(e) => setSessionConfig((s) => ({ ...s, model_name: e.target.value }))} />
                </Field>
                <Field label="Thinking mode">
                  <select className="s-input" value={sessionConfig.thinking_mode} onChange={(e) => setSessionConfig((s) => ({ ...s, thinking_mode: e.target.value as SessionFormState['thinking_mode'] }))}>
                    <option value="instant">instant</option>
                    <option value="extended">extended</option>
                    <option value="pro">pro</option>
                  </select>
                </Field>
                <Field label="Authorization">
                  <textarea className="s-input s-textarea" value={sessionConfig.authorization ?? ''} onChange={(e) => setSessionConfig((s) => ({ ...s, authorization: e.target.value }))} />
                </Field>
                <Field label="Cookies">
                  <textarea className="s-input s-textarea" placeholder="a=val; b=val" value={sessionConfig.cookies ?? ''} onChange={(e) => setSessionConfig((s) => ({ ...s, cookies: e.target.value }))} />
                </Field>
                <button className="save-btn" onClick={saveSession}>Save settings</button>
              </div>
            )}
          </div>
        </aside>

        {/* ══ MAIN ══ */}
        <main className="main-col">
          <header className="topbar fade-in">
            <button className="icon-btn p1" onClick={() => setSidebarOpen((s) => !s)} title="Toggle sidebar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
              </svg>
            </button>
            <div className="topbar-info">
              <span className="topbar-title">{chatQuery.data?.title ?? (pathname === '/' ? 'New conversation' : '…')}</span>
              <span className="topbar-meta">
                {sessionConfig.model_name}<span className="meta-dot" />{sessionConfig.thinking_mode}
                {isStreaming && <><span className="meta-dot" /><span className="stream-indicator"><span className="pulse-dot" />streaming</span></>}
              </span>
            </div>
          </header>

          <div ref={scrollRef} className="messages-area">
            {messages.length === 0 ? (
              <div className="empty-chat fade-in">
                <div className="empty-icon">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
                  </svg>
                </div>
                <h1 className="empty-title">GPT Fork Web</h1>
                <p className="empty-sub">Send a message to start a conversation.</p>
                <p className="empty-hint">Enter to send · Shift+Enter for new line</p>
              </div>
            ) : (
              <div className="messages-inner">
                {messages.map((item, i) => <MessageBubble key={item.id} item={item} index={i} />)}
              </div>
            )}
          </div>

          {(streamError || sendMessageMutation.error || createChatMutation.error) && (
            <div className="error-zone">
              {streamError && <div className="error-banner">{streamError}</div>}
              {sendMessageMutation.error && <div className="error-banner">{String(sendMessageMutation.error.message)}</div>}
              {createChatMutation.error && <div className="error-banner">{String(createChatMutation.error.message)}</div>}
            </div>
          )}

          <div className="input-dock">
            <div className="input-inner">
              <textarea
                ref={textareaRef}
                rows={1}
                className="msg-input"
                placeholder="Message… (Enter to send, Shift+Enter for newline)"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyDown}
              />
              <button className={clsx('send-btn', isBusy && 'send-busy')} disabled={!message.trim() || isBusy} onClick={doSend}>
                {isBusy
                  ? <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                  : <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                }
              </button>
            </div>
          </div>
        </main>
      </div>
    </>
  )
}

/* ════════════════════════════════════════════════════════
   ALL CSS
════════════════════════════════════════════════════════ */
const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:            #0c0d12;
  --panel:         #12141d;
  --panel-hi:      #181b26;
  --border:        rgba(255,255,255,0.07);
  --border-hi:     rgba(255,255,255,0.12);
  --border-sub:    rgba(255,255,255,0.03);

  --txt:           #b4bcd4;
  --txt-dim:       #7a82a0;
  --heading:       #e8ecf8;
  --muted:         #4e5470;

  --accent:        #e8a030;        /* amber – warm, readable */
  --accent-dim:    rgba(232,160,48,0.12);
  --accent-hi:     #f2bc5a;

  --blue:          #3b6ef5;
  --blue-dim:      rgba(59,110,245,0.15);
  --blue-hi:       #6090ff;

  --code-bg:       #090b10;
  --code-header:   #0f1118;
  --code-txt:      #c4cfdf;
  --inline-bg:     rgba(255,255,255,0.07);
  --inline-txt:    #d0a060;

  --bubble-ai:     rgba(20,22,32,0.9);
  --bubble-user-a: #1e3a6e;
  --bubble-user-b: #162d58;

  font-family: 'Geist', ui-sans-serif, system-ui, sans-serif;
}

*, *::before, *::after { box-sizing:border-box; margin:0; padding:0; }
button { cursor:pointer; border:none; background:none; font:inherit; }
input, textarea, select { font:inherit; }
input:focus, textarea:focus, select:focus { outline:none; }

/* ── Shell ── */
.shell {
  position:relative; display:flex; height:100svh; overflow:hidden;
  background:var(--bg); color:var(--txt);
  font-family:'Geist', ui-sans-serif, system-ui, sans-serif;
}

/* ── Background orbs ── */
.orb-field { position:absolute; inset:0; overflow:hidden; pointer-events:none; z-index:0; }
.orb { position:absolute; border-radius:50%; filter:blur(110px); }
.orb-1 { width:500px; height:500px; opacity:.09; background:radial-gradient(circle,#3b6ef5,transparent 70%); top:-160px; left:-60px; animation:d1 24s ease-in-out infinite alternate; }
.orb-2 { width:420px; height:420px; opacity:.07; background:radial-gradient(circle,#e8a030,transparent 70%); bottom:-100px; right:-50px; animation:d2 30s ease-in-out infinite alternate; }
.orb-3 { width:280px; height:280px; opacity:.06; background:radial-gradient(circle,#2dd4bf,transparent 70%); top:42%; left:38%; animation:d3 20s ease-in-out infinite alternate; }
@keyframes d1{from{transform:translate(0,0)}to{transform:translate(50px,30px)}}
@keyframes d2{from{transform:translate(0,0)}to{transform:translate(-35px,-22px)}}
@keyframes d3{from{transform:translate(0,0)}to{transform:translate(-28px,40px)}}

.noise {
  position:absolute; inset:0; pointer-events:none; z-index:0; opacity:.022;
  background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  background-size:128px;
}

/* ── Sidebar ── */
.sidebar {
  position:relative; z-index:10; display:flex; flex-direction:column;
  width:264px; min-width:264px;
  border-right:1px solid var(--border);
  background:rgba(18,20,29,.9);
  backdrop-filter:blur(24px);
  overflow:hidden;
  transition:width .28s cubic-bezier(.4,0,.2,1), min-width .28s cubic-bezier(.4,0,.2,1), border-color .28s;
}
.sidebar-closed { width:0!important; min-width:0!important; border-right-color:transparent!important; }

.sidebar-brand { display:flex; align-items:center; gap:10px; padding:18px 14px 12px; }
.brand-icon {
  display:flex; align-items:center; justify-content:center;
  width:28px; height:28px; border-radius:8px; flex-shrink:0;
  background:linear-gradient(135deg,#2a52c9,#1a3280);
  box-shadow:0 3px 10px rgba(42,82,201,.4);
}
.brand-name { font-size:13px; font-weight:700; letter-spacing:-.3px; color:var(--heading); white-space:nowrap; }

.px-new-chat { padding:0 10px 10px; }
.new-chat-btn {
  display:flex; align-items:center; gap:8px; width:100%;
  padding:9px 12px; border-radius:10px;
  border:1px solid rgba(232,160,48,.22);
  background:rgba(232,160,48,.06); color:var(--accent-hi);
  font-size:13px; font-weight:500;
  transition:background .15s, border-color .15s, transform .1s;
}
.new-chat-btn:hover { background:rgba(232,160,48,.12); border-color:rgba(232,160,48,.38); }
.new-chat-btn:active { transform:scale(.98); }

.chat-list { flex:1; overflow-y:auto; padding:4px 8px; display:flex; flex-direction:column; gap:2px; }
.empty-list { padding:24px 10px; text-align:center; font-size:12px; color:var(--muted); }

/* ── Chat row ── */
.chat-row {
  position:relative; display:flex; align-items:center; gap:6px;
  border-radius:10px; padding:9px 10px;
  border:1px solid transparent;
  cursor:pointer; user-select:none;
  transition:background .12s, border-color .12s;
  animation:rowIn .28s ease both;
}
.chat-row:hover { background:rgba(255,255,255,.04); }
.chat-row:hover .chat-row-actions { opacity:1; }
.chat-row-active { background:rgba(255,255,255,.065); border-color:var(--border); }
.active-pip {
  position:absolute; left:-1px; top:50%; transform:translateY(-50%);
  width:2px; height:18px; border-radius:0 2px 2px 0;
  background:var(--accent);
}
@keyframes rowIn{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:translateX(0)}}

.chat-row-body { flex:1; min-width:0; }
.chat-row-title { display:block; font-size:13px; font-weight:500; color:var(--txt); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.chat-row-active .chat-row-title { color:var(--heading); }
.chat-row-meta { display:block; font-size:11px; color:var(--muted); margin-top:2px; }

.chat-row-actions { display:flex; align-items:center; gap:2px; opacity:0; transition:opacity .12s; flex-shrink:0; }

.rename-input {
  flex:1; border-radius:6px; border:1px solid var(--accent);
  background:rgba(232,160,48,.08); color:var(--heading);
  padding:3px 8px; font-size:13px;
  box-shadow:0 0 0 2px rgba(232,160,48,.12);
}

.icon-btn {
  display:flex; align-items:center; justify-content:center;
  width:24px; height:24px; border-radius:6px;
  color:var(--muted); border:none; background:none;
  transition:color .12s, background .12s;
}
.icon-btn:hover { color:var(--txt); background:rgba(255,255,255,.08); }
.icon-btn-danger:hover { color:#f87171; background:rgba(248,113,113,.1); }
.icon-btn.p1 { width:32px; height:32px; border-radius:8px; }

/* ── Settings ── */
.settings-section { border-top:1px solid var(--border); padding:8px; }
.settings-toggle {
  display:flex; align-items:center; gap:7px; width:100%;
  padding:8px 10px; border-radius:8px;
  font-size:10px; font-weight:700; letter-spacing:.08em; text-transform:uppercase;
  color:var(--muted);
  transition:color .12s, background .12s;
}
.settings-toggle:hover { color:var(--txt-dim); background:rgba(255,255,255,.04); }
.settings-body { padding:8px 2px 4px; display:flex; flex-direction:column; gap:10px; }
@keyframes settDown{from{opacity:0;transform:translateY(-5px)}to{opacity:1;transform:translateY(0)}}
.settings-anim { animation:settDown .2s ease both; }

.field { display:flex; flex-direction:column; gap:5px; }
.field-label { font-size:10px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }

.s-input {
  width:100%; border-radius:8px; border:1px solid var(--border);
  background:rgba(255,255,255,.04); color:var(--heading);
  padding:7px 10px; font-size:13px;
  transition:border-color .15s, box-shadow .15s;
}
.s-input:focus { border-color:rgba(232,160,48,.5); box-shadow:0 0 0 2px rgba(232,160,48,.1); }
.s-textarea { min-height:64px; resize:none; }

.save-btn {
  width:100%; padding:8px; border-radius:8px;
  border:1px solid var(--border); background:rgba(255,255,255,.04);
  color:var(--txt-dim); font-size:12px; font-weight:500;
  transition:background .12s, color .12s;
}
.save-btn:hover { background:rgba(255,255,255,.08); color:var(--heading); }

/* ── Main ── */
.main-col { position:relative; z-index:10; display:flex; flex-direction:column; flex:1; min-width:0; }

/* ── Topbar ── */
.topbar {
  display:flex; align-items:center; gap:12px;
  padding:10px 18px; border-bottom:1px solid var(--border);
  background:rgba(12,13,18,.8); backdrop-filter:blur(20px);
}
.topbar-info { flex:1; min-width:0; }
.topbar-title { display:block; font-size:14px; font-weight:600; color:var(--heading); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.topbar-meta { display:flex; align-items:center; gap:6px; font-size:11px; color:var(--muted); margin-top:1px; }
.meta-dot { width:3px; height:3px; border-radius:50%; background:var(--muted); opacity:.5; flex-shrink:0; }
.stream-indicator { display:flex; align-items:center; gap:4px; color:var(--accent); }

/* ── Messages ── */
.messages-area { flex:1; overflow-y:auto; padding:28px 20px; }
.messages-inner { max-width:700px; margin:0 auto; display:flex; flex-direction:column; gap:20px; }

@keyframes msgIn{from{opacity:0;transform:translateY(9px)}to{opacity:1;transform:translateY(0)}}
.msg-enter { animation:msgIn .3s cubic-bezier(.22,1,.36,1) both; }

.msg-row { display:flex; gap:12px; align-items:flex-start; }
.msg-row-user { flex-direction:row-reverse; }

.avatar {
  flex-shrink:0; width:28px; height:28px; border-radius:8px; margin-top:2px;
  display:flex; align-items:center; justify-content:center;
  font-size:9px; font-weight:900; letter-spacing:.05em;
}
.avatar-ai { background:rgba(59,110,245,.15); border:1px solid rgba(59,110,245,.22); color:var(--blue-hi); }
.avatar-user { background:rgba(232,160,48,.1); border:1px solid rgba(232,160,48,.18); color:var(--accent-hi); }

.bubble { border-radius:16px; padding:12px 16px; font-size:14px; max-width:82%; min-width:40px; }
.bubble-ai { background:var(--bubble-ai); border:1px solid var(--border); backdrop-filter:blur(8px); }
.bubble-user {
  background:linear-gradient(135deg,var(--bubble-user-a),var(--bubble-user-b));
  border:1px solid rgba(59,110,245,.22);
}
.user-text { line-height:1.7; color:#dde6f8; white-space:pre-wrap; word-break:break-word; }

/* ── Markdown ── */
.md-content { font-size:14px; line-height:1.75; color:var(--txt); }
.md-content > *:first-child { margin-top:0!important; }
.md-content > *:last-child { margin-bottom:0!important; }
.md-p { margin:8px 0; }
.md-h1 { font-size:1.2em; font-weight:700; color:var(--heading); margin:18px 0 8px; }
.md-h2 { font-size:1.05em; font-weight:600; color:var(--heading); margin:14px 0 6px; }
.md-h3 { font-size:.95em; font-weight:600; color:var(--heading); margin:12px 0 5px; }
.md-ul,.md-ol { margin:8px 0 8px 20px; }
.md-li { margin:3px 0; line-height:1.7; }
.md-bq { border-left:2px solid var(--accent); padding-left:14px; margin:10px 0; color:var(--txt-dim); font-style:italic; }
.md-a { color:var(--blue-hi); text-decoration:underline; text-underline-offset:2px; transition:opacity .12s; }
.md-a:hover { opacity:.75; }
.md-hr { border:none; border-top:1px solid var(--border); margin:14px 0; }
.md-strong { font-weight:600; color:var(--heading); }
.md-em { color:var(--txt-dim); }
.md-table-wrap { margin:10px 0; overflow-x:auto; border-radius:10px; border:1px solid var(--border); }
.md-table { width:100%; border-collapse:collapse; font-size:13px; }
.md-th { padding:8px 14px; text-align:left; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); background:var(--code-header); border-bottom:1px solid var(--border); }
.md-td { padding:8px 14px; color:var(--txt); border-bottom:1px solid var(--border-sub); }
.inline-code { border-radius:5px; padding:1px 6px; font-family:'JetBrains Mono',monospace; font-size:.85em; background:var(--inline-bg); color:var(--inline-txt); }

/* ── Code block ── */
.code-block { margin:10px 0; border-radius:12px; overflow:hidden; border:1px solid var(--border-hi); }
.code-header { display:flex; align-items:center; justify-content:space-between; padding:8px 14px; background:var(--code-header); border-bottom:1px solid var(--border); }
.code-dots { display:flex; align-items:center; gap:6px; }
.dot { width:10px; height:10px; border-radius:50%; }
.dot-r { background:#ff5f57; opacity:.7; }
.dot-y { background:#febc2e; opacity:.7; }
.dot-g { background:#28c840; opacity:.7; }
.code-lang { margin-left:8px; font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--muted); }
.code-actions { display:flex; align-items:center; gap:4px; }
.code-btn {
  display:flex; align-items:center; gap:4px;
  padding:3px 8px; border-radius:6px; border:1px solid transparent;
  font-size:11px; font-weight:500; color:var(--muted);
  transition:color .12s, background .12s, border-color .12s;
}
.code-btn:hover { color:var(--txt); background:rgba(255,255,255,.06); border-color:var(--border); }
.code-pre { overflow-x:auto; padding:14px 16px; background:var(--code-bg); margin:0; }
.code-inner { font-family:'JetBrains Mono','Fira Code',monospace; font-size:13px; line-height:1.65; color:var(--code-txt); }

/* ── Empty state ── */
.empty-chat { max-width:400px; margin:80px auto 0; text-align:center; }
.empty-icon {
  width:54px; height:54px; margin:0 auto 18px; border-radius:16px;
  display:flex; align-items:center; justify-content:center;
  background:var(--blue-dim); border:1px solid rgba(59,110,245,.18); color:var(--blue-hi);
}
.empty-title { font-size:21px; font-weight:700; letter-spacing:-.4px; color:var(--heading); }
.empty-sub { margin-top:10px; font-size:13px; line-height:1.6; color:var(--muted); }
.empty-hint { margin-top:7px; font-size:11px; color:var(--muted); opacity:.5; }

/* ── Error zone ── */
.error-zone { max-width:700px; width:100%; margin:0 auto; padding:0 20px 6px; }
.error-banner { padding:9px 14px; border-radius:10px; font-size:12px; border:1px solid rgba(248,113,113,.18); background:rgba(248,113,113,.07); color:#f87171; margin-bottom:5px; }

/* ── Input dock ── */
.input-dock {
  padding:12px 20px 16px; border-top:1px solid var(--border);
  background:rgba(12,13,18,.85); backdrop-filter:blur(20px);
}
.input-inner { max-width:700px; margin:0 auto; display:flex; align-items:flex-end; gap:10px; }
.msg-input {
  flex:1; resize:none; overflow:hidden; border-radius:14px;
  border:1px solid var(--border); background:var(--panel-hi);
  padding:11px 15px; font-size:14px; line-height:1.6;
  color:var(--heading); font-family:'Geist',ui-sans-serif,system-ui,sans-serif;
  max-height:220px; transition:border-color .15s, box-shadow .15s;
}
.msg-input::placeholder { color:var(--muted); }
.msg-input:focus { border-color:rgba(232,160,48,.38); box-shadow:0 0 0 2px rgba(232,160,48,.08); }

.send-btn {
  flex-shrink:0; width:42px; height:42px; border-radius:12px;
  display:flex; align-items:center; justify-content:center;
  background:linear-gradient(135deg,var(--blue),#1c3a9e);
  color:#fff; box-shadow:0 4px 14px rgba(59,110,245,.28);
  transition:box-shadow .2s, transform .1s, opacity .15s;
  border:none; cursor:pointer;
}
.send-btn:not(:disabled):hover { box-shadow:0 4px 20px rgba(59,110,245,.46); transform:translateY(-1px); }
.send-btn:not(:disabled):active { transform:scale(.96); }
.send-btn:disabled { opacity:.3; cursor:not-allowed; box-shadow:none; }
.send-busy { background:rgba(59,110,245,.3)!important; }

/* ── Animations ── */
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.fade-in{animation:fadeIn .4s ease both;}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
.blink-cursor { display:inline-block; width:2px; height:1em; background:currentColor; vertical-align:middle; margin-left:2px; animation:blink 1s step-start infinite; }
@keyframes spin{to{transform:rotate(360deg)}}
.spin{animation:spin .75s linear infinite;}
@keyframes pDot{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.6);opacity:.5}}
.pulse-dot { display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--accent); animation:pDot 1.1s ease-in-out infinite; }

/* ── Scrollbar ── */
::-webkit-scrollbar{width:4px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.08);border-radius:99px;}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.14);}
`
