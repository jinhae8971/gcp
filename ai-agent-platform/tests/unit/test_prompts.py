"""Tests for prompt registry."""

from agent_platform.prompts.registry import PromptRegistry


def test_register_and_get():
    reg = PromptRegistry()
    reg.register("test_prompt", "Hello {{name}}")
    assert reg.get("test_prompt") == "Hello {{name}}"


def test_version_history():
    reg = PromptRegistry()
    reg.register("greeting", "v1 content")
    reg.register("greeting", "v2 content")
    assert reg.get("greeting") == "v2 content"
    assert reg.get("greeting", version=1) == "v1 content"


def test_render_template():
    reg = PromptRegistry()
    reg.register("task", "Workspace: {{workspace_root}}, Task: {{task_description}}")
    rendered = reg.render("task", workspace_root="/app", task_description="Fix bug")
    assert rendered == "Workspace: /app, Task: Fix bug"


def test_list_prompts():
    reg = PromptRegistry()
    reg.register("prompt_a", "content a", description="First prompt")
    reg.register("prompt_b", "content b", description="Second prompt")
    listing = reg.list_prompts()
    assert len(listing) == 2
    names = {p["name"] for p in listing}
    assert names == {"prompt_a", "prompt_b"}
