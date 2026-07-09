# quote0-burnout

MindReset Quote/0 墨水屏 AI 用量仪表盘 — OpenAI Codex + DeepSeek。

[English](README_EN.md)

![实机照片](docs/preview.jpg)
![渲染示例](docs/example.png)

## 效果

Canvas API 模式（v0.7 新增）：
```
                        08:51
[#] CODEX
5h   [████████████░░░░░] 66%  4h12m
Week [████████████░░░░░] 63%  6d4h
──────────────────────────────────
[#] DEEPSEEK
$18.42                        OK
```

与 Image API 的区别：
- **Image API（默认）**：本地用 PIL 渲染 296×152 PNG → base64 上传
- **Canvas API（`--canvas`）**：发送 windowData JSON → 服务器端渲染

> 完整的设计规范、API 参考、渲染细节见 [`skill/`](skill/) 目录。

## 安装

```bash
pip install -r requirements.txt
# 确保 codex CLI 已登录（仅首次）：
codex
```

## 配置

```bash
cp config.example.env .env
# 编辑 .env 填入密钥
```

| 变量 | 必须 | 说明 |
|------|------|------|
| `QUOTE0_API_KEY` | ✓ | Quote/0 API key |
| `QUOTE0_DEVICE_ID` | ✓ | 设备 ID |
| `QUOTE0_CANVAS_TASK_KEY` | | Canvas API task key（Canvas 模式） |
| `QUOTE0_IMAGE_TASK_KEY` | | Image API task key（Image 模式） |
| `QUOTE0_TEXT_TASK_KEY` | | Text API task key（Text 模式） |
| `DEEPSEEK_API_KEY` | | DeepSeek API key |
| `CODEX_ACCESS_TOKEN` | | 覆盖 Codex token（默认读 ~/.codex/auth.json） |

## 使用

```bash
python display.py                      # Image API（默认，本地渲染 PNG）
python display.py --canvas             # Canvas API（服务器端渲染）
python display.py --canvas --preview   # 保存 Canvas JSON 预览
python display.py --preview            # 保存 PNG 预览
python display.py --text               # Text API（纯文本卡片）
python display.py --check              # 自检
```

## 定时任务

```bash
# macOS launchd（每 5 分钟）
cp scripts/com.ajax.quote0-burnout.plist.example ~/Library/LaunchAgents/
# 编辑 plist 里的路径，然后：
launchctl load ~/Library/LaunchAgents/com.ajax.quote0-burnout.plist
```

## 故障排查

```bash
python display.py --check     # 检查所有环节
```

- **Codex 显示 "no auth"** — 运行 `codex` 重新认证
- **推送 404** — Dot. App 里删掉对应 API 卡片重新添加
- **Canvas 模式推送失败** — 确保 Dot. App Content Studio 里添加了 Canvas API content 到设备 loop task，且 `QUOTE0_CANVAS_TASK_KEY` 已配置
- **定时不更新** — `launchctl kickstart gui/$(id -u)/com.ajax.quote0-burnout`

## 技能文件

本项目附带 [skill/SKILL.md](skill/SKILL.md)，符合 Vercel Skills 标准，可直接导入 Hermes Agent 使用。
