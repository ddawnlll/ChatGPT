import test from 'node:test'
import assert from 'node:assert/strict'

import {
  extractAllFinalResponseTexts,
  extractFinalResponseText,
  normalizeAssistantText,
  chooseBetterAssistantText,
  computeAppendDelta,
  isIgnorableAssistantText,
} from './playwright_chat_transport.mjs'

test('extractFinalResponseText prefers last final_response tag', () => {
  const raw = [
    '<final_response>placeholder</final_response>',
    '<final_response>Ready.</final_response>',
  ].join('\n')

  assert.equal(extractFinalResponseText(raw), 'Ready.')
})

test('extractAllFinalResponseTexts returns all final responses in order', () => {
  const raw = '<final_response>One</final_response>\n<final_response>Two</final_response>'
  assert.deepEqual(extractAllFinalResponseTexts(raw), ['One', 'Two'])
})

test('normalizeAssistantText strips thinking-only lines and keeps final response content', () => {
  const raw = 'Thinking\n\n<final_response>Ready.</final_response>'
  assert.equal(normalizeAssistantText(raw), 'Ready.')
})

test('chooseBetterAssistantText prefers tagged final response over thinking placeholder', () => {
  assert.equal(
    chooseBetterAssistantText('Thinking', '<final_response>Ready.</final_response>'),
    'Ready.',
  )
})

test('computeAppendDelta emits replacement when earlier text diverges strongly', () => {
  const result = computeAppendDelta('Thinking', 'Ready.')
  assert.equal(result.replaced, true)
  assert.equal(result.delta, 'Ready.')
})

test('isIgnorableAssistantText treats thinking as ignorable and final answer as non-ignorable', () => {
  assert.equal(isIgnorableAssistantText('Thinking'), true)
  assert.equal(isIgnorableAssistantText('<final_response>Ready.</final_response>'), false)
})
