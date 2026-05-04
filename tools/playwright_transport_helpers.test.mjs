import { describe, expect, test } from 'bun:test'

import {
  extractAllFinalResponseTexts,
  extractFinalResponseText,
  normalizeAssistantText,
  chooseBetterAssistantText,
  computeAppendDelta,
  isIgnorableAssistantText,
} from './playwright_chat_transport.mjs'

describe('playwright transport helper extraction', () => {
  test('extractFinalResponseText prefers last final_response tag', () => {
    const raw = [
      '<final_response>placeholder</final_response>',
      '<final_response>Ready.</final_response>',
    ].join('\n')

    expect(extractFinalResponseText(raw)).toBe('Ready.')
  })

  test('extractAllFinalResponseTexts returns all final responses in order', () => {
    const raw = '<final_response>One</final_response>\n<final_response>Two</final_response>'
    expect(extractAllFinalResponseTexts(raw)).toEqual(['One', 'Two'])
  })

  test('normalizeAssistantText strips thinking-only lines and keeps final response content', () => {
    const raw = 'Thinking\n\n<final_response>Ready.</final_response>'
    expect(normalizeAssistantText(raw)).toBe('Ready.')
  })

  test('chooseBetterAssistantText prefers tagged final response over thinking placeholder', () => {
    expect(
      chooseBetterAssistantText('Thinking', '<final_response>Ready.</final_response>'),
    ).toBe('Ready.')
  })

  test('computeAppendDelta emits replacement when earlier text diverges strongly', () => {
    const result = computeAppendDelta('Thinking', 'Ready.')
    expect(result.replaced).toBe(true)
    expect(result.delta).toBe('Ready.')
  })

  test('isIgnorableAssistantText treats thinking as ignorable and final answer as non-ignorable', () => {
    expect(isIgnorableAssistantText('Thinking')).toBe(true)
    expect(isIgnorableAssistantText('<final_response>Ready.</final_response>')).toBe(false)
  })
})
