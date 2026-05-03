#!/usr/bin/env node
import fs from 'node:fs/promises'
import process from 'node:process'
import { spawn } from 'node:child_process'
import { chromium } from 'playwright'

async function readStdinJson() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(chunk)
  const raw = Buffer.concat(chunks).toString('utf8').trim()
  if (!raw) throw new Error('No JSON request payload received on stdin')
  return JSON.parse(raw)
}

const transportStartedAt = Date.now()

function emit(event) {
  const enriched = {
    ts: new Date().toISOString(),
    elapsed_ms: Date.now() - transportStartedAt,
    ...event,
  }
  process.stdout.write(`${JSON.stringify(enriched)}\n`)
}

const COMPOSER_SELECTORS = [
  '#prompt-textarea',
  'textarea[placeholder*="Message"]',
  'textarea',
  'div[contenteditable="true"][role="textbox"]',
  'div[contenteditable="true"][data-lexical-editor="true"]',
  'div[contenteditable="true"]',
]

async function findComposer(page) {
  for (const selector of COMPOSER_SELECTORS) {
    const locator = page.locator(selector)
    const count = await locator.count().catch(() => 0)
    for (let i = 0; i < count; i += 1) {
      const candidate = locator.nth(i)
      const visible = await candidate.isVisible().catch(() => false)
      if (visible) {
        return { locator: candidate, selector, index: i }
      }
    }
  }
  return null
}

async function waitForComposer(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const found = await findComposer(page)
    if (found) return found
    await delay(150)
  }
  throw new Error('Prompt composer did not appear before timeout')
}

async function delay(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForNoChallenge(page, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const title = await page.title().catch(() => '')
    const bodyText = await page.locator('body').innerText().catch(() => '')
    const challengeVisible = /just a moment/i.test(title) || /just a moment|checking your browser/i.test(bodyText)
    if (!challengeVisible) return
    await delay(200)
  }
}

async function waitForChatShell(page, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const bodyText = await page.locator('body').innerText().catch(() => '')
    const hasChatUi = /ready when you are|what.?s on your mind today|new chat|chat history|chatgpt/i.test(bodyText)
    if (hasChatUi) return
    await delay(200)
  }
}

async function waitForComposerInteractive(page, timeoutMs = 12000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const found = await findComposer(page)
    if (found) {
      try {
        await found.locator.click({ trial: true, timeout: 250 })
        return found
      } catch {}
    }
    await delay(150)
  }
  return waitForComposer(page, timeoutMs)
}

async function waitForConversationIdle(page, timeoutMs = 5000) {
  const stopButton = page.locator('button[aria-label*="Stop" i]').first()
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const stopVisible = await stopButton.isVisible().catch(() => false)
    if (!stopVisible) return
    await delay(150)
  }
}

async function detectLoggedInUi(page) {
  const bodyText = await page.locator('body').innerText().catch(() => '')
  const hasComposer = await page.locator('#prompt-textarea, textarea, div[contenteditable="true"]').first().isVisible().catch(() => false)
  const hasLoginCues = /log in|sign up|get started/i.test(bodyText)
  const hasChatUiCues = /what.?s on your mind today|new chat|chat history|chatgpt/i.test(bodyText)
  return {
    title: await page.title().catch(() => ''),
    url: page.url(),
    hasComposer,
    hasLoginCues,
    hasChatUiCues,
    loggedInLikely: Boolean(hasComposer || hasChatUiCues) && !hasLoginCues,
    bodyPreview: bodyText.slice(0, 1200),
  }
}

async function ensureComposerContext(page, targetUrl) {
  const initialComposer = await findComposer(page)
  emit({ type: 'status', stage: 'composer_probe', found: Boolean(initialComposer), selector: initialComposer?.selector ?? null, index: initialComposer?.index ?? null })
  if (initialComposer) {
    return await waitForComposerInteractive(page, 5000)
  }

  const newChatButton = page.locator('button:has-text("New chat"), a:has-text("New chat"), [role="button"]:has-text("New chat")').first()
  if (await newChatButton.isVisible().catch(() => false)) {
    emit({ type: 'status', stage: 'opening_new_chat' })
    await newChatButton.click().catch(() => {})
    const readyComposer = await waitForComposerInteractive(page, 10000)
    if (readyComposer) return readyComposer
  }

  emit({ type: 'status', stage: 'navigating_home_for_composer', target_url: targetUrl })
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch(() => {})
  await waitForNoChallenge(page, 10000)
  await waitForChatShell(page, 5000)
  return await waitForComposerInteractive(page, 15000)
}

