"""Signalpost CLI -- one command to run the agent."""
import json
import sys
import time
from pathlib import Path

import click
import structlog

from signalpost.config import OUTPUT_DIR

logger = structlog.get_logger()


@click.group()
@click.version_option(version="2.0.0", prog_name="signalpost")
def main():
    """Signalpost -- AI Agent for Norwegian Company Intelligence."""
    pass


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output", "-o", "output_file", required=True, type=click.Path())
@click.option("--workers", "-w", default=10, type=int)
@click.option("--max-requests", default=2000, type=int)
@click.option("--max-cost", default=10.0, type=float)
@click.option("--previous", "-p", "previous_file", default=None, type=click.Path(),
              help="Previous output file for refresh comparison")
def run(input_file, output_file, workers, max_requests, max_cost, previous_file):
    """Run the agent on a batch of companies."""
    import asyncio
    from signalpost.orchestrator import Orchestrator

    click.echo(f"\n{'='*60}")
    click.echo(f"  Signalpost -- Company Research Agent v2.0")
    click.echo(f"  Input:    {input_file}")
    click.echo(f"  Output:   {output_file}")
    click.echo(f"  Workers:  {workers}  |  Max Requests: {max_requests}")
    click.echo(f"  Max Cost: ${max_cost:.2f}")
    if previous_file:
        click.echo(f"  Previous: {previous_file} (refresh mode)")
    click.echo(f"{'='*60}\n")

    orchestrator = Orchestrator(
        input_file=input_file, output_file=output_file,
        max_workers=workers, max_requests=max_requests,
        max_cost_usd=max_cost, previous_file=previous_file,
    )

    start = time.time()
    asyncio.run(orchestrator.run())
    elapsed = time.time() - start

    click.echo(f"\n{'='*60}")
    click.echo(f"  [OK] Completed in {elapsed:.1f}s")
    click.echo(f"  Requests used: {orchestrator.budget.used}")
    click.echo(f"  API cost:      ${orchestrator.cost_tracker.total_cost:.4f}")
    click.echo(f"  Results:       {output_file}")
    click.echo(f"{'='*60}\n")


@main.command("smoke-test")
@click.option("--count", "-n", default=10, type=int)
@click.option("--output", "-o", "output_file", default=None, type=click.Path())
def smoke_test(count, output_file):
    """Quick smoke test on sample companies."""
    import asyncio

    if output_file is None:
        output_file = str(OUTPUT_DIR / "smoke_test.json")

    sample_file = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_companies.json"
    if not sample_file.exists():
        click.echo("Error: tests/fixtures/sample_companies.json not found.")
        sys.exit(1)

    lines = sample_file.read_text(encoding="utf-8").strip().split("\n")
    lines = lines[:count]

    temp_input = OUTPUT_DIR / "_smoke_input.jsonl"
    temp_input.parent.mkdir(parents=True, exist_ok=True)
    temp_input.write_text("\n".join(lines), encoding="utf-8")

    from signalpost.orchestrator import Orchestrator
    orchestrator = Orchestrator(
        input_file=str(temp_input), output_file=output_file,
        max_workers=5, max_requests=200, max_cost_usd=1.0,
    )

    start = time.time()
    asyncio.run(orchestrator.run())
    elapsed = time.time() - start

    results = json.loads(Path(output_file).read_text(encoding="utf-8"))
    available = sum(1 for r in results if r.get("status") == "available")
    failed = sum(1 for r in results if r.get("status") == "failed")
    na = sum(1 for r in results if r.get("status") == "not_available")

    click.echo(f"\n  Results ({elapsed:.1f}s): Available={available} Failed={failed} N/A={na}")
    click.echo(f"  Requests: {orchestrator.budget.used}  Cost: ${orchestrator.cost_tracker.total_cost:.4f}\n")
    temp_input.unlink(missing_ok=True)


@main.command()
@click.option("--port", "-p", default=5000, type=int)
@click.option("--host", "-h", "host", default="127.0.0.1")
@click.option("--profiles", default="out/signalpost_final.json", type=click.Path())
def serve(port, host, profiles):
    """Launch the web dashboard."""
    from signalpost.web.app import create_app

    click.echo(f"\n{'='*60}")
    click.echo(f"  Signalpost Web Dashboard")
    click.echo(f"  Profiles: {profiles}")
    click.echo(f"  URL:      http://{host}:{port}")
    click.echo(f"{'='*60}\n")

    app = create_app(profiles_path=profiles)
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
