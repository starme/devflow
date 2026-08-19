---
description: Vue 3 开发规范
paths: ["**/*.vue", "**/*.ts", "**/*.tsx", "**/*.js"]
alwaysApply: false
---

# Vue 3 开发规范

适用于本项目 Vue 3 前端代码。技术栈：Vue 3 + TypeScript + Pinia + Vue Router + Vitest。

---

## 1. 组件基础规范

### 必须使用 `<script setup>` + TypeScript

```vue
<!-- ✅ 标准结构 -->
<script setup lang="ts">
import { ref, computed } from 'vue'

interface Props {
  userId: number
  title?: string
}

const props = withDefaults(defineProps<Props>(), {
  title: '默认标题',
})

const emit = defineEmits<{
  update: [value: string]
  close: []
}>()
</script>

<template>
  <div>...</div>
</template>

<style scoped>
/* 组件样式 */
</style>
```

禁止：
- ❌ Options API（`export default { data(), methods: {} }`）
- ❌ `defineProps` 不带泛型类型
- ❌ `any` 类型（除非第三方库无类型声明）

### 文件命名

- 组件：`PascalCase.vue`（`UserCard.vue`、`OrderList.vue`）
- 页面：`PascalCase.vue`，放在 `views/` 或 `pages/` 目录
- 组合函数：`use` 前缀，`camelCase.ts`（`useUserStore.ts`、`useAuth.ts`）

---

## 2. 响应式数据

### ref vs reactive 选择原则

官方推荐 **ref 优先**，reactive 仅用于一组需作为整体操作的状态：

```ts
// ✅ 默认用 ref（基础类型、对象都适用）
const count = ref(0)
const name = ref('')
const isLoading = ref(false)
const form = ref({
  username: '',
  email: '',
  age: 0,
})
// 解构 form 用 toValue / 直接 form.value.xxx，响应式不丢失

// ✅ 仅当一组相关状态需作为整体传递/重置时用 reactive
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })

// ❌ 不要用 reactive 包裹基础类型
const count = reactive({ value: 0 }) // 冗余

// ❌ 不要解构 reactive 对象（丢失响应式）
const { username } = form // username 不再响应式
// ✅ 需解构用 toRefs
const { page, pageSize } = toRefs(pagination)
```

> 选择理由：ref 对基础类型和对象统一，解构安全（`.value` 一致）；reactive 的解构陷阱多。reactive 仅在状态强内聚、需整体操作时用。

### computed 规范

```ts
// ✅ 有明确依赖、只读
const fullName = computed(() => `${firstName.value} ${lastName.value}`)

// ✅ 需要 setter 时使用 get/set
const modelValue = computed({
  get: () => props.value,
  set: (val) => emit('update:modelValue', val),
})

// ❌ 不要在 computed 中产生副作用
const total = computed(() => {
  fetchData() // 禁止！
  return list.value.length
})
```

---

## 3. 模板规范

### v-for 必须绑定 key，禁止用 index

```vue
<!-- ✅ 用唯一业务 ID -->
<li v-for="item in list" :key="item.id">{{ item.name }}</li>

<!-- ❌ 用 index 作为 key（排序/删除时 DOM 复用错误） -->
<li v-for="(item, index) in list" :key="index">{{ item.name }}</li>
```

### v-if vs v-show 选择

```vue
<!-- ✅ 条件不频繁切换，或初始不渲染：用 v-if -->
<UserProfile v-if="isLoggedIn" />

<!-- ✅ 频繁切换（tab 切换、折叠面板）：用 v-show -->
<TabPanel v-show="activeTab === 'profile'" />

<!-- ❌ v-if 和 v-for 不放在同一元素上 -->
<li v-for="item in list" v-if="item.active" :key="item.id" />
<!-- ✅ 改为 computed 过滤后再渲染 -->
<li v-for="item in activeList" :key="item.id" />
```

### 事件处理

