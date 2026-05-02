#!/usr/bin/env node
import fs from 'node:fs/promises'
import path from 'node:path'
import process from 'node:process'
import { chromium } from 'playwright'

function parseArgs(argv) {
  const options = {
    url: 'https://chatgpt.com/',
    message: 'Reply with the single word: pong',
    output: 'session.discovered.json',
    cookies: 'cookies.txt',
    channel: 'chrome',
    headless: false,
    loginTimeoutMs: 180_000,
    captureTimeoutMs: 120_000,
    userDataDir: '.auth-profile/chatgpt-playwright',
    profileDirectory: '',
    writeSessionJson: false,
    sessionPath: 'session.json',
    executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || '',
  }

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    const next = argv[i + 1]
    if (arg === '--url' && next) options.url = next, i += 1
    else if (arg === '--message' && next) options.message = next, i += 1
    else if (arg === '--output' && next) options.output = next, i += 1
    else if (arg === '--cookies' && next) options.cookies = next, i += 1
    else if (arg === '--channel' && next) options.channel = next, i += 1
    else if (arg === '--user-data-dir' && next) options.userDataDir = next, i += 1
    else if (arg === '--profile-directory' && next) options.profileDirectory = next, i += 1
    else if (arg === '--session-path' && next) options.sessionPath = next, i += 1
    else if (arg === '--executable-path' && next) options.executablePath = next, i += 1
    else if (arg === '--login-timeout-ms' && next) options.loginTimeoutMs = Number(next), i += 1
    else if (arg === '--capture-timeout-ms' && next) options.captureTimeoutMs = Number(next), i += 1
    else if (arg === '--headless') options.headless = true
    else if (arg === '--write-session-json') options.writeSessionJson = true
    else if (arg === '--help') {
      printHelp()
      process.exit(0)
    }
  }

  return options
}

function printHelp() {
  console.log(`Usage: node tools/discover_authenticated_ws.mjs [options]

Options:
  --message <text>             Probe message to send
  --output <path>              Output JSON path (default: session.discovered.json)
  --cookies <path>             Netscape cookies file to import for fallback/debug mode
  --user-data-dir <path>       Chromium user data dir (required for real-profile reuse)
  --profile-directory <name>   Chromium profile directory name, e.g. Default or Profile 1
  --session-path <path>        session.json path for optional auto-update
  --write-session-json         Copy discovered websocket_url into session.json
  --headless                   Run headless (not recommended for login)
  --login-timeout-ms <ms>      Wait time for prompt UI/login
  --capture-timeout-ms <ms>    Wait time for websocket/handoff capture
  --channel <name>             Browser channel (default: chrome)
  --executable-path <path>     Use a system Chromium/Chrome binary
`)
}

async function exists(filePath) {
  try {
    await fs.access(filePath)
    return true
  } catch {
    return false
  }
}

