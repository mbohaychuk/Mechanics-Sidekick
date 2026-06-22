import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '../markdown'

describe('renderMarkdown', () => {
  it('renders the common markdown the model emits', () => {
    expect(renderMarkdown('**bold**')).toContain('<strong>bold</strong>')
    expect(renderMarkdown('*italic*')).toContain('<em>italic</em>')
    expect(renderMarkdown('`P0420`')).toContain('<code>P0420</code>')
    const list = renderMarkdown('- one\n- two')
    expect(list).toContain('<ul>')
    expect(list).toContain('<li>one</li>')
  })

  it('escapes raw HTML instead of executing it (no XSS via the model output)', () => {
    const out = renderMarkdown('hello <script>alert(1)</script>')
    expect(out).not.toContain('<script>')
    expect(out).toContain('&lt;script&gt;')
  })

  it('does not emit javascript: links', () => {
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('href="javascript:')
  })
})
