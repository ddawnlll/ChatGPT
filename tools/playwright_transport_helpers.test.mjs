import { describe, expect, test } from 'bun:test'

import {
  extractAllFinalResponseTexts,
  extractAllToolCallTexts,
  extractFinalResponseText,
  extractToolCallText,
  extractWriteContentText,
  isWriteToolCall,
  extractToolCallWithWriteContent,
  isPromptExampleToolCall,
  isPlaceholderToolCallText,
  hasIncompleteTaggedResponse,
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

  test('extractToolCallText prefers last tool_call block', () => {
    const raw = [
      '<tool_call><name>read</name><arguments><path>a</path></arguments></tool_call>',
      '<tool_call><name>bash</name><arguments><command>pwd</command></arguments></tool_call>',
    ].join('\n')
    expect(extractToolCallText(raw)).toContain('<name>bash</name>')
    expect(extractAllToolCallTexts(raw)).toHaveLength(2)
  })

  test('normalizeAssistantText returns empty string for incomplete tool tag and full text for complete tool call', () => {
    expect(normalizeAssistantText('<')).toBe('')
    expect(hasIncompleteTaggedResponse('<')).toBe(true)
    const full = '<tool_call><name>bash</name><arguments><command>tree app</command></arguments></tool_call>'
    expect(normalizeAssistantText(full)).toBe(full)
  })

  test('chooseBetterAssistantText prefers tagged final response over thinking placeholder', () => {
    expect(
      chooseBetterAssistantText('Thinking', '<final_response>Ready.</final_response>'),
    ).toBe('Ready.')
  })

  test('chooseBetterAssistantText prefers complete tool call over partial capture', () => {
    const full = '<tool_call><name>bash</name><arguments><command>tree app 2>/dev/null || find app -print | sort</command><timeout>10</timeout></arguments></tool_call>'
    expect(chooseBetterAssistantText('<', full)).toBe(full)
  })

  test('write tool helpers preserve adjacent write_content blocks', () => {
    const raw = [
      '<tool_call>',
      '<name>write</name>',
      '<arguments>',
      '<path>app/server.py</path>',
      '</arguments>',
      '</tool_call>',
      '<write_content>',
      'print("hello")',
      '</write_content>',
    ].join('\n')

    expect(extractWriteContentText(raw)).toContain('print("hello")')
    expect(isWriteToolCall(raw)).toBe(true)
    expect(extractToolCallWithWriteContent(raw)).toBe(raw)
    expect(normalizeAssistantText(raw)).toBe(raw)
    expect(chooseBetterAssistantText('', raw)).toBe(raw)
  })

  test('normalizeAssistantText keeps only the last write tool call with its matching write_content', () => {
    const raw = [
      '<tool_call><name>write</name><arguments><path>old.py</path></arguments></tool_call>',
      '<write_content>```python\nprint("old")\n```</write_content>',
      '<tool_call><name>write</name><arguments><path>new.py</path></arguments></tool_call>',
      '<write_content>```python\nprint("new")\n```</write_content>',
    ].join('\n')

    expect(normalizeAssistantText(raw)).toBe([
      '<tool_call><name>write</name><arguments><path>new.py</path></arguments></tool_call>',
      '<write_content>```python\nprint("new")\n```</write_content>',
    ].join('\n'))
  })

  test('normalizeAssistantText preserves fenced write_content for write calls', () => {
    const raw = [
      '<tool_call>',
      '<name>write</name>',
      '<arguments>',
      '<path>app/server.py</path>',
      '</arguments>',
      '</tool_call>',
      '<write_content>',
      '```python',
      'print("smoke ok")',
      '```',
      '</write_content>',
    ].join('\n')

    expect(normalizeAssistantText(raw)).toBe(raw)
    expect(chooseBetterAssistantText('', raw)).toBe(raw)
  })

  test('isPromptExampleToolCall rejects prompt template examples', () => {
    const example = [
      '<tool_call>',
      '<name>tool_name</name>',
      '<arguments>',
      '<arg_name>raw argument value</arg_name>',
      '</arguments>',
      '</tool_call>',
    ].join('\n')
    expect(isPromptExampleToolCall(example)).toBe(true)
    expect(chooseBetterAssistantText('<final_response>hello!</final_response>', example)).toBe('hello!')
  })

  test('isPlaceholderToolCallText rejects collapsed placeholder tool-call artifacts', () => {
    expect(isPlaceholderToolCallText('<tool_call>...</tool_call>')).toBe(true)
    expect(chooseBetterAssistantText('<final_response>hello!</final_response>', '<tool_call>...</tool_call>')).toBe('hello!')
    expect(chooseBetterAssistantText('<tool_call>...</tool_call>', '<final_response>hello!</final_response>')).toBe('hello!')
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
