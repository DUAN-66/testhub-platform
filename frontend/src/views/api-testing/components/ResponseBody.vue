<template>
  <pre class="response-content">{{ body }}</pre>
</template>

<script setup>
defineProps({ body: { type: String, default: '' } })
</script>
