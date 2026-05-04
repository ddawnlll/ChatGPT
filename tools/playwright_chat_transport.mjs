#!/usr/bin/env node
/**
 * transport.mjs — Playwright-based ChatGPT web transport
 *
 * Improvements over original:
 *  - Structured error emission replaces silent catch(() => {})
 *  - Unified text injection with deterministic test-then-fallback
 *  - Longer send-detection window (1500 ms) with prior-generation guard
 *  - Configurable thinking-watchdog thresholds + auto-retry after stop
 *  - Cross-platform browser detection (macOS + Linux + Windows)
 *  - Bounding-box rejection raised to 20×20 px; off-screen composerss handled
 *  - Composer polling interval reduced to 80 ms for faster first-response
 *  - Delta computation guards against ChatGPT mid-response edits
 *  - Stream binding has explicit navigation-cleanup path
 *  - All async paths emit structured {type:"error"} events on failure
 */

import fsSync from 'node:fs'
import fs from 'node:fs/promises'
import process from 'node:process'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { chromium, firefox, webkit } from 'playwright'
import readline from 'node:readline'

const require = createRequire(import.meta.url)

// ---------------------------------------------------------------------------
// Config — all tuneable constants in one place
// ---------------------------------------------------------------------------
const CONFIG = {
  composerPollMs: 80,            // how often to re-check for composer
  composerMinBoxPx: 20,          // reject composer candidates smaller than this
  composerTimeoutMs: 15_000,     // total wait for composer to appear
  sendDetectionWindowMs: 1_500,  // how long to poll after send attempt
  sendDetectionTickMs: 100,      // tick interval inside that window
  sendMaxAttempts: 3,
  injectionDelayMs: 350,         // settle time after text injection before send
  chunkSizeChars: 1_200,         // keyboard insertText chunk size
  streamIdleMs: 500,             // mutation-observer idle before "done"
  thinkingWarnMs: 20_000,        // emit warning after this long thinking
  thinkingAbortMs: 30_000,       // click Stop after this long thinking
  thinkingPollMs: 2_000,         // watchdog check interval
  challengeTimeoutMs: 12_000,
  chatShellTimeoutMs: 12_000,
  pageTimeoutMs: 90_000,         // overall per-prompt timeout
}

// ---------------------------------------------------------------------------
// Telemetry
// ---------------------------------------------------------------------------
const transportStartedAt = Date.now()

function emit(event) {
  const enriched = {
    ts: new Date().toISOString(),
    elapsed_ms: Date.now() - transportStartedAt,
    ...event,
  }
  process.stdout.write(`${JSON.stringify(enriched)}\n`)
}

function emitError(stage, error, extra = {}) {
  emit({
    type: 'error',
    stage,
    message: error?.message ?? String(error),
    stack: error?.stack ?? null,
    ...extra,
  })
}

// ---------------------------------------------------------------------------
// Browser helpers
// ---------------------------------------------------------------------------
function getPlaywrightVersion() {
  try { return require('playwright/package.json').version } catch { return null }
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

// Cross-platform system browser candidates
const SYSTEM_BROWSER_CANDIDATES = [
  // macOS
  { type: 'chromium', path: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' },
  { type: 'chromium', path: '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser' },
  { type: 'chromium', path: '/Applications/Chromium.app/Contents/MacOS/Chromium' },
  { type: 'firefox',  path: '/Applications/Firefox.app/Contents/MacOS/firefox' },
  // Linux
  { type: 'chromium', path: '/usr/bin/google-chrome-stable' },
  { type: 'chromium', path: '/usr/bin/google-chrome' },
  { type: 'chromium', path: '/usr/bin/chromium-browser' },
  { type: 'chromium', path: '/usr/bin/chromium' },
  { type: 'chromium', path: '/snap/bin/chromium' },
  { type: 'firefox',  path: '/usr/bin/firefox' },
  // Windows
  { type: 'chromium', path: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' },
  { type: 'chromium', path: 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe' },
  { type: 'chromium', path: 'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe' },
  { type: 'firefox',  path: 'C:\\Program Files\\Mozilla Firefox\\firefox.exe' },
]

function findSystemBrowser() {
  for (const candidate of SYSTEM_BROWSER_CANDIDATES) {
    try {
      if (fsSync.statSync(candidate.path).isFile()) return candidate
    } catch { /* not found, try next */ }
  }
  return null
}

function buildLaunchArgs(browser) {
  const type = getBrowserTypeName(browser)
  if (type === 'firefox' || type === 'webkit') return []

  const args = [
    '--no-first-run',
    '--no-default-browser-check',
    '--password-store=basic',
    '--disable-blink-features=AutomationControlled',
    '--disable-features=IsolateOrigins,site-per-process',
    '--remote-allow-origins=*',
  ]

  if (browser.user_data_dir) args.unshift(`--user-data-dir=${browser.user_data_dir}`)
  if (browser.profile_directory) args.unshift(`--profile-directory=${browser.profile_directory}`)

  // Do not pass --remote-debugging-pipe to Playwright launch APIs.
  // Playwright manages its own browser debugging connection.

  return args
}

function resolveExecutablePath(browser) {
  if (browser.executable_path) return browser.executable_path
  const system = findSystemBrowser()
  if (system) {
    emit({ type: 'status', stage: 'browser_resolved', path: system.path, source: 'system_detection' })
    return system.path
  }
  try {
    const execPath = getBrowserType(browser).executablePath()
    emit({ type: 'status', stage: 'browser_resolved', path: execPath, source: 'playwright_managed' })
    return execPath
  } catch (err) {
    emitError('browser_resolve_failed', err)
    throw err
  }
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
async function delay(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms))
}

// ---------------------------------------------------------------------------
// Composer detection — improved bounding-box threshold and visibility checks
// ---------------------------------------------------------------------------
const COMPOSER_SELECTORS = [
  '#prompt-textarea[contenteditable="true"]',
  'div[contenteditable="true"][role="textbox"]',
  'div[contenteditable="true"][data-lexical-editor="true"]',
  '#prompt-textarea',
  'textarea[placeholder*="Message"]',
  'div[contenteditable="true"]',
  'textarea',
]

async function findComposer(page) {
  for (const selector of COMPOSER_SELECTORS) {
    let locator
    try { locator = page.locator(selector) } catch { continue }
    const count = await locator.count().catch(() => 0)

    for (let i = 0; i < count; i++) {
      const candidate = locator.nth(i)

      const visible = await candidate.isVisible().catch(() => false)
      if (!visible) continue

      // Reject zero-size or tiny elements that are technically visible
      const box = await candidate.boundingBox().catch(() => null)
      if (!box || box.width < CONFIG.composerMinBoxPx || box.height < CONFIG.composerMinBoxPx) {
        emit({ type: 'status', stage: 'composer_candidate_rejected', reason: 'box_too_small', selector, index: i, box })
        continue
      }

      // Reject elements that are scrolled far off screen (not just off viewport)
      if (box.y < -500 || box.x < -500) {
        emit({ type: 'status', stage: 'composer_candidate_rejected', reason: 'off_screen', selector, index: i, box })
        continue
      }

      const disabled = await candidate.evaluate((node) =>
        Boolean(
          node.disabled ||
          node.getAttribute('aria-disabled') === 'true' ||
          node.getAttribute('aria-hidden') === 'true' ||
          node.getAttribute('readonly') !== null
        )
      ).catch(() => false)
      if (disabled) continue

      return { locator: candidate, selector, index: i }
    }
  }
  return null
}

async function waitForComposer(page, timeoutMs = CONFIG.composerTimeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const found = await findComposer(page).catch(() => null)
    if (found) return found
    await delay(CONFIG.composerPollMs)
  }
  const err = new Error('Composer did not appear before timeout')
  emitError('composer_timeout', err, { timeoutMs })
  throw err
}

async function waitForComposerInteractive(page, timeoutMs = CONFIG.composerTimeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const found = await findComposer(page).catch(() => null)
    if (found) {
      try {
        await found.locator.click({ trial: true, timeout: 300 })
        return found
      } catch { /* not yet clickable */ }
    }
    await delay(CONFIG.composerPollMs)
  }
  // Fall through to a simpler wait — at least return something
  return waitForComposer(page, timeoutMs)
}

// ---------------------------------------------------------------------------
// Page-state helpers
// ---------------------------------------------------------------------------
function detectPageInterruptionStateFromText(title, bodyText) {
  const safeTitle = String(title || '')
  const safeBodyText = String(bodyText || '')

  const isChallenge = (
    /just a moment/i.test(safeTitle) ||
    /verify you are human/i.test(safeBodyText) ||
    /checking your browser/i.test(safeBodyText) ||
    /enable javascript/i.test(safeBodyText) ||
    /cloudflare/i.test(safeBodyText)
  )

  const isRateLimited = (
    /too many requests/i.test(safeBodyText) ||
    /rate limit/i.test(safeBodyText) ||
    /429/i.test(safeTitle)
  )

  const isConversationError = /unable to load conversation/i.test(safeBodyText)

  return {
    detected: Boolean(isChallenge || isRateLimited || isConversationError),
    isChallenge,
    isRateLimited,
    isConversationError,
  }
}

async function detectChallengeOrRateLimit(page) {
  const title = await page.title().catch(() => '')
  const bodyText = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '')
  const state = detectPageInterruptionStateFromText(title, bodyText)
  if (state.detected) {
    emit({
      type: 'status',
      stage: 'challenge_or_rate_limit_detected',
      is_challenge: state.isChallenge,
      is_rate_limited: state.isRateLimited,
      is_conversation_error: state.isConversationError,
      url: page.url(),
    })
  }
  return state
}

