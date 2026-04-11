"""Interactive CLI for the Agent Platform.

Provides a terminal-based interface to create sessions and
converse with the agentic coding system.

Usage:
    agent-platform                      # interactive mode (default model + react)
    agent-platform --model gpt-4o       # use a specific model
    agent-platform --harness plan_execute
    agent-platform --list-models
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from agent_platform.core.factory import create_platform
from agent_platform.core.session import AgentSession, SessionStatus
from agent_platform.core.agent_loop import run_agent_loop


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent-platform",
        description="In-house Agentic Coding Platform CLI",
    )
    parser.add_argument(
        "--model", "-m",
        help="Model ID to use (default from settings)",
    )
    parser.add_argument(
        "--harness", "-H",
        default="react",
        choices=["react", "plan_execute"],
        help="Harness pattern (default: react)",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models and exit",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List registered tools and exit",
    )
    parser.add_argument(
        "--once", "-1",
        metavar="PROMPT",
        help="Run a single prompt non-interactively and exit",
    )
    return parser.parse_args()


def _print_banner(model: str, harness: str, n_tools: int, providers: list[str]) -> None:
    print("\n\033[1;36m=== Agent Platform CLI ===\033[0m")
    print(f"  Model:     {model}")
    print(f"  Harness:   {harness}")
    print(f"  Tools:     {n_tools} registered")
    print(f"  Providers: {', '.join(providers) or '(none)'}")
    print("  Type your message. Enter an empty line to send.")
    print("  Commands: /quit /status /cost /model <id>\n")


async def _run_interactive(args: argparse.Namespace) -> None:
    ctx = create_platform()

    model_id = args.model or ctx.settings.gateway.default_model
    harness_id = args.harness
    harness = ctx.harnesses.get(harness_id)
    if not harness:
        print(f"Error: Unknown harness '{harness_id}'")
        sys.exit(1)

    # List commands
    if args.list_models:
        print("\nAvailable models:")
        for m in ctx.gateway.list_models():
            print(f"  {m['model']:35s}  ({m['provider']})")
        return

    if args.list_tools:
        print("\nRegistered tools:")
        for t in ctx.tool_registry.list_tools():
            par = "parallel" if t.parallel_safe else "sequential"
            print(f"  {t.name:25s}  {par:12s}  {t.description}")
        return

    # Single-shot mode
    if args.once:
        session = AgentSession(model_id=model_id, harness_id=harness_id)
        session.add_message("user", args.once)
        result = await run_agent_loop(session, ctx.gateway, ctx.tool_registry, harness)
        if result.messages:
            last = result.messages[-1]
            print(last.content)
        return

    # Interactive REPL
    provider_names = list(ctx.gateway._providers.keys())
    _print_banner(model_id, harness_id, len(ctx.tool_registry.list_tools()), provider_names)

    session = AgentSession(model_id=model_id, harness_id=harness_id)
    await ctx.session_store.save(session)

    while True:
        try:
            lines: list[str] = []
            while True:
                prompt = "\033[1;32m> \033[0m" if not lines else "\033[90m. \033[0m"
                line = input(prompt)
                if line == "":
                    break
                lines.append(line)

            if not lines:
                continue

            user_input = "\n".join(lines)

            # Handle slash commands
            if user_input.startswith("/"):
                cmd = user_input.strip().lower()
                if cmd in ("/quit", "/exit", "/q"):
                    print("\nGoodbye.")
                    break
                elif cmd == "/status":
                    print(f"  Session:  {session.session_id}")
                    print(f"  Status:   {session.status.value}")
                    print(f"  Messages: {len(session.messages)}")
                    print(f"  Tokens:   {session.total_input_tokens} in / {session.total_output_tokens} out")
                    continue
                elif cmd == "/cost":
                    print(f"  Total cost: ${session.total_cost_usd:.6f}")
                    print(f"  Tokens:     {session.total_input_tokens + session.total_output_tokens:,}")
                    continue
                elif cmd.startswith("/model "):
                    new_model = cmd.split(" ", 1)[1].strip()
                    session.model_id = new_model
                    model_id = new_model
                    print(f"  Switched to model: {new_model}")
                    continue
                elif cmd == "/new":
                    session = AgentSession(model_id=model_id, harness_id=harness_id)
                    await ctx.session_store.save(session)
                    print("  New session started.")
                    continue
                else:
                    print(f"  Unknown command: {cmd}")
                    continue

            # Send to agent
            session.add_message("user", user_input)
            print("\033[90m  thinking...\033[0m")

            session = await run_agent_loop(session, ctx.gateway, ctx.tool_registry, harness)

            # Print the last assistant message
            for msg in reversed(session.messages):
                if msg.role == "assistant":
                    print(f"\n\033[1;34m{msg.content}\033[0m\n")
                    break

            # Reset status for next turn
            if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
                session.status = SessionStatus.IDLE

        except KeyboardInterrupt:
            print("\n\nInterrupted. Type /quit to exit.")
        except EOFError:
            print("\nGoodbye.")
            break


def main() -> None:
    args = _parse_args()
    asyncio.run(_run_interactive(args))


if __name__ == "__main__":
    main()
