# Photo Agent 专用名词表

> 本文档是项目内中英文专用名词和组件名称的统一入口。
> 新增界面、代码和文档应优先使用这里的标准名称；旧名称只作为兼容说明保留。

## 产品与功能

- **Photo Agent**：项目名称，中文可称“Photo Agent”或“摄影照片助手”。
- **照片库 / Photo Library**：用户导入并由 Photo Agent 管理的全部照片。
- **图片管理 / Photo Management**：浏览、筛选、排序、查看和维护照片库的功能模块。
- **智能相册 / Smart Album**：基于视觉相似度聚类生成的照片集合。
- **主题发现 / Topic Discovery**：从照片集合中发现主题并生成选题建议的功能。
- **图文工坊 / Post Studio**：围绕照片生成图文内容和编辑创作视角的功能模块。
- **黄金用例 / Golden Query**：用于检验语义检索质量的查询、相关照片和评估结果集合。
- **评估 / Evaluation**：使用黄金用例衡量检索质量的过程。

## 选图与连拍

- **照片缩略预览列表 / `PhotoThumbList`**：只读照片展示控件。默认展示首批照片缩略图，剩余照片以文件名列表展示；开启 `autoFit` 后按所在容器宽度动态计算首行缩略图数量。实现文件为 `web/src/components/PhotoThumbList.vue`。
- **图片选择器 / `PhotoPicker`**：通用选图控件。当前以全屏覆盖层实现，负责浏览照片、筛选和多选；实现文件为 `PhotoPickOverlay.vue`。
- **已选照片列表 / `SelectedPhotoList`**：通用已选照片控件，负责展示、移除、预览和连拍精选；实现文件为 `SelectedPhotoList.vue`。
- **选图覆盖层 / `PhotoPickOverlay`**：`PhotoPicker` 的当前实现载体，不作为跨页面的功能名称使用。
- **连拍组 / Burst Group**：由拍摄时间和图像相似度识别出的连续拍摄照片集合。
- **连拍精选 / Burst Curation**：进入连拍组后，从组内选择部分照片的操作。
- **连拍展示级别 / Burst View Level**：照片列表中的连拍展示方式，包括全部展开、精细折叠和粗略折叠。
- **精细连拍组 / Fine Burst Group**：较细粒度的连拍分组。
- **粗略连拍组 / Coarse Burst Group**：较粗粒度的连拍分组。
- **封面照片 / Cover Photo**：代表连拍组显示的照片，不等同于黄金用例中的唯一照片。

### 黄金用例中的选图约定

- 选图和已选照片界面可以暂时以连拍组形式展示。
- 未进行连拍精选的连拍组，在保存黄金用例时展开为组内全部单张照片。
- 进行连拍精选后，已选照片列表中的条目是单张照片。
- 黄金用例的底层存储、评估和追加逻辑只使用单张照片，不使用连拍粒度。

## AI、检索与数据

- **视觉语言模型 / VLM（Vision-Language Model）**：为照片生成视觉描述的多模态模型。
- **向量嵌入 / Embedding**：将文本或照片描述转换为向量，以支持语义相似度检索。
- **检索增强生成 / RAG（Retrieval-Augmented Generation）**：先检索照片或资料，再生成回答的流程。
- **ChromaDB**：项目使用的本地向量数据库。
- **Text-to-SQL**：将自然语言转换为 SQL，用于精确查询照片元数据。
- **LangGraph**：用于编排 SQL、RAG 和 Combined 查询路由的工作流框架。
- **Combined 查询 / Combined Query**：同时使用结构化查询和语义检索的复合查询。
- **全量照片集合 / Photo Collection**：以单张照片为单位保存所有照片向量的集合。
- **精细组图集合 / Fine Burst Collection**：以精细连拍组封面为单位的向量集合。
- **粗略组图集合 / Coarse Burst Collection**：以粗略连拍组封面为单位的向量集合。

## 评估指标与工程术语

- **P@10 / Precision@10**：前 10 个检索结果中的准确比例。
- **Recall**：相关照片中被检索到的比例。
- **MRR（Mean Reciprocal Rank）**：首个相关结果排名倒数的平均值。
- **命中 / Hit**：检索结果中属于黄金用例相关照片的照片。
- **遗漏 / Remaining**：黄金用例标注相关，但没有出现在评估结果中的照片。
- **未命中 / Miss**：出现在检索结果中，但尚未被黄金用例标注的照片。
- **Harness**：围绕工作模式、评估系统和 Trace 日志建立的 AI 开发辅助工程。
- **Trace**：记录一次 AI 流程输入、路由、工具调用和输出的结构化日志。
- **工作模式 / Work Mode**：规划、生成、评估和项目管理等协作流程。

## 命名维护规则

- 组件名称使用 PascalCase，功能概念使用稳定的中英文对照名称。
- `PhotoPicker` 和 `SelectedPhotoList` 是选图体系的标准组件名称。
- `PhotoPickOverlay` 只描述当前覆盖层实现，不替代 `PhotoPicker` 这一抽象名称。
- 同一概念不在新代码中创建新的中英文别名；如确需变更，先更新本文档和相关引用。