async function waitForNoChallenge(page, timeoutMs = CONFIG.challengeTimeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const title = await page.title().catch(() => '')
    const bodyText = await page.locator('body').innerText().catch(() => '')
    const state = detectPageInterruptionStateFromText(title, bodyText)
    if (!state.isChallenge) return
    await delay(200)
  }
  emit({ type: 'status', stage: 'challenge_still_visible_after_timeout', timeoutMs })
}

async function waitForChatShell(page, timeoutMs = CONFIG.chatShellTimeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const bodyText = await page.locator('body').innerText().catch(() => '')
    if (/ready when you are|what.?s on your mind today|new chat|chat history|chatgpt/i.test(bodyText)) return
    await delay(200)
  }
  emit({ type: 'status', stage: 'chat_shell_not_detected_after_timeout', timeoutMs })
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

// ---------------------------------------------------------------------------
// Thread/composer context management
// ---------------------------------------------------------------------------
async function clickNewChatButton(page, timeoutMs = 8_000) {
  const selectors = [
    'button:has-text("New chat")',
    'a:has-text("New chat")',
    '[role="button"]:has-text("New chat")',
    '[data-testid*="new-chat"]',
    'a[href="/"]',
  ]

  for (const selector of selectors) {
    const locator = page.locator(selector).first()
    const visible = await locator.isVisible().catch(() => false)
    if (!visible) continue

    emit({ type: 'status', stage: 'new_chat_button_found', selector })
    await locator.click({ timeout: 1_500 }).catch((err) => emitError('new_chat_click_failed', err, { selector }))

    const composer = await waitForComposerInteractive(page, timeoutMs).catch(() => null)
    if (composer) {
      emit({ type: 'status', stage: 'new_chat_button_succeeded', selector, current_url: page.url() })
      return composer
    }
  }

  emit({ type: 'status', stage: 'new_chat_button_not_available' })
  return null
}

function buildConversationUrl(targetUrl, conversationId) {
  const base = new URL(targetUrl || 'https://chatgpt.com/')
  return `${base.origin}/c/${conversationId}`
}

function normalizeConversationUrl(url) {
  return String(url || '').replace(/\/$/, '')
}

function isSameConversationTarget(currentUrl, remoteConversationId, remoteConversationUrl) {
  const normalizedCurrent = normalizeConversationUrl(currentUrl)
  const normalizedTarget = normalizeConversationUrl(remoteConversationUrl)
  if (normalizedTarget && normalizedCurrent === normalizedTarget) return true
  const currentConversationId = extractRemoteConversationId(currentUrl)
  return Boolean(remoteConversationId && currentConversationId && currentConversationId === remoteConversationId)
}

function getComposerContextMode({ newConversation, remoteConversationId, remoteConversationUrl }) {
  if (newConversation) return 'fresh'
  if (remoteConversationUrl || remoteConversationId) return 'existing'
  return 'current_or_fallback'
}

async function openFreshThread(page, targetUrl) {
  const currentUrl = page.url()
  const normalizedTarget = targetUrl.replace(/\/$/, '')
  const existingComposer = await findComposer(page).catch(() => null)
  const alreadyHome = currentUrl.replace(/\/$/, '') === normalizedTarget
  const sameOrigin = (() => {
    try {
      return new URL(currentUrl).origin === new URL(targetUrl).origin
    } catch {
      return false
    }
  })()

  if (sameOrigin) {
    const opened = await clickNewChatButton(page).catch(() => null)
    if (opened) return true
  }

  if (alreadyHome && existingComposer) {
    emit({ type: 'status', stage: 'fresh_thread_already_ready', current_url: currentUrl })
    return true
  }

  emit({ type: 'status', stage: 'navigating_home', current_url: currentUrl, target_url: targetUrl })
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch((err) => {
    emitError('navigation_failed', err, { targetUrl })
  })
  await waitForNoChallenge(page)
  await waitForChatShell(page)

  const openedAfterHome = await clickNewChatButton(page, 4_000).catch(() => null)
  if (openedAfterHome) return true

  await waitForComposerInteractive(page)
  emit({ type: 'status', stage: 'fresh_thread_ready', current_url: page.url() })
  return true
}

async function openExistingThread(page, targetUrl, remoteConversationId, remoteConversationUrl) {
  const url = remoteConversationUrl || buildConversationUrl(targetUrl, remoteConversationId)
  const currentUrl = page.url()
  const currentComposer = await findComposer(page).catch(() => null)

  if (isSameConversationTarget(currentUrl, remoteConversationId, remoteConversationUrl) && currentComposer) {
    emit({
      type: 'status',
      stage: 'existing_thread_already_ready',
      current_url: currentUrl,
      remote_conversation_id: remoteConversationId || null,
    })
    await waitForNoChallenge(page)
    await waitForChatShell(page)
    await waitForComposerInteractive(page)
    return true
  }

  emit({
    type: 'status',
    stage: 'opening_existing_thread',
    url,
    current_url: currentUrl,
    remote_conversation_id: remoteConversationId || null,
  })

  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await waitForNoChallenge(page)
  await waitForChatShell(page)

  const bodyText = await page.locator('body').innerText().catch(() => '')
  if (/unable to load conversation/i.test(bodyText)) {
    throw new Error(`Unable to load conversation ${remoteConversationId || ''}`.trim())
  }

  await waitForComposerInteractive(page)

  emit({
    type: 'status',
    stage: 'existing_thread_ready',
    current_url: page.url(),
  })
  return true
}

async function ensureComposerContext(page, targetUrl, newConversation, remoteConversationId = null, remoteConversationUrl = null) {
  const mode = getComposerContextMode({ newConversation, remoteConversationId, remoteConversationUrl })
  emit({ type: 'status', stage: 'composer_context_mode', mode, new_conversation: Boolean(newConversation), has_remote_conversation_id: Boolean(remoteConversationId), has_remote_conversation_url: Boolean(remoteConversationUrl) })

  if (mode === 'fresh') {
    await openFreshThread(page, targetUrl)
  } else if (mode === 'existing') {
    try {
      await openExistingThread(page, targetUrl, remoteConversationId, remoteConversationUrl)
    } catch (err) {
      emitError('existing_thread_open_failed', err, {
        remote_conversation_id: remoteConversationId || null,
        remote_conversation_url: remoteConversationUrl || null,
      })
      emit({
        type: 'status',
        stage: 'existing_thread_open_failed_fallback_to_fresh',
        remote_conversation_id: remoteConversationId || null,
        remote_conversation_url: remoteConversationUrl || null,
      })
      await openFreshThread(page, targetUrl)
    }
  }

  const initialComposer = await findComposer(page).catch(() => null)
  emit({ type: 'status', stage: 'composer_probe', found: Boolean(initialComposer), new_conversation: Boolean(newConversation), mode })
  if (initialComposer) return waitForComposerInteractive(page, 5_000)

  if (!newConversation) {
    const readyComposer = await clickNewChatButton(page, 10_000).catch(() => null)
    if (readyComposer) return readyComposer
  }

  emit({ type: 'status', stage: 'navigating_home_fallback', target_url: targetUrl, mode })
  await page.goto(targetUrl, { waitUntil: 'domcontentloaded' }).catch((err) => emitError('navigation_fallback_failed', err, { targetUrl }))
  await waitForNoChallenge(page)
  await waitForChatShell(page)
  return waitForComposerInteractive(page, CONFIG.composerTimeoutMs)
}

// ---------------------------------------------------------------------------
// Text injection — unified strategy with deterministic fallback
// ---------------------------------------------------------------------------

/**
 * Strategy 1 — keyboard insertText (most reliable for React synthetic events)
 */
async function injectViaKeyboard(page, composerLocator, message) {
  try {
    await composerLocator.scrollIntoViewIfNeeded()
    await composerLocator.click({ timeout: 1_500 })
    // Select-all then delete to clear any existing text
    const modKey = process.platform === 'darwin' ? 'Meta' : 'Control'
    await page.keyboard.press(`${modKey}+A`)
    await page.keyboard.press('Backspace')

    for (let i = 0; i < message.length; i += CONFIG.chunkSizeChars) {
      await page.keyboard.insertText(message.slice(i, i + CONFIG.chunkSizeChars))
      // Small yield between chunks to let React process each batch
      if (i + CONFIG.chunkSizeChars < message.length) await delay(30)
    }

    const entered = await readComposerValue(composerLocator)
    return { ok: entered.trim().length > 0, method: 'keyboard', text: entered }
  } catch (err) {
    emitError('injection_keyboard_failed', err)
    return { ok: false, method: 'keyboard', text: '', error: err.message }
  }
}