```vue
<!-- ✅ 简单调用：直接引用函数 -->
<button @click="handleSubmit">提交</button>

<!-- ✅ 需要传参：用箭头函数 -->
<button @click="() => handleDelete(item.id)">删除</button>

<!-- ❌ 不要在模板中写复杂逻辑 -->
<button @click="list = list.filter(i => i.id !== item.id); count--">删除</button>
```

---

## 4. 组合函数（Composables）

### 规范结构

```ts
// composables/useCounter.ts
export function useCounter(initialValue = 0) {
  const count = ref(initialValue)

  const increment = () => count.value++
  const decrement = () => count.value--
  const reset = () => (count.value = initialValue)

  return { count: readonly(count), increment, decrement, reset }
}
```

**规则：**
- 函数名必须以 `use` 开头
- 返回值用对象解构（不用数组，除非像 `useState` 那样有明确语义）
- 对外暴露的响应式数据用 `readonly()` 包裹，避免外部直接修改
- 副作用（事件监听、定时器）在 `onUnmounted` 中清理

### 异步数据获取模式

```ts
// composables/useUserList.ts
export function useUserList() {
  const list = ref<User[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  const fetchList = async (params?: ListParams) => {
    isLoading.value = true
    error.value = null
    try {
      const res = await userApi.getList(params)
      list.value = res.data.list
    } catch (e) {
      error.value = e instanceof Error ? e.message : '请求失败'
    } finally {
      isLoading.value = false
    }
  }

  return { list, isLoading, error, fetchList }
}
```

---

## 5. Pinia 状态管理

### Store 结构（Composition API 风格）

```ts
// stores/user.ts
import { defineStore } from 'pinia'

export const useUserStore = defineStore('user', () => {
  // state
  const userInfo = ref<UserInfo | null>(null)
  const token = ref(localStorage.getItem('token') ?? '')

  // getters
  const isLoggedIn = computed(() => !!token.value)
  const displayName = computed(() => userInfo.value?.nickname ?? '未登录')

  // actions
  async function login(params: LoginParams) {
    const res = await authApi.login(params)
    token.value = res.data.token
    localStorage.setItem('token', token.value)
    userInfo.value = res.data.userInfo
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('token')
  }

  return { userInfo, token, isLoggedIn, displayName, login, logout }
})
```

**规则：**
- 使用 Composition API 风格（不用 Options 风格的 `state/getters/actions`）
- Store 文件放在 `stores/` 目录，以功能模块命名
- 跨模块状态访问：直接在需要的 store 中引入另一个 store
- 禁止在组件外（路由守卫除外）直接修改 store 的 state

---

## 6. Vue Router

### 路由配置

```ts
// router/index.ts
const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'), // 懒加载
    meta: { requiresAuth: false },
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { requiresAuth: true, title: '工作台' },
  },
]
```

**规则：**
- 所有路由组件必须懒加载（`() => import(...)`）
- 路由 `name` 使用 PascalCase
- 权限相关信息放在 `meta` 中，在全局守卫中统一处理

### 导航守卫

```ts
router.beforeEach((to, _from) => {
  const userStore = useUserStore()
  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
})
```

### 编程式导航

```ts
// ✅ 使用 name 导航（路径变化不影响代码）
router.push({ name: 'UserDetail', params: { id: userId } })

// ❌ 硬编码路径（路径重构时遗漏）
router.push('/user/' + userId)
```

---

## 7. API 请求层

### 封装结构（与后端风格无关）

```ts
// api/user.ts
import request from '@/utils/request'

export const userApi = {
  // URL 路径风格以后端 API 文档为准，前端不自行约定
  // RPC 风格示例（Go 后端常用）：POST /user/list、POST /user/getDetail、POST /user/create
  // RESTful 风格示例（PHP 后端常用）：GET /users、GET /users/:id、POST /users
  getList: (params?: UserListParams) =>
    request.post<ListResponse<User>>('/user/list', params),
  getDetail: (userId: number) =>
    request.post<User>('/user/getDetail', { userId }),
  create: (params: CreateUserParams) =>
    request.post<{ userId: number }>('/user/create', params),
}
```

