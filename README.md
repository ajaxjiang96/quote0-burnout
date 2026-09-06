# quote0-burnout

MindReset Quote/0 墨水屏 AI 用量仪表盘 —— OpenAI Codex + Claude + DeepSeek + OpenCode Go 的实时用量。296×152、黑白 1-bit 渲染后推送到设备。

[English](README_EN.md)

![实机照片](docs/preview.jpg)

## 布局效果

`auto`（默认）按当前可用的 provider 数自适应；`--layout` / `LAYOUT` 可固定：

| `stack` 全宽堆叠 | `1+1` 上下两个半屏 | `1+2` 上1半 + 下2格 | `2+2` 四格 |
|---|---|---|---|
| ![stack](docs/images/layout-stack.png) | ![1+1](docs/images/layout-1x1.png) | ![1+2](docs/images/layout-1x2.png) | ![2+2](docs/images/layout-2x2.png) |

> 完整规格：格子内容契约、分隔线与交叉、字体/字号、面板排序、缓存 `*` 标记 —— 见 [docs/layouts.md](docs/layouts.md)。

## 特性

- **Codex / Claude**：同尺寸双行面板（5h / Week），点阵进度条 + 余量 % + 重置倒计时
- **DeepSeek**：余额大字 + 峰谷计费档（PEAK/OFF，官方价目 2026-08，谷段 = 峰段 ×0.5）+ 档位切换倒计时
- **OpenCode Go**：Zen "Go" 订阅用量（5h / Wk / Mo）
- **面板排序**：数据最近变化的 provider 排最前；鉴权失败/超时的 provider 自动隐藏
- **缓存兜底**：Codex API 不可用时展示上次快照，右上角时间为 `16:40*`（`*` = 缓存数据）
- **像素级字体**：PixelOperator 16px / Minecraftia 8px / VCR OSD 21px，全部原生尺寸 —— 缩放像素字体会毁掉字形
- **零 CLI 依赖**：Codex 直连 OpenAI OAuth API，Claude 走 CodexBar 的 Claude Code OAuth usage API

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
| `AGY_API_KEY` | | Google AGY (Antigravity) 配额 API key |
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
cp com.ajax.quote0-burnout.plist.example ~/Library/LaunchAgents/
# 编辑 plist 里的路径，然后：
launchctl load ~/Library/LaunchAgents/com.ajax.quote0-burnout.plist
```

## 故障排查

- **Codex / Claude 显示 "no auth"** —— 运行 `codex` / `claude` 重新认证
- **推送 404** —— Dot. App 里删掉 IMAGE_API 卡片重新添加
- **定时不更新** —— `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`

## 开发与贡献

- 贡献指南与 Provider 标准：[CONTRIBUTING.md](CONTRIBUTING.md)
- `providers/`：provider 实现（fetch → snapshot → text）
- `render.py`：布局引擎 + 渲染；`scripts/render_layout_gallery.py` 可重新生成上面的效果图
- 测试：`python3 -m pytest`
- 像素级设计规格：[skill/references/eink-design.md](skill/references/eink-design.md)
- 本仓库附带 [skill/SKILL.md](skill/SKILL.md)（Vercel Skills 标准），可直接导入 Hermes Agent 使用