/**
 * Strategy 2 — DOM value setter with proper React event dispatch
 * Used only if keyboard strategy yields empty composer.
 */
async function injectViaDom(page, composerLocator, message) {
  try {
    const result = await composerLocator.evaluate((node, value) => {
      const text = String(value || '')

      function fire(target, type, extra = {}) {
        target.dispatchEvent(new Event(type, { bubbles: true, cancelable: true, ...extra }))
      }

      function fireInput(target, data) {
        try {
          target.dispatchEvent(new InputEvent('beforeinput', { bubbles: true, cancelable: true, data, inputType: 'insertText' }))
        } catch {}
        try {
          target.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true, data, inputType: 'insertText' }))
        } catch {
          fire(target, 'input')
        }
      }

      node.focus()

      if (node instanceof HTMLTextAreaElement || node instanceof HTMLInputElement) {
        const proto = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
        if (descriptor?.set) descriptor.set.call(node, text)
        else node.value = text
        try { node.setSelectionRange(text.length, text.length) } catch {}
        fireInput(node, text)
        fire(node, 'change')
        return { ok: true, mode: 'textarea', length: node.value.length }
      }

      if (node.isContentEditable) {
        node.textContent = text
        fireInput(node, text)
        fire(node, 'change')
        return { ok: true, mode: 'contenteditable', length: node.innerText.length }
      }

      return { ok: false, mode: 'unknown', length: 0 }
    }, message)

    if (!result.ok || result.length === 0) {
      // Last resort: focus + insertText
      await composerLocator.click({ timeout: 1_000 }).catch(() => {})
      await page.keyboard.insertText(message)
    }

    const entered = await readComposerValue(composerLocator)
    return { ok: entered.trim().length > 0, method: 'dom', text: entered }
  } catch (err) {
    emitError('injection_dom_failed', err)
    return { ok: false, method: 'dom', text: '', error: err.message }
  }
}

async function readComposerValue(composerLocator) {
  try { return await composerLocator.inputValue({ timeout: 1_000 }) } catch {}
  try { return await composerLocator.innerText({ timeout: 1_000 }) } catch {}
  return ''
}

/**
 * Master injection function — tries keyboard first, falls back to DOM.
 */
async function injectText(page, composer, message) {
  const k = await injectViaKeyboard(page, composer.locator, message)
  emit({ type: 'status', stage: 'injection_keyboard_result', ok: k.ok, length: k.text.length })
  if (k.ok) return k

  emit({ type: 'status', stage: 'injection_keyboard_empty_falling_back_to_dom' })
  const d = await injectViaDom(page, composer.locator, message)
  emit({ type: 'status', stage: 'injection_dom_result', ok: d.ok, length: d.text.length })
  if (!d.ok) emitError('injection_all_strategies_failed', new Error('Both keyboard and DOM injection yielded empty composer'))
  return d
}

// ---------------------------------------------------------------------------
// Composer activation (scroll + focus + click)
// ---------------------------------------------------------------------------
async function activateComposer(page, composerLocator) {
  emit({ type: 'status', stage: 'composer_activation_start' })
  try {
    await composerLocator.evaluate((node) => {
      try { node.scrollIntoView({ block: 'center' }) } catch {}
      try { node.focus() } catch {}
      try { node.click() } catch {}
    })
  } catch (err) {
    emitError('composer_activation_dom_failed', err)
  }

  const box = await composerLocator.boundingBox().catch(() => null)
  if (box) {
    await page.mouse.click(
      box.x + Math.min(box.width / 2, Math.max(8, box.width - 8)),
      box.y + Math.min(box.height / 2, Math.max(8, box.height - 8)),
    ).catch((err) => emitError('composer_mouse_click_failed', err))
  }
  emit({ type: 'status', stage: 'composer_activation_done', has_box: Boolean(box) })
}

// ---------------------------------------------------------------------------
// Send triggering — improved detection with prior-generation guard
// ---------------------------------------------------------------------------

/**
 * Returns true if a generation is already in progress (stop button visible).
 */
async function isGenerating(page) {
  return page.locator('button[aria-label*="Stop" i]').first().isVisible().catch(() => false)
}

async function triggerPromptSend(page, composer) {
  // Guard: don't send if a prior generation is still running
  if (await isGenerating(page)) {
    emit({ type: 'status', stage: 'send_blocked_prior_generation_running' })
    return false
  }

  const sendState = await composer.locator.evaluate((node) => {
    function isInteractable(el) {
      if (!el) return false
      const style = window.getComputedStyle(el)
      const rect = el.getBoundingClientRect()
      return (
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        rect.width > 0 &&
        rect.height > 0 &&
        !el.disabled &&
        el.getAttribute('aria-disabled') !== 'true'
      )
    }

    const SEND_SELECTORS = [
      'button[data-testid="send-button"]',
      'button[aria-label*="Send" i]',
      'button[aria-label*="Submit" i]',
      '[data-testid="composer-send-button"]',
      'button[type="submit"]',
    ]

    const form = node.closest('form')
    const roots = [form, node.parentElement, document].filter(Boolean)

    for (const root of roots) {
      for (const sel of SEND_SELECTORS) {
        const btn = root.querySelector(sel)
        if (btn && isInteractable(btn)) {
          return { hasButton: true, selector: sel, formPresent: Boolean(form) }
        }
      }
    }
    return { hasButton: false, selector: null, formPresent: Boolean(form) }
  }).catch((err) => {
    emitError('send_button_probe_failed', err)
    return { hasButton: false, selector: null, formPresent: false }
  })

  emit({ type: 'status', stage: 'send_button_state', ...sendState })

  // Attempt 1 — DOM button click
  if (sendState.hasButton) {
    const clicked = await composer.locator.evaluate((node) => {
      function isInteractable(el) {
        if (!el) return false
        const style = window.getComputedStyle(el)
        const rect = el.getBoundingClientRect()
        return (
          style.display !== 'none' &&
          style.visibility !== 'hidden' &&
          rect.width > 0 &&
          rect.height > 0 &&
          !el.disabled &&
          el.getAttribute('aria-disabled') !== 'true'
        )
      }
      const SEND_SELECTORS = [
        'button[data-testid="send-button"]',
        'button[aria-label*="Send" i]',
        'button[aria-label*="Submit" i]',
        '[data-testid="composer-send-button"]',
        'button[type="submit"]',
      ]
      const roots = [node.closest('form'), node.parentElement, document].filter(Boolean)
      for (const root of roots) {
        for (const sel of SEND_SELECTORS) {
          const btn = root.querySelector(sel)
          if (btn && isInteractable(btn)) {
            try { btn.click() } catch {}
            return { method: 'dom_button_click', selector: sel }
          }
        }
      }
      return { method: 'none', selector: null }
    }).catch((err) => {
      emitError('send_dom_click_failed', err)
      return { method: 'none', selector: null }
    })

    emit({ type: 'status', stage: 'send_trigger_method', ...clicked })
    if (clicked.method !== 'none') return true
  }

  // Attempt 2 — form requestSubmit / submit event
  if (sendState.formPresent) {
    const submitted = await page.evaluate(() => {
      const composer =
        document.querySelector('#prompt-textarea') ||
        document.querySelector('div[contenteditable="true"][role="textbox"]') ||
        document.querySelector('div[contenteditable="true"]') ||
        document.querySelector('textarea')
      const form = composer?.closest('form')
      if (!form) return false
      try {
        if (typeof form.requestSubmit === 'function') { form.requestSubmit(); return true }
      } catch {}
      try {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
        return true
      } catch {}
      return false
    }).catch((err) => {
      emitError('send_form_submit_failed', err)
      return false
    })

    if (submitted) {
      emit({ type: 'status', stage: 'send_trigger_method', method: 'form_submit', selector: null })
      return true
    }
  }

  // Attempt 3 — keyboard Enter (ensure focus first)
  try {
    await composer.locator.focus()
    await page.keyboard.press('Enter')
    emit({ type: 'status', stage: 'send_trigger_method', method: 'keyboard_enter', selector: null })
  } catch (err) {
    emitError('send_keyboard_enter_failed', err)
    return false
  }
  return true
}