function parseNetscapeCookies(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'))
    .map((line) => line.split('\t'))
    .filter((parts) => parts.length >= 7)
    .map((parts) => {
      const [rawDomain, , cookiePath, secure, rawExpires, name, ...valueParts] = parts
      const domain = rawDomain.replace(/^#HttpOnly_/, '')
      const value = valueParts.join('\t')
      const cookie = {
        name,
        value,
        domain,
        path: cookiePath || '/',
        secure: String(secure).toUpperCase() === 'TRUE',
        httpOnly: rawDomain.startsWith('#HttpOnly_'),
      }
      const expires = Number(rawExpires)
      if (Number.isFinite(expires) && expires > 0) cookie.expires = expires
      return cookie
    })
    .filter((cookie) => cookie.domain.includes('chatgpt.com') || cookie.domain.includes('openai.com'))
}

function safeJsonParse(value) {
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function extractStreamMetadata(text) {
  const metadata = {
    resume_conversation_token: null,
    conversation_id: null,
    turn_exchange_id: null,
    handoff_topic_id: null,
    resume_sse_topic_id: null,
    stream_handoff_found: false,
  }

  for (const rawLine of String(text || '').split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line.startsWith('data:')) continue
    const payload = line.slice(5).trim()
    if (!payload || payload === '[DONE]') continue
    const parsed = safeJsonParse(payload)
    if (!parsed || typeof parsed !== 'object') continue

    if (parsed.type === 'resume_conversation_token' && parsed.token) {
      metadata.resume_conversation_token = parsed.token
      if (parsed.conversation_id) metadata.conversation_id = parsed.conversation_id
    }

    if (parsed.type === 'stream_handoff') {
      metadata.stream_handoff_found = true
      if (parsed.conversation_id) metadata.conversation_id = parsed.conversation_id
      if (parsed.turn_exchange_id) metadata.turn_exchange_id = parsed.turn_exchange_id
      for (const option of parsed.options || []) {
        if (!option || typeof option !== 'object') continue
        if (option.type === 'subscribe_ws_topic' && option.topic_id) metadata.handoff_topic_id = option.topic_id
        if (option.type === 'resume_sse_endpoint' && option.topic_id) metadata.resume_sse_topic_id = option.topic_id
      }
    }
  }

  return metadata
}

async function waitForComposer(page, timeoutMs) {
  const selectors = [
    '#prompt-textarea',
    'textarea[placeholder*="Message"]',
    'textarea',
    'div[contenteditable="true"]',
  ]

  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const locator = page.locator(selector).first()
      if (await locator.count().catch(() => 0)) {
        const visible = await locator.isVisible().catch(() => false)
        if (visible) return locator
      }
    }
    await page.waitForTimeout(1000)
  }
  throw new Error('Prompt composer did not appear before login timeout. Log in within the launched browser profile and retry.')
}

async function sendProbeMessage(page, message) {
  const composer = await waitForComposer(page, 5_000)
  await composer.click()
  try {
    await composer.fill(message)
  } catch {
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {})
    await page.keyboard.press('Backspace').catch(() => {})
    await page.keyboard.type(message, { delay: 15 })
  }

  const sendButton = page.locator('button[data-testid="send-button"], button[aria-label*="Send" i], button:has(svg)').first()
  if (await sendButton.isVisible().catch(() => false)) {
    await sendButton.click().catch(async () => {
      await page.keyboard.press('Enter')
    })
  } else {
    await page.keyboard.press('Enter')
  }
}

async function maybeImportCookies(context, cookiesPath) {
  if (!(await exists(cookiesPath))) return 0
  const browserCookies = await context.cookies()
  if (browserCookies.some((cookie) => cookie.domain.includes('chatgpt.com'))) return 0
  const raw = await fs.readFile(cookiesPath, 'utf8')
  const cookies = parseNetscapeCookies(raw)
  if (!cookies.length) return 0
  await context.addCookies(cookies)
  return cookies.length
}

async function detectLoggedInUi(page) {
  const title = await page.title().catch(() => '')
  const url = page.url()
  const bodyText = await page.locator('body').innerText().catch(() => '')
  const hasComposer = await page.locator('#prompt-textarea, textarea, div[contenteditable="true"]').first().isVisible().catch(() => false)
  const hasLoginCues = /log in|sign up|get started/i.test(bodyText)
  const hasChatUiCues = /what.?s on your mind today|new chat|chat history|chatgpt/i.test(bodyText)
  return {
    title,
    url,
    hasComposer,
    hasLoginCues,
    hasChatUiCues,
    loggedInLikely: Boolean(hasComposer || hasChatUiCues) && !hasLoginCues,
    bodyPreview: bodyText.slice(0, 1000),
  }
}

async function writeJson(filePath, payload) {
  await fs.mkdir(path.dirname(filePath), { recursive: true })
  await fs.writeFile(filePath, JSON.stringify(payload, null, 2) + '\n', 'utf8')
}

