"""cli.py – Conversational CLI entrypoint for the SRE agent (Strands).

Commands available during a session:
    /help               – Show available commands
    /reset              – Clear conversation history
    /summarize          – Print a summary of the current session from memory
    /recall <sessionId> – Load a previous session from AgentCore Memory
    /export             – Export the current investigation bundle to disk
    /quit, /exit, /q    – Exit the agent

Usage:
    cw-sre-agent [OPTIONS]
    python -m cw_sre_agent [OPTIONS]
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Optional

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from cw_sre_agent import __version__
from cw_sre_agent.agent import build_system_prompt, create_sre_agent
from cw_sre_agent.config import load_config
from cw_sre_agent.export import BundleBuilder, export_bundle
from cw_sre_agent.logging import AgentLogger, LogContext
from cw_sre_agent.memory import AgentMemory

console = Console()

# ── Slash-command registry ────────────────────────────────────────────────────

_HELP_TEXT = """
## Comandos disponibles

| Comando              | Descripción                                            |
|----------------------|--------------------------------------------------------|
| `/help`              | Muestra este mensaje                                   |
| `/reset`             | Limpia historial de conversación                       |
| `/summarize`         | Resumen de la sesión actual desde memoria              |
| `/recall <sessionId>`| Carga sesión anterior por session_id                  |
| `/export`            | Exporta bundle de investigación a disco                |
| `/quit` / `/exit`    | Termina el agente                                      |

Escribe cualquier otra cosa para conversar con el agente SRE.
"""


# ── Async core ────────────────────────────────────────────────────────────────

async def _run_session(
    config,
    export_dir: str,
) -> None:
    """Run the full interactive session loop using Strands Agent."""

    session_id = str(uuid.uuid4())

    # ── Bootstrap context + logging ──────────────────────────────────────────
    log_ctx = LogContext(session_id=session_id)
    logger = AgentLogger(
        context=log_ctx,
        aws_region=config.aws_region,
        log_group=config.agent_log_group,
        debug_mode=config.debug_mode,
        max_result_chars=config.max_result_chars,
    )

    logger.info(
        "session_start",
        version=__version__,
        model=config.effective_model_id,
        region=config.aws_region,
    )

    console.print(
        Panel.fit(
            f"[bold cyan]CW SRE Agent[/bold cyan]  v{__version__}\n"
            f"[dim]Modelo: {config.effective_model_id}  |  "
            f"Región runtime: {config.aws_region}[/dim]",
            border_style="cyan",
        )
    )

    # ── Memory ────────────────────────────────────────────────────────────────
    memory = AgentMemory(
        memory_id=config.memory_id,
        actor_id=config.memory_actor_id,
        region=config.aws_region,
        logger=logger,
    )

    # ── Bundle builder ────────────────────────────────────────────────────────
    bundle = BundleBuilder(
        session_id=session_id,
        model_id=config.effective_model_id,
        aws_region=config.aws_region,
    )

    # ── Strands Agent ─────────────────────────────────────────────────────────
    agent, mcp_client = create_sre_agent(config)

    console.print(
        f"\n[green]Sesión iniciada[/green]  |  session_id: [bold]{session_id}[/bold]"
    )
    console.print("[dim]Escribe /help para ver los comandos disponibles.[/dim]\n")

    # ── REPL ──────────────────────────────────────────────────────────────────
    try:
        while True:
            try:
                raw = console.input("[bold cyan]SRE>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Saliendo…[/dim]")
                break

            if not raw:
                continue

            # ── Slash commands ─────────────────────────────────────────────
            if raw.startswith("/"):
                parts = raw.split(maxsplit=1)
                cmd = parts[0].lower()

                if cmd in ("/quit", "/exit", "/q"):
                    console.print("[dim]Hasta luego.[/dim]")
                    break

                elif cmd == "/help":
                    console.print(Markdown(_HELP_TEXT))

                elif cmd == "/reset":
                    console.print("[yellow]Historial limpiado.[/yellow]")
                    session_id = str(uuid.uuid4())
                    log_ctx.session_id = session_id
                    bundle = BundleBuilder(
                        session_id=session_id,
                        model_id=config.effective_model_id,
                        aws_region=config.aws_region,
                    )
                    # Re-create agent with fresh conversation
                    try:
                        mcp_client.stop()
                    except Exception:
                        pass
                    agent, mcp_client = create_sre_agent(config)
                    console.print(
                        f"[green]Nueva sesión:[/green] {session_id}\n"
                    )

                elif cmd == "/summarize":
                    summary = memory.summarize_session(session_id)
                    console.print(Panel(summary, title="Memory Summary", border_style="blue"))

                elif cmd == "/recall":
                    if len(parts) < 2:
                        console.print("[red]/recall requiere un session_id.[/red]")
                        continue
                    recall_id = parts[1].strip()
                    records = memory.recall_session(recall_id)
                    if not records:
                        console.print(f"[yellow]No se encontraron registros para {recall_id}[/yellow]")
                    else:
                        console.print(
                            Panel(
                                memory.summarize_session(recall_id),
                                title=f"Recall – {recall_id}",
                                border_style="blue",
                            )
                        )

                elif cmd == "/export":
                    path = export_bundle(bundle.build(), output_dir=export_dir, logger=logger)
                    console.print(f"[green]Bundle exportado:[/green] {path}")

                else:
                    console.print(f"[red]Comando desconocido: {cmd}[/red]  Usa /help")

                continue

            # ── Normal chat turn ────────────────────────────────────────────
            console.print("[dim]Pensando…[/dim]")
            try:
                # Strands handles the full agentic loop
                result = agent(raw)
                answer = str(result)
                bundle.add_turn("user", raw, correlation_id=log_ctx.correlation_id)
                bundle.add_turn("assistant", answer, correlation_id=log_ctx.correlation_id)
            except Exception as exc:
                logger.error("repl_error", exc=exc)
                console.print(f"[red]Error:[/red] {exc}")
                continue

            # Render markdown in the response
            console.print(Panel(Markdown(answer), title="SRE Agent", border_style="green"))

    finally:
        # Clean up MCP client
        try:
            mcp_client.stop()
        except Exception:
            pass

    # Final export
    final_path = export_bundle(bundle.build(), output_dir=export_dir, logger=logger)
    console.print(f"[dim]Bundle final guardado en: {final_path}[/dim]")
    logger.info("session_end", bundle_path=final_path)


# ── Click entrypoint ──────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--model",
    default=None,
    help="Override MODEL_ID env var (local development only).",
    show_default=False,
)
@click.option(
    "--export-dir",
    default="./exports",
    show_default=True,
    help="Directory for exported investigation bundles.",
)
@click.version_option(__version__, prog_name="cw-sre-agent")
def main(
    model: Optional[str],
    export_dir: str,
) -> None:
    """CW SRE Agent – Conversational incident troubleshooting via Strands + MCP."""
    # Load .env file if present (helpful for local dev)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    config = load_config(model_id_override=model)

    console.print(
        f"[dim]Modelo seleccionado: [bold]{config.effective_model_id}[/bold][/dim]"
    )

    asyncio.run(
        _run_session(
            config=config,
            export_dir=export_dir,
        )
    )


if __name__ == "__main__":
    main()