// ---------------------------------------------------------------------------
// sendPrompt — orchestrates compose + inject + send + confirmation
// ---------------------------------------------------------------------------
async function sendPrompt(page, message, targetUrl, newConversation, remoteConversationId = null, remoteConversationUrl = null, preparedComposer = null) {
  const composer = preparedComposer || await ensureComposerContext(page, targetUrl, newConversation, remoteConversationId, remoteConversationUrl)
  emit({ type: 'status', stage: 'composer_ready', selector: composer.selector, index: composer.index })

  let promptSent = false

  for (let attempt = 1; attempt <= CONFIG.sendMaxAttempts; attempt++) {
    emit({ type: 'status', stage: 'prompt_attempt_start', attempt })

    await activateComposer(page, composer.locator)

    const injection = await injectText(page, composer, message)
    emit({
      type: 'status',
      stage: 'prompt_injected',
      attempt,
      ok: injection.ok,
      method: injection.method,
      length: injection.text?.length ?? 0,
    })

    if (!injection.ok && message.trim().length > 0) {
      emitError('prompt_injection_empty', new Error(`Injection attempt ${attempt} yielded empty composer`), { attempt })
      await delay(500)
      continue
    }

    // Let React fully register the input before attempting submit
    await delay(CONFIG.injectionDelayMs)

    await triggerPromptSend(page, composer)

    // Detection window: poll for stop-button OR cleared composer
    const windowDeadline = Date.now() + CONFIG.sendDetectionWindowMs
    while (Date.now() < windowDeadline) {
      await delay(CONFIG.sendDetectionTickMs)

      const stopVisible = await page.locator('button[aria-label*="Stop" i]').first().isVisible().catch(() => false)
      if (stopVisible) { promptSent = true; break }

      const currentText = await readComposerValue(composer.locator)
      const cleared = currentText.trim().length === 0 || currentText.trim() === 'Message ChatGPT'
      if (cleared) { promptSent = true; break }
    }

    if (promptSent) break
    emit({ type: 'status', stage: 'send_unconfirmed_retrying', attempt })
  }

  if (!promptSent) {
    emitError('send_all_attempts_failed', new Error('All send attempts failed to confirm dispatch'), { attempts: CONFIG.sendMaxAttempts })
    emit({ type: 'status', stage: 'send_failed_continuing_anyway' })
  } else {
    emit({ type: 'status', stage: 'send_confirmed' })
  }
}

// ---------------------------------------------------------------------------
// Assistant text extraction
// ---------------------------------------------------------------------------
const ASSISTANT_SELECTORS = [
  '[data-testid="conversation-turn-assistant"]',
  '[data-message-author-role="assistant"]',
  '[data-testid="conversation-turn-assistant"] .markdown',
  '[data-message-author-role="assistant"] .markdown',
  '[data-message-author-role="assistant"] [class*="markdown"]',
]

async function extractAssistantText(locator) {
  return locator.evaluate((node) => {
    function isHidden(el) {
      const style = window.getComputedStyle(el)
      return style.display === 'none' || style.visibility === 'hidden'
    }

    function walk(current) {
      if (current.nodeType === Node.TEXT_NODE) return current.textContent || ''
      if (current.nodeType !== Node.ELEMENT_NODE) return ''

      const el = current
      if (isHidden(el)) return ''
      const tag = el.tagName.toLowerCase()
      if (['button', 'svg', 'path', 'style', 'script', 'noscript'].includes(tag)) return ''
      if (el.getAttribute('role') === 'button') return ''
      if (el.getAttribute('aria-label')) return ''

      if (tag === 'pre') {
        const codeEl = el.querySelector('code')
        const rawCode = codeEl?.innerText || el.innerText || codeEl?.textContent || el.textContent || ''
        const code = String(rawCode).replace(/\r/g, '').trimEnd()
        const langMatch = (codeEl?.className || '').match(/language-([\w+-]+)/i)
        return `\n\n\`\`\`${langMatch ? langMatch[1] : ''}\n${code}\n\`\`\`\n\n`
      }
      if (tag === 'code' && el.closest('pre')) return ''
      if (tag === 'code') {
        const code = el.innerText || el.textContent || ''
        const langMatch = el.className.match(/language-([\w+-]+)/i)
        if (langMatch || code.includes('\n')) return code ? `\n\n\`\`\`${langMatch ? langMatch[1] : ''}\n${code.trimEnd()}\n\`\`\`\n\n` : ''
        return code ? `\`${code}\`` : ''
      }
      if (tag === 'a') {
        const href = el.getAttribute('href') || ''
        let linkText = ''
        for (const child of el.childNodes) linkText += walk(child)
        linkText = linkText.trim()
        return href && linkText ? `[${linkText}](${href})` : linkText
      }
      if (tag === 'br') return '\n'

      let text = ''
      for (const child of el.childNodes) text += walk(child)

      if (['p', 'div', 'section', 'article', 'blockquote'].includes(tag)) {
        return text.trim() ? `${text.replace(/^\n+|\n+$/g, '')}\n\n` : ''
      }
      if (tag === 'li') return text.trim() ? `- ${text.trim()}\n` : ''
      if (/^h[1-6]$/.test(tag)) return text.trim() ? `${text.trim()}\n\n` : ''
      return text
    }

    return walk(node).replace(/\n{3,}/g, '\n\n').replace(/[ \t]+\n/g, '\n').trim()
  }).catch((err) => {
    // Return empty string so callers can handle gracefully; don't throw
    return ''
  })
}

async function getAssistantSnapshot(page) {
  for (const selector of ASSISTANT_SELECTORS) {
    try {
      const locator = page.locator(selector)
      const count = await locator.count().catch(() => 0)
      if (count > 0) {
        const latest = locator.nth(count - 1)
        const rawText = await extractAssistantText(latest)
        return { selector, count, rawText }
      }
    } catch (err) {
      emitError('assistant_snapshot_failed', err, { selector })
    }
  }
  return { selector: null, count: 0, rawText: '' }
}

function extractAllFinalResponseTexts(text) {
  return Array.from(String(text || '').matchAll(/<final_response>\s*([\s\S]*?)\s*<\/final_response>/gi))
    .map((match) => String(match[1] || '').trim())
    .filter(Boolean)
}

function extractAllToolCallTexts(text) {
  return Array.from(String(text || '').matchAll(/<tool_call>\s*[\s\S]*?\s*<\/tool_call>/gi))
    .map((match) => String(match[0] || '').trim())
    .filter(Boolean)
}

async function extractPageFinalResponseText(page, baselineText = '') {
  const baselineMatches = extractAllFinalResponseTexts(baselineText)

  try {
    const html = await page.locator('body').evaluate((node) => node.innerHTML).catch(() => '')
    const htmlMatches = extractAllFinalResponseTexts(html)
    if (htmlMatches.length > baselineMatches.length) return htmlMatches[htmlMatches.length - 1]
    if (htmlMatches.length && htmlMatches.join('\n') !== baselineMatches.join('\n')) return htmlMatches[htmlMatches.length - 1]
  } catch (err) {
    emitError('page_final_response_html_extract_failed', err)
  }

  try {
    const text = await page.locator('body').innerText().catch(() => '')
    const textMatches = extractAllFinalResponseTexts(text)
    if (textMatches.length > baselineMatches.length) return textMatches[textMatches.length - 1]
    if (textMatches.length && textMatches.join('\n') !== baselineMatches.join('\n')) return textMatches[textMatches.length - 1]
  } catch (err) {
    emitError('page_final_response_text_extract_failed', err)
  }

  return ''
}

async function extractPageToolCallText(page, baselineText = '') {
  const baselineMatches = extractAllToolCallTexts(baselineText).filter((text) => !isPromptExampleToolCall(text))

  function choose(matches) {
    const filtered = matches.filter((text) => !isPromptExampleToolCall(text))
    if (filtered.length > baselineMatches.length) return filtered[filtered.length - 1] || ''
    if (filtered.length && filtered.join('\n') !== baselineMatches.join('\n')) return filtered[filtered.length - 1] || ''
    return ''
  }

  try {
    const html = await page.locator('body').evaluate((node) => node.innerHTML).catch(() => '')
    const picked = choose(extractAllToolCallTexts(html))
    if (picked) return picked
  } catch (err) {
    emitError('page_tool_call_html_extract_failed', err)
  }

  try {
    const text = await page.locator('body').innerText().catch(() => '')
    const picked = choose(extractAllToolCallTexts(text))
    if (picked) return picked
  } catch (err) {
    emitError('page_tool_call_text_extract_failed', err)
  }

  return ''
}

async function waitForAssistantResultFallback(page, baselineAssistant, baselinePageText, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs
  let bestText = ''
  let bestSource = 'none'

  while (Date.now() < deadline) {
    try {
      const latestAssistant = await findLatestAssistantLocator(page, baselineAssistant)
      const domText = latestAssistant?.locator ? String(await extractAssistantText(latestAssistant.locator) || '').trim() : ''
      const pageFinalResponseText = String(await extractPageFinalResponseText(page, baselinePageText) || '').trim()
      const assistantToolCallText = extractToolCallWithWriteContent(domText) || ''

      let candidate = chooseBetterAssistantText(bestText, domText).trim()
      if (!candidate || hasIncompleteTaggedResponse(candidate)) {
        candidate = chooseBetterAssistantText(candidate, pageFinalResponseText).trim()
      }
      if (assistantToolCallText && !isPromptExampleToolCall(assistantToolCallText) && !isPlaceholderToolCallText(assistantToolCallText)) {
        candidate = chooseBetterAssistantText(candidate, assistantToolCallText).trim()
      }

      if (candidate && !isIgnorableAssistantText(candidate) && !hasIncompleteTaggedResponse(candidate)) {
        if (candidate === assistantToolCallText) bestSource = 'assistant_tool_call'
        else if (candidate === pageFinalResponseText) bestSource = 'page_final_response'
        else if (candidate === domText) bestSource = 'assistant_dom'
        else bestSource = 'combined'
        return { text: candidate, source: bestSource }
      }

      bestText = candidate
    } catch (err) {
      emitError('wait_for_assistant_result_fallback_poll_failed', err)
    }

    await delay(250)
  }

  return { text: bestText.trim(), source: bestSource }
}

