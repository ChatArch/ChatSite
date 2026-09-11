# ChatImg 图像工作台

`chatsite image` 把 ChatImg 的文本生图能力作为独立 Web 入口运行，同时复用 ChatLogin 的登录页和会话模型。

## 交互边界

- 访客可直接生成图片，不强制登录。
- 登录是可选项；登录后可查看仅属于当前账号的生成历史。
- 匿名历史不会在登录后自动归属账号，旧生成文件仍按原链接读取。
- 失效或过期 Cookie 不会被静默降级；页面会明确提供“以访客继续”。
- 当前只提供文本生图，不展示尚未实现的图片编辑、多轮或房间入口。

页面保留既有 ChatImg 的 Logo、建议词、模型/尺寸/质量选项、阶段进度、耗时、结果元数据、下载和 ChatShare 分享流程。

## 配置与启动

Image 使用 ChatEnv provider `chatsite_image`。配置至少需要公开 URL、数据目录、管理员账号以及 ChatImg provider/profile；敏感值只保存在 ChatEnv profile 中。

```bash
chatenv new web -t chatsite_image -I --yes
chatsite image check --profile web
chatsite image serve --profile web --host 127.0.0.1 --port 8766
```

`check` 只验证配置，不请求模型，也不会生成图片。生产部署应由现有服务监督器启动 `serve`，不要并行启动第二个默认实例。

常用配置键：

- `CHATSITE_IMAGE_PUBLIC_URL`
- `CHATSITE_IMAGE_DATA_DIR`
- `CHATSITE_IMAGE_ADMIN_EMAIL`
- `CHATSITE_IMAGE_ADMIN_PASSWORD`
- `CHATSITE_IMAGE_PROVIDER`
- `CHATSITE_IMAGE_PROFILE`
- `CHATSITE_IMAGE_ALLOWED_ORIGINS`
- `CHATSITE_IMAGE_LEGACY_GENERATED_DIR`

## 数据与安全

- 新图片写入 Image 数据目录的 `generated/`。
- 历史元数据保存在 `image-history.sqlite3`，按标准化账号 owner 隔离。
- `CHATSITE_IMAGE_LEGACY_GENERATED_DIR` 只用于兼容读取旧文件，不会把旧匿名记录归给用户。
- 生成接口有有界的客户端限流；不信任浏览器可伪造的转发头。
- 登录、退出、历史和生成写请求使用 ChatLogin 会话与 CSRF 校验；JSON 响应使用 `no-store` 和 `nosniff`。