async function maybeUpdateSessionJson(sessionPath, discovered) {
  let session = {}
  if (await exists(sessionPath)) {
    try {
      session = JSON.parse(await fs.readFile(sessionPath, 'utf8'))
    } catch {
      session = {}
    }
  }
  if (discovered.websocket_url) session.websocket_url = discovered.websocket_url
  if (discovered.resume_conversation_token) session.websocket_verify_token = discovered.resume_conversation_token
  session.websocket_har_path = session.websocket_har_path || 'chatgpt.com3.har'
  await writeJson(sessionPath, session)
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  const usingRealProfile = Boolean(options.profileDirectory) || options.userDataDir !== '.auth-profile/chatgpt-playwright'
  const state = {
    started_at: new Date().toISOString(),
    page_url: options.url,
    probe_message: options.message,
    using_real_profile: usingRealProfile,
    user_data_dir: options.userDataDir,
    profile_directory: options.profileDirectory || null,
    profile_exists: false,
    cookie_import_mode: usingRealProfile ? 'disabled_for_real_profile' : 'fallback_debug_only',
    websocket_url: null,
    websocket_urls_seen: [],
    websocket_frames_seen: 0,
    websocket_sample_frames: [],
    conversation_id: null,
    turn_exchange_id: null,
    handoff_topic_id: null,
    resume_sse_topic_id: null,
    resume_conversation_token: null,
    stream_handoff_found: false,
    initial_conversation_response_preview: null,
    cookies_imported: 0,
    ui_logged_in_likely: false,
    ui_diagnostics: null,
    prepare_request_status: null,
    prepare_response_content_type: null,
    prepare_response_is_html_challenge: false,
    prepare_response_preview: null,
    hard_blocker: null,
    reached_handoff_stage: false,
    reached_websocket_stage: false,
  }

  state.profile_exists = await exists(options.userDataDir)
  console.log(`[discover-ws] user_data_dir=${options.userDataDir}`)
  console.log(`[discover-ws] profile_directory=${options.profileDirectory || '-'} using_real_profile=${usingRealProfile}`)
  console.log(`[discover-ws] profile_exists=${state.profile_exists}`)
  if (usingRealProfile && !state.profile_exists) {
    throw new Error(`Real profile user data dir does not exist: ${options.userDataDir}`)
  }

  const launchOptions = {
    headless: options.headless,
    viewport: { width: 1440, height: 960 },
    args: options.profileDirectory ? [`--profile-directory=${options.profileDirectory}`] : [],
  }
  if (options.executablePath) launchOptions.executablePath = options.executablePath
  else if (options.channel) launchOptions.channel = options.channel

  const context = await chromium.launchPersistentContext(options.userDataDir, launchOptions)

  try {
    if (usingRealProfile) {
      console.log('[discover-ws] cookie_import=skipped (real profile mode)')
    } else {
      console.log('[discover-ws] cookie_import=enabled (fallback/debug mode only)')
      state.cookies_imported = await maybeImportCookies(context, options.cookies)
    }
    const page = context.pages()[0] || await context.newPage()

    page.on('websocket', (ws) => {
      state.websocket_url = ws.url()
      state.websocket_urls_seen.push(ws.url())
      state.reached_websocket_stage = true
      console.log(`[discover-ws] websocket_created url=${ws.url()}`)

      ws.on('framesent', ({ payload }) => {
        state.websocket_frames_seen += 1
        const text = typeof payload === 'string' ? payload : payload?.toString?.('utf8')
        if (text && state.websocket_sample_frames.length < 5) {
          state.websocket_sample_frames.push({ direction: 'sent', preview: String(text).slice(0, 500) })
        }
      })

      ws.on('framereceived', ({ payload }) => {
        state.websocket_frames_seen += 1
        const text = typeof payload === 'string' ? payload : payload?.toString?.('utf8')
        if (text && state.websocket_sample_frames.length < 8) {
          state.websocket_sample_frames.push({ direction: 'received', preview: String(text).slice(0, 500) })
        }
      })
    })

    page.on('response', async (response) => {
      const url = response.url()
      const method = response.request().method()
      let text = ''
      try {
        text = await response.text()
      } catch {
        text = ''
      }

      if (url.includes('/backend-api/f/conversation/prepare') && method === 'POST') {
        state.prepare_request_status = response.status()
        state.prepare_response_content_type = response.headers()['content-type'] || null
        state.prepare_response_preview = text.slice(0, 1200)
        state.prepare_response_is_html_challenge = Boolean(
          state.prepare_response_content_type?.includes('text/html') || /__cf_chl|<html|meta http-equiv="refresh"/i.test(text)
        )
        console.log(`[discover-ws] prepare_response status=${state.prepare_request_status} content_type=${state.prepare_response_content_type ?? '-'} html_challenge=${state.prepare_response_is_html_challenge}`)
        if (state.prepare_request_status === 403 || state.prepare_response_is_html_challenge) {
          state.hard_blocker = 'prepare_conversation_challenge_or_403'
        }
      }

      if (!url.includes('/backend-api/f/conversation') || method !== 'POST') return
      state.initial_conversation_response_preview = text.slice(0, 1200)
      const meta = extractStreamMetadata(text)
      Object.assign(state, {
        conversation_id: meta.conversation_id || state.conversation_id,
        turn_exchange_id: meta.turn_exchange_id || state.turn_exchange_id,
        handoff_topic_id: meta.handoff_topic_id || state.handoff_topic_id,
        resume_sse_topic_id: meta.resume_sse_topic_id || state.resume_sse_topic_id,
        resume_conversation_token: meta.resume_conversation_token || state.resume_conversation_token,
        stream_handoff_found: meta.stream_handoff_found || state.stream_handoff_found,
      })
      state.reached_handoff_stage = Boolean(state.stream_handoff_found || state.handoff_topic_id || state.resume_sse_topic_id)
      console.log(`[discover-ws] conversation_response handoff=${state.stream_handoff_found} conversation_id=${state.conversation_id ?? '-'} topic=${state.handoff_topic_id ?? state.resume_sse_topic_id ?? '-'}`)
    })

    await page.goto(options.url, { waitUntil: 'domcontentloaded' })
    if (state.cookies_imported > 0) {
      console.log(`[discover-ws] imported_cookies=${state.cookies_imported}`)
      await page.goto(options.url, { waitUntil: 'domcontentloaded' })
    }

    state.ui_diagnostics = await detectLoggedInUi(page)
    state.ui_logged_in_likely = Boolean(state.ui_diagnostics?.loggedInLikely)
    console.log(`[discover-ws] ui_logged_in_likely=${state.ui_logged_in_likely} title=${state.ui_diagnostics?.title || '-'} url=${state.ui_diagnostics?.url || '-'}`)

    console.log('[discover-ws] waiting_for_prompt_or_login')
    await waitForComposer(page, options.loginTimeoutMs)
    console.log('[discover-ws] prompt_ready sending_probe_message')
    await sendProbeMessage(page, options.message)

    const deadline = Date.now() + options.captureTimeoutMs
    while (Date.now() < deadline) {
      if (state.websocket_url && state.handoff_topic_id) break
      await page.waitForTimeout(500)
    }

    state.completed_at = new Date().toISOString()
    state.reached_handoff_stage = Boolean(state.stream_handoff_found || state.handoff_topic_id || state.resume_sse_topic_id)
    state.reached_websocket_stage = Boolean(state.reached_websocket_stage || state.websocket_url)
    state.capture_succeeded = Boolean(state.websocket_url || state.handoff_topic_id || state.resume_conversation_token)

    await writeJson(options.output, state)
    console.log(`[discover-ws] wrote_output path=${options.output}`)
    console.log(`[discover-ws] websocket_url=${state.websocket_url ?? '-'}`)
    console.log(`[discover-ws] handoff_topic_id=${state.handoff_topic_id ?? '-'}`)
    console.log(`[discover-ws] resume_conversation_token_present=${Boolean(state.resume_conversation_token)}`)
    console.log(`[discover-ws] reached_handoff_stage=${state.reached_handoff_stage} reached_websocket_stage=${state.reached_websocket_stage}`)

    if (options.writeSessionJson && state.websocket_url) {
      await maybeUpdateSessionJson(options.sessionPath, state)
      console.log(`[discover-ws] updated_session_json path=${options.sessionPath}`)
    }

    if (state.hard_blocker) {
      process.exitCode = 3
      console.error(`[discover-ws] hard_blocker=${state.hard_blocker}`)
    } else if (!state.capture_succeeded) {
      process.exitCode = 2
      console.error('[discover-ws] no websocket or handoff artifacts were captured')
    }
  } finally {
    await context.close()
  }
}

main().catch((error) => {
  console.error('[discover-ws] failed', error)
  process.exit(1)
})
