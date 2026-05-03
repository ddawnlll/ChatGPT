#!/usr/bin/env node
import fsSync from 'node:fs'
import fs from 'node:fs/promises'
import process from 'node:process'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { createRequire } from 'node:module'
import { chromium, firefox, webkit } from 'playwright'

import readline from 'node:readline'

const require = createRequire(import.meta.url)

function getPlaywrightVersion() {
  try {
    return require('playwright/package.json').version
  } catch {
    return null
  }
}

function getBrowserTypeName(browser) {
  return String(browser.browser_type || 'firefox').toLowerCase()
}

function getBrowserType(browser) {
  const type = getBrowserTypeName(browser)

  if (type === 'firefox') return firefox
  if (type === 'webkit') return webkit
  if (type === 'chromium' || type === 'chrome') return chromium

  throw new Error(`Unsupported browser_type: ${type}`)
}

// System browser detection — no Playwright-managed browsers needed
const SYSTEM_BROWSER_CANDIDATES = [
  { type: 'chromium', path: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' },
  { type: 'chromium', path: '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser' },
  { type: 'chromium', path: '/Applications/Chromium.app/Contents/MacOS/Chromium' },
  { type: 'firefox',  path: '/Applications/Firefox.app/Contents/MacOS/firefox' },
]

function findSystemBrowser() {
  for (const candidate of SYSTEM_BROWSER_CANDIDATES) {
    try { if (fsSync.statSync(candidate.path).isFile()) return candidate } catch {}
  }
  return null
}

function buildLaunchArgs(browser) {
  const type = getBrowserTypeName(browser)

  if (type === 'firefox' || type === 'webkit') {
    return []
  }

  // Chromium args
  return [
    '--password-store=basic',
    '--no-first-run',
    '--no-default-browser-check',
    '--remote-allow-origins=*',
    '--hide-crash-restore-bubble',
    '--disable-session-crashed-bubble',
    '--disable-infobars',
  ]
}

function resolveExecutablePath(browser) {
  if (browser.executable_path) return browser.executable_path
  // Fall back to system browser detection
  const system = findSystemBrowser()
  if (system) return system.path
  // Last resort: let Playwright try its own
  const browserType = getBrowserType(browser)
  return browserType.executablePath()
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

async function openFreshThread(page, targetUrl) {
  const currentUrl = page.url()
  const normalizedTarget = `${targetUrl}`.replace(/\/$/, '')
  const existingComposer = await findComposer(page)
  const alreadyHome = currentUrl.replace(/\/$/, '') === normalizedTarget

  if (alreadyHome && existingComposer) {
    emit({ type: 'status', stage: 'fresh_thread_already_ready', current_url: currentUrl, selector: existingComposer.selector, index: existingComposer.index })
    return true
  }

  emit({ type: 'status', stage: 'navigating_home_for_fresh_thread', current_url: currentUrl, target_url: targetUrl })
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch(() => {})
  await waitForNoChallenge(page, 10000)
  await waitForChatShell(page, 5000)
  const homeComposer = await waitForComposerInteractive(page, 10000)
  emit({ type: 'status', stage: 'fresh_thread_home_ready', composer_found: Boolean(homeComposer), selector: homeComposer?.selector ?? null, index: homeComposer?.index ?? null, current_url: page.url() })
  return true
}

async function ensureComposerContext(page, targetUrl, newConversation) {
  if (newConversation) {
    await openFreshThread(page, targetUrl)
  }

  const initialComposer = await findComposer(page)
  emit({ type: 'status', stage: 'composer_probe', found: Boolean(initialComposer), selector: initialComposer?.selector ?? null, index: initialComposer?.index ?? null, new_conversation: Boolean(newConversation) })
  if (initialComposer) {
    return await waitForComposerInteractive(page, 5000)
  }

  if (!newConversation) {
    const newChatButton = page.locator('button:has-text("New chat"), a:has-text("New chat"), [role="button"]:has-text("New chat")').first()
    if (await newChatButton.isVisible().catch(() => false)) {
      emit({ type: 'status', stage: 'opening_new_chat' })
      await newChatButton.click().catch(() => {})
      const readyComposer = await waitForComposerInteractive(page, 10000)
      if (readyComposer) return readyComposer
    }
  }

  emit({ type: 'status', stage: 'navigating_home_for_composer', target_url: targetUrl })
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch(() => {})
  await waitForNoChallenge(page, 10000)
  await waitForChatShell(page, 5000)
  return await waitForComposerInteractive(page, 15000)
}

async function sendPrompt(page, message, targetUrl, newConversation) {
  const composer = await ensureComposerContext(page, targetUrl, newConversation)
  emit({ type: 'status', stage: 'composer_ready', selector: composer.selector, index: composer.index })

  const activateComposer = async (locator) => {
    await locator.scrollIntoViewIfNeeded().catch(() => {})
    await locator.focus().catch(() => {})
    await locator.click({ timeout: 1500 }).catch(async () => {
      await locator.evaluate((node) => {
        if (node && typeof node.focus === 'function') node.focus()
      }).catch(() => {})
    })
  }

  // Loop to type and send, retrying if the message doesn't send or type correctly
  let promptSent = false
  for (let attempt = 1; attempt <= 3; attempt++) {
    await activateComposer(composer.locator)
    await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {})
    await page.keyboard.press('Backspace').catch(() => {})

    if (composer.selector.includes('textarea')) {
      await composer.locator.fill('').catch(() => {})
      await composer.locator.fill(message).catch(async () => {
        await page.keyboard.insertText(message)
      })
    } else {
      await page.keyboard.insertText(message)
    }

    let enteredText = ''
    try {
      enteredText = await composer.locator.inputValue()
    } catch {
      enteredText = await composer.locator.innerText().catch(() => '')
    }
    emit({ type: 'status', stage: 'prompt_entered', attempt, prompt_length: enteredText.length })
    
    // If it completely failed to type, retry the whole typing block
    if (enteredText.trim().length === 0 && message.trim().length > 0) {
      await delay(500)
      continue
    }

    // Wait a tiny bit for React state to register the input
    await delay(100)
    
    const sendButton = page.locator('button[data-testid="send-button"], button[aria-label*="Send" i]').first()
    
    if (await sendButton.isVisible().catch(() => false)) {
      // Ensure the button isn't disabled before clicking
      const isDisabled = await sendButton.isDisabled().catch(() => false)
      if (!isDisabled) {
        await sendButton.click({ force: true, timeout: 1000 }).catch(async () => page.keyboard.press('Enter'))
      } else {
        await page.keyboard.press('Enter')
      }
    } else {
      await page.keyboard.press('Enter')
    }
    
    // Wait up to 1.5 seconds for the composer to clear (indicating successful send)
    let cleared = false
    for (let i = 0; i < 10; i++) {
      await delay(150)
      let currentText = ''
      try {
        currentText = await composer.locator.inputValue()
      } catch {
        currentText = await composer.locator.innerText().catch(() => '')
      }
      if (currentText.trim().length === 0 || currentText.trim() === 'Message ChatGPT') {
        cleared = true
        break
      }
    }
    
    if (cleared) {
      promptSent = true
      break
    } else {
      emit({ type: 'status', stage: 'send_retry', attempt })
    }
  }
  
  if (!promptSent) {
    emit({ type: 'status', stage: 'send_failed_but_continuing' })
  } else {
    emit({ type: 'status', stage: 'send_triggered' })
  }
}

const ASSISTANT_SELECTORS = [
  '[data-message-author-role="assistant"] .markdown',
  '[data-message-author-role="assistant"] [class*="markdown"]',
  '[data-message-author-role="assistant"]',
  '[data-testid="conversation-turn-assistant"] .markdown',
  '[data-testid="conversation-turn-assistant"]',
]

async function extractAssistantText(locator) {
  return locator.evaluate((node) => {
    function isHidden(el) {
      const style = window.getComputedStyle(el)
      return style.display === 'none' || style.visibility === 'hidden'
    }

    function walk(current) {
      if (current.nodeType === Node.TEXT_NODE) {
        return current.textContent || ''
      }
      if (current.nodeType !== Node.ELEMENT_NODE) return ''

      const el = current
      if (isHidden(el)) return ''
      const tag = el.tagName.toLowerCase()
      if (['button', 'svg', 'path', 'style', 'script', 'noscript'].includes(tag)) return ''
      if (el.getAttribute('role') === 'button') return ''
      if (el.getAttribute('aria-label')) return ''

      if (tag === 'pre') {
        const codeEl = el.querySelector('code')
        const code = (codeEl?.textContent || codeEl?.innerText || el.textContent || el.innerText || '').trimEnd()
        const className = codeEl?.className || ''
        const langMatch = className.match(/language-([\w+-]+)/i)
        const language = langMatch ? langMatch[1] : ''
        return `\n\n\`\`\`${language ? language : ''}\n${code}\n\`\`\`\n\n`
      }
      if (tag === 'code' && el.closest('pre')) {
        return ''
      }
      if (tag === 'code') {
        const code = el.innerText || el.textContent || ''
        const className = el.className || ''
        const langMatch = className.match(/language-([\w+-]+)/i)
        const language = langMatch ? langMatch[1] : ''
        if (language || code.includes('\n')) {
          return code ? `\n\n\`\`\`${language ? language : ''}\n${code.trimEnd()}\n\`\`\`\n\n` : ''
        }
        return code ? `\`${code}\`` : ''
      }
      if (tag === 'a') {
        const href = el.getAttribute('href') || ''
        let linkText = ''
        for (const child of el.childNodes) linkText += walk(child)
        linkText = linkText.trim()
        if (href && linkText) return `[${linkText}](${href})`
        return linkText
      }
      if (tag === 'br') return '\n'

      let text = ''
      for (const child of el.childNodes) text += walk(child)

      if (['p', 'div', 'section', 'article', 'blockquote'].includes(tag)) {
        return text.trim() ? `${text.replace(/^\n+|\n+$/g, '')}\n\n` : ''
      }
      if (['li'].includes(tag)) {
        return text.trim() ? `- ${text.trim()}\n` : ''
      }
      if (/^h[1-6]$/.test(tag)) {
        return text.trim() ? `${text.trim()}\n\n` : ''
      }
      return text
    }

    return walk(node)
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]+\n/g, '\n')
      .trim()
  }).catch(() => '')
}

