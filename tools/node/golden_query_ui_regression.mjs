/**
 * 黄金用例选图回归：只走打开、填写、覆盖层取消和草稿恢复，不写入业务数据。
 * 依赖本地 web(:10006)、agent(:10005)、backend(:10004) 已启动。
 */
import { chromium } from 'playwright'

const baseUrl = process.env.WEB_URL || 'http://127.0.0.1:10006'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

try {
  await page.goto(`${baseUrl}/#/golden-queries`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '新建', exact: true }).click()
  await page.getByPlaceholder('例如：佛像和人的合照').fill('回归草稿无需保存')
  await page.getByPlaceholder('可留空').first().fill('回归')
  await page.getByRole('button', { name: '选择照片（进入图片管理选图）' }).click()

  await page.locator('.pick-overlay').waitFor({ state: 'visible' })
  await page.getByRole('button', { name: '完成选择', exact: true }).waitFor()
  await page.getByRole('button', { name: '取消', exact: true }).last().click()

  await page.getByPlaceholder('例如：佛像和人的合照').waitFor({ state: 'visible' })
  const query = await page.getByPlaceholder('例如：佛像和人的合照').inputValue()
  const category = await page.getByPlaceholder('可留空').first().inputValue()
  if (query !== '回归草稿无需保存' || category !== '回归') {
    throw new Error(`取消覆盖层后草稿未恢复: query=${query}, category=${category}`)
  }

  console.log('PASS: 黄金用例选图覆盖层打开、取消与草稿恢复')
} finally {
  await browser.close()
}