**通用规则：**
- API 按模块组织，每个模块一个文件
- 统一通过封装好的 `request` 实例发请求（拦截器处理 token、错误码）
- 响应类型必须声明泛型，禁止 `any`
- 禁止在组件中直接使用 `fetch`/`axios`
- URL 路径风格（RPC 单数 / RESTful 复数、GET 读 / POST 写）**以后端 API 文档为准**，前端照调用，不在前端规范里约定

### 请求拦截器模板

```ts
// utils/request.ts
instance.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

instance.interceptors.response.use(
  (res) => res.data,
  (error) => {
    if (error.response?.status === 401) {
      router.push({ name: 'Login' })
    }
    return Promise.reject(error)
  }
)
```

---

## 8. 性能规范

```vue
<!-- ✅ 大列表使用虚拟滚动（vue-virtual-scroller 或 vueuse/useVirtualList） -->
<RecycleScroller :items="bigList" :item-size="60" key-field="id" v-slot="{ item }">
  <ListItem :data="item" />
</RecycleScroller>

<!-- ✅ 纯展示组件（无响应式依赖）用 v-once -->
<StaticBanner v-once />

<!-- ✅ 稳定子树用 v-memo 避免不必要更新 -->
<div v-memo="[item.id, item.status]">
  <HeavyComponent :item="item" />
</div>
```

**规则：**
- 超过 50 条的列表必须虚拟化或分页
- 图片使用懒加载（`loading="lazy"` 或 `v-lazy`）
- 非首屏组件用 `defineAsyncComponent` 异步加载
- 避免在模板中使用复杂的内联计算——提取为 `computed`

---

## 9. 错误处理

```ts
// 全局错误边界：捕获未处理异常
app.config.errorHandler = (err, instance, info) => {
  console.error('全局错误:', err, info)
  // 上报错误监控
}
```

异步数据错误在 composable 内 try/catch 暴露 `error` 状态（见 §4 useUserList），组件据此渲染：

```vue
<template>
  <ErrorBoundary v-if="error" :error="error" @retry="fetchData" />
  <LoadingSkeleton v-else-if="isLoading" />
  <slot v-else />
</template>
```

**规则：**
- 异步请求必须 catch，错误写入响应式 `error` 供模板展示，禁止吞掉
- 全局 `errorHandler` 兜底未捕获异常并上报
- 用户可见错误给可重试入口（如 ErrorBoundary 的 retry），不只是 console

---

## 10. 测试规范（Vitest + Vue Test Utils）

```ts
// UserCard.test.ts
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import UserCard from './UserCard.vue'

describe('UserCard', () => {
  it('displays user name', () => {
    const wrapper = mount(UserCard, {
      props: { userId: 1, name: 'Alice' },
      global: {
        plugins: [createTestingPinia()],
      },
    })
    expect(wrapper.text()).toContain('Alice')
  })

  it('emits close event on button click', async () => {
    const wrapper = mount(UserCard, { props: { userId: 1, name: 'Alice' } })
    await wrapper.find('[data-testid="close-btn"]').trigger('click')
    expect(wrapper.emitted('close')).toBeTruthy()
  })
})
```

**规则：**
- 测试选择器优先使用 `data-testid` 属性，不用 CSS 类名
- Store 测试用 `createTestingPinia`，不真实发请求
- 禁止在测试中直接操作 DOM（`document.querySelector`）
- 每个公共组件必须有测试文件

---

## 11. 禁止行为

- ❌ Options API
- ❌ 在 `<template>` 中直接修改 props
- ❌ 父组件直接访问子组件内部数据（除 `defineExpose` 显式暴露）
- ❌ 在 `watch` 中执行大量同步计算（用 `computed`）
- ❌ 未清理的定时器/事件监听（`onUnmounted` 中清理）
- ❌ 组件超过 300 行不拆分
- ❌ 一个 `.vue` 文件中超过 5 个 `ref`（提取为 composable）
