# 剧本因果链审阅报告

> 生成时间：2026-06-19 04:30:23

> 检查对象：`chapters`

## 📊 总览

| 指标 | 数值 |
|------|------|
| 结局总数 | 6 |
| ✅ 可达结局 | 5 |
| ❌ 不可达结局 | 1 |
| 🔴 错误 | 2 |
| 🟡 警告 | 0 |
| 🔵 提示 | 0 |
| **问题合计** | **2** |


## 🗂️ 结局跨章节分布

| 结局名称 | 涉及章节 | 跨越章节数 |
|----------|----------|------------|
| 井中永生结局 | chap3\_jieju.md → chap2\_zhenxiang.md → chap1\_laozhai.md | 3 |
| 井底真相结局 | chap3\_jieju.md → chap2\_zhenxiang.md → chap1\_laozhai.md | 3 |
| 坠入深渊结局 | chap3\_jieju.md → chap2\_zhenxiang.md → chap1\_laozhai.md | 3 |
| 被母亲带走结局 | chap3\_jieju.md → chap2\_zhenxiang.md → chap1\_laozhai.md | 3 |
| 逃离老宅结局 | chap3\_jieju.md → chap2\_zhenxiang.md → chap1\_laozhai.md | 3 |


## 🔍 问题清单

### 📌 结局：(未关联结局) （1 条）

### 1. 🔴 [错误] 条件冲突

**问题描述**：物品「日记」在chap1\_laozhai.md:13被失去/烧毁/消耗，但在chap1\_laozhai.md:14的条件中仍然需要它

**涉及章节**：chap1_laozhai.md、chap1_laozhai.md

**修复建议**：在chap1\_laozhai.md:13后移除对「日记」的条件要求，或在那里不要失去该物品

<details>
<summary>查看技术细节（选择链/路线片段）</summary>

**玩家选择链**：

```text
  [chap1_laozhai.md:7] 选择「去卧室」
  [chap1_laozhai.md:12] 选择「烧毁日记」
```

**完整路线片段**：

```text
  ↳ [chap1_laozhai.md:4] 第一章 老宅
  ↳ [chap1_laozhai.md:5] 主角回到已故母亲的老宅，整理遗物。
  ↳ [chap1_laozhai.md:6] 打开门厅抽屉
  ↳ [chap1_laozhai.md:7] 选择:去卧室
  ↳ [chap1_laozhai.md:8] 翻找床头柜
  ↳ [chap1_laozhai.md:12] 选择:烧毁日记
  ↳ [chap1_laozhai.md:13] 烧掉日记
  ↳ [chap1_laozhai.md:14] 条件:日记
```

</details>

---


### 📌 结局：隐藏真相结局 （1 条）

### 2. 🔴 [错误] 不可达结局

**问题描述**：结局「隐藏真相结局」没有任何有效路径可以到达

**关联结局**：「隐藏真相结局」

**涉及章节**：chap3_jieju.md

**修复建议**：检查进入该结局的条件是否能被满足，或者是否有选择分支能够通向该结局

<details>
<summary>查看技术细节（选择链/路线片段）</summary>

**玩家选择链**：

```text
  [chap1_laozhai.md:7] 选择「去卧室」
  [chap1_laozhai.md:9] 选择「阅读日记」
  [chap3_jieju.md:24] 选择「打开地下室」
```

**完整路线片段**：

```text
  ↳ [chap1_laozhai.md:4] 第一章 老宅
  ↳ [chap1_laozhai.md:5] 主角回到已故母亲的老宅，整理遗物。
  ↳ [chap1_laozhai.md:6] 打开门厅抽屉
  ↳ [chap1_laozhai.md:7] 选择:去卧室
  ↳ [chap1_laozhai.md:8] 翻找床头柜
  ↳ [chap1_laozhai.md:9] 选择:阅读日记
  ↳ [chap1_laozhai.md:10] @clue:日记记载母亲年轻时曾在井下工作
  ↳ [chap1_laozhai.md:11] @flag:读过日记
  ↳ [chap2_zhenxiang.md:21] 前往第三章
  ↳ [chap3_jieju.md:4] 第三章 结局
  ↳ [chap3_jieju.md:24] 选择:打开地下室
  ↳ [chap3_jieju.md:25] 条件:地下室钥匙
  ↳ [chap3_jieju.md:26] 结局:隐藏真相结局
```

</details>

---

