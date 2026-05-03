#!/usr/bin/env node
import process from 'node:process'
import { spawn } from 'node:child_process'
import { chromium } from 'playwright'

const FRONTEND_URL = 'http://127.0.0.1:3000'
const CHAT_ID = 'chat-1'

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForHttp(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {}
    await sleep(250)
  }
  throw new Error(`Timed out waiting for ${url}`)
}

async function main() {
  const frontend = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '3000'], {
    cwd: 'frontend',
    stdio: 'ignore',
  })

  try {
    await waitForHttp(FRONTEND_URL)
    const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/chromium' })
    const page = await browser.newPage()

    await page.addInitScript(({ chatId }) => {
      const oldReply = 'OLD_REPLY'
      const newReply = 'NEW_REPLY'
      const chat = {
        id: chatId,
        title: 'Existing chat',
        created_at: '2026-05-03T00:00:00Z',
        updated_at: '2026-05-03T00:00:00Z',
        message_count: 2,
        messages: [
          { id: 'm1', role: 'user', content: 'old question', created_at: '2026-05-03T00:00:00Z' },
          { id: 'm2', role: 'assistant', content: oldReply, created_at: '2026-05-03T00:00:01Z' },
        ],
        session_id: 'web-session',
        thinking_mode: 'extended',
        model_name: 'auto',
        transport_mode: 'playwright',
        allow_anon_fallback: false,
        verification: { history_verification: 'not_checked' },
        last_transport_diagnostics: { selected_transport_mode: 'playwright', effective_transport_mode: 'playwright' },
      }

      globalThis.fetch = new Proxy(globalThis.fetch, {
        apply(target, thisArg, args) {
          const [input, init] = args
          const url = typeof input === 'string' ? input : input.url
          const method = (init?.method || 'GET').toUpperCase()
          const u = new URL(url)
          if (u.port === '6969') {
            if (u.pathname === '/chats' && method === 'GET') {
              return Promise.resolve(new Response(JSON.stringify([{ ...chat, messages: undefined }]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
            }
            if (u.pathname === `/chats/${chatId}` && method === 'GET') {
              return Promise.resolve(new Response(JSON.stringify(chat), { status: 200, headers: { 'Content-Type': 'application/json' } }))
            }
            if (u.pathname === `/debug/transports/${chatId}` && method === 'GET') {
              return Promise.resolve(new Response(JSON.stringify({
                chat_id: chatId,
                transport_mode: 'playwright',
                allow_anon_fallback: false,
                verification: chat.verification,
                last_transport_diagnostics: chat.last_transport_diagnostics,
                session_status: { transport_mode: 'playwright' },
                debug_summary: { session_status: {}, last_request_summary: {}, last_response_summary: {}, request_diagnostics: chat.last_transport_diagnostics },
                transport_audit: { selected_transport_mode: 'playwright' },
              }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
            }
            if (u.pathname === `/chats/${chatId}/messages/stream` && method === 'POST') {
              const encoder = new TextEncoder()
              const body = new ReadableStream({
                async start(controller) {
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'user', message: { id: 'pending', role: 'user', content: 'new question', created_at: new Date().toISOString() } })}\n\n`))
                  await new Promise((r) => setTimeout(r, 500))
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: 'NEW_' })}\n\n`))
                  await new Promise((r) => setTimeout(r, 500))
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'chunk', content: 'REPLY' })}\n\n`))
                  await new Promise((r) => setTimeout(r, 50))
                  controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'done', chat: {
                    ...chat,
                    message_count: 4,
                    messages: [
                      ...chat.messages,
                      { id: 'm3', role: 'user', content: 'new question', created_at: new Date().toISOString() },
                      { id: 'm4', role: 'assistant', content: newReply, created_at: new Date().toISOString() },
                    ],
                  } })}\n\n`))
                  controller.close()
                },
              })
              return Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }))
            }
          }
          return Reflect.apply(target, thisArg, args)
        },
      })
    }, { chatId: CHAT_ID })

    await page.goto(`${FRONTEND_URL}/chat/${CHAT_ID}`)
    await page.waitForSelector('textarea')
    await page.waitForSelector(`text=OLD_REPLY`)

    const initialOldReplyCount = await page.locator('text=OLD_REPLY').count()
    if (initialOldReplyCount !== 1) throw new Error(`Expected exactly one OLD_REPLY before send, got ${initialOldReplyCount}`)

    await page.locator('textarea').fill('new question')
    await page.keyboard.press('Enter')

    await page.waitForTimeout(150)
    const oldReplyCountDuringStart = await page.locator('text=OLD_REPLY').count()
    const newReplyCountDuringStart = await page.locator('text=NEW_REPLY').count()
    if (oldReplyCountDuringStart !== 1) throw new Error(`Expected no duplicate OLD_REPLY during stream start, got ${oldReplyCountDuringStart}`)
    if (newReplyCountDuringStart !== 0) throw new Error(`Expected NEW_REPLY to not appear before chunks arrive, got ${newReplyCountDuringStart}`)

    await page.waitForSelector('text=NEW_REPLY', { timeout: 5000 })
    const finalOldReplyCount = await page.locator('text=OLD_REPLY').count()
    if (finalOldReplyCount !== 1) throw new Error(`Expected exactly one OLD_REPLY after stream, got ${finalOldReplyCount}`)

    console.log('[frontend-playwright-test] PASS streaming does not instantly reuse latest old assistant reply')
    await browser.close()
  } finally {
    frontend.kill('SIGTERM')
  }
}

main().catch((error) => {
  console.error('[frontend-playwright-test] FAIL', error)
  process.exit(1)
})
