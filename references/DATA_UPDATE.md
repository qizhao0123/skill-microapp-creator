# 数据更新包

> 本文件主体同步自 `app-deployer/docs/DATA_UPDATE.md`（2026-08-05）；示例目标已按本 skill 用户数据安全策略改为明确的后台资源目录。若工作区存在更新后的 App Deployer，以 live 文档、`data-update.schema.json` 和平台上传校验为准，但不得降低 [`DATA_SAFETY.md`](DATA_SAFETY.md) 的门禁。

数据更新包用于只修改报告 JSON、CSV、PDF、业务图片等可变资源，不重新上传源码，也不重新构建 Docker 镜像。

使用前必须完成 [`DATA_SAFETY.md`](DATA_SAFETY.md) 数据归属清单。DataPatch 只能面向完全由后台维护、且与用户数据目录不重叠的资源；未知或混合数据禁止更新。

## 应用声明

应用必须是 `persistence.mode: files`，并在 `app.yaml` 明确允许更新的相对目录：

```yaml
spec:
  persistence:
    mode: files
    containerPath: /app/data
    mutablePaths:
      - operator-resources
```

未声明的 `/app/data/db`、`uploads` 等目录不能通过数据更新包修改。`mutablePaths` 不能使用绝对路径、`..`，也不能互相重叠。不能把用户数据目录或同时包含后台资源和用户数据的上级目录加入 `mutablePaths`。

## ZIP 结构

```text
data-update.yaml
files/
  report-001.json
  report-002.pdf
  images/
    result-001.png
```

`data-update.yaml`：

```yaml
apiVersion: deploy.xzd5/v1
kind: DataPatch

metadata:
  app: sample-app
  revision: 2026.07.31.1
  description: 更新七月份报告

spec:
  target: operator-resources
  mode: merge
  delete:
    - expired-report.json
```

`files/` 中的路径和 `spec.delete` 都相对于 `spec.target`。上述文件最终写入 `/app/data/operator-resources`。同路径上传会完整覆盖旧文件。删除必须明确声明；平台不会因为 ZIP 中缺少某个文件就自动删除服务器文件。同一路径不能既上传又删除。

可在数据包目录执行：

```bash
zip -r sample-app-data-2026.07.31.1.zip data-update.yaml files
```

可从本 skill 的 [`assets/data-update.yaml`](../assets/data-update.yaml) 开始，也可使用 [`scripts/build_data_patch.py`](../scripts/build_data_patch.py) 生成带 SHA-256 的标准数据包。

## 发布流程

1. 在应用详情页上传数据更新 ZIP。
2. 平台校验大小、SHA-256、路径、压缩比、文件类型、应用名和目标目录。
3. 上传只生成 `READY` 记录，不自动修改线上数据。
4. 点击“发布数据”后获取与代码发布共用的应用锁。
5. runner 启用维护页、停止当前容器并完整备份 `/app/data`。
6. 在同一文件系统的临时目录合并文件和显式删除项。
7. 目录级原子切换后重新启动原容器，不构建镜像。
8. 健康检查和公网 smoke 通过后记录 `SUCCEEDED`。
9. 任一步失败，恢复原数据目录、原容器和原 Nginx 配置，记录 `FAILED`。

数据更新减少的是上传量和镜像构建时间。按照数据保护要求，首版仍会在服务器本地完整备份 `/app/data`，因此超大数据目录的备份耗时不会消失。
