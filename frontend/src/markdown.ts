import MarkdownIt from 'markdown-it'

// Renders the assistant's markdown (bold, italic, lists, inline code / code blocks, links, headings)
// to HTML for display. Safety: `html: false` escapes any raw HTML in the model output — a stray
// <script> renders as literal text, never executed — and markdown-it's default validateLink rejects
// javascript:/vbscript:/data: URLs. So the output is safe to v-html without a separate sanitizer.
// `breaks: true` turns single newlines into <br>, matching how the model lays out short answers.
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

export function renderMarkdown(src: string): string {
  return md.render(src)
}
