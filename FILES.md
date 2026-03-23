# 项目文件索引

本项目实现了一个基于 LangGraph 和 CodeBuddy 的智能任务编排系统。

## 📁 目录结构

```
langgraph-todo-orchestrator/
├── README.md                 # 项目介绍和快速开始
├── INDEX.md                  # 文档索引
├── ARCHITECTURE.md           # 架构设计文档
├── USAGE.md                  # 使用指南
├── API_REFERENCE.md          # API 参考文档
├── EXAMPLES.md               # 示例和用例
├── requirements.txt          # Python 依赖
├── .gitignore               # Git 忽略规则
├── todos.example.yaml       # 示例配置文件
├── todo_orchestrator.py     # 主程序（待实现）
└── codebuddy_client.py      # CodeBuddy 客户端（待实现）
```

## 📚 文档说明

| 文档 | 大小 | 说明 |
|------|------|------|
| README.md | ~5 KB | 项目主页，包含简介、特性、快速开始 |
| INDEX.md | ~4 KB | 文档导航索引 |
| ARCHITECTURE.md | ~15 KB | 详细架构设计，包含分层架构、核心组件、数据流 |
| USAGE.md | ~12 KB | 完整使用指南，包含配置、执行、故障排除 |
| API_REFERENCE.md | ~10 KB | API 文档，包含所有类和方法的详细说明 |
| EXAMPLES.md | ~14 KB | 20+ 个实际使用示例 |

## 🎯 核心文件

### 待实现文件

| 文件 | 优先级 | 说明 |
|------|--------|------|
| todo_orchestrator.py | 高 | 主程序，包含 TodoOrchestrator 类 |
| codebuddy_client.py | 高 | CodeBuddy 调用封装 |
| test_todo_orchestrator.py | 中 | 单元测试 |
| config.py | 中 | 配置管理模块 |

### 配置文件

| 文件 | 说明 |
|------|------|
| requirements.txt | Python 依赖列表 |
| .gitignore | Git 忽略规则 |
| todos.example.yaml | 示例任务配置 |

## 📖 文档阅读路径

### 新手路径

```
README.md → INDEX.md (快速开始) → EXAMPLES.md (简单示例) → USAGE.md (基础用法)
```

### 开发者路径

```
ARCHITECTURE.md (架构理解) → API_REFERENCE.md (接口了解) → todo_orchestrator.py (代码实现)
```

### 高级用户路径

```
ARCHITECTURE.md (扩展性设计) → EXAMPLES.md (高级用例) → USAGE.md (最佳实践)
```

## 🔍 关键概念

### 1. 分层架构

```
应用层 → 业务逻辑层 → 流程编排层 → AI 能力层 → 基础设施层
```

### 2. 任务类型

- **Simple Task**: 简单任务，一次性执行
- **Loop Task**: 循环任务，AI 驱动的自动重试

### 3. 核心组件

- **TodoOrchestrator**: 任务编排器
- **CodeBuddyClient**: AI 能力封装
- **LangGraph**: 流程控制框架

## 📊 文件统计

### 文档文件

- 总数：6 个
- 总大小：~60 KB
- 总行数：~2000 行

### 代码文件（待实现）

- 预计总数：3-5 个
- 预计总大小：~10 KB
- 预计总行数：~1000 行

## 🚀 快速定位

### 我想...

- **了解项目**: 阅读 [README.md](README.md)
- **快速开始**: 阅读 [INDEX.md](INDEX.md) 的快速开始章节
- **理解架构**: 阅读 [ARCHITECTURE.md](ARCHITECTURE.md)
- **配置任务**: 阅读 [USAGE.md](USAGE.md) 的配置文件章节
- **查看 API**: 阅读 [API_REFERENCE.md](API_REFERENCE.md)
- **找示例**: 阅读 [EXAMPLES.md](EXAMPLES.md)
- **解决问题**: 阅读 [USAGE.md](USAGE.md) 的故障排除章节

## 📝 开发计划

### Phase 1: 核心实现（当前）

- [x] 编写完整文档
- [ ] 实现 CodeBuddyClient
- [ ] 实现 TodoOrchestrator
- [ ] 实现简单任务执行器
- [ ] 实现 LangGraph 循环图

### Phase 2: 功能完善

- [ ] 添加状态持久化
- [ ] 添加错误处理
- [ ] 添加日志系统
- [ ] 添加配置验证

### Phase 3: 高级特性

- [ ] 支持任务依赖
- [ ] 支持并行任务
- [ ] 支持条件任务
- [ ] 支持 Git 集成
- [ ] 支持通知集成

### Phase 4: 测试和优化

- [ ] 编写单元测试
- [ ] 性能优化
- [ ] 文档完善

## 🔗 相关项目

- [autoresearch](../autoresearch) - Karpathy 的自动化研究项目
- [CodeBuddy](https://iwiki.woa.com/space/CodeBuddy) - AI 编程助手

## 📞 贡献指南

欢迎提交 Issue 和 Pull Request！

### 文档贡献

- 修正错别字
- 补充示例
- 改进说明

### 代码贡献

- 实现待开发功能
- 修复 bug
- 性能优化

## 📄 许可证

MIT License

---

**最后更新**: 2026-03-23
**版本**: 0.1.0 (文档阶段)
