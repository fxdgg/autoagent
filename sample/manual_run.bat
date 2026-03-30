@ECHO OFF

REM 首先生成设计文档并人工审核，然后再全自动运行

python ../orchestrator.py --ideas ideas.md --config todos.yaml --workspace cufftdx_optimization --model deepseek-v3.2 --ideas-only

python ../orchestrator.py --ideas ideas.md --config todos.yaml --workspace cufftdx_optimization --model deepseek-v3.2