请详细描述这张照片的内容，并以严格的 JSON 格式输出，包含以下字段。
每个字段的值必须是基于视觉观察的客观事实，避免主观评价（如“美丽”、“壮观”）。
如果某个信息无法确定，请填写 null。

先判断图像本身是否完整可辨，并把结论写入 image_integrity 字段：
若画面呈现彩条、彩色条纹噪声、花屏、大面积异常纯色块、内容截断等显示损坏，
或画面为标准测试图/测试卡，请如实标记，不要把损坏现象当作拍摄内容来描述。

JSON 结构（请严格遵循）：

```json
{
    "image_type": "string",       // 可能值：["photograph", "screenshot", "illustration", "painting", "diagram", "other"]
    "image_integrity": "string",  // 可能值：["normal", "corrupted", "test_pattern"]；normal=图像完整可辨，corrupted=图像存在显示损坏，test_pattern=标准测试图/测试卡
    "subject": {
    "main_objects": ["list"],   // 主要物体/人物，不超过5个，按显著性排序
    "count": "number",          // 主要对象数量（如果可数）
    "attributes": {             // 关键属性（颜色、大小、姿态、动作）
        "color": "string or list",
        "pose/action": "string",
        "other": "string"
    }
    },
    "scene": {
    "environment": "string",    // 室内/室外/虚拟/不确定
    "setting": "string",        // 具体场景，如 "办公室", "街道", "森林"
    "time_of_day": "string",    // 白天/夜晚/黄昏/清晨/不确定
    "weather": "string"         // 晴/雨/雪/阴/雾/无（室外适用）
    },
    "lighting": {
    "source": "string",         // 自然光/人工光/混合/未知
    "brightness": "string",     // 明亮/适中/昏暗
    "contrast": "string"        // 高对比/中等/低对比
    },
    "color_palette": {
    "dominant_colors": ["list"], // 主色调（最多3种）
    "overall_tone": "string"    // 暖色/冷色/中性
    },
    "composition": {
    "focus": "string",          // 主体位置 (如 "中心", "偏左", "前景")
    "depth": "string",          // 景深层次 (如 "浅景深", "广角深景")
    "symmetry": "string"        // 对称/非对称/半对称
    },
    "background": {
    "description": "string",    // 背景内容简述
    "blur": "string"            // 模糊/清晰/部分模糊
    },
    "foreground": {
    "description": "string",    // 前景内容（如果有）
    "overlaps_main": "boolean"  // 是否遮挡主体
    },
    "text_and_symbols": "string", // 图像中可见的文字、符号或标志（若无则填 null）
    "mood": "string",             // 氛围词汇（如 "平静", "紧张", "欢快"），尽量客观
    "overall_summary": "string"   // 一句话总结图像主要内容（不超过30字）
}
```

输出示例

```json
{
  "image_type": "photograph",
  "image_integrity": "normal",
  "subject": {
    "main_objects": ["一只橘猫", "一个毛线球"],
    "count": 2,
    "attributes": {
      "color": "橘色猫, 蓝色毛线球",
      "pose/action": "猫正在用爪子拨弄毛线球",
      "other": "猫的耳朵竖起，眼神专注"
    }
  },
  "scene": {
    "environment": "室内",
    "setting": "客厅",
    "time_of_day": "白天",
    "weather": null
  },
  "lighting": {
    "source": "自然光",
    "brightness": "明亮",
    "contrast": "中等"
  },
  "color_palette": {
    "dominant_colors": ["橘色", "米白", "蓝色"],
    "overall_tone": "暖色"
  },
  "composition": {
    "focus": "中心偏下",
    "depth": "浅景深",
    "symmetry": "非对称"
  },
  "background": {
    "description": "模糊的沙发和书架",
    "blur": "模糊"
  },
  "foreground": {
    "description": "一块木质地板",
    "overlaps_main": false
  },
  "text_and_symbols": null,
  "mood": "活泼",
  "overall_summary": "一只橘猫在客厅地板上玩蓝色毛线球"
}
```
