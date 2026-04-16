"""Ideas Decomposer - prompt builder for decomposing ideas into tasks.

Re-exports the decomposition prompt builder from the prompts package.
The actual decomposition logic is part of IdeasWatcher._decompose_idea_to_tasks().
"""

from prompts.ideas_decompose import build_ideas_decompose_prompt

__all__ = ["build_ideas_decompose_prompt"]
