"""Command line interface for DraftProof."""

from __future__ import annotations

import json
import platform
import shutil
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from draftproof import __version__
from draftproof.config import Settings, configure_logging
from draftproof.domain.models import Brief, ContentType, RunStatus, Tone
from draftproof.evaluation import EvalReport, load_cases, run_suite
from draftproof.pipeline.events import EventSink
from draftproof.pipeline.service import RunService
from draftproof.storage.db import Database

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="DraftProof: evidence-first, evaluation-driven publishing.",
)
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

DEMO_TOPIC = "Retrieval-augmented generation in production"


def _utf8_stdio() -> None:
    """Force UTF-8 output so box drawing and arrows work on Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - unusual streams
            continue


class ConsoleSink:
    """Streams pipeline progress to the terminal."""

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type == "stage_started":
            console.print(f"[dim]-> {data.get('stage')}[/dim]")
        elif event_type == "stage_finished":
            console.print(
                f"[green]ok[/green] {data.get('stage')} "
                f"[dim]({data.get('duration_ms', 0)} ms)[/dim]"
            )
        elif event_type == "outline_ready":
            console.print(
                f"  outline: [bold]{data.get('title')}[/bold] "
                f"({len(data.get('sections', []))} sections)"
            )
        elif event_type == "evidence_ready":
            console.print(f"  sources: {data.get('count', 0)} selected")
        elif event_type == "section_ready":
            console.print(f"  section {data.get('section_id')}: {data.get('words', 0)} words")
        elif event_type == "verification_ready":
            console.print(
                f"  claims: {data.get('verified_claims')}/{data.get('total_claims')} verified"
            )
        elif event_type == "quality_scored":
            style = "green" if data.get("passed") else "yellow"
            console.print(
                f"  quality: [{style}]{data.get('score')} ({data.get('grade')})[/{style}]"
            )
        elif event_type == "revision_started":
            console.print(f"  [yellow]revision {data.get('attempt')}[/yellow]")
        elif event_type == "warning":
            console.print(f"[yellow]! {data.get('message')}[/yellow]")
        elif event_type == "run_finished":
            status = data.get("status")
            style = "green" if status == "completed" else "red"
            console.print(f"[{style}]run {status}[/{style}]")


def _settings(
    *,
    data_dir: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> Settings:
    overrides: dict[str, Any] = {}
    if data_dir is not None:
        overrides["data_dir"] = data_dir
    if provider is not None:
        overrides["provider"] = provider
    if model is not None:
        overrides["model"] = model
    return Settings(**overrides)


def _service(settings: Settings, *, quiet: bool = False) -> RunService:
    sinks: list[EventSink] = [] if quiet else [ConsoleSink()]
    return RunService.build(settings, extra_sinks=sinks)


def _copy_artifacts(service: RunService, run_id: str, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    run = service.get_run(run_id)
    for artifact in run.artifacts:
        source = service.artifacts.resolve(artifact.relative_path)
        target = out / source.name
        shutil.copyfile(source, target)
        written.append(target)
    return written


def _summary_table(service: RunService, run_id: str) -> Table:
    run = service.get_run(run_id)
    table = Table(title=f"Run {run.id}", show_header=False, box=None)
    table.add_row("Status", run.status.value)
    if run.quality:
        table.add_row(
            "Quality",
            f"{run.quality.score:.1f} ({run.quality.grade}) - "
            + (
                "gates passed"
                if run.quality.passed
                else "failed: " + ", ".join(run.quality.failed_gates)
            ),
        )
    table.add_row("Sections", str(len(run.sections)))
    claims = [claim for section in run.sections for claim in section.claims]
    table.add_row(
        "Claims", f"{sum(1 for claim in claims if claim.verified)}/{len(claims)} verified"
    )
    table.add_row("Sources", str(len(run.evidence)))
    table.add_row(
        "Usage",
        f"{run.usage.total_tokens} tokens, {run.usage.calls} calls, ${run.usage.cost_usd:.4f}",
    )
    table.add_row("Artifacts", ", ".join(artifact.kind for artifact in run.artifacts) or "none")
    if run.error:
        table.add_row("Error", run.error)
    return table


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"DraftProof {__version__}")


@app.command()
def doctor(
    data_dir: Annotated[Path | None, typer.Option("--data-dir", help="Data directory")] = None,
) -> None:
    """Check configuration, storage and provider availability."""
    settings = _settings(data_dir=data_dir)
    table = Table(title="DraftProof doctor", show_header=True)
    table.add_column("Check")
    table.add_column("Result")
    table.add_column("Detail", overflow="fold")

    ok = True

    def record(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and passed
        table.add_row(name, "[green]pass[/green]" if passed else "[red]fail[/red]", detail)

    current = sys.version_info
    record("python", current >= (3, 11), platform.python_version())

    try:
        settings.ensure_dirs()
        probe = settings.data_dir / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        record("data directory", True, str(settings.data_dir.resolve()))
    except OSError as exc:
        record("data directory", False, str(exc))

    try:
        service = _service(settings, quiet=True)
    except Exception as exc:
        record("providers", False, str(exc))
        console.print(table)
        raise typer.Exit(code=1) from exc

    try:
        database = Database(settings.db_path)
        applied = database.migrate()
        count = database.scalar("SELECT COUNT(*) FROM schema_migrations")
        database.close()
        record("database", True, f"{settings.db_path} ({count} migrations, {len(applied)} new)")
    except Exception as exc:
        record("database", False, str(exc))

    chain = ", ".join(service.settings.provider_chain)
    record("provider chain", True, chain)

    for info in service.describe_providers():
        required = info.name in service.settings.provider_chain
        if required:
            record(
                f"provider:{info.name}",
                info.available,
                info.note or f"{info.kind} / {info.model}",
            )
        else:
            table.add_row(
                f"provider:{info.name}",
                "[dim]optional[/dim]",
                info.note or f"{info.kind} / {info.model}",
            )

    record("retriever", True, service.settings.retriever)
    record("verification", True, service.settings.verification_mode)
    record(
        "budget", service.settings.max_cost_usd > 0, f"${service.settings.max_cost_usd:.2f} per run"
    )

    console.print(table)
    service.close()
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def run(
    topic: Annotated[str, typer.Option("--topic", "-t", help="Article topic")],
    audience: Annotated[
        str, typer.Option("--audience", help="Target audience")
    ] = "software engineers",
    content_type: Annotated[
        str, typer.Option("--type", help="explainer|tutorial|comparison|analysis|announcement")
    ] = "explainer",
    tone: Annotated[
        str, typer.Option("--tone", help="practical|authoritative|conversational|technical")
    ] = "practical",
    target_words: Annotated[int, typer.Option("--words", min=300, max=6000)] = 1400,
    sources: Annotated[
        bool, typer.Option("--sources/--no-sources", help="Require verified citations")
    ] = True,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Override the configured provider")
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the model name")] = None,
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Copy artifacts into this directory")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the run record as JSON")] = False,
) -> None:
    """Run the full pipeline once and print the result."""
    try:
        brief = Brief(
            topic=topic,
            audience=audience,
            content_type=ContentType(content_type),
            tone=Tone(tone),
            target_words=target_words,
            sources_required=sources,
        )
    except ValueError as exc:
        err_console.print(f"[red]Invalid brief:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    settings = _settings(data_dir=data_dir, provider=provider, model=model)
    service = _service(settings)
    try:
        record = service.create_run(brief)
        console.print(f"[dim]run {record.id}[/dim]")
        final = service.execute(record.id)
        if as_json:
            console.print_json(final.model_dump_json())
        else:
            console.print(_summary_table(service, record.id))
        if out is not None:
            written = _copy_artifacts(service, record.id, out)
            console.print(f"[dim]artifacts copied to {out} ({len(written)} files)[/dim]")
    finally:
        service.close()

    if final.status is not RunStatus.COMPLETED and final.status is not RunStatus.AWAITING_REVIEW:
        raise typer.Exit(code=1)


@app.command()
def demo(
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path(".draftproof"),
    out: Annotated[Path, typer.Option("--out")] = Path("demo-output"),
    provider: Annotated[str, typer.Option("--provider")] = "mock",
) -> None:
    """Run a complete offline demo with the deterministic mock provider."""
    provider = "mock" if provider == "mock" else provider
    settings = _settings(data_dir=data_dir, provider="mock")
    if provider != "mock":  # pragma: no cover - explicit opt-in
        settings = settings.model_copy(update={"provider": provider})
    console.print(
        Panel.fit(
            "[bold]DraftProof demo[/bold]\n"
            f"topic: {DEMO_TOPIC}\n"
            f"provider: {settings.provider} · retriever: {settings.retriever}\n"
            f"verification: {settings.verification_mode}",
            border_style="green",
        )
    )
    service = _service(settings)
    try:
        record = service.create_run(
            Brief(topic=DEMO_TOPIC, target_words=1200, sources_required=True)
        )
        final = service.execute(record.id)
        console.print(_summary_table(service, record.id))
        written = _copy_artifacts(service, record.id, out)
        console.print(f"[green]artifacts written to[/green] {out} ({len(written)} files)")
        if final.quality and not final.quality.passed:
            raise typer.Exit(code=1)
    finally:
        service.close()


@app.command("list")
def list_runs(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 15,
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
) -> None:
    """List recent runs."""
    settings = _settings(data_dir=data_dir)
    service = _service(settings, quiet=True)
    try:
        runs = service.repo.list_runs(limit=limit)
    finally:
        service.close()
    if not runs:
        console.print("[dim]No runs yet. Try `draftproof demo`.[/dim]")
        return
    table = Table(title="Recent runs")
    table.add_column("Run", style="dim")
    table.add_column("Topic", overflow="fold")
    table.add_column("Status")
    table.add_column("Score", justify="right")
    table.add_column("Cost", justify="right")
    table.add_column("Created")
    for item in runs:
        table.add_row(
            item.id,
            item.topic,
            item.status.value,
            f"{item.score:.1f}" if item.score is not None else "-",
            f"${item.cost_usd:.4f}",
            item.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="Run id")],
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
) -> None:
    """Show one run as JSON."""
    settings = _settings(data_dir=data_dir)
    service = _service(settings, quiet=True)
    try:
        record = service.get_run(run_id)
    finally:
        service.close()
    console.print_json(record.model_dump_json())


@app.command()
def approve(
    run_id: Annotated[str, typer.Argument(help="Run id")],
    notes: Annotated[str, typer.Option("--notes")] = "",
    reviewer: Annotated[str, typer.Option("--reviewer")] = "editor",
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
) -> None:
    """Approve a run that is waiting for review."""
    settings = _settings(data_dir=data_dir)
    service = _service(settings, quiet=True)
    try:
        record = service.approve(run_id, notes=notes, reviewer=reviewer)
    finally:
        service.close()
    console.print(f"[green]approved[/green] {record.id} -> {record.status.value}")


@app.command()
def export(
    run_id: Annotated[str, typer.Argument(help="Run id")],
    out: Annotated[Path, typer.Option("--out")] = Path("export"),
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
) -> None:
    """Copy every published artifact for a run into a directory."""
    settings = _settings(data_dir=data_dir)
    service = _service(settings, quiet=True)
    try:
        written = _copy_artifacts(service, run_id, out)
    finally:
        service.close()
    for path in written:
        console.print(f"{path}")


@app.command("eval")
def evaluate(
    cases_dir: Annotated[Path, typer.Option("--cases")] = Path("evals/cases"),
    provider: Annotated[str | None, typer.Option("--provider")] = None,
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Score the golden-case evaluation suite."""
    try:
        cases = load_cases(cases_dir)
    except FileNotFoundError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc

    settings = _settings(data_dir=data_dir or Path(".draftproof-eval"), provider=provider or "mock")
    service = _service(settings, quiet=True)
    started = time.perf_counter()
    try:
        report: EvalReport = run_suite(service, cases)
    finally:
        service.close()

    if as_json:
        console.print_json(json.dumps(report.to_dict()))
    else:
        table = Table(title=f"Evaluation suite ({report.total} cases)")
        table.add_column("Case")
        table.add_column("Result")
        table.add_column("Score", justify="right")
        table.add_column("Grade")
        table.add_column("Sections", justify="right")
        table.add_column("Claims", justify="right")
        table.add_column("Time", justify="right")
        table.add_column("Failures", overflow="fold")
        for outcome in report.outcomes:
            table.add_row(
                outcome.case_id,
                "[green]pass[/green]" if outcome.passed else "[red]fail[/red]",
                f"{outcome.score:.1f}",
                outcome.grade,
                str(outcome.sections),
                str(outcome.verified_claims),
                f"{outcome.duration_s:.1f}s",
                "; ".join(outcome.failures),
            )
        console.print(table)
        console.print(
            f"[bold]{report.passed}/{report.total} passed[/bold] · "
            f"mean score {report.mean_score:.1f} · "
            f"{time.perf_counter() - started:.1f}s total"
        )

    if report.failed:
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    data_dir: Annotated[Path | None, typer.Option("--data-dir")] = None,
    provider: Annotated[str | None, typer.Option("--provider")] = None,
) -> None:
    """Start the API and the studio UI."""
    import uvicorn

    settings = _settings(data_dir=data_dir, provider=provider)
    configure_logging(settings.log_level)
    console.print(
        Panel.fit(
            f"[bold]DraftProof Studio[/bold]\nhttp://{host}:{port}\n"
            f"provider: {settings.provider} · retriever: {settings.retriever}",
            border_style="green",
        )
    )
    uvicorn.run("draftproof.api.app:app", host=host, port=port, reload=False)


def main() -> None:
    """Console entry point."""
    _utf8_stdio()
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
