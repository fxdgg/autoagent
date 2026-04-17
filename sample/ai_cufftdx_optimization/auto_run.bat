@ECHO OFF

REM 全自动运行（AI调度模式）

python ../../src/orchestrator.py --config todos.yaml --workspace cufftdx_optimization --model deepseek-v3.2 --mode ai