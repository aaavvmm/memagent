# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与语义化版本。

## [0.2.0] - 2026-11-06

### Added
- CI 工作流: ruff lint/format + mypy + pytest(覆盖率) 矩阵 (Python 3.10/3.12)
- Dependabot / Makefile / MIT LICENSE
- SQLite 加固: WAL 模式 + busy_timeout + schema 版本迁移(_meta 表, 升级不丢数据)
- 结构化事件日志(stderr, JSON 行): memory_added / memories_expired 全程可审计
- 测试 14 个, 覆盖率 83%

## [0.1.0] - 2026-10-12

### Added
- 分层记忆系统: 槽位冲突消解(版本链归档) / 三级遗忘 / BM25式检索
- 自建中文评测: 70 标准场景 + 20 长期演化场景, 4 配置消融
- 消融结论: 关冲突消解 100→74%(过时率 26%); 关分层保护 270 天过敏记忆存活 0%; 关遗忘存储 +38%
- 助理外壳: chat/ask/记忆面板/手工修正/虚拟时钟注入