async function sendPrompt(page, message, targetUrl) {
  const composer = await ensureComposerContext(page, targetUrl)
  emit({ type: 'status', stage: 'composer_ready', selector: composer.selector, index: composer.index })
  await composer.locator.click()
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {})
  await page.keyboard.press('Backspace').catch(() => {})
  await page.keyboard.insertText(message)
  let enteredText = ''
  try {
    enteredText = await composer.locator.inputValue()
  } catch {
    enteredText = await composer.locator.innerText().catch(() => '')
  }
  emit({ type: 'status', stage: 'prompt_entered', prompt_length: enteredText.length })
  const sendButton = page.locator('button[data-testid="send-button"], button[aria-label*="Send" i]').first()
  if (await sendButton.isVisible().catch(() => false)) {
    await sendButton.click().catch(async () => page.keyboard.press('Enter'))
  } else {
    await page.keyboard.press('Enter')
  }
  emit({ type: 'status', stage: 'send_triggered' })
}

async function findLatestAssistantLocator(page) {
  const selectors = [
    '[data-message-author-role="assistant"] .markdown',
    '[data-message-author-role="assistant"] [class*="markdown"]',
    '[data-message-author-role="assistant"]',
    '[data-testid="conversation-turn-assistant"] .markdown',
    '[data-testid="conversation-turn-assistant"]',
  ]
  for (const selector of selectors) {
    const locator = page.locator(selector)
    const count = await locator.count().catch(() => 0)
    if (count > 0) return locator.nth(count - 1)
  }
  return null
}

function normalizeAssistantText(text) {
  return String(text || '')
    .replace(/\r/g, '')
    .replace(/^Thinking\s*/i, '')
    .trim()
}

function isPlaceholderOnly(text) {
  const normalized = normalizeAssistantText(text)
  return !normalized || /^(thinking|analyzing|reasoning)\.?$/i.test(normalized)
}

