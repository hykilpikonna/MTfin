# MTfin

是一个很简单的，输入 IMDB ID 就可以从 M-Team 上下载种子整合到 Jellyfin 的工具 qwq

## 工作原理

1. 查询 M-Team 上这个 IMDB ID 对应哪些种子
2. 调用 LLM 挑选其中最好的种子（输入是 1. 的种子列表）
3. 从 M-Team 下载种子 .torrent
4. 调用 qbittorrent api 把种子里的文件下载它到一个乱的文件夹
5. 调用 qbittorrent api 查看种子里的文件树
6. 调用 LLM 生成符合 Jellyfin 结构的重命名表（输入是 5. 的文件树）
7. 用 symlink 在 Jellyfin 媒体目录把它链接上

## 用法

1. 写 config.toml

```toml
[qb]
host = "http://127.0.0.1:8920"
username = "cat"
password = "meow"

[mt]
username = "cat"
password = "meow"
otp_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
api_key = "01234567-0123-0123-0123-0123456789ab"

[openai]
token = "sk-your-openai-token"

[paths]
qb_download_dir = "/data/QB"
jellyfin_dir = "/data/Jellyfin"

[telegram]
# 也可以不写在 config.toml，改用环境变量 TELEGRAM_BOT_TOKEN
bot_token = "123456:telegram-bot-token"
# 建议限制允许使用 bot 的 chat id；不配置则所有 chat 都可以触发下载
allowed_chat_ids = [123456789]
workers = 2
progress_interval = 10
```

2. 装依赖：`uv sync`
3. 跑: `uv run launcher.py tt114514 tt1919810 ...`

## Telegram bot

配置好 `[telegram]` 后运行：

```bash
uv run telegram_bot.py
```

然后给 bot 发送 `/download tt0903747`，或者 `/download` 加任意包含 IMDB tt id 的 URL/text。URL 被 decode 后包含 tt id 也可以识别。bot 会启动现有的 `workflow.py`，并把下载进度、当前步骤和日志路径持续更新到 Telegram 消息里。

如果在群聊里开着 Telegram bot privacy mode，请使用 `/download@YourBotUsername tt0903747`。普通的 `@YourBotUsername tt0903747` mention 通常不会被 Telegram 投递给 bot。

可用命令：

- `/help`：查看用法
- `/download tt0903747`：开始处理 IMDB ID
- `/status`：查看当前队列/运行中的 IMDB ID
- `/chatid`：查看当前 Telegram chat id，方便配置 `allowed_chat_ids`
