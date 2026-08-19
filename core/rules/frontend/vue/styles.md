---
description: 样式规范
paths: ["**/*.vue", "**/*.css", "**/*.scss", "**/*.less"]
alwaysApply: false
---

# 样式规范

适用于本项目 Vue 3 前端样式。采用 **Scoped CSS + CSS 自定义属性（设计 Token）** 方案。

---

## 1. 样式分层

```
src/
├── assets/
│   └── styles/
│       ├── variables.css     # 设计 Token（颜色/间距/字号）
│       ├── reset.css         # CSS Reset
│       ├── typography.css    # 全局字体规则
│       └── utilities.css     # 全局工具类（慎用，保持精简）
└── components/
    └── Button/
        └── Button.vue        # <style scoped> 在组件内
```

**原则：**
- 组件样式写在 `<style scoped>` 内，不污染全局
- 全局样式只存放真正全局的内容（Reset、CSS 变量、字体）
- 禁止在组件中直接写内联样式（`style="..."` 属性）

---

## 2. CSS 自定义属性（设计 Token）

所有颜色、间距、字号必须通过 CSS 变量定义，不允许硬编码。具体 Token 值是项目级设计决策，由各项目在 `assets/styles/variables.css` 中定义，本规范只约定命名与组织原则：

```css
/* assets/styles/variables.css — 项目自行定义具体值，本结构为约定 */
:root {
  /* 颜色：主色按状态梯度（base/hover/active），辅以 success/warning/error */
  --color-primary: /* 项目定义 */;
  --color-primary-hover: /* 项目定义 */;

  /* 文字：primary/secondary/disabled 三级 */
  --color-text-primary: /* 项目定义 */;

  /* 背景：base/secondary/container */
  /* 边框：border/border-secondary */

  /* 间距：4px 栅格，xs/sm/md/lg/xl/2xl */
  --spacing-xs: /* 4 的倍数 */;

  /* 字号：xs/sm/base/lg/xl/2xl/3xl */
  /* 圆角：sm/md/lg/full */
  /* 阴影：sm/md/lg */
  /* 过渡：fast(0.15s)/base(0.2s)/slow(0.3s) */

  /* z-index 层级：dropdown < sticky < modal < toast < tooltip */
}
```

**规则：**
- 颜色值禁止在组件中硬编码（`color: #1677ff` → 用 `var(--color-primary)`）
- 间距禁止使用非 4px 倍数的任意值（除非是 1px 边框）
- Token 命名遵循上述约定，跨项目一致；具体值由设计稿/项目决定

---

## 3. 暗色模式

通过覆盖 CSS 变量切换，不重写组件样式。具体暗色值由项目定义：

```css
/* 暗色主题覆盖——仅覆盖需要变化的变量，结构与亮色一致 */
[data-theme='dark'] {
  --color-text-primary: /* 项目定义 */;
  --color-bg-base: /* 项目定义 */;
  --color-bg-container: /* 项目定义 */;
  --color-border: /* 项目定义 */;
}
```

```ts
// composables/useTheme.ts
export function useTheme() {
  const theme = ref<'light' | 'dark'>('light')

  const toggle = () => {
    theme.value = theme.value === 'light' ? 'dark' : 'light'
    document.documentElement.setAttribute('data-theme', theme.value)
    localStorage.setItem('theme', theme.value)
  }

  return { theme, toggle }
}
```

---

## 4. 组件样式规范

### scoped 样式

```vue
<style scoped>
/* ✅ 直接写类名，scoped 自动加 hash 隔离 */
.card {
  padding: var(--spacing-md);
  border-radius: var(--radius-md);
  background: var(--color-bg-container);
  box-shadow: var(--shadow-sm);
}

.card__title {
  font-size: var(--font-size-lg);
  color: var(--color-text-primary);
  font-weight: 600;
}

.card__footer {
  margin-top: var(--spacing-md);
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--color-border-secondary);
}
</style>
```

### 覆盖子组件样式（:deep）

```vue
<style scoped>
/* ✅ 必须修改第三方组件样式时，用 :deep() */
:deep(.el-input__inner) {
  border-radius: var(--radius-sm);
}

/* ❌ 不要用全局样式覆盖组件库（影响所有实例） */
</style>
```

---

## 5. 命名规范

scoped 已自动隔离作用域，类名**不必强求 BEM 全路径**，简短语义化即可。BEM 仅作命名约定参考，用于表达状态/变体：

```vue
<style scoped>
/* ✅ scoped 后类名简短，直接表意 */
.card { ... }
.card--featured { ... }     /* -- 表状态/变体 */
.avatar { ... }             /* 不必 card__avatar，组件内层级清晰即可 */
.role--admin { ... }
</style>
```

**规则：**
- 类名用 kebab-case，语义化，禁止无意义名（`box`、`div1`）
- `--` 表状态/变体（`card--active`），`__` 可省略（scoped 已隔离）
- 子元素层级深时优先**提取子组件**，而非堆 `__` 选择器
- 禁止选择器嵌套超过 3 层

---

## 6. 响应式与视觉

### 移动优先断点

基础样式针对移动端，媒体查询扩展大屏。断点值由项目 Token 定义：

```css
.layout {
  display: flex;
  flex-direction: column;      /* 移动端纵向 */
}
@media (min-width: 768px) {
  .layout { flex-direction: row; }  /* 大屏横向 */
}
```

### 动画

- 优先 `transform`/`opacity`（GPU 加速、不触发重排），避免动画 `width`/`height`/`margin`
- 时长：微交互 150ms、普通 200-300ms、复杂 ≤500ms
- 必须尊重系统偏好，禁用非必要动画：

```css
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

路由/组件过渡用 Vue `<Transition name="fade" mode="out-in">`，过渡类引用 Token：`transition: opacity var(--transition-base)`。

### 布局

- 优先 Flexbox（一维对齐）和 Grid（二维栅格），禁用 `float` 布局
- `position: absolute` 仅用于脱离文档流的场景（覆盖层、提示），不用于常规流布局
- 禁硬编码宽高，用 `min-height`/`max-width`/百分比/`fr` 代替
- 禁 `width: 100vw`（滚动条导致布局抖动，用 `100%`）

禁止：
- ❌ `position: absolute` 用于常规文档流布局
- ❌ 使用 `float` 布局
- ❌ 硬编码宽高（用 `min-height`、`max-width`、百分比代替）

---

## 7. 可访问性（A11y）

```vue
<template>
  <!-- ✅ 图片必须有 alt -->
  <img :src="user.avatar" :alt="`${user.name}的头像`" />

  <!-- ✅ 图标按钮必须有 aria-label -->
  <button aria-label="关闭对话框" @click="close">
    <CloseIcon />
  </button>

  <!-- ✅ 表单必须有 label 关联 -->
  <label for="username">用户名</label>
  <input id="username" v-model="form.username" />

  <!-- ✅ 模态框管理焦点 -->
  <dialog role="dialog" aria-modal="true" aria-labelledby="dialog-title">
    <h2 id="dialog-title">确认操作</h2>
  </dialog>
</template>
```

---

## 8. 禁止行为

- ❌ 内联样式（`style="color: red"`）
- ❌ 硬编码颜色值（使用 CSS 变量）
- ❌ `!important`（用更具体的选择器）
- ❌ 全局覆盖组件库样式（影响所有实例）
- ❌ CSS 选择器嵌套超过 3 层
- ❌ 组件内定义全局 `<style>`（无 `scoped`），除非有明确意图
- ❌ `width: 100vw`（忽略滚动条导致布局抖动，用 `width: 100%`）
