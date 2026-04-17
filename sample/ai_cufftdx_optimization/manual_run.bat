@ECHO OFF

REM 首先生成设计文档并人工审核，然后再全自动运行（AI调度模式）

python ../../src/orchestrator.py --ideas ideas.md --config todos.yaml --workspace cufftdx_optimization --model deepseek-v3.2 --ideas-only --human-review

python ../../src/orchestrator.py --config todos.yaml --workspace cufftdx_optimization --model deepseek-v3.2 --mode ai