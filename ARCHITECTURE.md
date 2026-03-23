# 架构设计文档

本文档详细描述 LangGraph + CodeBuddy Todo Orchestrator 的架构设计。

## 目录

- [系统架构](#系统架构)
- [核心组件](#核心组件)
- [任务类型](#任务类型)
- [数据流](#数据流)
- [状态管理](#状态管理)
- [长时间任务处理](#长时间任务处理)
- [错误处理](#错误处理)
- [扩展性设计](#扩展性设计)

## 系统架构

### 分层架构

```
┌─────────────────────────────────────────┐
│  应用层 (Application Layer)             │
│  - orchestrator.py                      │
│  - CLI 命令行接口                        │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  业务逻辑层 (Business Logic Layer)      │
│  - TaskOrchestrator 类                  │
│  - 任务调度器                           │
│  - 配置解析器                           │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  任务执行层 (Task Execution Layer)      │
│  - SimpleTaskExecutor                   │
│  - NestedTaskExecutor                   │
│  - SubtaskExecutor                      │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  AI 能力层 (AI Capability Layer)        │
│  - CodeBuddyClient 类                   │
│  - 提示词构造器                         │
│  - 响应解析器                           │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  基础设施层 (Infrastructure Layer)      │
│  - 文件系统                             │
│  - 子进程执行                           │
│  - Nohup 监控                           │
│  - Git 操作（可选）                     │
└─────────────────────────────────────────┘
```

### 模块依赖关系

```
orchestrator.py
    ├── yaml (配置解析)
    ├── task_executor.py (任务执行)
    │   ├── codebuddy_client.py (AI 能力)
    │   │   └── subprocess (调用 CodeBuddy)
    │   └── subprocess (执行命令)
    └── monitor.py (长时间任务监控)
        └── subprocess (监控进程)
```

## 核心组件

### 1. TaskOrchestrator

**职责**：任务编排和执行管理

**核心方法**：
```python
class TaskOrchestrator:
    def __init__(self, todos_file: str = "todos.yaml", state_file: str = "todos_state.yaml")
    def load_todos(self) -> list
    def load_state(self) -> dict
    def save_state(self, state: dict)
    def run(self)
    def execute_task(self, task: dict)
    def execute_simple_task(self, task: dict)
    def execute_nested_task(self, task: dict)
    def execute_subtask(self, parent_task_id: str, subtask: dict)
    def call_codebuddy(self, prompt: str) -> str
```

**设计要点**：
- 单一职责：只负责任务调度，不涉及具体执行逻辑
- 状态持久化：支持保存和恢复执行状态
- 统一接口：所有任务类型通过统一接口调用

### 2. SimpleTaskExecutor

**职责**：执行简单任务（一次性命令 + AI 判断）

**执行流程**：
```python
def execute_simple_task_node(task: dict) -> bool:
    """执行简单任务"""
    attempts = 0
    max_attempts = 100  # 防止无限循环
    
    while attempts < max_attempts:
        attempts += 1
        
        # 1. 调用 AI 尝试完成任务
        result = call_codebuddy(f"""
        任务：{task['description']}
        
        完成条件：{task['completion_criteria']}
        
        初始提示：{task.get('initial_hint', '无')}
        
        请尝试完成这个任务。
        
        完成后，请回复以下格式：
        - ✅ 完成：如果满足完成条件
        - ❌ 未完成：如果不满足，并说明你打算如何改进
        """)
        
        # 2. AI 自己判断是否达标
        if "✅ 完成" in result:
            mark_task_completed(task.id)
            return True
        
        # 3. AI 决定如何改进，然后继续循环
        # （AI 自己决定改什么、怎么改）
    
    return False
```

**设计要点**：
- AI 完全自主判断完成条件
- AI 完全自主决定如何改进
- 持续迭代直到达标
- 防止无限循环

### 3. NestedTaskExecutor

**职责**：执行嵌套任务（包含子任务）

**执行流程**：
```python
def execute_nested_task(task: dict):
    """执行嵌套任务"""
    task_id = task['id']
    mark_task_status(task_id, "in_progress")
    
    # 执行所有子任务
    for subtask in task['subtasks']:
        execute_subtask(task_id, subtask)
    
    # 所有子任务完成后，AI 判断主任务是否完成
    result = call_codebuddy(f"""
    主任务：{task['name']}
    
    完成条件：{task['completion_criteria']}
    
    所有子任务已完成。请检查子任务的执行结果，并告诉我主任务是否满足完成条件。
    
    - ✅ 主任务完成：如果满足完成条件
    - ❌ 主任务未完成：如果不满足，并说明原因
    """)
    
    if "✅ 主任务完成" in result:
        mark_task_status(task_id, "completed")
    else:
        mark_task_status(task_id, "failed")
```

**设计要点**：
- 子任务按顺序执行
- 所有子任务完成后，AI 判断主任务是否完成
- 如果未完成，重新从第一个子任务开始

## 任务类型

### 1. 简单任务 (simple)

**定义**：一次性执行命令，由 AI 判断是否完成

**配置示例**：
```yaml
- id: 1
  name: "下载数据集"
  type: simple
  completion_criteria: "data.csv 文件存在且大小 > 10MB"
  initial_hint: "使用 python download.py"
```

**执行流程**：
```
1. AI 尝试完成任务（根据 initial_hint）
   ↓
2. AI 自我评估是否满足完成条件
   ↓
3. 如果满足：标记完成
   如果不满足：AI 决定如何改进，重新尝试
   ↓
4. 循环直到满足条件或达到最大尝试次数
```

### 2. 嵌套任务 (nested)

**定义**：包含多个子任务的任务

**配置示例**：
```yaml
- id: 2
  name: "优化模型性能"
  type: nested
  completion_criteria: "训练成功完成且 val_loss < 0.5"
  subtasks:
    - id: 2.1
      name: "修改训练代码"
      type: ai_action
      completion_criteria: "代码修改完成"
      
    - id: 2.2
      name: "运行训练"
      type: long_running
      command: "python train.py --config modified_config.yaml"
      completion_criteria: "训练正常退出且验证集指标满足要求"
```

**执行流程**：
```
1. 执行子任务 2.1（AI 修改代码）
   ↓
2. 执行子任务 2.2（运行训练，可能很长）
   ↓
3. 所有子任务完成后，AI 判断主任务是否完成
   ↓
4. 如果未完成：重新从子任务 2.1 开始
   ↓
5. 循环直到满足条件或达到最大尝试次数
```

### 3. AI 操作任务 (ai_action)

**定义**：调用 AI 修改代码或执行其他操作

**配置示例**：
```yaml
- id: 2.1
  name: "修改训练代码"
  type: ai_action
  completion_criteria: "代码修改完成"
```

**执行流程**：
```
1. 调用 CodeBuddy 执行操作
   ↓
2. AI 自我评估是否满足完成条件
   ↓
3. 如果满足：标记完成
   如果不满足：继续改进
   ↓
4. 循环直到满足条件或达到最大尝试次数
```

### 4. 长时间任务 (long_running)

**定义**：使用 nohup 后台运行的任务，避免超时

**配置示例**：
```yaml
- id: 2.2
  name: "运行训练"
  type: long_running
  command: "python train.py --config modified_config.yaml"
  completion_criteria: "训练正常退出且验证集指标满足要求"
```

**执行流程**：
```
1. 构造 nohup 命令
   ↓
2. 启动后台训练
   ↓
3. 启动监控进程
   ↓
4. 监控进程持续检查日志
   ↓
5. 检测到完成：调用 AI 检查结果
   ↓
6. AI 判断是否满足完成条件
```

**技术实现**：
- 使用 `nohup` 在后台运行
- 启动独立的监控进程
- 监控进程持续检查日志文件
- 检测到完成标志后通知 AI

## 数据流

### 简单任务执行流程

```
1. 加载 todos.yaml
   ↓
2. 解析任务配置
   ↓
3. 尝试 #1：
   ├─ 调用 CodeBuddy
   ├─ AI 尝试完成任务
   ├─ AI 自我评估
   └─ 如果完成：标记完成
      如果未完成：继续
   ↓
4. 尝试 #2：
   ├─ 调用 CodeBuddy
   ├─ AI 根据上次的反馈改进
   ├─ AI 自我评估
   └─ 如果完成：标记完成
      如果未完成：继续
   ↓
5. 循环直到完成或达到最大尝试次数
```

### 嵌套任务执行流程

```
1. 加载 todos.yaml
   ↓
2. 解析任务配置
   ↓
3. 执行主任务
   ↓
4. 执行子任务 2.1（ai_action）
   ├─ 调用 CodeBuddy
   ├─ AI 修改代码
   └─ AI 判断是否完成
   ↓
5. 执行子任务 2.2（long_running）
   ├─ 使用 nohup 启动后台训练
   ├─ 启动监控进程
   ├─ 监控进程检查日志
   └─ 检测到完成：调用 AI 检查结果
   ↓
6. 所有子任务完成
   ↓
7. AI 判断主任务是否完成
   ├─ 如果完成：标记主任务完成
   └─ 如果未完成：重新从子任务 2.1 开始
   ↓
8. 循环直到主任务完成或达到最大尝试次数
```

## 状态管理

### 状态文件结构

```yaml
# todos_state.yaml
tasks:
  - id: 1
    status: "completed"  # pending | in_progress | completed | failed
    attempts: 3
    last_attempt: "2026-03-23 22:30:00"
    
  - id: 2
    status: "in_progress"
    current_subtask: 2.2
    subtasks:
      - id: 2.1
        status: "completed"
        attempts: 3
        history:
          - attempt: 1
            time: "2026-03-23 22:00:00"
            action: "修改学习率为 0.001"
            result: "修改完成"
          - attempt: 2
            action: "优化网络结构"
            result: "修改完成"
          - attempt: 3
            action: "添加正则化"
            result: "修改完成，满足条件"
            
      - id: 2.2
        status: "running"  # running | completed | failed
        started_at: "2026-03-23 22:30:00"
        log_file: "logs/2.2.log"
        monitor_pid: 12345
        command: "python train.py --config modified_config.yaml"
```

### 状态持久化

```python
class TaskOrchestrator:
    def __init__(self, todos_file="todos.yaml", state_file="todos_state.yaml"):
        self.todos_file = todos_file
        self.state_file = state_file
        self.todos = self.load_todos()
        self.state = self.load_state()
    
    def load_state(self):
        try:
            with open(self.state_file) as f:
                return yaml.safe_load(f) or {"tasks": {}}
        except FileNotFoundError:
            return {"tasks": {}}
    
    def save_state(self):
        with open(self.state_file, "w") as f:
            yaml.dump(self.state, f)
    
    def get_task_state(self, task_id):
        return self.state["tasks"].get(task_id, {"status": "pending"})
    
    def mark_task_status(self, task_id, status, **kwargs):
        if task_id not in self.state["tasks"]:
            self.state["tasks"][task_id] = {}
        
        self.state["tasks"][task_id]["status"] = status
        self.state["tasks"][task_id].update(kwargs)
        self.save_state()
```

## 长时间任务处理

### 问题背景

**为什么需要长时间任务处理？**

CodeBuddy 有超时限制（通常 1 小时），但某些任务（如模型训练）可能需要更长时间。

### 解决方案

**使用 nohup 后台运行 + 独立监控进程：**

```python
def execute_long_running_task(subtask):
    log_file = f"logs/{subtask_id}.log"
    command = subtask["command"]
    
    # 1. 构造 nohup 命令
    full_command = f"nohup {command} > {log_file} 2>&1 &"
    
    # 2. 启动后台任务
    subprocess.run(full_command, shell=True)
    mark_task_status(subtask_id, "running", 
                    log_file=log_file, 
                    started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    
    # 3. 启动监控
    start_monitor(subtask_id, log_file, subtask["completion_criteria"])
    
    # 4. 等待监控完成
    wait_for_completion(subtask_id)
```

### 监控进程

```python
def start_monitor(subtask_id, log_file, completion_criteria):
    monitor_script = f"""#!/bin/bash
LOG_FILE="{log_file}"
SUBTASK_ID="{subtask_id}"
COMPLETION_CRITERIA="{completion_criteria}"

while true; do
    if [ -f "$LOG_FILE" ]; then
        # 检查是否有错误
        if grep -q "ERROR\\|Exception\\|Traceback" "$LOG_FILE"; then
            echo "检测到错误"
            codebuddy -y -m "子任务 $SUBTASK_ID 检测到错误。请检查 $LOG_FILE 并修复问题。"
            exit 1
        fi
        
        # 检查是否完成
        if grep -q "Training completed\\|Done\\|Finished" "$LOG_FILE"; then
            echo "任务完成"
            codebuddy -y -m "子任务 $SUBTASK_ID 已完成。完成条件：$COMPLETION_CRITERIA。请检查 $LOG_FILE 中的结果，并告诉我是否满足完成条件。回复格式：- ✅ 子任务完成 或 - ❌ 子任务未完成"
            exit 0
        fi
    fi
    sleep 30
done
"""
    
    monitor_file = f"monitors/{subtask_id}.sh"
    with open(monitor_file, "w") as f:
        f.write(monitor_script)
    
    subprocess.run(f"chmod +x {monitor_file} && nohup {monitor_file} > monitors/{subtask_id}.log 2>&1 &", shell=True)
```

### 项目结构

```
langgraph-todo-orchestrator/
├── orchestrator.py          # 主程序
├── todos.yaml              # 任务定义
├── todos_state.yaml        # 任务状态（自动生成）
├── logs/                   # 长时间任务日志
│   └── 2.2.log
├── monitors/               # 监控脚本
│   ├── 2.2.sh
│   └── 2.2.log
└── README.md
```

## 错误处理

### 错误分类

1. **配置错误**
   - YAML 语法错误
   - 缺少必需字段
   - 字段类型错误

2. **执行错误**
   - 命令执行失败（退出码 != 0）
   - 超时
   - OOM（内存溢出）

3. **AI 错误**
   - CodeBuddy 调用失败
   - 响应解析失败
   - AI 返回无效响应

### 错误处理策略

```python
def execute_task(self, task: dict) -> bool:
    try:
        # 1. 验证配置
        self._validate_task(task)
        
        # 2. 执行任务
        if task['type'] == 'simple':
            result = self.execute_simple_task(task)
        elif task['type'] == 'nested':
            result = self.execute_nested_task(task)
        
        return result
    
    except ConfigError as e:
        print(f"❌ 配置错误: {e}")
        return False
    
    except ExecutionError as e:
        print(f"❌ 执行错误: {e}")
        return False
    
    except AICallError as e:
        print(f"❌ AI 调用错误: {e}")
        return False
    
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        self._log_error(e)
        return False
```

## 扩展性设计

### 1. 新增任务类型

```yaml
# 并行任务
- id: 1
  name: "并行数据预处理"
  type: parallel
  commands:
    - "python process_part1.py"
    - "python process_part2.py"
    - "python process_part3.py"
```

### 2. 新增验证器

```python
class CompletionValidator:
    """完成标准验证器"""
    
    def validate(self, criteria: str, context: dict) -> bool:
        # 将自然语言标准转换为验证逻辑
        # 可以使用 AI 或规则引擎
        
        # 示例：简单的关键词匹配
        if "accuracy >=" in criteria:
            threshold = float(criteria.split("accuracy >= ")[1].split()[0])
            return context['accuracy'] >= threshold
        
        # 更复杂的逻辑可以调用 AI
        return self._ask_ai(criteria, context)
```

### 3. 新增通知方式

```python
class Notifier:
    """任务完成通知"""
    
    def notify(self, task_id: int, status: str, message: str):
        # 支持：邮件、企业微信、Slack 等
        pass
```

## 总结

本架构设计实现了：

- ✅ 统一的任务执行模型（不再区分简单任务和循环任务）
- ✅ AI 完全自主判断完成条件
- ✅ 支持嵌套任务
- ✅ 支持长时间任务的 nohup 处理
- ✅ 清晰的分层结构
- ✅ 完善的状态管理
- ✅ 可扩展的设计