async function streamAssistantText(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let lastRawText = ''
  let lastNormalizedText = ''
  let stableTicks = 0
  let observedAnyText = false
  while (Date.now() < deadline) {
    const locator = await findLatestAssistantLocator(page)
    const rawText = locator ? await locator.innerText().catch(() => '') : ''
    const normalizedText = normalizeAssistantText(rawText)
    if (rawText && rawText !== lastRawText) {
      observedAnyText = true
      const chunk = normalizedText.slice(lastNormalizedText.length)
      if (chunk) emit({ type: 'chunk', content: chunk })
      lastRawText = rawText
      lastNormalizedText = normalizedText
      stableTicks = 0
      emit({ type: 'status', stage: 'assistant_text_updated', raw_length: rawText.length, normalized_length: normalizedText.length })
    } else if (rawText && rawText === lastRawText) {
      stableTicks += 1
    }

    const stopButtonVisible = await page.locator('button[aria-label*="Stop" i]').first().isVisible().catch(() => false)
    if (observedAnyText && stableTicks >= 4 && !stopButtonVisible && !isPlaceholderOnly(lastRawText)) {
      return { text: lastNormalizedText, timedOut: false, placeholderOnly: false }
    }
    await page.waitForTimeout(700)
  }
  return { text: lastNormalizedText, timedOut: true, placeholderOnly: isPlaceholderOnly(lastRawText) }
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

async function startDebugBrowser(browser, targetUrl) {
  const executable = browser.executable_path
  if (!executable) throw new Error('browser_executable_path is required when auto-starting the debug browser')
  const args = [
    `--remote-debugging-port=${browser.debugging_port || 9222}`,
  ]
  if (browser.user_data_dir) args.push(`--user-data-dir=${browser.user_data_dir}`)
  if (browser.profile_directory) args.push(`--profile-directory=${browser.profile_directory}`)
  args.push(targetUrl || 'https://chatgpt.com/')
  const child = spawn(executable, args, {
    detached: true,
    stdio: 'ignore',
  })
  child.unref()
}

async function openOrAttachBrowser(browser, targetUrl) {
  if (browser.connect_over_cdp) {
    const cdpUrl = browser.cdp_url || `http://127.0.0.1:${browser.debugging_port || 9222}`
    emit({ type: 'status', stage: 'connecting_over_cdp', cdp_url: cdpUrl })
    let ready = await waitForCdp(cdpUrl, 2000)
    if (!ready && browser.auto_start_debug_browser) {
      emit({ type: 'status', stage: 'starting_debug_browser', cdp_url: cdpUrl })
      await startDebugBrowser(browser, targetUrl)
      ready = await waitForCdp(cdpUrl, 30000)
    }
    if (!ready) throw new Error(`cdp_unavailable:${cdpUrl}`)
    const attachedBrowser = await chromium.connectOverCDP(cdpUrl)
    const context = attachedBrowser.contexts()[0]
    if (!context) throw new Error('No browser context was available after CDP attach')
    const page = context.pages()[0] || await context.newPage()
    return { browserHandle: attachedBrowser, context, page, attachedViaCdp: true }
  }

  const launchOptions = {
    headless: Boolean(browser.headless),
    viewport: { width: 1440, height: 960 },
    args: browser.profile_directory ? [`--profile-directory=${browser.profile_directory}`] : [],
  }
  if (browser.executable_path) launchOptions.executablePath = browser.executable_path
  else if (browser.channel) launchOptions.channel = browser.channel
  const context = await chromium.launchPersistentContext(browser.user_data_dir, launchOptions)
  const page = context.pages()[0] || await context.newPage()
  return { browserHandle: null, context, page, attachedViaCdp: false }
}

async function ensureChatPage(page, targetUrl) {
  const currentUrl = page.url()
  const alreadyOnChat = currentUrl.startsWith('https://chatgpt.com/') || currentUrl === 'https://chatgpt.com'

  if (!alreadyOnChat) {
    emit({ type: 'status', stage: 'navigating_to_chatgpt', from_url: currentUrl || null, target_url: targetUrl })
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' })
  } else {
    emit({ type: 'status', stage: 'reusing_existing_chatgpt_page', current_url: currentUrl })
  }

  await page.waitForLoadState('domcontentloaded').catch(() => {})
  await waitForNoChallenge(page, 10000)
  await waitForChatShell(page, 5000)
}

async function main() {
  const request = await readStdinJson()
  const transport = request.transport || {}
  const browser = transport.browser || {}
  emit({ type: 'status', stage: browser.connect_over_cdp ? 'opening_browser_via_cdp' : 'launching_browser', transport_mode: 'playwright' })
  const { browserHandle, context, page, attachedViaCdp } = await openOrAttachBrowser(browser, request.url || 'https://chatgpt.com/')
  try {
    page.on('websocket', (ws) => emit({ type: 'status', stage: 'websocket_created', websocket_url: ws.url() }))
    await ensureChatPage(page, request.url || 'https://chatgpt.com/')
    emit({ type: 'status', stage: 'page_loaded', url: page.url() })
    const ui = await detectLoggedInUi(page)
    emit({ type: 'status', stage: 'ui_detected', ui })
    if (!ui.loggedInLikely) {
      emit({ type: 'result', success: false, error: 'ui_not_logged_in', transport_details: { ui } })
      return
    }

    emit({ type: 'status', stage: 'sending_prompt' })
    await waitForConversationIdle(page, 2500)
    await sendPrompt(page, request.message, request.url || 'https://chatgpt.com/')
    emit({ type: 'status', stage: 'awaiting_assistant_stream' })
    const streamResult = await streamAssistantText(page, Number(request.capture_timeout_ms || 120000))
    const text = streamResult.text
    const finalUi = await detectLoggedInUi(page)
    if (streamResult.timedOut) {
      emit({ type: 'status', stage: 'assistant_stream_timeout', placeholder_only: streamResult.placeholderOnly, text_preview: String(text || '').slice(0, 200) })
    }
    emit({
      type: 'result',
      success: Boolean(text) && !streamResult.placeholderOnly,
      text,
      remote_conversation_id: null,
      remote_parent_message_id: null,
      transport_details: {
        ui_before_send: ui,
        ui_after_send: finalUi,
        transport_mode: 'playwright',
        browser: {
          user_data_dir: browser.user_data_dir,
          profile_directory: browser.profile_directory || null,
          executable_path_present: Boolean(browser.executable_path),
        },
        timed_out: streamResult.timedOut,
        placeholder_only: streamResult.placeholderOnly,
      },
      verification_hints: {
        remote_conversation_exists: Boolean(text) && !streamResult.placeholderOnly,
        effective_transport_mode: 'playwright',
        endpoint_family: 'browser-playwright',
      },
      error: streamResult.placeholderOnly ? 'assistant_response_placeholder_only' : undefined,
    })
  } finally {
    if (attachedViaCdp) {
      await browserHandle.close().catch(() => {})
    } else {
      await context.close().catch(() => {})
    }
  }
}

main().catch((error) => {
  emit({ type: 'result', success: false, error: String(error?.message || error), transport_details: { transport_mode: 'playwright' } })
  process.exit(1)
})
