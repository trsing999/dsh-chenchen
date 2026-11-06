# CHANGELOG

## 0.1.0 — 2026-11-06

首个可安装版本。

- 六个零成本工具：`breath` / `now_playing` / `look_screen` / `dream` / `room_read` / `stop_me`
- 结果统一从房间文件读，不接管子进程 stdout（受限环境更稳）
- 不托管常驻服务（宿主 job object 会连带杀子进程）
- 叫停必须 `confirm: true`
- 加载痕迹写到 `~/.dsh/chenchen.log`，出问题可查
- 本机验证：DSH 0.2.1-rc.5 / Node 24.21 / Python 3.11 + Pillow 13
