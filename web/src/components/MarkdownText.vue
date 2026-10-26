<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

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

const html = computed(() => md.render(props.source || ''))
</script>

<template>
  <div class="prose" v-html="html" />
</template>
