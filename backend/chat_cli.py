"""
MAIHERA — Terminal Chat Interface (Phase 1 only)
Simple CLI for testing the brain layer end-to-end.
Replaced entirely by the Electron app in Phase 2.
Requires the FastAPI server running on port 8000.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

import httpx

BASE_URL = "http://localhost:8000"
SESSION_ID = str(uuid.uuid4())


def print_maihera(text: str) -> None:
    print(f"\n  MAIHERA: {text}\n")


def print_system(text: str) -> None:
    print(f"  [{text}]")


async def send_message(
    client: httpx.AsyncClient,
    message: str,
    create_node: bool = True
) -> None:
    try:
        response = await client.post(
            f"{BASE_URL}/chat/message",
            json={
                "message": message,
                "session_id": SESSION_ID,
                "create_node_if_detected": create_node
            },
            timeout=30.0
        )
        data = response.json()
        print_maihera(data.get("response", "No response"))

        if data.get("node_created"):
            node = data["node_created"]
            print_system(
                f"Node auto-created: [{node['type']}] "
                f"{node['label']} "
                f"(project: {node.get('project', 'none')})"
            )

    except httpx.TimeoutException:
        print_system("Request timed out — is the server running?")
    except Exception as e:
        print_system(f"Error: {e}")


async def show_graph(client: httpx.AsyncClient) -> None:
    try:
        response = await client.get(f"{BASE_URL}/brain/graph")
        graph = response.json()
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        print(f"\n  Brain Graph Summary")
        print(f"  {'─' * 36}")
        print(f"  Nodes : {len(nodes)}")
        print(f"  Edges : {len(edges)}")

        # Group by type
        by_type: dict[str, list] = {}
        for node in nodes:
            t = node.get("type", "unknown")
            by_type.setdefault(t, []).append(node)

        for node_type, type_nodes in sorted(by_type.items()):
            print(f"\n  {node_type.upper()} ({len(type_nodes)})")
            for n in type_nodes:
                imp = n.get("importance", 0)
                att = n.get("attention", 0)
                status = n.get("status", "active")
                print(
                    f"    • {n.get('label', 'unnamed')}"
                    f" [imp:{imp:.2f} att:{att:.2f}]"
                    f" {status}"
                )
        print()

    except Exception as e:
        print_system(f"Graph error: {e}")


async def show_nodes(client: httpx.AsyncClient) -> None:
    try:
        response = await client.get(f"{BASE_URL}/brain/nodes")
        data = response.json()
        nodes = data.get("nodes", [])

        print(f"\n  All Nodes ({len(nodes)} total)")
        print(f"  {'─' * 36}")

        # Group by project
        by_project: dict[str, list] = {}
        for node in nodes:
            pid = node.get("project_id") or "no project"
            by_project.setdefault(pid, []).append(node)

        for project_id, proj_nodes in by_project.items():
            print(f"\n  Project: {project_id[:8]}...")
            for n in proj_nodes:
                urgency_resp = await client.get(
                    f"{BASE_URL}/brain/nodes/{n['id']}/urgency"
                )
                urgency = urgency_resp.json().get("urgency", 0)
                print(
                    f"    [{n.get('type', '?'):10}] "
                    f"{n.get('label', 'unnamed')[:40]}"
                    f" | imp:{n.get('importance', 0):.2f}"
                    f" att:{n.get('attention', 0):.2f}"
                    f" urg:{urgency:.2f}"
                    f" | {n.get('status', 'active')}"
                )
        print()

    except Exception as e:
        print_system(f"Nodes error: {e}")


async def show_stats(client: httpx.AsyncClient) -> None:
    try:
        stats_resp = await client.get(f"{BASE_URL}/brain/stats")
        quota_resp = await client.get(f"{BASE_URL}/chat/quota")
        health_resp = await client.get(f"{BASE_URL}/health/full")

        stats = stats_resp.json()
        quota = quota_resp.json()
        health = health_resp.json()

        print(f"\n  MAIHERA System Stats")
        print(f"  {'─' * 36}")
        print(f"  Brain nodes  : {stats.get('node_count', 0)}")
        print(f"  Brain edges  : {stats.get('edge_count', 0)}")
        print(f"  Node types   : {stats.get('type_counts', {})}")

        ollama = quota.get('ollama', {})
        groq = quota.get('groq', {})
        print(f"\n  LLM Quota")
        print(
            f"  Ollama session: "
            f"{ollama.get('session_used', 0)}/"
            f"{ollama.get('session_cap', 20)} used"
            f" ({ollama.get('session_remaining', 0)} remaining)"
        )
        print(
            f"  Groq daily   : "
            f"{groq.get('daily_used', 0)}/"
            f"{groq.get('daily_cap', 200)} used"
            f" ({groq.get('daily_remaining', 0)} remaining)"
        )

        decay = health.get('services', {}).get('decay_worker', {})
        decay_stats = decay.get('stats', {})
        print(f"\n  Decay Worker")
        print(f"  Running      : {decay_stats.get('running', False)}")
        print(
            f"  Total runs   : "
            f"{decay_stats.get('total_decay_runs', 0)}"
        )
        print(
            f"  Last run     : "
            f"{decay_stats.get('last_run', 'never')}"
        )
        print()

    except Exception as e:
        print_system(f"Stats error: {e}")


async def search_nodes(
    client: httpx.AsyncClient,
    query: str
) -> None:
    try:
        response = await client.get(
            f"{BASE_URL}/brain/search",
            params={"q": query}
        )
        data = response.json()
        results = data.get("results", [])

        print(f"\n  Search: '{query}' — {len(results)} results")
        print(f"  {'─' * 36}")
        for r in results[:5]:
            dist = r.get('_search_distance', 0)
            print(
                f"  [{r.get('type', '?'):10}] "
                f"{r.get('label', 'unnamed')[:40]}"
                f" | distance: {dist:.3f}"
            )
        print()

    except Exception as e:
        print_system(f"Search error: {e}")


def print_help() -> None:
    print("""
  Commands:
  ─────────────────────────────────────
  /graph          Show brain graph summary
  /nodes          List all nodes with signals
  /stats          Show system stats and quota
  /search <query> Semantic search the brain
  /seed           Check if seed data exists
  /help           Show this help
  /quit           Exit

  Anything else is sent to MAIHERA as a message.
  Node auto-creation is ON by default.
  Prefix message with ! to disable: !just chatting
    """)


async def check_server(client: httpx.AsyncClient) -> bool:
    try:
        response = await client.get(
            f"{BASE_URL}/health", timeout=3.0
        )
        return response.status_code == 200
    except Exception:
        return False


async def main() -> None:
    print("\n" + "=" * 44)
    print("  M.A.I.H.E.R.A — Terminal Interface")
    print("  Phase 1 — The Brain is Born")
    print("=" * 44)

    async with httpx.AsyncClient() as client:
        # Check server
        if not await check_server(client):
            print_system(
                "Cannot reach MAIHERA API at localhost:8000. "
                "Start the server first: "
                "uvicorn api.main:app --port 8000"
            )
            sys.exit(1)

        print_system("Connected to MAIHERA API")
        print_system(f"Session: {SESSION_ID[:8]}...")
        print_system("Type /help for commands or just start talking")
        print()

        # Initial greeting
        await send_message(
            client,
            "MAIHERA, I just started a new session.",
            create_node=False
        )

        # Main loop
        while True:
            try:
                user_input = input("  You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n")
                print_system("Session ended.")
                break

            if not user_input:
                continue

            # Commands
            if user_input == "/quit":
                print_system("Goodbye, Boss.")
                break

            elif user_input == "/help":
                print_help()

            elif user_input == "/graph":
                await show_graph(client)

            elif user_input == "/nodes":
                await show_nodes(client)

            elif user_input == "/stats":
                await show_stats(client)

            elif user_input.startswith("/search "):
                query = user_input[8:].strip()
                if query:
                    await search_nodes(client, query)
                else:
                    print_system("Usage: /search <query>")

            elif user_input == "/seed":
                response = await client.get(f"{BASE_URL}/brain/stats")
                stats = response.json()
                print_system(
                    f"Brain has {stats.get('node_count', 0)} nodes "
                    f"and {stats.get('edge_count', 0)} edges."
                )

            elif user_input.startswith("!"):
                # No node creation
                await send_message(
                    client,
                    user_input[1:].strip(),
                    create_node=False
                )

            else:
                await send_message(client, user_input)


if __name__ == "__main__":
    asyncio.run(main())