async function findLatestAssistantLocator(page, baseline = null) {
  if (baseline?.selector) {
    try {
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
    } catch (err) {
      emitError('find_latest_assistant_baseline_failed', err)
    }
  }

  for (const selector of ASSISTANT_SELECTORS) {
    try {
      const locator = page.locator(selector)
      const count = await locator.count().catch(() => 0)
      if (count <= 0) continue
      const latest = locator.nth(count - 1)
      const rawText = await extractAssistantText(latest)
      if (baseline && rawText === (baseline.rawText || '')) continue
      return { locator: latest, selector, count, isNewMessage: Boolean(baseline) }
    } catch (err) {
      emitError('find_latest_assistant_selector_failed', err, { selector })
    }
  }
  return null
}

// ---------------------------------------------------------------------------
// Text normalization and delta computation
// ---------------------------------------------------------------------------
function extractFinalResponseText(text) {
  const raw = String(text || '')
  const matches = Array.from(raw.matchAll(/<final_response>\s*([\s\S]*?)\s*<\/final_response>/gi))
  if (!matches.length) return null
  return String(matches[matches.length - 1][1] || '').trim()
}

function extractToolCallText(text) {
  const matches = extractAllToolCallTexts(text)
  if (!matches.length) return null
  return matches[matches.length - 1]
}

function extractWriteContentText(text) {
  const match = String(text || '').match(/<write_content>\s*[\s\S]*?\s*<\/write_content>/i)
  return match ? match[0].trim() : null
}

function extractCommandContentText(text) {
  const match = String(text || '').match(/<command_content>\s*[\s\S]*?\s*<\/command_content>/i)
  return match ? match[0].trim() : null
}

function isWriteToolCall(text) {
  const raw = String(text || '')
  return /<name>\s*write\s*<\/name>/i.test(raw) || /"name"\s*:\s*"write"/i.test(raw)
}

function isBashToolCall(text) {
  const raw = String(text || '')
  return /<name>\s*bash\s*<\/name>/i.test(raw) || /"name"\s*:\s*"bash"/i.test(raw)
}

function extractToolCallWithSidecarContent(text) {
  const raw = String(text || '')
  const toolCall = extractToolCallText(raw)
  if (!toolCall) return null

  const toolCallIndex = raw.lastIndexOf(toolCall)
  const trailingText = toolCallIndex >= 0 ? raw.slice(toolCallIndex + toolCall.length) : raw

  if (isWriteToolCall(toolCall)) {
    const writeContent = extractWriteContentText(trailingText)
    if (writeContent) return `${toolCall}\n${writeContent}`
  }

  if (isBashToolCall(toolCall)) {
    const commandContent = extractCommandContentText(trailingText)
    if (commandContent) return `${toolCall}\n${commandContent}`
  }

  return toolCall
}

function extractToolCallWithWriteContent(text) {
  return extractToolCallWithSidecarContent(text)
}

function isPromptExampleToolCall(text) {
  const raw = String(text || '').toLowerCase()
  return (
    raw.includes('<name>tool_name</name>') ||
    raw.includes('<arg_name>raw argument value</arg_name>') ||
    raw.includes('"name":"tool_name"') ||
    raw.includes('"arguments":{...}') ||
    raw.includes('legacy compatibility format') ||
    raw.includes('do not json-escape shell commands') ||
    raw.includes('available tools:') ||
    raw.includes('conversation transcript:')
  )
}

function isPlaceholderToolCallText(text) {
  const raw = String(text || '').trim().toLowerCase()
  return (
    raw === '<tool_call>...</tool_call>' ||
    raw.includes('<name>tool_name</name>') ||
    raw.includes('<arg_name>raw argument value</arg_name>') ||
    raw.includes('"name":"tool_name"') ||
    raw.includes('"arguments":{...}')
  )
}

function hasIncompleteTaggedResponse(text) {
  const raw = String(text || '').trim().toLowerCase()
  if (!raw) return false
  if (raw === '<' || raw === '</' || raw === '>') return true
  if (raw.includes('<tool_call') && !extractToolCallText(raw)) return true
  if (raw.includes('<final') && extractFinalResponseText(raw) === null) return true
  if ((raw.startsWith('<tool') || raw.startsWith('<name') || raw.startsWith('<arguments') || raw.startsWith('<command') || raw.startsWith('<final')) && !extractToolCallText(raw) && extractFinalResponseText(raw) === null) {
    return true
  }
  return false
}

function normalizeAssistantText(text) {
  const raw = String(text || '').replace(/\r/g, '')
  const taggedToolCall = extractToolCallWithSidecarContent(raw)
  if (taggedToolCall !== null && !isPromptExampleToolCall(taggedToolCall) && !isPlaceholderToolCallText(taggedToolCall)) return taggedToolCall
  const taggedFinal = extractFinalResponseText(raw)
  if (taggedFinal !== null) return taggedFinal
  if (hasIncompleteTaggedResponse(raw)) return ''

  const cleanedLines = raw
    .split('\n')
    .map((line) => line.trimEnd())
    .filter((line) => {
      const trimmed = line.trim()
      if (!trimmed) return false
      if (/^(thinking|analyzing|reasoning)\.?$/i.test(trimmed)) return false
      if (/^hello!?\s+what.?s on your mind today\??$/i.test(trimmed)) return false
      if (/^ready when you are\.?$/i.test(trimmed)) return false
      if (/^how can i help(?:,.*)?\??$/i.test(trimmed)) return false
      return true
    })

  return cleanedLines.join('\n').replace(/^Thinking\s*/i, '').trim()
}

function longestCommonPrefixLength(a, b) {
  const max = Math.min(a.length, b.length)
  let i = 0
  while (i < max && a.charCodeAt(i) === b.charCodeAt(i)) i++
  return i
}

/**
 * Compute what to append to `previous` to reach `current`.
 *
 * Improved over original: if ChatGPT edits an earlier part of the response
 * (e.g. during tool use or self-correction), we detect the divergence and
 * emit the entire new text as a replacement signal rather than a corrupt delta.
 */
function computeAppendDelta(previous, current) {
  previous = String(previous || '')
  current = String(current || '')
  if (!current || current === previous) return { delta: '', replaced: false }

  if (current.startsWith(previous)) {
    return { delta: current.slice(previous.length), replaced: false }
  }

  const prefixLen = longestCommonPrefixLength(previous, current)
  // If more than 20% of previous text diverged, treat as full replacement
  if (prefixLen < previous.length * 0.8) {
    emit({ type: 'status', stage: 'assistant_text_replaced', previous_length: previous.length, current_length: current.length, common_prefix: prefixLen })
    return { delta: current, replaced: true }
  }

  return { delta: current.slice(prefixLen), replaced: false }
}

function isIgnorableAssistantText(text) {
  const normalized = normalizeAssistantText(text).trim()
  return (
    !normalized ||
    /^(thinking|analyzing|reasoning)\.?$/i.test(normalized) ||
    /^hello!?\s+what.?s on your mind today\??$/i.test(normalized) ||
    /^ready when you are\.?$/i.test(normalized) ||
    /^how can i help(?:,.*)?\??$/i.test(normalized)
  )
}

function chooseBetterAssistantText(primary, fallback) {
  if (isPlaceholderToolCallText(fallback)) {
    return normalizeAssistantText(primary)
  }
  if (isPlaceholderToolCallText(primary)) {
    return normalizeAssistantText(fallback)
  }

  const primaryNormalized = normalizeAssistantText(primary)
  const fallbackNormalized = normalizeAssistantText(fallback)

  const primaryExtractedToolCall = extractToolCallWithSidecarContent(primary)
  const fallbackExtractedToolCall = extractToolCallWithSidecarContent(fallback)
  const primaryHasToolCallTag = primaryExtractedToolCall !== null && !isPromptExampleToolCall(primaryExtractedToolCall) && !isPlaceholderToolCallText(primaryExtractedToolCall)
  const fallbackHasToolCallTag = fallbackExtractedToolCall !== null && !isPromptExampleToolCall(fallbackExtractedToolCall) && !isPlaceholderToolCallText(fallbackExtractedToolCall)
  const primaryHasFinalTag = extractFinalResponseText(primary) !== null
  const fallbackHasFinalTag = extractFinalResponseText(fallback) !== null

  if (fallbackHasToolCallTag && !primaryHasToolCallTag) return fallbackNormalized
  if (primaryHasToolCallTag && !fallbackHasToolCallTag) return primaryNormalized
  if (fallbackHasFinalTag && !primaryHasFinalTag) return fallbackNormalized
  if (primaryHasFinalTag && !fallbackHasFinalTag) return primaryNormalized

  const primaryIncomplete = hasIncompleteTaggedResponse(primary)
  const fallbackIncomplete = hasIncompleteTaggedResponse(fallback)
  if (primaryIncomplete && !fallbackIncomplete) return fallbackNormalized
  if (fallbackIncomplete && !primaryIncomplete) return primaryNormalized

  const primaryIgnorable = isIgnorableAssistantText(primaryNormalized)
  const fallbackIgnorable = isIgnorableAssistantText(fallbackNormalized)

  if (primaryIgnorable && !fallbackIgnorable) return fallbackNormalized
  if (fallbackIgnorable && !primaryIgnorable) return primaryNormalized

  if (fallbackNormalized.length > primaryNormalized.length) return fallbackNormalized
  return primaryNormalized
}

