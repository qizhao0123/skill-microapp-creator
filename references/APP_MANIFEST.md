# `app.yaml` 契约

> 本文件主体同步自 `app-deployer/docs/APP_MANIFEST.md`（2026-08-05）；示例的 `mutablePaths` 已按本 skill 用户数据安全策略默认置空。若工作区存在更新后的 App Deployer，以 live 文档、`app.schema.json` 和 `deployctl validate` 为准，但不得降低 [`DATA_SAFETY.md`](DATA_SAFETY.md) 的门禁。

编辑器和 CI 可直接使用 [`app.schema.json`](./app.schema.json)；最终仍以 `deployctl validate` 的运行时校验为准。

```yaml
apiVersion: deploy.xzd5/v1
kind: WebApp

metadata:
  name: appointment-qihang
  displayName: 启航预约
  version: 1.0.0

spec:
  route:
    path: /appointment/qihang
    mode: native

  container:
    port: 8767

  health:
    path: /health
    expectedStatus: 200

  persistence:
    mode: files
    containerPath: /app/data
    mutablePaths: []

  env:
    - name: ADMIN_PASSWORD
      type: string
      required: true
      secret: true
      description: 管理后台密码

  entrypoints:
    - key: booking
      name: 预约页面
      path: /
      primary: true
    - key: admin
      name: 管理后台
      path: /admin/
      authRequired: true

  smokeTests:
    - path: /
      method: GET
      expectedStatus: 200
      contentType: text/html

  resources:
    cpus: "1.0"
    memory: 512m
    pids: 256
```

## 规则

- `metadata.name` 匹配 `^[a-z][a-z0-9-]{2,40}$`。
- `metadata.version` 必须是 SemVer。
- `route.path` 是无尾斜杠的绝对二级目录，不能包含查询串、编码路径、双斜杠或 `..`。
- `route.mode` 只能为 `native` 或 `static-strip`；动态应用使用 `native`。
- `health` 只允许无副作用 GET。
- `env` 只能声明变量结构，敏感变量不得有默认值。
- `entrypoints.path` 相对于应用公共路径解析，发布成功后控制面生成可复制的完整 URL。
- `persistence.mode=files` 时 `containerPath` 必须严格为 `/app/data`。
- `persistence.mutablePaths` 声明允许通过数据更新包修改的相对目录；未声明目录不能被数据包写入或删除，目录之间不能重叠。
- 本 skill 默认将 `mutablePaths` 置空。只有完成 [`DATA_SAFETY.md`](DATA_SAFETY.md) 数据归属清单后，才能加入与用户数据完全隔离的后台维护目录。
- 用户数据库、用户上传、提交记录及其任意上级目录不得声明为 `mutablePaths`；混在同一文件中的数据不得使用 DataPatch。
- smoke test 只允许 GET/HEAD，写接口不得在生产发布流程中自动调用。
- 路径只允许 URL-safe ASCII 段，避免把空格、控制字符或 Nginx 指令字符带入平台配置。
- `resources` 限制为 0.1–8 CPU、64m–16g 内存、32–4096 PIDs。
