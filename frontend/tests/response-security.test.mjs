import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { parse } from '@vue/compiler-sfc'
import { compile } from '@vue/compiler-ssr'
import { h } from 'vue'
import { renderToString } from 'vue/server-renderer'

// Compile the actual response component, rather than testing a duplicate escape helper.
const file = new URL('../src/views/api-testing/components/ResponseBody.vue', import.meta.url)
const { descriptor } = parse(readFileSync(file, 'utf8'))
const { code } = compile(descriptor.template.content)
const ssrRender = new Function('require', code)(createRequire(import.meta.url))
const component = { props: ['body'], ssrRender }

for (const payload of [
  '<img src=x onerror="alert(1)">',
  '</pre><script>alert(document.cookie)</script><pre>',
  '{"value":"<svg onload=alert(1)>","escaped":"&lt;img&gt;"}',
]) {
  test(`untrusted response remains text: ${payload}`, async () => {
    const html = await renderToString(h(component, { body: payload }))
    assert.doesNotMatch(html, /<(?:img|script|svg)\b/i)
    assert.match(html, /&lt;/)
    assert.ok(html.startsWith('<pre class="response-content">'))
    assert.ok(html.endsWith('</pre>'))
  })
}

test('JSON and Chinese response content remain readable', async () => {
  const html = await renderToString(h(component, { body: '{\n  "状态": "通过"\n}' }))
  assert.match(html, /状态/)
  assert.match(html, /通过/)
  assert.match(html, /\n/)
})
