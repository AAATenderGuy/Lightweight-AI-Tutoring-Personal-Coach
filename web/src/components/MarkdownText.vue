<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps({
  source: { type: String, default: '' },
})

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const defaultLinkOpen = md.renderer.rules.link_open
md.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  if (defaultLinkOpen) return defaultLinkOpen(tokens, index, options, env, self)
  return self.renderToken(tokens, index, options)
}

/**
 * 模型讲数学题时几乎必然输出 LaTeX（$...$ / $$...$$），而 markdown-it 不认识它。
 * 做法：先把公式抠出来渲染成 KaTeX HTML，用占位符顶住，走完 markdown-it 再换回去。
 * 这样不用装 markdown 插件，也不会被 html:false 过滤掉。
 */
const PLACEHOLDER = /@@MATH:(\d+)@@/g

function extractMath(source) {
  const blocks = []
  const stash = (tex, display) => {
    const cleaned = String(tex || '').trim()
    if (!cleaned) return ''
    try {
      blocks.push(katex.renderToString(cleaned, {
        displayMode: display,
        throwOnError: false,
        strict: false,
        output: 'html',
      }))
    } catch {
      blocks.push('')
    }
    return `@@MATH:${blocks.length - 1}@@`
  }

  let text = String(source || '')
  // 块级公式先切，避免 $$ 被拆成两个配对的 $
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_m, tex) => stash(tex, true))
  // 行内公式：$...$，不跨行，前面不能是反斜杠或 $
  text = text.replace(/(^|[^\\$])\$([^$\n]+?)\$/g, (_m, prefix, tex) => prefix + stash(tex, false))
  return { text, blocks }
}

const html = computed(() => {
  const { text, blocks } = extractMath(props.source)
  const rendered = md.render(text)
  return rendered.replace(PLACEHOLDER, (_m, index) => blocks[Number(index)] || '')
})
</script>

<template>
  <div class="prose" v-html="html" />
</template>
