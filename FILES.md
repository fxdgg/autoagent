# 项目文件说明

本文档详细说明 CodeBuddy Todo Orchestrator 的项目结构和各个文件的作用。

## 📁 目录结构

```
langgraph-todo-orchestrator/
├── README.md                    # 项目介绍和快速开始
├── INDEX.md                     # 文档索引
├── ARCHITECTURE.md              # 架构设计文档
├── USAGE.md                     # 使用指南
├── FILES.md                     # 本文件：项目文件说明
├── requirements.txt             # Python 依赖列表
├── .gitignore                   # Git 忽略规则
├── todos.example.yaml           # 任务配置示例
├── orchestrator.py              # 主程序（待实现）
├── todos.yaml                   # 实际任务配置（用户创建）
├── todos_state.yaml             # 任务状态文件（自动生成）
├── logs/                        # 长时间任务日志目录（自动创建）
│   └── *.log                    # 各个子任务的日志文件
└── monitors/                    # 监控脚本目录（自动创建）
    ├── *.sh                     # 监控脚本
    └── *.log                    # 监控进程日志
```

## 📄 文件说明

### 文档文件

#### README.md
- **作用**：项目的主入口文档
- **内容**：
  - 项目简介和核心特性
  - 快速开始指南
  - 核心概念介绍
  - 使用场景示例
- **更新频率**：项目重大变更时更新

#### INDEX.md
- **作用**：文档导航和索引
- **内容**：
  - 所有文档的列表和说明
  - 按需求查找指南
  - 阅读建议
  - 快速开始指南
- **更新频率**：文档结构变更时更新

#### ARCHITECTURE.md
- **作用**：系统架构设计文档
- **内容**：
  - 分层架构设计
  - 核心组件说明
  - 任务类型详解
  - 数据流和状态管理
  - 长时间任务处理机制
  - 扩展性设计
- **更新频率**：架构设计变更时更新

#### USAGE.md
- **作用**：详细使用指南
- **内容**：
  - 安装和配置说明
  - 配置文件详解
  - 任务类型说明
  - 执行方式说明
  - 最佳实践
  - 故障排除
- **更新频率**：功能变更或新增功能时更新

#### FILES.md
- **作用**：项目文件说明（本文件）
- **内容**：
  - 完整的目录结构
  - 每个文件的作用和说明
  - 配置文件格式说明
- **更新频率**：项目结构变更时更新

### 配置文件

#### requirements.txt
- **作用**：Python 依赖列表
- **内容**：
  ```txt
  pyyaml>=6.0
  ```
- **用途**：通过 `pip install -r requirements.txt` 安装依赖

#### .gitignore
- **作用**：Git 忽略规则
- **内容**：
  ```gitignore
  # 自动生成的文件
  todos_state.yaml
  logs/
  monitors/
  
  # Python
  __pycache__/
  *.py[cod]
  *.so
  .Python
  
  # IDE
  .vscode/
  .idea/
  
  # 临时文件
  *.log
  *.tmp
  ```
- **用途**：避免将不必要的文件提交到 Git

#### todos.example.yaml
- **作用**：任务配置示例文件
- **内容**：各种类型的任务配置示例
- **用途**：用户可以复制此文件作为 `todos.yaml` 的模板
- **详细说明**：见下方"配置文件详解"

### 程序文件

#### orchestrator.py
- **作用**：主程序入口
- **核心类**：
  - `TaskOrchestrator`：任务编排器，负责任务调度和执行
- **主要方法**：
  - `load_todos()`：加载任务配置
  - `load_state()`：加载任务状态
  - `save_state()`：保存任务状态
  - `run()`：执行所有任务
  - `execute_task()`：执行单个任务
  - `execute_simple_task()`：执行简单任务
  - `execute_nested_task()`：执行嵌套任务
  - `execute_subtask()`：执行子任务
  - `call_codebuddy()`：调用 CodeBuddy
- **状态**：待实现

### 用户文件

#### todos.yaml
- **作用**：用户的任务配置文件
- **创建方式**：用户复制 `todos.example.yaml` 并修改
- **内容**：定义要执行的任务列表
- **详细说明**：见下方"配置文件详解"

#### todos_state.yaml
- **作用**：任务状态文件
- **创建方式**：程序自动创建和更新
- **内容**：记录每个任务的执行状态和历史
- **用途**：
  - 支持断点续传
  - 查看任务进度
  - 记录执行历史
- **示例**：
  ```yaml
  tasks:
    - id: 1
      status: "completed"
      attempts: 3
      last_attempt: "2026-03-23 22:30:00"
      
    - id: 2
      status: "in_progress"
      current_subtask: 2.2
      subtasks:
        - id: 2.1
          status: "completed"
          attempts: 3
        - id: 2.2
          status: "in_progress"
          started_at: "2026-03-23 22:30:00"
          log_file: "logs/2.2.log"
  ```

### 自动生成的目录

#### logs/
- **作用**：存储长时间任务的日志文件
- **创建方式**：程序自动创建
- **内容**：
  - 各个子任务的日志文件（如 `2.2.log`）
- **用途**：
  - 查看长时间任务的输出
  - 监控进程读取此目录检查任务状态
  - AI 读取日志文件判断任务是否完成

