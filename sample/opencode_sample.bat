@ECHO OFF

REM 首先生成设计文档并人工审核，然后再全自动运行

python ../orchestrator.py --ideas ideas.md --config todos.yaml --workspace cufftdx_optimization --provider opencode --model model-scope/ZhipuAI/GLM-5 --ideas-only --human-review

python ../orchestrator.py --ideas ideas.md --config todos.yaml --workspace cufftdx_optimization --provider opencode --model model-scope/ZhipuAI/GLM-5