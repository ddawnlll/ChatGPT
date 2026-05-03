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

  const args = [
    `--user-data-dir=${browser.user_data_dir || ''}`,
    '--remote-debugging-pipe',
    '--password-store=basic',
    '--no-first-run',
    '--no-default-browser-check',
    '--remote-allow-origins=*',
    '--disable-blink-features=AutomationControlled',
    'about:blank'
  ]

  if (browser.profile_directory) {
    args.splice(1, 0, `--profile-directory=${browser.profile_directory}`)
  }

  return args
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
  '#prompt-textarea[contenteditable="true"]',
  'div[contenteditable="true"][role="textbox"]',
  'div[contenteditable="true"][data-lexical-editor="true"]',
  'div[contenteditable="true"]',
  '#prompt-textarea',
  'textarea[placeholder*="Message"]',
  'textarea',
]

async function findComposer(page) {
  for (const selector of COMPOSER_SELECTORS) {
    const locator = page.locator(selector)
    const count = await locator.count().catch(() => 0)
    for (let i = 0; i < count; i += 1) {
      const candidate = locator.nth(i)
      const visible = await candidate.isVisible().catch(() => false)
      if (!visible) continue

      const box = await candidate.boundingBox().catch(() => null)
      if (!box || box.width < 4 || box.height < 4) {
        emit({
          type: 'status',
          stage: 'composer_candidate_rejected_zero_box',
          selector,
          index: i,
        })
        continue
      }

      const disabled = await candidate.evaluate((node) => {
        return Boolean(
          node.disabled ||
          node.getAttribute('aria-disabled') === 'true' ||
          node.getAttribute('aria-hidden') === 'true'
        )
      }).catch(() => false)

      if (!disabled) {
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

async function typeComposerTextWithKeyboard(page, composer, message) {
  await composer.locator.scrollIntoViewIfNeeded().catch(() => {})
  await composer.locator.click({ timeout: 1500 }).catch(() => {})
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {})
  await page.keyboard.press('Backspace').catch(() => {})

  const chunkSize = 1200
  for (let i = 0; i < message.length; i += chunkSize) {
    await page.keyboard.insertText(message.slice(i, i + chunkSize))
    await delay(20)
  }

  let enteredText = ''
  try {
    enteredText = await composer.locator.inputValue({ timeout: 1000 })
  } catch {
    enteredText = await composer.locator.innerText({ timeout: 1000 }).catch(() => '')
  }

  return enteredText
}

async function setComposerText(page, composer, message) {
  const result = await composer.locator.evaluate((node, value) => {
    const text = String(value || '')

    function fire(target, type) {
      target.dispatchEvent(new Event(type, { bubbles: true, cancelable: true }))
    }

    function fireInput(target, insertedText) {
      try {
        target.dispatchEvent(new InputEvent('beforeinput', {
          bubbles: true,
          cancelable: true,
          data: insertedText,
          inputType: 'insertText',
        }))
      } catch {}
      try {
        target.dispatchEvent(new InputEvent('input', {
          bubbles: true,
          cancelable: true,
          data: insertedText,
          inputType: 'insertText',
        }))
      } catch {
        fire(target, 'input')
      }
    }

    node.focus()

    if (node instanceof HTMLTextAreaElement || node instanceof HTMLInputElement) {
      const proto = node instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype

      const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
      if (descriptor?.set) {
        descriptor.set.call(node, text)
      } else {
        node.value = text
      }

      try {
        if (typeof node.setSelectionRange === 'function') {
          node.setSelectionRange(text.length, text.length)
        }
      } catch {}

      fireInput(node, text)
      fire(node, 'change')

      return {
        ok: true,
        mode: 'textarea',
        length: node.value.length,
        text: node.value,
      }
    }

    if (node.isContentEditable) {
      node.textContent = text
      fireInput(node, text)
      fire(node, 'change')

      return {
        ok: true,
        mode: 'contenteditable',
        length: node.innerText.length,
        text: node.innerText,
      }
    }

    return {
      ok: false,
      mode: 'unknown',
      length: 0,
      text: '',
      tag: node.tagName,
    }
  }, message).catch((error) => ({
    ok: false,
    mode: 'evaluate_failed',
    length: 0,
    text: '',
    error: String(error?.message || error),
  }))

  if (!result.ok || result.length === 0) {
    await composer.locator.click({ timeout: 1000 }).catch(() => {})
    await page.keyboard.insertText(message)
  }

  let enteredText = ''
  try {
    enteredText = await composer.locator.inputValue({ timeout: 1000 })
  } catch {
    enteredText = await composer.locator.innerText({ timeout: 1000 }).catch(() => '')
  }

  return {
    ...result,
    enteredText,
    enteredLength: enteredText.length,
  }
}

async function triggerPromptSend(page, composer) {
  const sendState = await composer.locator.evaluate((node) => {
    function isVisible(el) {
      if (!el) return false
      const style = window.getComputedStyle(el)
      const rect = el.getBoundingClientRect()
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
    }

    function isEnabled(el) {
      return isVisible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true'
    }

    const selectors = [
      'button[data-testid="send-button"]',
      'button[aria-label*="Send" i]',
      'button[aria-label*="Submit" i]',
      '[data-testid="composer-send-button"]',
      'button[type="submit"]',
    ]

    const form = node.closest('form')
    const roots = [form, node.parentElement, document]
    let matchedButton = null
    let matchedSelector = null

    for (const root of roots) {
      if (!root) continue
      for (const selector of selectors) {
        const button = root.querySelector(selector)
        if (button && isEnabled(button)) {
          matchedButton = button
          matchedSelector = selector
          break
        }
      }
      if (matchedButton) break
    }

    return {
      hasEnabledButton: Boolean(matchedButton),
      selector: matchedSelector,
      formPresent: Boolean(form),
      ariaLabel: matchedButton?.getAttribute('aria-label') || '',
      disabled: matchedButton ? Boolean(matchedButton.disabled || matchedButton.getAttribute('aria-disabled') === 'true') : null,
    }
  }).catch(() => ({ hasEnabledButton: false, selector: null, formPresent: false, ariaLabel: '', disabled: null }))

  emit({ type: 'status', stage: 'send_button_state', ...sendState })

  if (sendState.hasEnabledButton) {
    const clicked = await composer.locator.evaluate((node) => {
      function isVisible(el) {
        if (!el) return false
        const style = window.getComputedStyle(el)
        const rect = el.getBoundingClientRect()
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
      }

      function isEnabled(el) {
        return isVisible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true'
      }

      const selectors = [
        'button[data-testid="send-button"]',
        'button[aria-label*="Send" i]',
        'button[aria-label*="Submit" i]',
        '[data-testid="composer-send-button"]',
        'button[type="submit"]',
      ]

      const form = node.closest('form')
      const roots = [form, node.parentElement, document]
      for (const root of roots) {
        if (!root) continue
        for (const selector of selectors) {
          const button = root.querySelector(selector)
          if (button && isEnabled(button)) {
            try { button.click() } catch {}
            return { method: 'dom_button_click', selector }
          }
        }
      }

      if (form) {
        try {
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit()
            return { method: 'form_request_submit', selector: null }
          }
        } catch {}
        try {
          form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
          return { method: 'form_submit_event', selector: null }
        } catch {}
      }

      return { method: 'none', selector: null }
    }).catch(() => ({ method: 'none', selector: null }))

    emit({ type: 'status', stage: 'send_trigger_method', ...clicked })
    if (clicked.method !== 'none') return
  }

  const submittedByForm = await page.evaluate(() => {
    const composer =
      document.querySelector('#prompt-textarea') ||
      document.querySelector('div[contenteditable="true"][role="textbox"]') ||
      document.querySelector('div[contenteditable="true"]') ||
      document.querySelector('textarea')

    const form = composer?.closest('form')
    if (!form) return false

    try {
      form.dispatchEvent(new SubmitEvent('submit', {
        bubbles: true,
        cancelable: true,
        submitter: null,
      }))
      return true
    } catch {
      return false
    }
  }).catch(() => false)

  if (submittedByForm) {
    emit({ type: 'status', stage: 'send_trigger_method', method: 'form_submit_event', selector: null })
    return
  }

  await composer.locator.focus().catch(() => {})
  await page.keyboard.press('Enter').catch(() => {})
  emit({ type: 'status', stage: 'send_trigger_method', method: 'keyboard_enter', selector: null })
}

async function sendPrompt(page, message, targetUrl, newConversation) {
  const composer = await ensureComposerContext(page, targetUrl, newConversation)
  emit({ type: 'status', stage: 'composer_ready', selector: composer.selector, index: composer.index })

  const activateComposer = async (locator) => {
    emit({ type: 'status', stage: 'composer_activation_start' })

    emit({ type: 'status', stage: 'composer_activation_dom_prepare_start' })
    await locator.evaluate((node) => {
      if (!node) return
      try {
        if (typeof node.scrollIntoView === 'function') {
          node.scrollIntoView({ block: 'center', inline: 'nearest' })
        }
      } catch {}
      try {
        if (typeof node.focus === 'function') node.focus()
      } catch {}
      try {
        if (typeof node.click === 'function') node.click()
      } catch {}
    }).catch(() => {})
    emit({ type: 'status', stage: 'composer_activation_dom_prepare_done' })

    emit({ type: 'status', stage: 'composer_activation_bbox_start' })
    const box = await locator.boundingBox().catch(() => null)
    emit({ type: 'status', stage: 'composer_activation_bbox_done', has_box: Boolean(box) })

    if (box) {
      emit({ type: 'status', stage: 'composer_activation_mouse_click_start' })
      await page.mouse.click(
        box.x + Math.min(box.width / 2, Math.max(8, box.width - 8)),
        box.y + Math.min(box.height / 2, Math.max(8, box.height - 8)),
      ).catch(() => {})
      emit({ type: 'status', stage: 'composer_activation_mouse_click_done' })
    }

    emit({ type: 'status', stage: 'composer_activation_done' })
  }

  // Loop to type and send, retrying if the message doesn't send or type correctly
  let promptSent = false
  for (let attempt = 1; attempt <= 3; attempt++) {
    emit({ type: 'status', stage: 'prompt_attempt_start', attempt })
    await activateComposer(composer.locator)

    emit({ type: 'status', stage: 'before_prompt_injection', selector: composer.selector, index: composer.index, attempt })

    let enteredText = await typeComposerTextWithKeyboard(page, composer, message)

    let typed = {
      ok: enteredText.trim().length > 0,
      mode: 'keyboard_insertText',
      length: enteredText.length,
      enteredText,
      enteredLength: enteredText.length,
    }

    if (!typed.ok) {
      typed = await setComposerText(page, composer, message)
      enteredText = typed.enteredText || ''
    }

    emit({
      type: 'status',
      stage: 'prompt_entered',
      attempt,
      prompt_length: enteredText.length,
      composer_mode: typed.mode,
      typed_length: typed.length,
      entered_length: typed.enteredLength,
      typed_ok: typed.ok,
    })

    // If it completely failed to type, retry the whole typing block
    if (enteredText.trim().length === 0 && message.trim().length > 0) {
      await delay(500)
      continue
    }

    // Wait a tiny bit for React state to register the input
    await delay(150)

    await triggerPromptSend(page, composer)

    // Wait briefly for the composer to clear or the stop button to appear.
    let sentSignal = false
    for (let i = 0; i < 4; i++) {
      await delay(75)

      const stopVisible = await page.locator('button[aria-label*="Stop" i]').first().isVisible().catch(() => false)
      if (stopVisible) {
        sentSignal = true
        break
      }

      let currentText = ''
      try {
        currentText = await composer.locator.inputValue()
      } catch {
        currentText = await composer.locator.innerText().catch(() => '')
      }

      if (currentText.trim().length === 0 || currentText.trim() === 'Message ChatGPT') {
        sentSignal = true
        break
      }
    }

    if (sentSignal) {
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
}

function longestCommonPrefixLength(a, b) {
  const max = Math.min(a.length, b.length)
  let i = 0
  while (i < max && a.charCodeAt(i) === b.charCodeAt(i)) i += 1
  return i
}

function computeAppendDelta(previous, current) {
  previous = String(previous || '')
  current = String(current || '')

  if (!current || current === previous) return ''

  if (current.startsWith(previous)) {
    return current.slice(previous.length)
  }

  const prefixLength = longestCommonPrefixLength(previous, current)
  if (prefixLength >= Math.floor(previous.length * 0.8)) {
    return current.slice(prefixLength)
  }

  return ''
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

function isPlaceholderOnly(text) {
  return isIgnorableAssistantText(text)
}

let activeAssistantStreamSink = null
let assistantStreamBindingInstalled = false

async function ensureAssistantStreamBinding(page) {
  if (assistantStreamBindingInstalled) return

  await page.exposeBinding('__chatgptProxyAssistantStreamEvent', async (_source, event) => {
    if (typeof activeAssistantStreamSink === 'function') {
      activeAssistantStreamSink(event)
    }
  })

  assistantStreamBindingInstalled = true
}

async function streamAssistantText(page, timeoutMs, baselineAssistant = null) {
  await ensureAssistantStreamBinding(page)

  let lastNormalizedText = ''
  let lastRawText = ''
  let observedAnyText = false
  let settled = false
  let timeoutHandle = null

  return await new Promise(async (resolve) => {
    const finish = async (payload = {}) => {
      if (settled) return
      settled = true

      if (timeoutHandle) {
        clearTimeout(timeoutHandle)
        timeoutHandle = null
      }

      activeAssistantStreamSink = null

      await page.evaluate(() => {
        if (typeof window.__chatgptProxyStopAssistantObserver === 'function') {
          window.__chatgptProxyStopAssistantObserver()
        }
      }).catch(() => {})

      resolve({
        text: payload.text ?? lastNormalizedText,
        timedOut: Boolean(payload.timedOut),
        placeholderOnly: Boolean(payload.placeholderOnly ?? isPlaceholderOnly(lastRawText)),
      })
    }

    timeoutHandle = setTimeout(async () => {
      let fallbackRawText = lastRawText

      try {
        const fallbackState = await findLatestAssistantLocator(page, baselineAssistant)
        if (fallbackState?.locator) {
          const extracted = await extractAssistantText(fallbackState.locator)
          if (extracted) fallbackRawText = extracted
        }
      } catch {}

      const fallbackText = normalizeAssistantText(fallbackRawText || lastNormalizedText)

      if (fallbackText && !isIgnorableAssistantText(fallbackText)) {
        const finalDelta = computeAppendDelta(lastNormalizedText, fallbackText)
        if (finalDelta) emit({ type: 'chunk', content: finalDelta })
        lastNormalizedText = fallbackText
        lastRawText = fallbackRawText
      }

      emit({
        type: 'status',
        stage: 'assistant_timeout_dom_fallback',
        fallback_length: fallbackText.length,
      })

      finish({
        text: lastNormalizedText,
        timedOut: true,
        placeholderOnly: isPlaceholderOnly(lastRawText || lastNormalizedText),
      })
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
          const chunk = computeAppendDelta(lastNormalizedText, normalizedText)
          if (chunk) emit({ type: 'chunk', content: chunk })
          lastNormalizedText = normalizedText
        }

        emit({
          type: 'status',
          stage: 'assistant_text_updated',
          raw_length: rawText.length,
          normalized_length: normalizedText.length,
          assistant_selector: event.selector ?? null,
          assistant_count: event.count ?? null,
          is_new_message: event.isNewMessage ?? null,
          ignorable,
          observer_driven: true,
        })
      }

      if (event.kind === 'done') {
        const finalText = normalizeAssistantText(event.rawText || lastRawText || lastNormalizedText)
        const finalDelta = computeAppendDelta(lastNormalizedText, finalText)

        if (finalDelta && !isIgnorableAssistantText(finalText)) {
          emit({ type: 'chunk', content: finalDelta })
        }

        if (!isIgnorableAssistantText(finalText)) {
          lastNormalizedText = finalText
        }

        emit({
          type: 'status',
          stage: 'assistant_completion_detected',
          observer_driven: true,
          reason: event.reason || 'mutation_idle',
          observed_any_text: observedAnyText,
        })

        await finish({
          text: lastNormalizedText,
          timedOut: false,
          placeholderOnly: isPlaceholderOnly(lastRawText || lastNormalizedText),
        })
      }
    }

    await page.evaluate(({ baselineAssistant, assistantSelectors }) => {
      const idleMs = 350
      let lastSeenRawText = ''
      let observedText = false
      let idleTimer = null
      let rafPending = false
      let stopped = false

      function isVisible(el) {
        if (!el) return false
        const style = window.getComputedStyle(el)
        const rect = el.getBoundingClientRect()
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0
      }

      function stopButtonVisible() {
        const buttons = Array.from(document.querySelectorAll('button'))
        return buttons.some((button) => {
          const label = button.getAttribute('aria-label') || ''
          return /stop/i.test(label) && isVisible(button)
        })
      }

      function extractAssistantTextFromNode(node) {
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
            return `\n\n\ \ \ ${language ? language : ''}\n${code}\n\ \ \ \n\n`.replace(/\u0000/g, '`')
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
              return code ? `\n\n\ \ \ ${language ? language : ''}\n${code.trimEnd()}\n\ \ \ \n\n`.replace(/\u0000/g, '`') : ''
            }
            return code ? `\ ${code}\ `.replace(/\u0000/g, '`') : ''
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
      }

      function latestAssistantState() {
        for (const selector of assistantSelectors) {
          const nodes = Array.from(document.querySelectorAll(selector))
          const count = nodes.length
          if (count <= 0) continue

          const latest = nodes[count - 1]
          const rawText = extractAssistantTextFromNode(latest)

          if (baselineAssistant?.selector === selector) {
            const baselineCount = Number(baselineAssistant.count || 0)

            if (count > baselineCount) {
              return { node: latest, selector, count, rawText, isNewMessage: true }
            }

            if (rawText && rawText !== String(baselineAssistant.rawText || '')) {
              return { node: latest, selector, count, rawText, isNewMessage: false }
            }

            continue
          }

          if (!baselineAssistant && rawText) {
            return { node: latest, selector, count, rawText, isNewMessage: true }
          }
        }

        return null
      }

      function sendDone(reason) {
        if (stopped) return
        const state = latestAssistantState()
        const rawText = state?.rawText || lastSeenRawText || ''
        window.__chatgptProxyAssistantStreamEvent({ kind: 'done', reason, rawText })
      }

      function scheduleCompletionCheck() {
        clearTimeout(idleTimer)
        idleTimer = setTimeout(() => {
          if (stopped) return

          const state = latestAssistantState()

          if (state?.rawText && state.rawText !== lastSeenRawText) {
            lastSeenRawText = state.rawText
            observedText = true

            window.__chatgptProxyAssistantStreamEvent({
              kind: 'text',
              rawText: state.rawText,
              selector: state.selector,
              count: state.count,
              isNewMessage: state.isNewMessage,
            })
          }

          if (!observedText) {
            scheduleCompletionCheck()
            return
          }

          if (stopButtonVisible()) {
            scheduleCompletionCheck()
            return
          }

          sendDone('assistant_text_idle_and_stop_hidden')
        }, idleMs)
      }

      function scan() {
        if (stopped) return

        const state = latestAssistantState()
        if (!state || !state.rawText) {
          scheduleCompletionCheck()
          return
        }

        if (state.rawText !== lastSeenRawText) {
          lastSeenRawText = state.rawText
          observedText = true
          window.__chatgptProxyAssistantStreamEvent({
            kind: 'text',
            rawText: state.rawText,
            selector: state.selector,
            count: state.count,
            isNewMessage: state.isNewMessage,
          })
        }

        scheduleCompletionCheck()
      }

      function scheduleScan() {
        if (rafPending || stopped) return
        rafPending = true
        window.requestAnimationFrame(() => {
          rafPending = false
          scan()
        })
      }

      const observer = new MutationObserver(scheduleScan)
      observer.observe(document.body, {
        childList: true,
        subtree: true,
        characterData: true,
      })

      window.__chatgptProxyStopAssistantObserver = () => {
        stopped = true
        clearTimeout(idleTimer)
        observer.disconnect()
      }

      scan()
    }, {
      baselineAssistant,
      assistantSelectors: ASSISTANT_SELECTORS,
    }).catch(async (error) => {
      emit({
        type: 'status',
        stage: 'assistant_observer_install_failed',
        error: String(error?.message || error),
      })

      await finish({
        text: lastNormalizedText,
        timedOut: true,
        placeholderOnly: true,
      })
    })
  })
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
        ignoreDefaultArgs: true, // Drop all Playwright bot-detection flags completely!
      }

      if (browser.executable_path) {
        launchOptions.executablePath = browser.executable_path
      }

      const browserType = getBrowserType(browser)
      
      emit({
        type: 'status',
        stage: 'launching_persistent_context',
        browser_type: browserTypeName,
        executable_path: launchOptions.executablePath || 'playwright-default',
        user_data_dir: browser.user_data_dir || null,
        profile_directory: browser.profile_directory || null,
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
    emit({
      type: 'status',
      stage: 'stream_result_collected',
      text_length: String(streamResult.text || '').length,
      timed_out: streamResult.timedOut,
      placeholder_only: streamResult.placeholderOnly,
    })
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