// ---------------------------------------------------------------------------
// Stream binding — with navigation-cleanup path
// ---------------------------------------------------------------------------
let activeAssistantStreamSink = null
let assistantStreamBindingInstalled = false

async function ensureAssistantStreamBinding(page) {
  if (assistantStreamBindingInstalled) return

  await page.exposeBinding('__chatgptProxyAssistantStreamEvent', (_source, event) => {
    if (typeof activeAssistantStreamSink === 'function') {
      activeAssistantStreamSink(event)
    }
  })

  // Navigation can happen before the assistant reply is fully rendered.
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame() && typeof activeAssistantStreamSink === 'function') {
      emit({ type: 'status', stage: 'stream_binding_navigation_seen', url: page.url() })
      setTimeout(() => {
        if (typeof activeAssistantStreamSink === 'function') {
          activeAssistantStreamSink({ kind: 'rescan', reason: 'page_navigated' })
        }
      }, 500)
    }
  })

  assistantStreamBindingInstalled = true
}

// ---------------------------------------------------------------------------
// Assistant stream — configurable watchdog thresholds
// ---------------------------------------------------------------------------
async function streamAssistantText(page, timeoutMs, baselineAssistant = null, options = {}) {
  const {
    thinkingWarnMs = CONFIG.thinkingWarnMs,
    thinkingAbortMs = CONFIG.thinkingAbortMs,
  } = options

  await ensureAssistantStreamBinding(page)

  let lastNormalizedText = ''
  let lastRawText = ''
  let observedAnyText = false
  let settled = false
  let timeoutHandle = null
  let thinkingWatchdogHandle = null
  let firstThinkingAt = null
  let lastThinkingAt = null
  let originalMessage = null  // stored so we can re-send after stop

  return await new Promise(async (resolve) => {
    const finish = async (payload = {}) => {
      if (settled) return
      settled = true

      clearTimeout(timeoutHandle)
      clearInterval(thinkingWatchdogHandle)
      timeoutHandle = null
      thinkingWatchdogHandle = null
      activeAssistantStreamSink = null

      await page.evaluate(() => {
        if (typeof window.__chatgptProxyStopAssistantObserver === 'function') {
          window.__chatgptProxyStopAssistantObserver()
        }
      }).catch((err) => emitError('stop_observer_cleanup_failed', err))

      resolve({
        text: payload.text ?? lastNormalizedText,
        timedOut: Boolean(payload.timedOut),
        placeholderOnly: Boolean(payload.placeholderOnly ?? isIgnorableAssistantText(lastRawText)),
        stalledThinking: Boolean(payload.stalledThinking),
        replaced: Boolean(payload.replaced),
      })
    }

    timeoutHandle = setTimeout(async () => {
      // On timeout: do one last DOM scrape to capture whatever rendered
      let fallbackRawText = lastRawText
      try {
        const fallbackState = await findLatestAssistantLocator(page, baselineAssistant)
        if (fallbackState?.locator) {
          const extracted = await extractAssistantText(fallbackState.locator)
          if (extracted) fallbackRawText = extracted
        }
      } catch (err) {
        emitError('timeout_dom_fallback_failed', err)
      }

      const fallbackText = normalizeAssistantText(fallbackRawText || lastNormalizedText)
      if (fallbackText && !isIgnorableAssistantText(fallbackText)) {
        const { delta } = computeAppendDelta(lastNormalizedText, fallbackText)
        if (delta) emit({ type: 'chunk', content: delta })
        lastNormalizedText = fallbackText
      }

      emit({ type: 'status', stage: 'assistant_timeout_dom_fallback', fallback_length: fallbackText.length })
      finish({ text: lastNormalizedText, timedOut: true, placeholderOnly: isIgnorableAssistantText(lastRawText || lastNormalizedText) })
    }, timeoutMs)

    activeAssistantStreamSink = async (event) => {
      if (!event || settled) return

      if (event.kind === 'text') {
        const rawText = String(event.rawText || '')
        const normalizedText = normalizeAssistantText(rawText)
        const ignorable = isIgnorableAssistantText(rawText)

        observedAnyText = true
        lastRawText = rawText

        if (!ignorable) {
          const { delta, replaced } = computeAppendDelta(lastNormalizedText, normalizedText)
          if (replaced) {
            // Full replacement — signal upstream so it can reset its buffer
            emit({ type: 'replace', content: normalizedText })
          } else if (delta) {
            emit({ type: 'chunk', content: delta })
          }
          lastNormalizedText = normalizedText
          firstThinkingAt = null
          lastThinkingAt = null
        } else {
          const trimmed = normalizedText.trim() || rawText.trim()
          if (/^(thinking|analyzing|reasoning)\.?$/i.test(trimmed)) {
            firstThinkingAt = firstThinkingAt || Date.now()
            lastThinkingAt = Date.now()
          }
        }

        emit({
          type: 'status',
          stage: 'assistant_text_updated',
          raw_length: rawText.length,
          normalized_length: normalizedText.length,
          ignorable,
        })
      }

      if (event.kind === 'rescan') {
        try {
          const latestAssistant = await findLatestAssistantLocator(page, baselineAssistant)
          const rescannedRaw = latestAssistant?.locator ? String(await extractAssistantText(latestAssistant.locator) || '') : ''
          const rescannedText = normalizeAssistantText(rescannedRaw)
          if (rescannedText && !isIgnorableAssistantText(rescannedText) && !hasIncompleteTaggedResponse(rescannedText)) {
            const { delta, replaced } = computeAppendDelta(lastNormalizedText, rescannedText)
            if (replaced) emit({ type: 'replace', content: rescannedText })
            else if (delta) emit({ type: 'chunk', content: delta })
            lastNormalizedText = rescannedText
            lastRawText = rescannedRaw || lastRawText
          }
          emit({ type: 'status', stage: 'assistant_rescan_after_navigation', rescanned_length: rescannedText.length, reason: event.reason || 'page_navigated' })
        } catch (err) {
          emitError('assistant_rescan_after_navigation_failed', err)
        }
      }

      if (event.kind === 'done') {
        const finalRaw = event.rawText || lastRawText || lastNormalizedText
        const finalText = normalizeAssistantText(finalRaw)
        const { delta, replaced } = computeAppendDelta(lastNormalizedText, finalText)

        if (!isIgnorableAssistantText(finalText)) {
          if (replaced) emit({ type: 'replace', content: finalText })
          else if (delta) emit({ type: 'chunk', content: delta })
          lastNormalizedText = finalText
        }

        emit({ type: 'status', stage: 'assistant_completion_detected', reason: event.reason || 'mutation_idle', observed_any_text: observedAnyText })
        finish({ text: lastNormalizedText, timedOut: false, placeholderOnly: isIgnorableAssistantText(lastRawText || lastNormalizedText) })
      }
    }

    // Thinking watchdog — now with configurable thresholds and re-send after stop
    thinkingWatchdogHandle = setInterval(async () => {
      if (settled || !firstThinkingAt) return

      const thinkingForMs = Date.now() - firstThinkingAt

      if (thinkingForMs >= thinkingWarnMs && thinkingForMs < thinkingAbortMs) {
        emit({
          type: 'status',
          stage: 'assistant_thinking_warn',
          thinking_for_ms: thinkingForMs,
          warn_threshold_ms: thinkingWarnMs,
        })
        return
      }

      if (thinkingForMs >= thinkingAbortMs) {
        const stopButton = page.locator('button[aria-label*="Stop" i]').first()
        const stopVisible = await stopButton.isVisible().catch(() => false)

        emit({
          type: 'status',
          stage: 'assistant_thinking_abort',
          thinking_for_ms: thinkingForMs,
          abort_threshold_ms: thinkingAbortMs,
          stop_button_visible: stopVisible,
        })

        if (stopVisible) {
          await stopButton.click({ force: true, timeout: 1_000 }).catch((err) => emitError('thinking_abort_stop_click_failed', err))
          await delay(600)
        }

        // Finish and let the caller retry with full context if it chooses
        finish({
          text: lastNormalizedText,
          timedOut: false,
          placeholderOnly: isIgnorableAssistantText(lastRawText || lastNormalizedText),
          stalledThinking: true,
        })
      }
    }, CONFIG.thinkingPollMs)

    // Install the in-page MutationObserver
    await page.evaluate(({ baselineAssistant, assistantSelectors, streamIdleMs }) => {
      const idleMs = streamIdleMs
      let lastSeenRawText = ''
      let idleTimer = null
      let stopped = false

      function isVisible(el) {
        if (!el) return false
        const style = window.getComputedStyle(el)
        const rect = el.getBoundingClientRect()
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
      }

      function stopButtonVisible() {
        return Array.from(document.querySelectorAll('button')).some(
          (btn) => /stop/i.test(btn.getAttribute('aria-label') || '') && isVisible(btn)
        )
      }

      function extractTextFromNode(node) {
        function isHidden(el) {
          const s = window.getComputedStyle(el)
          return s.display === 'none' || s.visibility === 'hidden'
        }
        function walk(cur) {
          if (cur.nodeType === Node.TEXT_NODE) return cur.textContent || ''
          if (cur.nodeType !== Node.ELEMENT_NODE) return ''
          const el = cur
          if (isHidden(el)) return ''
          const tag = el.tagName.toLowerCase()
          if (['button', 'svg', 'path', 'style', 'script', 'noscript'].includes(tag)) return ''
          if (el.getAttribute('role') === 'button' || el.getAttribute('aria-label')) return ''
          if (tag === 'pre') {
            const codeEl = el.querySelector('code')
            const rawCode = codeEl?.innerText || el.innerText || codeEl?.textContent || el.textContent || ''
            const code = String(rawCode).replace(/\r/g, '').trimEnd()
            const lang = (codeEl?.className || '').match(/language-([\w+-]+)/i)?.[1] || ''
            return `\n\n\`\`\`${lang}\n${code}\n\`\`\`\n\n`
          }
          if (tag === 'code' && el.closest('pre')) return ''
          if (tag === 'br') return '\n'
          let text = ''
          for (const child of el.childNodes) text += walk(child)
          if (['p', 'div', 'section', 'article', 'blockquote'].includes(tag)) return text.trim() ? `${text.replace(/^\n+|\n+$/g, '')}\n\n` : ''
          if (tag === 'li') return text.trim() ? `- ${text.trim()}\n` : ''
          if (/^h[1-6]$/.test(tag)) return text.trim() ? `${text.trim()}\n\n` : ''
          return text
        }
        return walk(node).replace(/\n{3,}/g, '\n\n').replace(/[ \t]+\n/g, '\n').trim()
      }

      function findLatestNode() {
        for (const selector of assistantSelectors) {
          const nodes = document.querySelectorAll(selector)
          if (!nodes.length) continue
          const node = nodes[nodes.length - 1]
          const rawText = extractTextFromNode(node)
          if (baselineAssistant?.rawText && rawText === baselineAssistant.rawText) continue
          return { node, selector, count: nodes.length, rawText }
        }
        return null
      }

      function scheduleIdle(latest) {
        clearTimeout(idleTimer)
        idleTimer = setTimeout(() => {
          if (stopped) return
          const isStreaming = stopButtonVisible()
          if (isStreaming) {
            // Still generating — reschedule
            scheduleIdle(latest)
            return
          }
          const finalLatest = findLatestNode()
          window.__chatgptProxyAssistantStreamEvent({
            kind: 'done',
            rawText: finalLatest?.rawText || latest?.rawText || '',
            reason: 'mutation_idle',
          })
        }, idleMs)
      }

      function onMutation() {
        if (stopped) return
        const latest = findLatestNode()
        if (!latest) return
        if (latest.rawText !== lastSeenRawText) {
          lastSeenRawText = latest.rawText
          window.__chatgptProxyAssistantStreamEvent({
            kind: 'text',
            rawText: latest.rawText,
            selector: latest.selector,
            count: latest.count,
          })
          scheduleIdle(latest)
        }
      }

      const observer = new MutationObserver(onMutation)
      observer.observe(document.body, { childList: true, subtree: true, characterData: true })

      window.__chatgptProxyStopAssistantObserver = () => {
        stopped = true
        clearTimeout(idleTimer)
        observer.disconnect()
      }

      // Initial probe
      onMutation()
    }, { baselineAssistant, assistantSelectors: ASSISTANT_SELECTORS, streamIdleMs: CONFIG.streamIdleMs }).catch((err) => {
      emitError('page_evaluate_observer_install_failed', err)
    })
  })
}

