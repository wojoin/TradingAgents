<script setup lang="ts">
// A red bull's head: horns, ears, eyes and a broad darker muzzle with nostrils.
defineProps<{ size?: number }>()
</script>

<template>
  <svg :width="size || 22" :height="size || 22" viewBox="0 0 24 24" aria-hidden="true">
    <g fill="#ef4444">
      <path d="M1.4 3.2 C1 7.8 3.6 10.4 7.6 10.2 L8 8.2 C5 8.3 3 6.6 2.8 3.4 Z" />
      <path d="M22.6 3.2 C23 7.8 20.4 10.4 16.4 10.2 L16 8.2 C19 8.3 21 6.6 21.2 3.4 Z" />
      <path d="M2.6 10.8 C3.7 9.8 5.4 10 6.3 11 L6 12.9 C4.7 13.1 3.3 12.5 2.6 10.8 Z" />
      <path d="M21.4 10.8 C20.3 9.8 18.6 10 17.7 11 L18 12.9 C19.3 13.1 20.7 12.5 21.4 10.8 Z" />
      <path d="M7.4 8 H16.6 C18 8 18.7 9 18.6 10.2 L18 16.4 C17.9 17.3 17.3 18 16.5 18.3 H7.5 C6.7 18 6.1 17.3 6 16.4 L5.4 10.2 C5.3 9 6 8 7.4 8 Z" />
    </g>
    <ellipse cx="12" cy="18.7" rx="5.3" ry="3.1" fill="#b91c1c" />
    <g fill="#111827">
      <circle cx="9.9" cy="18.9" r="0.95" />
      <circle cx="14.1" cy="18.9" r="0.95" />
      <circle cx="8.9" cy="12.7" r="0.85" />
      <circle cx="15.1" cy="12.7" r="0.85" />
    </g>
  </svg>
</template>
