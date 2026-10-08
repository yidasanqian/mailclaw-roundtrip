# MailClaw Round-Trip Test

一个用于验证 MailClaw 发信与收信链路的命令行脚本：发送测试邮件到 Cloudflare Email Routing 的 catch-all 地址，再轮询 MailClaw API，确认邮件已被接收。

脚本只使用 Python 标准库，不需要安装第三方依赖。它会实际发送邮件；请使用专门的测试发件地址和收件域名。

## 工作流程

1. 检查 MailClaw 的 `/api/health` 接口。
2. 向指定地址发送一封带唯一标记的测试邮件。
3. 按收件地址查询 MailClaw，直到找到对应主题或等待超时。
4. 输出收件地址、邮件 ID 和主题。

默认生成新的地址，例如 `mailclaw-test-20261008123456-a1b2c3@example.com`，避免匹配到之前收到的邮件。

## 前置条件

- Python 3.10 或更高版本。
- 已部署并可访问的 [MailClaw](https://github.com/missuo/mailclaw) Worker，以及对应的 API Token。
- MailClaw 配置的发件服务已验证 `MAILCLAW_FROM` 使用的地址或域名。
- Cloudflare Email Routing 的 Catch-all 已设置为 **Send to a Worker → mailclaw**。
- 收件域名由该 Catch-all 接收。

## 配置

在项目根目录复制 `.env.example` 为 `.env`，并填写实际值：

```dotenv
MAILCLAW_HOST=https://your-mailclaw-worker.workers.dev
MAILCLAW_API_TOKEN=your-mailclaw-api-token
MAILCLAW_FROM=sender@example.com
MAILCLAW_DOMAIN=example.com

# 可选
MAILCLAW_POLL_INTERVAL=5
MAILCLAW_TIMEOUT=90
```

脚本会自动读取项目根目录的 `.env`。已存在的系统环境变量优先于 `.env`。`.env` 含有密钥，已列入 `.gitignore`，不要提交真实配置或令牌。

| 变量 | 必需 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `MAILCLAW_HOST` | 是 | 无 | MailClaw Worker 的 URL，不要在末尾添加 `/` |
| `MAILCLAW_API_TOKEN` | 是 | 无 | MailClaw Worker 的 API Token |
| `MAILCLAW_FROM` | 是 | 无 | MailClaw 发信服务中已验证的发件地址 |
| `MAILCLAW_DOMAIN` | 否 | `example.com` | 自动生成的 catch-all 收件地址所用域名 |
| `MAILCLAW_POLL_INTERVAL` | 否 | `5` | 收件箱轮询间隔，单位为秒 |
| `MAILCLAW_TIMEOUT` | 否 | `90` | 最长等待时间，单位为秒 |

## 运行

```bash
python mailclaw_roundtrip.py
```

指定收件地址并延长等待时间：

```bash
python mailclaw_roundtrip.py --recipient test@example.com --timeout 180
```

命令行参数优先于对应的轮询环境变量：

```text
--recipient ADDRESS       指定测试收件地址；省略时自动生成唯一地址
--poll-interval SECONDS   轮询间隔（秒）
--timeout SECONDS         最长等待时间（秒）
```

退出码为 `0` 表示收发验证成功，`1` 表示配置、网络或 API 错误，`2` 表示在超时时间内未收到邮件。

## 故障排查

- **未收到邮件**：确认 Catch-all 已路由到 `mailclaw` Worker，并检查发件域名是否已在所选发信服务完成验证。
- **401/403**：确认 `MAILCLAW_API_TOKEN` 与 Worker 配置一致。
- **连接失败**：检查 `MAILCLAW_HOST` 是否可访问，且配置值中没有多余的路径或末尾斜杠。
- **使用固定地址时匹配异常**：优先省略 `--recipient`，让脚本生成新的唯一地址。

脚本不会主动打印 API Token。若 API 返回错误，错误详情可能包含服务端返回的内容；分享日志前请检查并移除其中可能存在的敏感信息。