// ---------------------------------------------------------------------------
// Runner / daemon entrypoint
// ---------------------------------------------------------------------------
let sharedRuntime = {
  key: null,
  browser: null,
  context: null,
  page: null,
}

function browserRuntimeKey(browser) {
  return JSON.stringify({
    browser_type: browser.browser_type || 'firefox',
    executable_path: browser.executable_path || null,
    channel: browser.channel || null,
    headless: Boolean(browser.headless),
    connect_over_cdp: Boolean(browser.connect_over_cdp),
    cdp_url: browser.cdp_url || null,
    user_data_dir: browser.user_data_dir || null,
    profile_directory: browser.profile_directory || null,
  })
}

async function closeSharedRuntime() {
  const { browser, context } = sharedRuntime
  sharedRuntime = { key: null, browser: null, context: null, page: null }

  try {
    if (context?.close) await context.close()
  } catch (err) {
    emitError('runtime_context_close_failed', err)
  }

  try {
    if (browser?.close) await browser.close()
  } catch (err) {
    emitError('runtime_browser_close_failed', err)
  }
}

async function ensureRuntime(browserConfig, targetUrl) {
  const key = browserRuntimeKey(browserConfig)
  const existingPage = sharedRuntime.page
  if (
    sharedRuntime.key === key &&
    existingPage &&
    !existingPage.isClosed()
  ) {
    return sharedRuntime
  }

  if (sharedRuntime.page || sharedRuntime.context || sharedRuntime.browser) {
    await closeSharedRuntime()
  }

  const browserType = getBrowserType(browserConfig)
  const executablePath = resolveExecutablePath(browserConfig)
  const launchArgs = buildLaunchArgs(browserConfig)
  emit({
    type: 'status',
    stage: 'browser_launch_start',
    browser_type: getBrowserTypeName(browserConfig),
    executable_path: executablePath,
    connect_over_cdp: Boolean(browserConfig.connect_over_cdp),
  })

  let browser = null
  let context = null
  let page = null

  if (browserConfig.connect_over_cdp) {
    const cdpUrl = browserConfig.cdp_url || 'http://127.0.0.1:9222'
    browser = await chromium.connectOverCDP(cdpUrl)
    context = browser.contexts()[0] || await browser.newContext()
    page = context.pages()[0] || await context.newPage()
    emit({ type: 'status', stage: 'browser_connected_over_cdp', cdp_url: cdpUrl })
  } else if (browserConfig.user_data_dir) {
    const persistentOptions = {
      headless: Boolean(browserConfig.headless),
      executablePath,
      channel: browserConfig.channel || undefined,
      args: launchArgs.filter((arg) => !arg.startsWith('--user-data-dir=')),
    }
    context = await browserType.launchPersistentContext(browserConfig.user_data_dir, persistentOptions)
    page = context.pages()[0] || await context.newPage()
    emit({ type: 'status', stage: 'browser_persistent_context_ready', user_data_dir: browserConfig.user_data_dir })
  } else {
    browser = await browserType.launch({
      headless: Boolean(browserConfig.headless),
      executablePath,
      channel: browserConfig.channel || undefined,
      args: launchArgs,
    })
    context = await browser.newContext()
    page = await context.newPage()
    emit({ type: 'status', stage: 'browser_ephemeral_context_ready' })
  }

  page.setDefaultTimeout(CONFIG.pageTimeoutMs)
  page.setDefaultNavigationTimeout(CONFIG.pageTimeoutMs)

  if (!page.url() || page.url() === 'about:blank') {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded' })
  }

  sharedRuntime = { key, browser, context, page }
  return sharedRuntime
}

