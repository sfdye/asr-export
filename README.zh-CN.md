# asr-export

Avenue South Residence（Habitap App）文档批量导出工具。[English](README.md)

## 背景

ASR 正从 Habitap 迁移到 iCondo。iCondo 无法按户提供文档（户型图、电器说明书、保修函等），住户需要自行备份 Habitap 里的文档。每个账号有 300+ 份文档，在手机上一份份手动下载并不现实。

`asr-export` 把这件事自动化：用你自己的账号登录，列出你可见的全部文档（按楼栋过滤，与 App 内一致），确认后按类别批量下载到本地文件夹 — 支持断点续传，并有限速保护。

## 凭据与隐私

一切都在你的电脑上**本地**进行：

- 邮箱和密码仅用于通过 HTTPS 登录 Habitap，**绝不会发送到其他任何服务器** — 本工具只与 Habitap 自家的 API 和文件 CDN 通信。
- 密码**绝不落盘** — 只在登录瞬间存在于内存中。落盘的只有会话 cookie，存于 `~/.asr/`（权限 0600，约 1 年有效，只需登录一次）。
- 文档文件从 Habitap 的 CDN 直接下载到你指定的文件夹。

## 安装

需要 Python 3，然后二选一：

```bash
bash install.sh          # 安装 `asr-export` 命令（推荐）
```

或直接在项目目录运行：`python3 asr-export.py <命令>`。

## 使用

```bash
asr-export login                 # 登录（新设备需一次邮箱 OTP）
asr-export list                  # 按类别浏览文档（大类别默认只预览前 10 条）
asr-export list --cat Circulars --all
asr-export download              # 选类别 → 确认 → 下载
asr-export download --cat Circulars
asr-export download --dry-run    # 只看会下载什么
```

- 输出：`<目录>/<类别>/<文件名>.pdf`（默认目录：脚本旁的 `asr-export/`；安装后的命令默认 `~/Documents/asr-export`；`-o` 可改）。
- 续传：重复运行会自动跳过已下载文件（记录在 `~/.asr/manifests/` 下按输出目录区分的 manifest）；`--force` 强制重下。
- 随时 Ctrl+C 中断 — 每个文件下载后立即保存进度。

## 语言

默认中文界面在中文系统上自动启用；也可用 `ASR_EXPORT_LANG=zh` 强制中文、`=en` 强制英文。

## 致谢

登录流程与 API 模式参考了社区项目 [asrlife.vip](https://asrlife.vip) — 该项目逆向了 Habitap 住户端 API 用于场地预订。

## 说明

- 你看到的文档集合与 App 内完全一致（按你的楼栋过滤）— 不同住户看到的文档不同。
- 下载有 ~0.4s 间隔限速。请勿并发轰炸服务器；仅下载自己账号可见的文档、自用存档。

## 常见问题

- **`SSL: CERTIFICATE_VERIFY_FAILED`（CA cert does not include key usage extension）** — Python 3.13+ 默认启用的严格证书校验不兼容 Habitap 的证书链。脚本已内置处理（证书链仍被完整校验）。
- **已经登录过了？** `asr-export login` 检测到有效会话会直接退出；用 `--force` 重新登录或切换账号。
