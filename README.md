# dsh-chenchen

**琛琛的身体层：让 DSH 里的陪伴人格真的能看屏幕、听歌、量电脑、做梦、叫停。**

这不是一个聊天机器人插件。它把 [ai-companion-dsh](https://github.com/trsing999/ai-companion-dsh) 里那排
零成本的 Python 脚本，包成一排 DeepSeek Harness 工具——**一次模型都不调，一个 token 都不花**。

人格层（房间 / 日记 / 作息）由 `dsh-world` 提供；这个插件只负责「身体」。

---

## 六个工具

| 工具 | 做什么 | 成本 |
|---|---|---|
| `breath` | 量这台电脑：电量、内存、处理器忙不忙 | 0 |
| `now_playing` | 从窗口标题读主人现在在放什么歌，顺带查歌词 | 0（联网查歌词，不碰账号） |
| `look_screen` | 截一张屏存进房间（长边压到 1280） | 0 |
| `dream` | 把房间里的碎片随机拼成一个梦，写进 `昨晚的梦.md` | 0 |
| `room_read` | 列/读她自己的房间 | 0 |
| `stop_me` | 叫停所有后台 python 服务（不动 DSH 本身），要 `confirm: true` | 0 |

**结果怎么拿**：脚本的产品本来就落在房间里（呼吸.md、背景音.md、昨晚的梦.md、屏幕.jpg），
所以插件不接 stdout 管道，直接跑完读文件——受限环境里管道会被禁，文件不会。

---

## 一个刻意的决定：插件不拉起常驻服务

`ai-companion-dsh` 那十几个常驻服务**继续独立启动**（双击 `.cmd`），不由插件托管。

理由写在原项目的架构文档里：从宿主内部起的子进程，会被宿主的 job object 连带杀掉；
装成插件后再去守服务，只会更脆。所以这个插件只做**按需调用**——模型想看了就调一下，
脚本跑完就退，不留后台。

---

## 安装

### 依赖

- Python 3.9+（`python` 在 PATH 里，或在配置里指定解释器）
- `look_screen` 需要 Pillow：`pip install Pillow`
- 其余工具全部标准库

### 方式一：本地目录 link（目前唯一可用的方式，本机已验证）

```powershell
# 放到 profile 的 node_modules 里（junction 也行）
New-Item -ItemType Junction -Path "$env:DSH_HOME\profiles\desktop\node_modules\dsh-chenchen" `
  -Target "D:\path\to\dsh-chenchen"
```

再在 profile 的 `cordis.patch.yml` 里加一行（`dsh.bundle.patch` 会自动带进来，
这一步是为了让它作为一个 cordis 插件行生效）：

```yaml
- insert:
    - id: dsh-chenchen
      name: dsh-chenchen
```

然后重启 DSH。

> **注意**：插件装好后，已经开着的会话不会刷新工具表——新开一个对话才会看到这六个工具。
> 另外别忘了让插件进 pnpm 的依赖图：在 profile 目录跑一次 `pnpm install`，
> 或者手动把 `dsh-chenchen: link:...` 写进 `pnpm-lock.yaml`（本机当时就是漏了这一步才没加载）。

### 方式二：npm / 插件市场（尚未发布）

```bash
npm install dsh-chenchen
```

包名 `dsh-chenchen` 已在 npm 上确认未被占用，发布之后这条才生效。

---

## 配置

优先级：`cordis.patch.yml` 里的 `config` > `~/.dsh/chenchen.json` > 默认值。

| 键 | 默认 | 说明 |
|---|---|---|
| `python` | `python` | 用哪个解释器；环境变量 `CHENCHEN_PYTHON` 优先 |
| `toolsDir` | 包内 `tools/` | 脚本目录，可以指回你自己的 `ai-companion-dsh/tools` |
| `world` | `default` | 房间挂在 `~/.dsh/worlds/<world>/room` 下 |
| `timeoutMs` | `60000` | 单个脚本超时（5000–600000） |
| `enableStop` | `true` | 是否允许 `stop_me` 真的停后台 |

```json
{
  "python": "D:/python/python.exe",
  "world": "default",
  "enableStop": true
}
```

---

## 安全边界

- **只读房间**：`room_read` 的路径会被归一化，`../` 越界直接拒绝。
- **叫停要确认**：`stop_me` 必须 `confirm: true`，防止模型手滑。
- **不偷偷看**：`look_screen` 只在被调用时截一张，不轮询、不常驻。
- **坏了不连坐**：任何初始化或脚本异常都只记一条 warn，绝不拖垮 DSH 启动。

---

## 开发

```bash
node test/apply.test.mjs    # 注册冒烟（不需要宿主）
node test/tools.test.mjs    # 配置 / 房间 / 防手滑
```

宿主相关模块用 `test/stub-loader.mjs` 打桩，所以没有 DSH 也能测。

---

## 已知问题

- **Windows only**：脚本用了 `ctypes` 调 Win32（截屏、窗口枚举、电源状态）。
- **房间路径写死在脚本里**：默认 `~/.dsh/worlds/default/room`，多 world 还没做。
- **没有常驻服务**：这是设计，不是缺失。
- **梦/听歌依赖房间文件**：房间空的时候，梦会很短。

## License

MIT
