#!/usr/bin/env node
import fs from 'node:fs/promises'
import process from 'node:process'
import { spawn } from 'node:child_process'
import { chromium } from 'playwright'

function parseArgs(argv) {
  const options = {
    output: 'session.discovered.json',
    url: 'https://chatgpt.com/',
    executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH || '/usr/bin/chromium',
    userDataDir: process.env.CHROMIUM_USER_DATA_DIR || `${process.env.HOME || ''}/.config/chromium`,
    profileDirectory: process.env.CHROMIUM_PROFILE_DIRECTORY || 'Default',
    connectOverCdp: true,
    cdpUrl: 'http://127.0.0.1:9222',
    autoStartDebugBrowser: true,
    debuggingPort: 9222,
    timeoutMs: 30000,
  }

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i]
    const next = argv[i + 1]
    if (arg === '--output' && next) options.output = next, i += 1
    else if (arg === '--url' && next) options.url = next, i += 1
    else if (arg === '--executable-path' && next) options.executablePath = next, i += 1
    else if (arg === '--user-data-dir' && next) options.userDataDir = next, i += 1
    else if (arg === '--profile-directory' && next) options.profileDirectory = next, i += 1
    else if (arg === '--cdp-url' && next) options.cdpUrl = next, i += 1
    else if (arg === '--debugging-port' && next) options.debuggingPort = Number(next), i += 1
    else if (arg === '--timeout-ms' && next) options.timeoutMs = Number(next), i += 1
    else if (arg === '--no-auto-start-debug-browser') options.autoStartDebugBrowser = false
    else if (arg === '--no-cdp') options.connectOverCdp = false
    else if (arg === '--help') {
      console.log(`Usage: node tools/extract_authenticated_session.mjs [options]

Options:
  --output <path>
  --url <url>
  --executable-path <path>
  --user-data-dir <path>
  --profile-directory <name>
  --cdp-url <url>
  --debugging-port <port>
  --timeout-ms <ms>
  --no-auto-start-debug-browser
  --no-cdp
`)
      process.exit(0)
    }
  }
  return options
}

function log(message) {
  console.log(`[extract-session] ${message}`)
}

async function waitForCdp(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url.replace(/\/$/, '')}/json/version`)
      if (response.ok) return true
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  return false
}

async function startDebugBrowser(options) {
  const args = [`--remote-debugging-port=${options.debuggingPort}`]
  if (options.userDataDir) args.push(`--user-data-dir=${options.userDataDir}`)
  if (options.profileDirectory) args.push(`--profile-directory=${options.profileDirectory}`)
  args.push(options.url)
  const child = spawn(options.executablePath, args, { detached: true, stdio: 'ignore' })
  child.unref()
}

async function openBrowser(options) {
  if (options.connectOverCdp) {
    log(`connecting_over_cdp url=${options.cdpUrl}`)
    let ready = await waitForCdp(options.cdpUrl, 2000)
    if (!ready && options.autoStartDebugBrowser) {
      log(`starting_debug_browser executable=${options.executablePath} user_data_dir=${options.userDataDir} profile_directory=${options.profileDirectory}`)
      await startDebugBrowser(options)
      ready = await waitForCdp(options.cdpUrl, options.timeoutMs)
    }
    if (!ready) throw new Error(`cdp_unavailable:${options.cdpUrl}`)
    const browser = await chromium.connectOverCDP(options.cdpUrl)
    const context = browser.contexts()[0]
    if (!context) throw new Error('No browser context available after CDP attach')
    const page = context.pages()[0] || await context.newPage()
    return { browser, context, page, attachedViaCdp: true }
  }

  const context = await chromium.launchPersistentContext(options.userDataDir, {
    executablePath: options.executablePath,
    headless: false,
    viewport: { width: 1440, height: 960 },
    args: options.profileDirectory ? [`--profile-directory=${options.profileDirectory}`] : [],
  })
  const page = context.pages()[0] || await context.newPage()
  return { browser: null, context, page, attachedViaCdp: false }
}

async function detectUi(page) {
  const bodyText = await page.locator('body').innerText().catch(() => '')
  const title = await page.title().catch(() => '')
  return {
    title,
    url: page.url(),
    hasComposer: await page.locator('#prompt-textarea, textarea, div[contenteditable="true"]').first().isVisible().catch(() => false),
    loggedInLikely: /what.?s on your mind today|new chat|chat history|chatgpt/i.test(bodyText) && !/log in|sign up|get started/i.test(bodyText),
    bodyPreview: bodyText.slice(0, 1000),
  }
}

async function writeJson(path, payload) {
  await fs.writeFile(path, JSON.stringify(payload, null, 2) + '\n', 'utf8')
}

async function captureWebsocketUrl(context, discovered, targetUrl, timeoutMs) {
  if (discovered.websocket_url) return
  const probePage = await context.newPage()
  probePage.on('websocket', (ws) => {
    discovered.websocket_url = ws.url()
    discovered.websocket_urls_seen.push(ws.url())
    log(`probe_websocket_created url=${ws.url()}`)
  })
  try {
    await probePage.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch(() => {})
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline && !discovered.websocket_url) {
      await new Promise((resolve) => setTimeout(resolve, 250))
    }
  } finally {
    await probePage.close().catch(() => {})
  }
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  const discovered = {
    captured_at: new Date().toISOString(),
    browser: {
      executable_path: options.executablePath,
      user_data_dir: options.userDataDir,
      profile_directory: options.profileDirectory,
      connect_over_cdp: options.connectOverCdp,
      cdp_url: options.cdpUrl,
      auto_start_debug_browser: options.autoStartDebugBrowser,
      debugging_port: options.debuggingPort,
    },
    websocket_url: null,
    websocket_urls_seen: [],
    cookies: {},
    ui: null,
  }

  const { browser, context, page, attachedViaCdp } = await openBrowser(options)
  try {
    page.on('websocket', (ws) => {
      discovered.websocket_url = ws.url()
      discovered.websocket_urls_seen.push(ws.url())
      log(`websocket_created url=${ws.url()}`)
    })

    await page.goto(options.url, { waitUntil: 'domcontentloaded' })
    discovered.ui = await detectUi(page)
    log(`ui_detected logged_in=${discovered.ui.loggedInLikely} title=${discovered.ui.title}`)

    if (!discovered.websocket_url && discovered.ui.loggedInLikely) {
      log('websocket_url_missing_after_initial_attach probing_new_page')
      await captureWebsocketUrl(context, discovered, options.url, options.timeoutMs)
    }

    const cookies = await context.cookies().catch(() => [])
    for (const cookie of cookies) {
      if (cookie.domain.includes('chatgpt.com') || cookie.domain.includes('openai.com')) {
        discovered.cookies[cookie.name] = cookie.value
      }
    }
    log(`cookie_count=${Object.keys(discovered.cookies).length}`)

    await writeJson(options.output, discovered)
    log(`wrote_output path=${options.output}`)
  } finally {
    if (attachedViaCdp) {
      await browser.close().catch(() => {})
    } else {
      await context.close().catch(() => {})
    }
  }
}

main().catch((error) => {
  console.error(`[extract-session] failed ${error?.message || error}`)
  process.exit(1)
})
