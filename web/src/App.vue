<script setup lang="ts">
import {
  darkTheme,
  dateZhCN,
  zhCN,
  NConfigProvider,
  NMessageProvider,
} from 'naive-ui'
import PhotoManagement from './views/PhotoManagement.vue'
</script>

<template>
  <NConfigProvider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN">
    <NMessageProvider>
      <PhotoManagement />
    </NMessageProvider>
  </NConfigProvider>
</template>