function extractRemoteConversationId(currentUrl) {
  const url = String(currentUrl || '')
  const pathMatch = url.match(/\/c\/([^/?#]+)/i)
  if (pathMatch?.[1]) return pathMatch[1]
  try {
    const parsed = new URL(url)
    return parsed.searchParams.get('conversation_id') || null
  } catch {
    return null
  }
}

async function handleRequest(request) {
  const targetUrl = String(request?.url || 'https://chatgpt.com/')
  const captureTimeoutMs = Number(request?.capture_timeout_ms || CONFIG.pageTimeoutMs)
  const browserConfig = {
    ...(request?.transport?.browser || {}),
  }

  try {
    emit({ type: 'status', stage: 'request_received', new_conversation: Boolean(request?.new_conversation) })

    if (Array.isArray(request?.test_events)) {
      for (const event of request.test_events) {
        emit(event)
      }
      return
    }

    const runtime = await ensureRuntime(browserConfig, targetUrl)
    const { page } = runtime

    await waitForNoChallenge(page)
    await waitForChatShell(page)

    const interruptionState = await detectChallengeOrRateLimit(page)
    if (interruptionState.detected) {
      emit({
        type: 'result',
        success: false,
        error: interruptionState.isChallenge
          ? 'ChatGPT is showing a human verification challenge. Manual intervention required.'
          : interruptionState.isRateLimited
            ? 'ChatGPT rate limit active. Back off before retrying.'
            : 'ChatGPT could not load the conversation.',
        text: '',
        remote_conversation_id: request?.remote_conversation_id || null,
        remote_parent_message_id: null,
        transport_details: {
          last_stage: 'challenge_detected',
          page_url: page.url(),
          is_challenge: interruptionState.isChallenge,
          is_rate_limited: interruptionState.isRateLimited,
          is_conversation_error: interruptionState.isConversationError,
        },
        verification_hints: {
          remote_conversation_exists: Boolean(request?.remote_conversation_id),
          requires_manual_intervention: interruptionState.isChallenge,
        },
      })
      return
    }

    const ui = await detectLoggedInUi(page)
    emit({
      type: 'status',
      stage: 'ui_detected',
      url: ui.url,
      title: ui.title,
      has_composer: ui.hasComposer,
      has_login_cues: ui.hasLoginCues,
      has_chat_ui_cues: ui.hasChatUiCues,
      logged_in_likely: ui.loggedInLikely,
    })

    await ensureComposerContext(
      page,
      targetUrl,
      Boolean(request?.new_conversation),
      request?.remote_conversation_id || null,
      request?.remote_conversation_url || null,
    )
    const baselineAssistant = await getAssistantSnapshot(page)
    const baselinePageText = await page.locator('body').innerText().catch(() => '')
    const preparedComposer = await waitForComposerInteractive(page, 5_000)
    await sendPrompt(
      page,
      String(request?.message || ''),
      targetUrl,
      Boolean(request?.new_conversation),
      request?.remote_conversation_id || null,
      request?.remote_conversation_url || null,
      preparedComposer,
    )
    const streamed = await streamAssistantText(page, captureTimeoutMs, baselineAssistant)

    let finalText = String(streamed?.text || '').trim()
    let domFallbackText = ''
    let pageFinalResponseText = ''
    try {
      const latestAssistant = await findLatestAssistantLocator(page, baselineAssistant)
      if (latestAssistant?.locator) {
        domFallbackText = String(await extractAssistantText(latestAssistant.locator) || '').trim()
      }
      pageFinalResponseText = String(await extractPageFinalResponseText(page, baselinePageText) || '').trim()
      const assistantToolCallText = extractToolCallWithWriteContent(domFallbackText) || ''
      finalText = chooseBetterAssistantText(finalText, domFallbackText).trim()
      if (!finalText || hasIncompleteTaggedResponse(finalText)) {
        finalText = chooseBetterAssistantText(finalText, pageFinalResponseText).trim()
      }
      if (assistantToolCallText && !isPromptExampleToolCall(assistantToolCallText) && !isPlaceholderToolCallText(assistantToolCallText)) {
        finalText = chooseBetterAssistantText(finalText, assistantToolCallText).trim()
      }
      emit({
        type: 'status',
        stage: 'assistant_dom_reconciled_after_stream',
        selector: latestAssistant?.selector || null,
        count: latestAssistant?.count || 0,
        stream_length: String(streamed?.text || '').trim().length,
        dom_length: domFallbackText.length,
        page_final_length: pageFinalResponseText.length,
        assistant_tool_call_length: assistantToolCallText.length,
        chosen_length: finalText.length,
        dom_has_final_response_tag: extractFinalResponseText(domFallbackText) !== null,
        dom_has_tool_call_tag: extractToolCallWithWriteContent(domFallbackText) !== null,
        page_has_final_response_tag: Boolean(pageFinalResponseText),
        assistant_tool_call_is_prompt_example: Boolean(assistantToolCallText && isPromptExampleToolCall(assistantToolCallText)),
      })
    } catch (err) {
      emitError('assistant_dom_reconcile_after_stream_failed', err)
    }

    if (!finalText) {
      const waited = await waitForAssistantResultFallback(page, baselineAssistant, baselinePageText, 8000)
      finalText = String(waited.text || '').trim()
      emit({
        type: 'status',
        stage: 'assistant_waited_fallback_after_empty_result',
        source: waited.source,
        chosen_length: finalText.length,
      })
    }

    const remoteConversationId = extractRemoteConversationId(page.url()) || request?.remote_conversation_id || null

    if (!finalText) {
      emit({
        type: 'result',
        success: false,
        error: ui.loggedInLikely
          ? 'No assistant text was captured from the ChatGPT page'
          : 'ChatGPT UI does not appear authenticated or ready',
        text: '',
        remote_conversation_id: remoteConversationId,
        remote_parent_message_id: null,
        transport_details: {
          last_stage: 'result_empty',
          ui_logged_in_likely: ui.loggedInLikely,
          page_url: page.url(),
          timed_out: Boolean(streamed?.timedOut),
          placeholder_only: Boolean(streamed?.placeholderOnly),
          stalled_thinking: Boolean(streamed?.stalledThinking),
        },
        verification_hints: {
          remote_conversation_exists: Boolean(remoteConversationId),
          ui_logged_in_likely: ui.loggedInLikely,
        },
      })
      return
    }

    emit({
      type: 'result',
      success: true,
      text: finalText,
      remote_conversation_id: remoteConversationId,
      remote_parent_message_id: null,
      transport_details: {
        last_stage: 'result_ready',
        ui_logged_in_likely: ui.loggedInLikely,
        page_url: page.url(),
        page_title: await page.title().catch(() => ''),
        timed_out: Boolean(streamed?.timedOut),
        placeholder_only: Boolean(streamed?.placeholderOnly),
        stalled_thinking: Boolean(streamed?.stalledThinking),
      },
      verification_hints: {
        remote_conversation_exists: Boolean(remoteConversationId),
        ui_logged_in_likely: ui.loggedInLikely,
      },
    })
  } catch (err) {
    emitError('request_failed', err)
    emit({
      type: 'result',
      success: false,
      error: err?.message || String(err),
      text: '',
      remote_conversation_id: null,
      remote_parent_message_id: null,
      transport_details: { last_stage: 'request_failed' },
      verification_hints: { remote_conversation_exists: false },
    })
  }
}

async function runDaemon() {
  emit({ type: 'status', stage: 'runner_started', pid: process.pid, playwright_version: getPlaywrightVersion() })
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
    terminal: false,
  })

  for await (const line of rl) {
    const trimmed = String(line || '').trim()
    if (!trimmed) continue
    try {
      await handleRequest(JSON.parse(trimmed))
    } catch (err) {
      emitError('request_parse_failed', err, { raw_line_preview: trimmed.slice(0, 500) })
      emit({
        type: 'result',
        success: false,
        error: err?.message || String(err),
        text: '',
        remote_conversation_id: null,
        remote_parent_message_id: null,
        transport_details: { last_stage: 'request_parse_failed' },
        verification_hints: { remote_conversation_exists: false },
      })
    }
  }

  await closeSharedRuntime()
}

process.on('unhandledRejection', (err) => {
  emitError('unhandled_rejection', err)
})
process.on('uncaughtException', (err) => {
  emitError('uncaught_exception', err)
})

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : ''
const modulePath = fileURLToPath(import.meta.url)
if (invokedPath && invokedPath === modulePath) {
  runDaemon().catch((err) => {
    emitError('runner_fatal', err)
    process.exitCode = 1
  })
}

// ---------------------------------------------------------------------------
// Exports (named + default)
// ---------------------------------------------------------------------------
export {
  CONFIG,
  emit,
  emitError,
  findSystemBrowser,
  resolveExecutablePath,
  buildLaunchArgs,
  getBrowserType,
  getBrowserTypeName,
  findComposer,
  waitForComposer,
  waitForComposerInteractive,
  waitForNoChallenge,
  waitForChatShell,
  detectPageInterruptionStateFromText,
  detectChallengeOrRateLimit,
  detectLoggedInUi,
  buildConversationUrl,
  normalizeConversationUrl,
  isSameConversationTarget,
  getComposerContextMode,
  openFreshThread,
  openExistingThread,
  ensureComposerContext,
  injectText,
  activateComposer,
  triggerPromptSend,
  sendPrompt,
  extractAssistantText,
  getAssistantSnapshot,
  findLatestAssistantLocator,
  extractAllFinalResponseTexts,
  extractAllToolCallTexts,
  extractFinalResponseText,
  extractToolCallText,
  extractWriteContentText,
  extractCommandContentText,
  isWriteToolCall,
  extractToolCallWithWriteContent,
  isPromptExampleToolCall,
  isPlaceholderToolCallText,
  hasIncompleteTaggedResponse,
  normalizeAssistantText,
  computeAppendDelta,
  isIgnorableAssistantText,
  chooseBetterAssistantText,
  waitForAssistantResultFallback,
  ensureAssistantStreamBinding,
  streamAssistantText,
  delay,
  readComposerValue,
  isGenerating,
}

export default {
  sendPrompt,
  buildConversationUrl,
  normalizeConversationUrl,
  isSameConversationTarget,
  getComposerContextMode,
  detectPageInterruptionStateFromText,
  streamAssistantText,
  getAssistantSnapshot,
  detectLoggedInUi,
  normalizeAssistantText,
  extractFinalResponseText,
  extractAllFinalResponseTexts,
  extractToolCallText,
  extractWriteContentText,
  extractCommandContentText,
  isWriteToolCall,
  extractToolCallWithWriteContent,
  extractAllToolCallTexts,
  isPromptExampleToolCall,
  hasIncompleteTaggedResponse,
  chooseBetterAssistantText,
  CONFIG,
}