#### monitors/
- **作用**：存储监控脚本和日志
- **创建方式**：程序自动创建
- **内容**：
  - 监控脚本（如 `2.2.sh`）
  - 监控进程日志（如 `2.2.log`）
- **用途**：
  - 监控长时间任务的执行状态
  - 检测任务完成或错误
  - 通知 AI 检查结果

## 📝 配置文件详解

### todos.yaml 完整示例

```yaml
tasks:
  # 简单任务示例
  - id: 1
    name: "下载数据集"
    type: simple
    completion_criteria: "data.csv 文件存在且大小 > 10MB"
    initial_hint: "使用 python download.py"
    
  # 嵌套任务示例
  - id: 2
    name: "优化模型性能"
    type: nested
    completion_criteria: |
      训练成功完成
      验证集精度 >= 0.9
      验证集 loss < 0.1
    subtasks:
      # AI 操作任务
      - id: 2.1
        name: "修改训练代码"
        type: ai_action
        completion_criteria: "代码修改完成"
        
      # 长时间任务
      - id: 2.2
        name: "运行训练"
        type: long_running
        command: "python train.py --config modified_config.yaml"
        completion_criteria: "训练正常退出且验证集指标满足要求"
```

### 字段说明

#### 任务通用字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | int/string | 是 | 任务 ID（唯一标识） |
| `name` | string | 是 | 任务名称 |
| `type` | string | 是 | 任务类型 |
| `completion_criteria` | string | 是 | 完成标准（自然语言描述） |

#### 简单任务 (type: simple)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `initial_hint` | string | 否 | 初始提示（给 AI 的参考信息） |

#### 嵌套任务 (type: nested)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `subtasks` | list | 是 | 子任务列表 |

#### AI 操作任务 (type: ai_action)

无额外字段，使用通用的 `completion_criteria`。

#### 长时间任务 (type: long_running)

| 额外字段 | 类型 | 必填 | 说明 |
|---------|------|------|------|
| `command` | string | 是 | 要执行的命令 |

## 🔧 工作流程

### 首次使用流程

1. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

2. **配置 CodeBuddy**
   ```bash
   codebuddy -p "login_test"
   ```

3. **创建任务配置**
   ```bash
   cp todos.example.yaml todos.yaml
   # 编辑 todos.yaml
   ```

4. **运行 Orchestrator**
   ```bash
   python orchestrator.py
   ```

### 正常使用流程

1. **编辑任务配置**
   - 修改 `todos.yaml`
   - 添加或删除任务

2. **运行程序**
   ```bash
   python orchestrator.py
   ```

3. **查看进度**
   ```bash
   cat todos_state.yaml
   ```

4. **查看日志**
   ```bash
   tail -f logs/2.2.log
   ```

### 断点续传流程

1. **中断执行**
   - 按 `Ctrl+C` 中断
   - 或者程序意外终止

2. **查看状态**
   ```bash
   cat todos_state.yaml
   ```

3. **继续执行**
   ```bash
   python orchestrator.py
   ```
   - 程序会自动读取 `todos_state.yaml`
   - 跳过已完成的任务
   - 继续执行未完成的任务

## 📊 状态值说明

### 任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 待执行 |
| `in_progress` | 执行中 |
| `completed` | 已完成 |
| `failed` | 失败 |

### 子任务状态

| 状态 | 说明 |
|------|------|
| `pending` | 待执行 |
| `in_progress` | 执行中（包括长时间任务正在后台运行） |
| `completed` | 已完成 |
| `failed` | 失败 |

## 🚀 扩展文件

未来可能添加的文件：

### codebuddy_client.py
- **作用**：封装 CodeBuddy 调用逻辑
- **类**：`CodeBuddyClient`
- **方法**：
  - `ask(prompt)`：调用 CodeBuddy
  - `modify_code(file, instruction)`：修改代码
  - `check_completion(task, context)`：检查完成条件

### monitor.py
- **作用**：监控长时间任务
- **类**：`TaskMonitor`
- **方法**：
  - `start_monitor(task_id, log_file)`：启动监控
  - `check_status()`：检查状态
  - `stop_monitor(task_id)`：停止监控

### config.py
- **作用**：配置管理
- **类**：`Config`
- **用途**：统一管理配置项

### utils.py
- **作用**：工具函数
- **内容**：日志、文件操作等通用函数

## 📝 文件维护

### 文档更新

- **README.md**：项目重大变更时更新
- **INDEX.md**：文档结构变更时更新
- **ARCHITECTURE.md**：架构设计变更时更新
- **USAGE.md**：功能变更或新增功能时更新
- **FILES.md**：项目结构变更时更新

### 配置更新

- **requirements.txt**：添加新依赖时更新
- **.gitignore**：发现新的需要忽略的文件时更新
- **todos.example.yaml**：新增任务类型或字段时更新

## 总结

本文档详细说明了：

- ✅ 完整的项目目录结构
- ✅ 每个文件的作用和说明
- ✅ 配置文件的详细格式
- ✅ 工作流程说明
- ✅ 状态值说明
- ✅ 未来可能的扩展文件

如有其他问题，请参考：
- [README.md](README.md) - 项目介绍
- [ARCHITECTURE.md](ARCHITECTURE.md) - 架构设计
- [USAGE.md](USAGE.md) - 使用指南
