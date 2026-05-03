#!/usr/bin/env node
import fsSync from 'node:fs'
import fs from 'node:fs/promises'
import process from 'node:process'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { createRequire } from 'node:module'
import { chromium, firefox, webkit } from 'playwright'

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

  // Chromium args — disable automation detection flags
  return [
    '--password-store=basic',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-blink-features=AutomationControlled',
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
  const browserTypeName = getBrowserTypeName(browser)

  if (browserTypeName !== 'chromium') {
    throw new Error('startDebugBrowser/CDP auto-start is only supported for Chromium')
  }

  const executable = resolveExecutablePath(browser)

  emit({
    type: 'status',
    stage: 'starting_debug_browser_resolved',
    executable,
    browser_type: browserTypeName,
    playwright_version: getPlaywrightVersion(),
    playwright_browsers_path: process.env.PLAYWRIGHT_BROWSERS_PATH || null,
  })

  const args = [
    `--remote-debugging-port=${browser.debugging_port || 9222}`,
    '--password-store=basic',
    '--no-first-run',
    '--no-default-browser-check',
  ]

  if (browser.profile_directory) {
    args.push(`--profile-directory=${browser.profile_directory}`)
  }

  if (browser.user_data_dir) {
    args.push(`--user-data-dir=${browser.user_data_dir}`)
  }

  args.push(targetUrl || 'https://chatgpt.com/')

  const child = spawn(executable, args, {
    detached: true,
    stdio: 'ignore',
    env: {
      ...process.env,
      OBJC_DISABLE_INITIALIZE_FORK_SAFETY: process.env.OBJC_DISABLE_INITIALIZE_FORK_SAFETY || 'YES',
    },
  })

  child.unref()
}

async function pickBestExistingPage(contexts, targetUrl) {
  const normalizedTarget = `${targetUrl}`.replace(/\/$/, '')
  let fallbackPage = null
  let fallbackContext = null
  for (const context of contexts) {
    for (const page of context.pages()) {
      const url = page.url()
      if (!fallbackPage) {
        fallbackPage = page
        fallbackContext = context
      }
      if (url.startsWith('https://chatgpt.com/c/')) {
        return { page, context, reason: 'existing_conversation_page' }
      }
      if (url.replace(/\/$/, '') === normalizedTarget) {
        return { page, context, reason: 'existing_home_page' }
      }
    }
  }
  if (fallbackPage) return { page: fallbackPage, context: fallbackContext, reason: 'fallback_existing_page' }
  return null
}

async function openOrAttachBrowser(browser, targetUrl) {
  const browserTypeName = getBrowserTypeName(browser)
  const browserType = getBrowserType(browser)

  // CDP is Chromium-only
  if (browserTypeName !== 'chromium' && browser.connect_over_cdp) {
    throw new Error('connect_over_cdp is only supported for Chromium. Disable CDP when using Firefox.')
  }

  if (browser.connect_over_cdp) {
    const cdpUrl = browser.cdp_url || `http://127.0.0.1:${browser.debugging_port || 9222}`
    emit({ type: 'status', stage: 'connecting_over_cdp', cdp_url: cdpUrl, browser_type: browserTypeName })
    let ready = await waitForCdp(cdpUrl, 2000)
    if (!ready && browser.auto_start_debug_browser) {
      emit({ type: 'status', stage: 'starting_debug_browser', cdp_url: cdpUrl })
      await startDebugBrowser(browser, targetUrl)
      ready = await waitForCdp(cdpUrl, 30000)
    }
    if (!ready) throw new Error(`cdp_unavailable:${cdpUrl}`)
    const attachedBrowser = await chromium.connectOverCDP(cdpUrl)
    const contexts = attachedBrowser.contexts()
    const picked = await pickBestExistingPage(contexts, targetUrl)
    if (picked) {
      emit({ type: 'status', stage: 'attached_existing_page', reason: picked.reason, current_url: picked.page.url() })
      return { browserHandle: attachedBrowser, context: picked.context, page: picked.page, attachedViaCdp: true }
    }
    const context = contexts[0]
    if (!context) throw new Error('No browser context was available after CDP attach')
    const page = await context.newPage()
    emit({ type: 'status', stage: 'attached_new_page_created', current_url: page.url() })
    return { browserHandle: attachedBrowser, context, page, attachedViaCdp: true }
  }

  // Persistent context launch (works for all browser types)
  const launchOptions = {
    headless: Boolean(browser.headless),
    viewport: { width: 1440, height: 960 },
    args: buildLaunchArgs(browser),
  }

  if (browser.executable_path) {
    launchOptions.executablePath = browser.executable_path
  }

  // `channel` is Chromium-only. Do not use channel for Firefox.
  if (browserTypeName === 'chromium' && browser.channel) {
    launchOptions.channel = browser.channel
  }

  // Firefox stealth prefs (only needed if using Playwright's patched Firefox)
  if (browserTypeName === 'firefox' && !launchOptions.executablePath) {
    launchOptions.firefoxUserPrefs = {
      'dom.webdriver.enabled': false,
      'marionette.enabled': false,
    }
  }

  emit({
    type: 'status',
    stage: 'launching_persistent_context',
    browser_type: browserTypeName,
    executable_path: launchOptions.executablePath || 'playwright-default',
    playwright_version: getPlaywrightVersion(),
    user_data_dir: browser.user_data_dir || null,
    args: launchOptions.args,
  })

  const context = await browserType.launchPersistentContext(browser.user_data_dir, launchOptions)
  const page = context.pages()[0] || await context.newPage()

  return {
    browserHandle: null,
    context,
    page,
    attachedViaCdp: false,
  }
}