async function getAssistantSnapshot(page) {
  for (const selector of ASSISTANT_SELECTORS) {
    const locator = page.locator(selector)
    const count = await locator.count().catch(() => 0)
    if (count > 0) {
      const latest = locator.nth(count - 1)
      const rawText = await extractAssistantText(latest)
      return { selector, count, rawText }
    }
  }
  return { selector: null, count: 0, rawText: '' }
}

async function findLatestAssistantLocator(page, baseline = null) {
  if (baseline?.selector) {
    const baselineLocator = page.locator(baseline.selector)
    const baselineCount = await baselineLocator.count().catch(() => 0)
    if (baselineCount > 0) {
      if (baselineCount > (baseline.count || 0)) {
        return { locator: baselineLocator.nth(baselineCount - 1), selector: baseline.selector, count: baselineCount, isNewMessage: true }
      }
      const latest = baselineLocator.nth(baselineCount - 1)
      const rawText = await extractAssistantText(latest)
      if (rawText !== (baseline.rawText || '')) {
        return { locator: latest, selector: baseline.selector, count: baselineCount, isNewMessage: false }
      }
      return null
    }
  }

  for (const selector of ASSISTANT_SELECTORS) {
    const locator = page.locator(selector)
    const count = await locator.count().catch(() => 0)
    if (count <= 0) continue
    const latest = locator.nth(count - 1)
    const rawText = await extractAssistantText(latest)
    if (baseline && rawText === (baseline.rawText || '')) {
      continue
    }
    return { locator: latest, selector, count, isNewMessage: Boolean(baseline) }
  }
  return null
}

