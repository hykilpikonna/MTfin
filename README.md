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
```

2. 装依赖：`uv sync`
3. 跑: `uv run launcher.py tt114514 tt1919810 ...`
