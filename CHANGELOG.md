# CHANGELOG

## 0.2.0 — 2026-11-24

- 工具表 15 个：`breath` `now_playing` `look_screen` `dream` `cook` `say` `sing` `typewrite`
  `wechat` `lesson` `touched` `voice` `pet` `room_read` `stop_me`，全部零 token、纯本地。
- 新增 `sing`：用绮萱的声音照数字简谱唱一段（OpenUtau 渲染，一次 1–2 分钟）。
- 新增 `voice`：调她自己的嗓子（list / pick / engine / tune / preview）。
- 插件只负责工具，不再管开关和常驻服务：开关、备份、重置、发布统一在
  `tools\chenchen_control.ps1` 总控里。
- 世界可以被干净重置：房间 / 日记 / 记忆清空后，所有工具都按“文件不存在”兜底，
  第一次用时自己建目录，不报错。
- 装法见发布包 README。

## 0.1.6 — 2026-11-11

- 声音调过一遍：`say` 现在默认 **+3 半音**、共振峰一起上移（听感年轻），
  再压一点高频、收一点音量，去掉 piper 那种「播报感」。语速不受影响。
- **断句改成自己管**：按标点把话切开、逐句合成，句号后停 0.30s、逗号后停 0.12s；
  她一句话没打标点时按 36 字断一口气。piper 自己断句会一顿一顿的。
- 移调只用重采样（干净）；「事后把时间拉回来」那种做法会在语音上留颗粒感，已弃用。
- 工具数不变（9 个）

## 0.1.5 — 2026-11-11

- 新增 `pet`：指挥屏幕上那只桌宠（深深）动起来——点播动作、散步、跳舞、发呆、
  挪到屏幕某个位置、冒泡说话、看它在干嘛、叫它睡或醒。
  走的是 dsh-pet 自己的 HTTP 接口（`/anim` `/position` `/broadcast` `/sleep` `/wake`），
  **一行 dsh-pet 的代码都不改**，它升级不会把这边覆盖掉。
- 动作名和它右键菜单里那棵树同源（直接读 `assets/config.jsonc`，109 个），
  名字按大意模糊匹配（「跳舞」「走两步」「伸个懒腰」），对不上就明说有哪些。
- 散步 / 跳舞 / 发呆是后台时间线连着演一段，同一时间只跑一段；工具立刻回话，不占她一步。
- 桌宠没起来、端口换了、动作不存在，都给能看懂的说法，不装作成功。
- 工具数 8 → 9

## 0.1.4 — 2026-11-09

- 新增 `say`：用自己的声音念一句话（Windows 本地 SAPI，离线、零 token）。
  念之前洗掉括号里的动作备注、表情符号和 markdown，只留话本身。
  留了 `--engine edge` 的口子（edge-tts，音质好得多），但这台机器连不上微软，默认走 SAPI。
- 工具数 7 → 8

## 0.1.3 — 2026-11-09

- **修好「工具注册了，但 agent 里看不到」**：宿主按 agent 自己的 ctx 组装工具表，
  原先只注册在插件 ctx 上，`breath` / `dream` / `cook` 这批一直没进过任何会话的工具表。
  现在像 dsh-world 一样，在 `agent/created` 和 `agent/pre-step` 时挂到 `agent.ctx`（同一 agent 只挂一次）。
- 插件 ctx 上的旧注册保留，旧宿主仍能靠它工作。

## 0.1.2 — 2026-11-09

- 新增 `cook`：她自己决定今天做什么菜，直接做（`kitchen.py --dish <菜名>`），不传就自己挑
- `runPy` 传入 `CHENCHEN_ROOM`，脚本推房间路径和插件用同一个世界，`DSH_HOME` 不一致也不会错位
- 工具数 6 → 7

## 0.1.1 — 2026-11-06

- `repository` / `homepage` / `bugs` 指向独立仓库 `trsing999/dsh-chenchen`
- README 补上仓库与 npm 入口

## 0.1.0 — 2026-11-06

首个可安装版本。

- 六个零成本工具：`breath` / `now_playing` / `look_screen` / `dream` / `room_read` / `stop_me`
- 结果统一从房间文件读，不接管子进程 stdout（受限环境更稳）
- 不托管常驻服务（宿主 job object 会连带杀子进程）
- 叫停必须 `confirm: true`
- 加载痕迹写到 `~/.dsh/chenchen.log`，出问题可查
- 本机验证：DSH 0.2.1-rc.5 / Node 24.21 / Python 3.11 + Pillow 13
