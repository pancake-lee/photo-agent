# 导入工作流 W1-W4 评估报告

- **报告 ID**：eval-a3f8c2d91e4b
- **日期**：2026-08-18T10:30:00
- **对象**：导入工作流（Windows 客户端）：W1 Wails 工程搭建 + W2 服务端 NEF 存储与 storage/info + W3 客户端文件操作 + W4 前端导入三步流程页面

## 摘要

**总分 7.7/10 ✅ 通过**（阈值 6.0）。

导入工作流 W1-W4 整体质量良好，是四阶段中最完整的一轮落地：实测 146 JPG + 113 NEF 正确落盘入库，分类比对、EXIF 时间、重名冲突检测的核心逻辑均正确且有单测覆盖。代码结构上纯函数/绑定分离、前后端类型对应、注释充分，是明显的加分项。主要失分集中在边界与体验层面：配置模板 PhotoSrc/StorageRoot 分叉（实际 .local 配置规避了它）、上传长任务无进度反馈、storage/info 的 warning 字段被前端丢弃、overwrite 不回写 shot_at。惊喜度与 AI 增量两维度对文件导入类工具不适用，未纳入评分。

## 分维度评分

### 代码质量

#### 正确性 8

得分点：

- 实测数据正确：146 张 JPG + 113 张 NEF 落盘到 202608-山西旅游/，DB 记录 146 jpg + 113 nef 一一对应，file_path 正确携带 folder 归档目录
- NEF 的 shot_at 正确从 EXIF 提取入库（服务端 createPhotoRecord 对 NEF 也读 EXIF），非空率为 100%
- 四类 NEF 分类（收藏/已迁移/留存/废弃）逻辑正确，compareNef 用基础名去扩展名+小写匹配，有单元测试覆盖
- 归档目录命名 YYYYMM-活动名（- 分隔符）前后端一致，client folderName 与 server activityDirRe 吻合
- 重名冲突检测 storage/conflicts 与上传时的 sanitizeFilename 判重规则一致

失分点：

- configs/config.yaml 模板中 PhotoSrc(./data/photos/src) 与 StorageRoot(./data/photos_src) 指向不同目录：上传落盘目录与 storage/info 扫描目录分叉。用户实际 .local/pancake.yaml 里两者同为 /root/share/photo-agent/pic-like/ 才未暴露，按模板部署会踩坑
- overwritePhoto 未回写 shot_at/latitude/longitude/altitude，覆盖同名文件时新文件的拍摄时间不会更新到 DB（同文件名通常拍摄时间相同，边界上仍缺失）

#### 健壮性 7

得分点：

- 所有绑定方法统一 recoverPanic，避免 Wails 进程无信息崩溃，堆栈落日志文件
- 上传并发 3 + 单文件超时 10min，NEF 大文件有足够时间；storage/info 单独 2s 超时
- 客户端复制/上传回写原始 mtime（copyFile + preserveTimes 双平台 build tag 实现）
- scanDir 对无 EXIF 文件回退修改时间；异常日期用相邻最大间隙启发式（7 天阈值），有测试覆盖
- 上传前冲突预检 checkConflicts，skip 模式避免重复传输已存在文件

失分点：

- uploadOneFile 无重试机制，网络抖动导致单文件 failed 后需用户手动重新同步
- countFiles 的 WalkDir 回调遇 err 直接 return nil，子目录无权限时静默少算且无提示
- handleStorageInfo 存储根不可访问时返回 200 + warning 字段而非错误，但前端未渲染 warning（见完整性维度）
- 客户端为防 goexif 卡死而跳过 NEF 的 EXIF 读取，但服务端 createPhotoRecord 仍对 NEF 调用 exif.Decode，前后端对 NEF 安全性判断矛盾，若 goexif 真会卡 NEF 则服务端同样会卡

#### 可维护性 8

得分点：

- 纯函数与绑定委托分离（import.go/sync.go 不依赖 Wails，app.go 仅做绑定），单测无需 Wails 环境
- 前后端类型定义清晰：Go json tag 与 TS interface 一一对应，wails.ts 集中定义返回类型
- 注释充分且解释了非常规点：时间戳保留策略、Windows 坐标系统换算、queryLastSync 的 SQLite 时间扫描坑
- window/logging/times 按平台 build tag 拆分，跨平台编译边界清晰

