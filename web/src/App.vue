<script setup lang="ts">
import {
  darkTheme,
  dateZhCN,
  zhCN,
  NConfigProvider,
  NMessageProvider,
  NLayout,
} from 'naive-ui'
import SideMenu from './components/SideMenu.vue'
</script>

<template>
  <NConfigProvider :theme="darkTheme" :locale="zhCN" :date-locale="dateZhCN">
    <NMessageProvider>
      <NLayout has-sider position="absolute">
        <SideMenu />
        <router-view />
      </NLayout>
    </NMessageProvider>
  </NConfigProvider>
</template>