function buildConversationUrl(targetUrl, remoteConversationId) {
  const base = new URL(targetUrl)
  return `${base.origin}/c/${remoteConversationId}`
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

async function main() {
  const request = await readStdinJson()
  const transport = request.transport || {}
  const browser = transport.browser || {}
  const browserTypeName = getBrowserTypeName(browser)
  emit({ type: 'status', stage: browser.connect_over_cdp ? 'opening_browser_via_cdp' : 'launching_browser', transport_mode: 'playwright', browser_type: browserTypeName })
  const { browserHandle, context, page, attachedViaCdp } = await openOrAttachBrowser(browser, request.url || 'https://chatgpt.com/')
  try {
    page.on('websocket', (ws) => emit({ type: 'status', stage: 'websocket_created', websocket_url: ws.url() }))
    await ensureChatPage(page, request.url || 'https://chatgpt.com/')
    if (!request.new_conversation && request.remote_conversation_id) {
      await ensureRemoteConversation(page, request.url || 'https://chatgpt.com/', request.remote_conversation_id)
    }
    emit({ type: 'status', stage: 'page_loaded', url: page.url() })
    const ui = await detectLoggedInUi(page)
    emit({ type: 'status', stage: 'ui_detected', ui })
    if (!ui.loggedInLikely) {
      emit({ type: 'result', success: false, error: 'ui_not_logged_in', transport_details: { ui } })
      return
    }

    const baselineAssistant = await getAssistantSnapshot(page)
    emit({ type: 'status', stage: 'sending_prompt', baseline_assistant: baselineAssistant })
    await waitForConversationIdle(page, 2500)
    await sendPrompt(page, request.message, request.url || 'https://chatgpt.com/', Boolean(request.new_conversation))
    emit({ type: 'status', stage: 'awaiting_assistant_stream', baseline_assistant: baselineAssistant })
    const streamResult = await streamAssistantText(page, Number(request.capture_timeout_ms || 120000), baselineAssistant)
    const text = streamResult.text
    const finalUi = await detectLoggedInUi(page)
    if (streamResult.timedOut) {
      emit({ type: 'status', stage: 'assistant_stream_timeout', placeholder_only: streamResult.placeholderOnly, text_preview: String(text || '').slice(0, 200) })
    }
    emit({
      type: 'result',
      success: Boolean(text) && !streamResult.placeholderOnly,
      text,
      remote_conversation_id: page.url().includes('/c/') ? page.url().split('/c/')[1]?.split(/[?#]/)[0] ?? null : null,
      remote_parent_message_id: null,
      transport_details: {
        ui_before_send: ui,
        ui_after_send: finalUi,
        transport_mode: 'playwright',
        browser_type: browserTypeName,
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
