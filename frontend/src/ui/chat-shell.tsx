import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useRouterState } from '@tanstack/react-router'
import clsx from 'clsx'
import { createChat, deleteChat, getChat, listChats, renameChat, streamMessage, type ChatMessage, type SessionConfig } from '../lib/api'

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
  try {
    return { ...defaultSessionConfig, ...JSON.parse(raw) }
  } catch {
    return defaultSessionConfig
  }
}

export function ChatShell() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const params = useParams({ strict: false }) as { chatId?: string }
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const [sessionConfig, setSessionConfig] = useState<SessionFormState>(() => loadSessionConfig())
  const [message, setMessage] = useState('')
  const [titleInput, setTitleInput] = useState('')
  const [renameInput, setRenameInput] = useState('')
  const [streamingAssistant, setStreamingAssistant] = useState('')
  const [pendingUserMessage, setPendingUserMessage] = useState<ChatMessage | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)

  const chatsQuery = useQuery({ queryKey: ['chats'], queryFn: listChats, retry: false })
  const activeChatId = params.chatId
  const chatQuery = useQuery({
    queryKey: ['chat', activeChatId],
    queryFn: () => getChat(activeChatId!),
    enabled: Boolean(activeChatId),
    retry: false,
  })

  const createChatMutation = useMutation({
    mutationFn: () => createChat({ title: titleInput || undefined, ...sessionConfig }),
    onSuccess: (chat) => {
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })
      setTitleInput('')
    },
  })

  const renameChatMutation = useMutation({
    mutationFn: () => renameChat(activeChatId!, renameInput.trim()),
    onSuccess: (chat) => {
      queryClient.setQueryData(['chat', chat.id], chat)
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      setRenameInput('')
    },
  })

  const deleteChatMutation = useMutation({
    mutationFn: () => deleteChat(activeChatId!),
    onSuccess: () => {
      if (activeChatId) {
        queryClient.removeQueries({ queryKey: ['chat', activeChatId] })
      }
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      navigate({ to: '/' })
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
        if (event.type === 'chunk') {
          setStreamingAssistant((prev) => prev + (event.content ?? ''))
        }
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

  const saveSession = () => {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessionConfig))
  }

  const messages = useMemo(() => {
    const base = [...(chatQuery.data?.messages ?? [])]
    if (pendingUserMessage) {
      base.push(pendingUserMessage)
    }
    if (streamingAssistant) {
      base.push({
        id: 'streaming-assistant',
        role: 'assistant',
        content: streamingAssistant,
        created_at: new Date().toISOString(),
      })
    }
    return base
  }, [chatQuery.data, pendingUserMessage, streamingAssistant])

  useEffect(() => {
    if (!activeChatId || !chatQuery.error) return
    if (String(chatQuery.error.message).includes('404') || String(chatQuery.error.message).includes('Chat not found')) {
      navigate({ to: '/' })
    }
  }, [activeChatId, chatQuery.error, navigate])

  useEffect(() => {
    if (pathname !== '/' || activeChatId || !chatsQuery.data?.length) return
    navigate({ to: '/chat/$chatId', params: { chatId: chatsQuery.data[0].id } })
  }, [activeChatId, chatsQuery.data, navigate, pathname])

  useEffect(() => {
    setRenameInput(chatQuery.data?.title ?? '')
  }, [chatQuery.data?.title])

  return (
    <div className="flex h-screen bg-surface text-white">
      <aside className="flex w-80 flex-col border-r border-border bg-panel/80">
        <div className="border-b border-border p-4">
          <button
            className="w-full rounded-md bg-accent px-4 py-2 font-medium text-white hover:bg-accent/90"
            onClick={() => createChatMutation.mutate()}
          >
            + New chat
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          {chatsQuery.data?.map((chat) => (
            <button
              key={chat.id}
              className={clsx(
                'w-full rounded-md px-3 py-2 text-left text-sm hover:bg-white/10',
                activeChatId === chat.id && 'bg-white/10',
              )}
              onClick={() => navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })}
            >
              <div className="truncate font-medium">{chat.title}</div>
              <div className="mt-1 text-xs text-slate-400">{chat.message_count} messages</div>
            </button>
          ))}
        </div>

        <div className="border-t border-border p-4 space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Session ID</label>
            <input className="w-full rounded border border-border bg-surface px-3 py-2" value={sessionConfig.session_id ?? ''} onChange={(e) => setSessionConfig((s) => ({ ...s, session_id: e.target.value }))} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Model</label>
            <input className="w-full rounded border border-border bg-surface px-3 py-2" value={sessionConfig.model_name} onChange={(e) => setSessionConfig((s) => ({ ...s, model_name: e.target.value }))} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Thinking mode</label>
            <select className="w-full rounded border border-border bg-surface px-3 py-2" value={sessionConfig.thinking_mode} onChange={(e) => setSessionConfig((s) => ({ ...s, thinking_mode: e.target.value as SessionFormState['thinking_mode'] }))}>
              <option value="instant">instant</option>
              <option value="extended">extended</option>
              <option value="pro">pro</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Authorization</label>
            <textarea className="min-h-20 w-full rounded border border-border bg-surface px-3 py-2" value={sessionConfig.authorization ?? ''} onChange={(e) => setSessionConfig((s) => ({ ...s, authorization: e.target.value }))} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-300">Cookies</label>
            <textarea className="min-h-28 w-full rounded border border-border bg-surface px-3 py-2" placeholder="cookie_a=value; cookie_b=value" value={sessionConfig.cookies ?? ''} onChange={(e) => setSessionConfig((s) => ({ ...s, cookies: e.target.value }))} />
          </div>
          <button className="w-full rounded border border-border bg-white/5 px-4 py-2 text-sm hover:bg-white/10" onClick={saveSession}>Save session settings</button>
        </div>
      </aside>

      <main className="flex flex-1 flex-col">
        <header className="border-b border-border px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-lg font-semibold">{chatQuery.data?.title ?? (pathname === '/' ? 'New chat' : 'Loading...')}</div>
              <div className="text-sm text-slate-400">{sessionConfig.model_name} · {sessionConfig.thinking_mode}</div>
            </div>
            {activeChatId ? (
              <div className="flex items-center gap-2">
                <input
                  className="rounded border border-border bg-panel px-3 py-2 text-sm"
                  value={renameInput}
                  onChange={(e) => setRenameInput(e.target.value)}
                  placeholder="Rename chat"
                />
                <button
                  className="rounded border border-border bg-white/5 px-3 py-2 text-sm hover:bg-white/10 disabled:opacity-50"
                  disabled={!renameInput.trim() || renameChatMutation.isPending}
                  onClick={() => renameChatMutation.mutate()}
                >
                  Rename
                </button>
                <button
                  className="rounded border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-200 hover:bg-red-500/20 disabled:opacity-50"
                  disabled={deleteChatMutation.isPending}
                  onClick={() => deleteChatMutation.mutate()}
                >
                  Delete
                </button>
              </div>
            ) : null}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {messages.length === 0 ? (
            <div className="mx-auto mt-20 max-w-2xl text-center text-slate-400">
              <h1 className="text-3xl font-semibold text-white">GPT Fork Web</h1>
              <p className="mt-4">Create a chat from the sidebar or send a message to start a conversation.</p>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {messages.map((item) => (
                <div key={item.id} className={clsx('rounded-2xl px-4 py-3', item.role === 'assistant' ? 'bg-panel' : 'bg-accent/20')}>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-300">{item.role}</div>
                  <div className="whitespace-pre-wrap text-sm leading-7">{item.content}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-border px-6 py-4">
          <div className="mx-auto flex max-w-3xl gap-3">
            <textarea
              className="min-h-24 flex-1 rounded-2xl border border-border bg-panel px-4 py-3 outline-none focus:border-accent"
              placeholder="Send a message..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <div className="flex w-36 flex-col gap-2">
              <input
                className="rounded border border-border bg-panel px-3 py-2 text-sm"
                placeholder="Optional title"
                value={titleInput}
                onChange={(e) => setTitleInput(e.target.value)}
              />
              <button
                className="rounded-xl bg-accent px-4 py-3 font-medium text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!message.trim() || sendMessageMutation.isPending || isStreaming}
                onClick={() => sendMessageMutation.mutate()}
              >
                {sendMessageMutation.isPending || isStreaming ? 'Streaming…' : 'Send'}
              </button>
            </div>
          </div>
          {chatQuery.error ? <div className="mx-auto mt-3 max-w-3xl text-sm text-amber-400">Active chat was not found. You were redirected to a new chat view.</div> : null}
          {streamError ? <div className="mx-auto mt-3 max-w-3xl text-sm text-red-400">{streamError}</div> : null}
          {sendMessageMutation.error ? <div className="mx-auto mt-3 max-w-3xl text-sm text-red-400">{String(sendMessageMutation.error.message)}</div> : null}
          {createChatMutation.error ? <div className="mx-auto mt-3 max-w-3xl text-sm text-red-400">{String(createChatMutation.error.message)}</div> : null}
          {renameChatMutation.error ? <div className="mx-auto mt-3 max-w-3xl text-sm text-red-400">{String(renameChatMutation.error.message)}</div> : null}
          {deleteChatMutation.error ? <div className="mx-auto mt-3 max-w-3xl text-sm text-red-400">{String(deleteChatMutation.error.message)}</div> : null}
        </div>
      </main>
    </div>
  )
}