失分点：

- ImportWorkflow.vue 单文件 868 行（模板+脚本+样式混排），超出理想单文件规模，后续维护成本上升
- sync 的 skip/overwrite/空 resolution 三种语义散在注释里，缺少统一枚举类型

#### 简洁性 8

得分点：

- 无明显 dead code：CheckConflicts/ConflictCheck/StorageInfo 等类型均被使用
- 异常日期检测用简单启发式而非引入复杂统计依赖，符合小体量项目定位
- 同步并发用 channel semaphore 实现，简洁直接


### 功能效果

#### 准确性 8

得分点：

- 实测落盘文件与 DB 记录一致，folder 字段正确传递到服务端入库
- 统计摘要（full/收藏/NEF 四类计数）与时间范围、异常警告逻辑与设计一致

失分点：

- countFiles 把 png/webp 也计入 jpg_count，字段名与实际口径轻微不符（当前存储仅 jpg/nef 未暴露）

#### 完整性 7

得分点：

- W1-W4 四个阶段全部落地：Wails 工程、NEF 存储、storage/info、三步前端页面
- 三步流程覆盖新建/分析/上传全链路，异常分支（missing NEF、outliers、no date、冲突重名）均有 UI
- 前端非 Wails 环境有守护卡片提示，菜单入口正确隐藏

失分点：

- storage/info 返回的 warning 字段前端未渲染，存储根不可访问时用户看到全 0 状态却无任何提示
- 上传完成后无「清空中转目录」收尾步骤或提醒，闭环靠用户自觉（设计原文有清空意图，UI 未落地）

#### 一致性 8

得分点：

- 前端 NaiveUI 组件风格与现有页面一致（NCard/NSteps/NDescriptions/NAlert 等）
- 归档命名 YYYYMM-活动名 前后端一致，storage/info 的 months/activities 与前端 folderExistsOnServer 判断吻合
- isWails 环境检测正确区分浏览器/Wails，导入入口只在桌面环境出现

失分点：

- 客户端跳过 NEF EXIF 读取（防卡死）vs 服务端仍读 NEF EXIF，前后端对 goexif 对 NEF 是否安全的判断不一致


### 用户价值

#### 可用性 8

得分点：

- 把原本手动的建目录/比对/迁移/上传四件事串成三步引导，显著降低误操作
- 中转目录路径 localStorage 记忆，下次打开自动回填
- 异常文件（缺 NEF / 无拍摄时间）折叠列表可点击预览，便于核对
- 迁移仅复制不删除，数据安全（NEF 删除交还用户）

失分点：

- 服务器地址默认 localhost:10004，Windows 客户端连真实服务器需手动改 IP，无历史地址记忆

#### 交互体验 7

得分点：

- 每步有 loading 状态与成功/失败 message 提示
- 冲突二次确认弹窗（跳过/覆盖），避免误覆盖服务端已有文件
- 上传结果显示成功/跳过/失败/耗时，失败可展开看逐文件详情
- 刷新按钮、上一步/下一步导航清晰

失分点：

- 上传 259 个文件（含约 16MB 的 NEF）时只有按钮 spinner，无逐文件/百分比进度，长等待下用户难以判断是否卡死
- 服务器地址填错时，连接验证（2s 超时）能快速发现，但若地址在验证后失效，同步阶段（10min 超时）才报错

## 下一步建议

- configs/config.yaml 模板中 PhotoSrc 与 StorageRoot 指向不同目录，按模板部署时 storage/info 扫描目录与上传落盘目录不一致
- storage/info 返回的 warning 字段前端未消费，存储根不可访问时用户无提示
- 上传阶段（大量文件含大体积 NEF）无进度反馈，仅按钮 loading
- overwritePhoto 未回写 shot_at/GPS 字段，覆盖同名文件时新拍摄时间不更新
- 客户端与服务端对 NEF 的 goexif EXIF 读取策略不一致（客户端跳过、服务端仍读）
