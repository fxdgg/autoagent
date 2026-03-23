# 架构设计文档

本文档详细描述 LangGraph + CodeBuddy Todo Orchestrator 的架构设计。

## 目录

- [系统架构](#系统架构)
- [核心组件](#核心组件)
- [数据流](#数据流)
- [状态管理](#状态管理)
- [错误处理](#错误处理)
- [扩展性设计](#扩展性设计)

## 系统架构

### 分层架构

```
┌─────────────────────────────────────────┐
│  应用层 (Application Layer)             │
│  - todo_orchestrator.py                 │
│  - CLI 命令行接口                        │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  业务逻辑层 (Business Logic Layer)      │
│  - TodoOrchestrator 类                  │
│  - 任务调度器                           │
│  - 配置解析器                           │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│  流程编排层 (Orchestration Layer)       │
│  - LangGraph 图构建器                   │
│  - 节点函数                             │
│  - 条件边函数                           │
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
│  - Git 操作（可选）                     │
└─────────────────────────────────────────┘
```

### 模块依赖关系

```
todo_orchestrator.py
    ├── yaml (配置解析)
    ├── langgraph (流程编排)
    └── codebuddy_client.py (AI 能力)
            ├── subprocess (调用 CodeBuddy)
            └── json (响应解析)
```

## 核心组件

### 1. TodoOrchestrator

**职责**：任务编排和执行管理

**核心方法**：
```python
class TodoOrchestrator:
    def __init__(self, todos_file: str = "todos.yaml")
    def load_todos(self) -> list
    def execute_task(self, task: dict) -> bool
    def run(self, task_id: int = None)
```

**设计要点**：
- 单一职责：只负责任务调度，不涉及具体执行逻辑
- 依赖注入：通过构造函数注入 CodeBuddyClient
- 状态持久化：支持保存和恢复执行状态

### 2. SimpleTaskExecutor

**职责**：执行简单的一次性任务

**核心方法**：
```python
def execute_simple_task_node(state: TodoState) -> TodoState:
    """执行简单任务（一次性命令）"""
    task = state['current_task']
    command = task['command']
    
    result = subprocess.run(command, shell=True, ...)
    
    return {
        **state,
        'task_result': result,
        'should_continue': False
    }
```

**设计要点**：
- 直接执行命令，不涉及 AI
- 通过退出码判断成功/失败
- 不支持重试

### 3. LoopTaskGraph (LangGraph)

**职责**：管理循环任务的执行流程

**核心节点**：

#### modify_code_node
```python
def modify_code_node(state: TodoState) -> TodoState:
    """AI 修改代码（循环任务的第一步）"""
    prompt = f"""
    任务: {task['description']}
    完成标准: {task['completion_criteria']}
    当前重试次数: {retry}/{task['max_retries']}
    
    请修改相关代码以完成任务。
    """
    
    ai_response = codebuddy.ask(prompt)
    
    return {**state, 'ai_decision': ai_response}
```

#### run_training_node
```python
def run_training_node(state: TodoState) -> TodoState:
    """运行训练（循环任务第二步）"""
    result = subprocess.run(
        ["uv", "run", "train.py"],
        capture_output=True,
        text=True
    )
    
    return {**state, 'task_result': result}
```

#### check_completion_node
```python
def check_completion_node(state: TodoState) -> TodoState:
    """AI 检查是否完成任务（循环任务第三步）"""
    prompt = f"""
    任务: {task['description']}
    完成标准: {task['completion_criteria']}
    训练结果: {training_result}
    
    根据完成标准判断任务是否完成？
    """
    
    ai_response = codebuddy.ask(prompt)
    
    return {
        **state,
        'ai_decision': ai_response,
        'should_continue': not ai_response['completed']
    }
```

**条件边**：

```python
def should_continue_edge(state: TodoState) -> str:
    """决定是否继续循环"""
    if not state['should_continue']:
        return "done"
    
    if state['retry_count'] >= task['max_retries']:
        return "failed"
    
    return "modify_code"
```

**执行图**：

```
modify_code_node
    ↓ (普通边)
run_training_node
    ↓ (普通边)
check_completion_node
    ↓ (条件边 should_continue_edge)
    ├─ should_continue=True + 未超限 → modify_code_node
    ├─ should_continue=False → END
    └─ 超过 max_retries → END (失败)
```

### 4. CodeBuddyClient

**职责**：封装 CodeBuddy 调用逻辑

**核心方法**：
```python
class CodeBuddyClient:
    def __init__(self, 
                 codebuddy_path: str = "/root/.local/bin/codebuddy",
                 model: str = "glm-4.7",
                 timeout: int = 3600)
    
    def ask(self, prompt: str, expect_json: bool = False) -> dict | str
    def modify_code(self, file_path: str, instruction: str) -> dict
    def check_completion(self, task_description: str, context: dict) -> bool
```

**设计要点**：
- 统一的调用接口
- 自动处理 JSON 解析
- 超时控制
- 错误重试

## 数据流

### 简单任务执行流程

```
1. 加载 todos.yaml
   ↓
2. 解析任务配置
   ↓
3. 执行命令: subprocess.run(command)
   ↓
4. 检查退出码
   ↓
5. 返回成功/失败
```

### 循环任务执行流程

```
1. 加载 todos.yaml
   ↓
2. 解析任务配置
   ↓
3. 启动 LangGraph
   ↓
4. modify_code_node
   ├─ 构造提示词
   ├─ 调用 CodeBuddy
   ├─ 返回 AI 响应
   └─ 更新状态
   ↓
5. run_training_node
   ├─ 执行训练命令
   ├─ 捕获输出
   └─ 更新状态
   ↓
6. check_completion_node
   ├─ 构造提示词（包含训练结果）
   ├─ 调用 CodeBuddy
   ├─ 返回 AI 判断
   └─ 更新状态
   ↓
7. should_continue_edge (条件边)
   ├─ 检查 should_continue
   ├─ 检查 retry_count
   ├─ 返回 "modify_code" / "done" / "failed"
   └─ LangGraph 路由
   ↓ (如果需要继续)
4. modify_code_node (循环)
   ...
```

## 状态管理

### TodoState 定义

```python
class TodoState(TypedDict):
    current_task: dict           # 当前任务信息
    task_result: dict            # 任务执行结果
    ai_decision: dict            # AI 决策结果
    retry_count: int             # 当前重试次数
    should_continue: bool        # 是否继续循环
    completion_status: str       # 完成状态
```

### 状态传递机制

LangGraph 自动管理状态传递：

```python
# 节点函数接收完整状态
def modify_code_node(state: TodoState) -> TodoState:
    # 1. 读取状态
    task = state['current_task']
    retry = state['retry_count']
    
    # 2. 执行逻辑
    ai_response = call_codebuddy(...)
    
    # 3. 返回更新后的状态
    return {
        **state,                    # 保留原有状态
        'ai_decision': ai_response, # 更新部分字段
        'retry_count': retry + 1    # 更新部分字段
    }

# LangGraph 自动将返回的状态传递给下一个节点
```

### 状态持久化

```python
class TodoOrchestrator:
    def __init__(self):
        self.state_file = ".orchestrator_state.json"
    
    def save_state(self, state: dict):
        """保存状态到文件"""
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def load_state(self) -> dict:
        """从文件加载状态"""
        if os.path.exists(self.state_file):
            with open(self.state_file) as f:
                return json.load(f)
        return {}
    
    def execute_task(self, task: dict):
        """执行任务（支持恢复）"""
        # 尝试加载已保存的状态
        saved_state = self.load_state()
        
        if saved_state and saved_state['task_id'] == task['id']:
            # 从中断点继续
            initial_state = saved_state
        else:
            # 从头开始
            initial_state = self._init_state(task)
        
        # 执行
        final_state = self.loop_graph.invoke(initial_state)
        
        # 保存最终状态
        self.save_state(final_state)
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
   - JSON 解析失败
   - AI 返回无效响应

### 错误处理策略

```python
def execute_task(self, task: dict) -> bool:
    try:
        # 1. 验证配置
        self._validate_task(task)
        
        # 2. 执行任务
        if task['type'] == 'simple':
            result = self._execute_simple_task(task)
        elif task['type'] == 'loop':
            result = self._execute_loop_task(task)
        
        return result['success']
    
    except ConfigError as e:
        print(f"❌ 配置错误: {e}")
        return False
    
    except ExecutionError as e:
        print(f"❌ 执行错误: {e}")
        return False
    
    except AICallError as e:
        print(f"❌ AI 调用错误: {e}")
        # 重试一次
        return self._retry_with_new_prompt(task)
    
    except TimeoutError as e:
        print(f"⏱️ 超时错误: {e}")
        return False
    
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        self._log_error(e)
        return False
```

### 重试机制

```python
def execute_with_retry(self, func, max_retries=3, backoff=2):
    """带重试的执行"""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            
            wait_time = backoff ** attempt
            print(f"重试 {attempt + 1}/{max_retries}，等待 {wait_time}s...")
            time.sleep(wait_time)
```

## 扩展性设计

### 1. 新增任务类型

```python
# 在 todos.yaml 中定义新类型
tasks:
  - id: 1
    type: parallel  # 并行任务
    commands:
      - "python script1.py"
      - "python script2.py"

# 在 todo_orchestrator.py 中实现新类型
def execute_parallel_task_node(state: TodoState) -> TodoState:
    """并行执行多个命令"""
    from concurrent.futures import ThreadPoolExecutor
    
    with ThreadPoolExecutor() as executor:
        futures = [
            executor.submit(subprocess.run, cmd, shell=True)
            for cmd in state['current_task']['commands']
        ]
        results = [f.result() for f in futures]
    
    return {**state, 'task_result': results}
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

class TodoOrchestrator:
    def __init__(self, notifier: Notifier = None):
        self.notifier = notifier
    
    def execute_task(self, task: dict):
        result = self._execute_task(task)
        
        if self.notifier:
            self.notifier.notify(
                task_id=task['id'],
                status="success" if result else "failed",
                message=task['description']
            )
```

### 4. 新增状态后端

```python
class StateBackend:
    """状态存储后端"""
    
    def save(self, key: str, state: dict):
        pass
    
    def load(self, key: str) -> dict:
        pass

class FileStateBackend(StateBackend):
    """文件存储后端"""
    
    def __init__(self, base_dir: str = ".orchestrator_state"):
        self.base_dir = base_dir
    
    def save(self, key: str, state: dict):
        path = os.path.join(self.base_dir, f"{key}.json")
        with open(path, 'w') as f:
            json.dump(state, f)
    
    def load(self, key: str) -> dict:
        path = os.path.join(self.base_dir, f"{key}.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return {}

class RedisStateBackend(StateBackend):
    """Redis 存储后端（适用于分布式）"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def save(self, key: str, state: dict):
        self.redis.set(key, json.dumps(state))
    
    def load(self, key: str) -> dict:
        data = self.redis.get(key)
        return json.loads(data) if data else {}
```

## 性能优化

### 1. 并行执行

对于不依赖的任务，可以并行执行：

```python
def execute_parallel_tasks(tasks: list):
    """并行执行多个任务"""
    from concurrent.futures import ThreadPoolExecutor
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(execute_task, task): task
            for task in tasks
        }
        
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                print(f"任务 {task['id']} 完成: {result}")
            except Exception as e:
                print(f"任务 {task['id']} 失败: {e}")
```

### 2. 缓存 AI 响应

```python
class CachedCodeBuddyClient(CodeBuddyClient):
    """带缓存的 CodeBuddy 客户端"""
    
    def __init__(self, *args, cache_file: str = ".codebuddy_cache.json", **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_file = cache_file
        self.cache = self._load_cache()
    
    def ask(self, prompt: str, expect_json: bool = False):
        # 计算提示词的 hash
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()
        
        # 检查缓存
        if prompt_hash in self.cache:
            print("使用缓存的 AI 响应")
            return self.cache[prompt_hash]
        
        # 调用 CodeBuddy
        response = super().ask(prompt, expect_json)
        
        # 保存到缓存
        self.cache[prompt_hash] = response
        self._save_cache()
        
        return response
```

### 3. 批量操作

对于相似的任务，可以批量构造提示词：

```python
def batch_modify_code(files: list, instruction: str):
    """批量修改多个文件"""
    prompt = f"""
    请修改以下文件以实现: {instruction}
    
    文件列表:
    {chr(10).join(f'- {f}' for f in files)}
    
    返回格式: JSON
    {{
      "modifications": [
        {{"file": "file1.py", "content": "...", "reason": "..."}},
        {{"file": "file2.py", "content": "...", "reason": "..."}}
      ]
    }}
    """
    
    response = codebuddy.ask(prompt, expect_json=True)
    
    for mod in response['modifications']:
        with open(mod['file'], 'w') as f:
            f.write(mod['content'])
```

## 安全考虑

1. **命令注入防护**
   - 使用 `subprocess.run` 的 `shell=False` 模式
   - 验证命令白名单

2. **敏感信息保护**
   - 不要将 API Key 写入日志
   - 使用环境变量管理敏感配置

3. **资源限制**
   - 设置超时时间
   - 限制并发数量
   - 监控内存使用

## 总结

本架构设计实现了：

- ✅ 清晰的分层结构
- ✅ 松耦合的组件设计
- ✅ 可扩展的任务类型
- ✅ 完善的错误处理
- ✅ 灵活的状态管理
- ✅ 良好的性能优化空间
