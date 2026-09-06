# quote0-burnout

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Hardware](https://img.shields.io/badge/Hardware-MindReset%20Quote%2F0-FF6B00.svg)](https://mindreset.tech/)
[![Display](https://img.shields.io/badge/Display-296%C3%97152%201--bit%20E--Ink-000000.svg)](docs/layouts.md)
[![Tests](https://img.shields.io/badge/Tests-98%20passed-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![LLM Context](https://img.shields.io/badge/LLMs.txt-Standard-purple.svg)](llms.txt)

MindReset Quote/0 墨水屏 AI 用量与配额仪表盘 —— 实时聚合 OpenAI Codex、Claude Code、Google Antigravity (AGY)、DeepSeek 与 OpenCode Go 的配额、余量与余额。296×152、纯黑白 1-bit 原生点阵渲染并推送到设备。

[English](README_EN.md) · [LLMs.txt](llms.txt) · [完整规格](docs/layouts.md)

![实机照片](docs/preview.jpg)

## 布局效果

`auto`（默认）按当前可用的 provider 数自适应；`--layout` / `LAYOUT` 可固定：

| `stack` 全宽堆叠 | `1+1` 上下两个半屏 | `1+2` 上1半 + 下2格 | `2+2` 四格 |
|---|---|---|---|
| ![stack](docs/images/layout-stack.png) | ![1+1](docs/images/layout-1x1.png) | ![1+2](docs/images/layout-1x2.png) | ![2+2](docs/images/layout-2x2.png) |

> 完整规格：格子内容契约、分隔线与交叉、字体/字号、面板排序、缓存 `*` 标记 —— 见 [docs/layouts.md](docs/layouts.md)。

## 特性

- **Google AGY (Antigravity)**：通过 `agy --print /quota` 获取 5 小时与每周配额，自动折算使用百分比与重置倒计时，搭配官方 16×16 反重力拱门点阵 Logo
- **OpenAI Codex / Claude Code**：同尺寸双行面板（5h / Week），点阵进度条 + 余量 % + 重置倒计时，Codex 支持手动重置额度与到期提示
- **DeepSeek**：余额大字（VCR 21px）+ 峰谷计费档（PEAK/OFF，官方价目 2026-08，谷段 = 峰段 ×0.5）+ 档位切换倒计时
- **OpenCode Go**：Zen "Go" 订阅用量三行视图（5h / Wk / Mo）
- **动态自适应布局**：自动依据当前可用的 Provider 数量匹配 `stack` / `1+1` / `1+2` / `2+2`，无缝填满屏幕
- **热度优先排序**：数据最近发生变化的 provider 自动排到最显眼位置；鉴权失败或超时的 provider 自动隐藏
- **高可用缓存兜底**：Provider API 临时不可用时自动展示最近一次有效快照，右上角标记 `*`（如 `16:40*`）
- **像素级原生排版**：PixelOperator 16px / Minecraftia 8px / VCR OSD 21px，全部原生点阵尺寸绘制，零抗锯齿发虚
- **多样化运行方式**：支持单次推送、本地预览 (`--preview`)、自调度循环 (`--interval 5m`)、macOS launchd 守护进程以及 Docker 容器化部署

## 安装

```bash
pip install -r requirements.txt
# codex CLI（仅首次认证）：codex
```

## 配置

```bash
cp config.example.env .env
```

| 变量 | 必须 | 说明 |
|------|------|------|
| `QUOTE0_API_KEY` | ✓ | Quote/0 API key |
| `QUOTE0_DEVICE_ID` | ✓ | 设备 ID |
| `CODEX_ACCESS_TOKEN` | | 覆盖 Codex token（默认 `~/.codex/auth.json`） |
| `CLAUDE_ACCESS_TOKEN` | | 覆盖 Claude token（默认 `~/.claude/.credentials.json` 或 macOS Keychain；缺失时 fallback 到 `claude /usage`） |
| `DEEPSEEK_API_KEY` | | DeepSeek 余额 + 价目（`DEEPSEEK_MODEL` 选计价模型） |
| `OPENCODE_GO_API_KEY` | | OpenCode Zen 用量 API |
| `AGY_API_KEY` | | Google AGY (Antigravity) 配额 API key（默认自动读取本地 `~/.gemini/antigravity-cli/`） |
| `LAYOUT` | | `auto`（默认）/ `stack` / `1+1` / `1+2` / `2+2` |
| `REFRESH_INTERVAL` | | 自调度循环间隔（如 `60`, `5m`, `1h`；最低 60s） |

## 使用

```bash
python display.py --preview    # 本地生成预览 PNG（不推送）
python display.py              # 推送到设备
python display.py --interval 5m # 自调度循环（每 5 分钟推送一次，最低 60s）
python display.py --layout 2+2 # 固定布局，覆盖 LAYOUT 环境变量
python display.py --text       # Text API
python display.py --debug-json # 打印快照 JSON
python display.py --check      # 自检
python display.py --list-tasks # 列出任务槽位
```

## 定时任务（macOS launchd，每 5 分钟）

```bash
cp scripts/com.example.quote0-burnout.plist.example ~/Library/LaunchAgents/
# 编辑 plist 里的 Label / Program / 日志路径，然后：
launchctl load ~/Library/LaunchAgents/com.example.quote0-burnout.plist
```

## 常见问题（FAQ）

### Q: quote0-burnout 支持哪些 AI 平台与客户端？
当前原生支持 5 大主流平台：
1. **OpenAI Codex**（Codex CLI / direct OAuth）
2. **Claude Code**（Anthropic Claude Code OAuth / `claude /usage` CLI）
3. **Google Antigravity**（`agy` CLI slash command）
4. **DeepSeek**（官方开放平台余额与动态阶梯计费）
5. **OpenCode**（Zen "Go" 订阅用量）

### Q: 墨水屏为什么使用纯黑白 1-bit，不做灰阶抖动？
MindReset Quote/0 采用 296×152 分辨率黑白电子纸屏。灰阶抖动（Dithering）会在小尺寸字体和点阵进度条边缘产生严重的残影与噪点。本项目严格采用原生像素字体（PixelOperator 16px、Minecraftia 8px、VCR 21px）进行 1-bit 点对点精准栅格化，确保在电子墨水屏上达到最极致的对比度与锐度。

### Q: 某个 Provider 的 Token 过期或网络报错会影响屏幕其他内容吗？
不会。系统具有**故障隔离机制**与**死节点静默规则**：未配置或超时的 Provider 会自动从屏幕隐藏，剩余活跃 Provider 会自动重组为适应的布局（如 1+2 自动降级为 1+1）。对于临时断网的活跃 Provider，系统会自动提供缓存快照并在标题添加 `*` 标识，绝不在桌面上渲染大面积报错文字。

### Q: 怎样让它在后台静默运行？
- **macOS**：配置 `launchd` plist 定时任务（推荐每 5 分钟执行一次 `run.sh`）。
- **进程循环**：直接运行 `python display.py --interval 5m`，自带最小 60 秒保底自调度。
- **Docker**：使用项目提供的 `Dockerfile` 和 `docker-compose.yml` 容器化部署。

## 故障排查

- **Codex / Claude 显示 "no auth"** —— 运行 `codex` / `claude` 重新认证
- **推送 404** —— Dot. App 里删掉 IMAGE_API 卡片重新添加
- **定时不更新** —— `launchctl kickstart gui/$(id -u)/com.example.quote0-burnout`

## 开发与贡献

- 贡献指南与 Provider 标准：[CONTRIBUTING.md](CONTRIBUTING.md)
- `providers/`：provider 实现（fetch → snapshot → text）
- `render.py`：布局引擎 + 渲染；`scripts/render_layout_gallery.py` 可重新生成上面的效果图
- 测试：`python3 -m pytest`
- 像素级设计规格：[skills/quote0-burnout-develop/references/eink-design.md](skills/quote0-burnout-develop/references/eink-design.md)

### 仓库自带 Agent 技能

本仓库随附两个 Hermes 兼容的技能，供 agent（如 Hermes Agent）在对应场景下加载：

- [skills/quote0-burnout-develop/SKILL.md](skills/quote0-burnout-develop/SKILL.md) —— **开发**：架构、provider 契约（含 AGY `--print /quota` 取数）、布局/渲染、陷阱与验证清单。改代码时加载。
- [skills/quote0-burnout-deploy/SKILL.md](skills/quote0-burnout-deploy/SKILL.md) —— **部署**：deploy worktree、launchd kickstart、验证上屏。发布版本时加载。

### 通过 Agent 部署（Deploy via Agent）

设备由 launchd 守护进程定时从**独立的部署 worktree**（脱离开发目录）拉取并推送。要让设备跑最新 `main`，让 agent 加载 [skills/quote0-burnout-deploy/SKILL.md](skills/quote0-burnout-deploy/SKILL.md) 并按其中的「发布流程」执行：把部署 worktree 切到最新 `origin/main`，触发一次 `launchctl kickstart`，再确认设备返回「内容已切换」。

worktree 路径、launchd label 等按各自机器配置（skill 里已用占位变量），本仓库不携带具体服务器路径或个人设备标识。