function normalizeAssistantText(text) {
  return String(text || '')
    .replace(/\r/g, '')
    .replace(/^Thinking\s*/i, '')
    .trim()
}

function isIgnorableAssistantText(text) {
  const normalized = normalizeAssistantText(text)
  return (
    !normalized ||
    /^(thinking|analyzing|reasoning)\.?$/i.test(normalized) ||
    /^hello!?\s+what.?s on your mind today\??$/i.test(normalized) ||
    /^ready when you are\.?$/i.test(normalized) ||
    /^how can i help(?:,.*)?\\??$/i.test(normalized)
  )
}

function isPlaceholderOnly(text) {
  return isIgnorableAssistantText(text)
}

function looksLikeCompleteAssistantText(text) {
  const normalized = normalizeAssistantText(text)
  if (!normalized) return false
  if (/```\s*$/.test(normalized)) return true
  if (/[.!?"')\]]$/.test(normalized)) return true
  if (/\n\n/.test(normalized)) return true
  return false
}

async function streamAssistantText(page, timeoutMs, baselineAssistant = null) {
  const deadline = Date.now() + timeoutMs
  let lastRawText = ''
  let lastNormalizedText = ''
  let stableTicks = 0
  let observedAnyText = false
  while (Date.now() < deadline) {
    const assistantState = await findLatestAssistantLocator(page, baselineAssistant)
    const rawText = assistantState ? await extractAssistantText(assistantState.locator) : ''
    const normalizedText = normalizeAssistantText(rawText)
    if (rawText && rawText !== lastRawText) {
      observedAnyText = true
      const ignorable = isIgnorableAssistantText(rawText)
      const chunk = ignorable ? '' : normalizedText.slice(lastNormalizedText.length)
      if (chunk) emit({ type: 'chunk', content: chunk })
      lastRawText = rawText
      lastNormalizedText = ignorable ? '' : normalizedText
      stableTicks = 0
      emit({ type: 'status', stage: 'assistant_text_updated', raw_length: rawText.length, normalized_length: normalizedText.length, assistant_selector: assistantState?.selector ?? null, assistant_count: assistantState?.count ?? null, is_new_message: assistantState?.isNewMessage ?? null, ignorable })
    } else if (rawText && rawText === lastRawText) {
      stableTicks += 1
    }

    const stopButtonVisible = await page.locator('button[aria-label*="Stop" i]').first().isVisible().catch(() => false)
    const composerVisible = await page.locator(COMPOSER_SELECTORS.join(', ')).first().isVisible().catch(() => false)
    const sendButtonVisible = await page.locator('button[data-testid="send-button"], button[aria-label*="Send" i]').first().isVisible().catch(() => false)
    if (observedAnyText && !isPlaceholderOnly(lastRawText)) {
      const textLooksComplete = looksLikeCompleteAssistantText(lastRawText)
      if (!stopButtonVisible && textLooksComplete && (composerVisible || sendButtonVisible) && stableTicks >= 1) {
        emit({ type: 'status', stage: 'assistant_completion_detected', stable_ticks: stableTicks, composer_visible: composerVisible, send_button_visible: sendButtonVisible, text_looks_complete: textLooksComplete })
        return { text: lastNormalizedText, timedOut: false, placeholderOnly: false }
      }
      if (!stopButtonVisible && stableTicks >= (textLooksComplete ? 2 : 4)) {
        emit({ type: 'status', stage: 'assistant_completion_detected', stable_ticks: stableTicks, composer_visible: composerVisible, send_button_visible: sendButtonVisible, text_looks_complete: textLooksComplete })
        return { text: lastNormalizedText, timedOut: false, placeholderOnly: false }
      }
    }
    await page.waitForTimeout(250)
  }
  return { text: lastNormalizedText, timedOut: true, placeholderOnly: isPlaceholderOnly(lastRawText) }
}



function buildConversationUrl(targetUrl, remoteConversationId) {
  const base = new URL(targetUrl)
  return `${base.origin}/c/${remoteConversationId}`
}

async function ensureChatPage(page, targetUrl) {
  const currentUrl = page.url()
  const normalizedTarget = targetUrl.replace(/\/$/, '')
  const alreadyOnChat = currentUrl.startsWith(normalizedTarget)

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

async function ensureRemoteConversation(page, targetUrl, remoteConversationId) {
  if (!remoteConversationId) return
  const desiredUrl = buildConversationUrl(targetUrl, remoteConversationId)
  const currentUrl = page.url().split(/[?#]/)[0]
  if (currentUrl === desiredUrl) {
    emit({ type: 'status', stage: 'reusing_matching_remote_conversation', remote_conversation_id: remoteConversationId, current_url: page.url() })
    return
  }
  emit({ type: 'status', stage: 'switching_remote_conversation', remote_conversation_id: remoteConversationId, from_url: page.url(), target_url: desiredUrl })
  await page.goto(desiredUrl, { waitUntil: 'domcontentloaded' }).catch(() => {})
  await page.waitForLoadState('domcontentloaded').catch(() => {})
  await waitForNoChallenge(page, 10000)
  await waitForChatShell(page, 5000)
}

// Global persistent state
let globalContext = null
let globalPage = null
let processingRequest = false

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
})

rl.on('line', async (line) => {
  if (!line.trim()) return
  if (processingRequest) {
    emit({ type: 'status', stage: 'warning', message: 'overlapping_request_dropped' })
    return
  }
  processingRequest = true
  
  try {
    const request = JSON.parse(line)
    await handleRequest(request)
  } catch (error) {
    emit({ type: 'result', success: false, error: String(error?.message || error), transport_details: { transport_mode: 'playwright' } })
  } finally {
    processingRequest = false
  }
})

rl.on('close', async () => {
  if (globalContext) {
    await globalContext.close().catch(() => {})
  }
  process.exit(0)
})

async function handleRequest(request) {
  const transport = request.transport || {}
  const browser = transport.browser || {}
  const browserTypeName = getBrowserTypeName(browser)
  const targetUrl = request.url || 'https://chatgpt.com/'

  emit({ type: 'status', stage: 'processing_request', transport_mode: 'playwright', browser_type: browserTypeName })

  try {
    if (!globalContext) {
      const launchOptions = {
        headless: Boolean(browser.headless),
        viewport: { width: 1440, height: 960 },
        args: buildLaunchArgs(browser),
        ignoreDefaultArgs: ['--enable-automation'],
      }

      if (browser.executable_path) {
        launchOptions.executablePath = browser.executable_path
      }

      const browserType = getBrowserType(browser)
      
      emit({
        type: 'status',
        stage: 'launching_persistent_context',
        browser_type: browserTypeName,
        executable_path: launchOptions.executablePath || 'playwright-default'
      })

      globalContext = await browserType.launchPersistentContext(browser.user_data_dir, launchOptions)
      globalPage = globalContext.pages()[0] || await globalContext.newPage()
      
      globalPage.on('websocket', (ws) => emit({ type: 'status', stage: 'websocket_created', websocket_url: ws.url() }))
    }

    await ensureChatPage(globalPage, targetUrl)
    
    if (!request.new_conversation && request.remote_conversation_id) {
      await ensureRemoteConversation(globalPage, targetUrl, request.remote_conversation_id)
    }
    
    emit({ type: 'status', stage: 'page_loaded', url: globalPage.url() })
    const ui = await detectLoggedInUi(globalPage)
    emit({ type: 'status', stage: 'ui_detected', ui })
    if (!ui.loggedInLikely) {
      emit({ type: 'result', success: false, error: 'ui_not_logged_in', transport_details: { ui } })
      return
    }

    const baselineAssistant = await getAssistantSnapshot(globalPage)
    emit({ type: 'status', stage: 'sending_prompt', baseline_assistant: baselineAssistant })
    await waitForConversationIdle(globalPage, 2500)
    await sendPrompt(globalPage, request.message, targetUrl, Boolean(request.new_conversation))
    emit({ type: 'status', stage: 'awaiting_assistant_stream', baseline_assistant: baselineAssistant })
    const streamResult = await streamAssistantText(globalPage, Number(request.capture_timeout_ms || 120000), baselineAssistant)
    const text = streamResult.text
    const finalUi = await detectLoggedInUi(globalPage)
    if (streamResult.timedOut) {
      emit({ type: 'status', stage: 'assistant_stream_timeout', placeholder_only: streamResult.placeholderOnly, text_preview: String(text || '').slice(0, 200) })
    }
    
    emit({
      type: 'result',
      success: Boolean(text) && !streamResult.placeholderOnly,
      text,
      remote_conversation_id: globalPage.url().includes('/c/') ? globalPage.url().split('/c/')[1]?.split(/[?#]/)[0] ?? null : null,
      remote_parent_message_id: null,
      transport_details: {
        ui_before_send: ui,
        ui_after_send: finalUi,
        transport_mode: 'playwright',
        browser_type: browserTypeName,
        browser: {
          user_data_dir: browser.user_data_dir,
          executable_path_present: Boolean(browser.executable_path),
        },
        timed_out: streamResult.timedOut,
        placeholder_only: streamResult.placeholderOnly,
      },
      verification_hints: {
        remote_conversation_exists: Boolean(text) && !streamResult.placeholderOnly,
        effective_transport_mode: 'playwright',
      },
      error: streamResult.placeholderOnly ? 'assistant_response_placeholder_only' : undefined,
    })
  } catch (err) {
    emit({ type: 'result', success: false, error: String(err?.message || err), transport_details: { transport_mode: 'playwright' } })
  }
}
