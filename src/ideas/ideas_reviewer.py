"""Ideas Reviewer - prompt builders for reviewing decomposed tasks.

Re-exports the review prompt builders from the prompts package.
The actual review logic is part of IdeasWatcher._review_tasks() and
IdeasWatcher._review_and_validate_loop().
"""

from prompts.ideas_review import build_ideas_review_prompt, build_revision_prompt

__all__ = ["build_ideas_review_prompt", "build_revision_prompt"]
