"""Signalpost CLI - One command to run the agent."""
import json
import sys
import time
from pathlib import Path

import click
import structlog

from signalpost.config import OUTPUT_DIR

logger = structlog.get_logger()


@click.group()
@click.version_option(version="1.0.0", prog_name="signalpost")
def main():
    """Signalpost - AI Agent for Norwegian Company Intelligence.

    Researches Norwegian companies using public sources and returns
    verified company profiles with evidence-backed facts.
    """
    pass


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True),
              help="Input JSONL file with organisation numbers")
@click.option("--output", "-o", "output_file", required=True, type=click.Path(),
              help="Output JSON file for results")
@click.option("--workers", "-w", default=10, type=int,
              help="Number of concurrent workers (default: 10)")
@click.option("--max-requests", default=2000, type=int,
              help="Maximum outbound requests (default: 2000)")
@click.option("--max-cost", default=10.0, type=float,
              help="Maximum API cost in USD (default: 10.0)")
def run(input_file, output_file, workers, max_requests, max_cost):
    """Run the agent on a batch of companies."""
    import asyncio
    from signalpost.orchestrator import Orchestrator

    click.echo(f"\n{'='*55}")
    click.echo(f"  Signalpost - Company Research Agent")
    click.echo(f"  Input: {input_file}")
    click.echo(f"  Output: {output_file}")
    click.echo(f"  Workers: {workers}")
    click.echo(f"{'='*55}\n")

    orchestrator = Orchestrator(
        input_file=input_file,
        output_file=output_file,
        max_workers=workers,
        max_requests=max_requests,
        max_cost_usd=max_cost,
    )

    start = time.time()
    asyncio.run(orchestrator.run())
    elapsed = time.time() - start

    click.echo(f"\nCompleted in {elapsed:.1f}s")
    click.echo(f"Results saved to: {output_file}")


@main.command("smoke-test")
@click.option("--output", "-o", "output_file", default="out/smoke_test_report.json",
              type=click.Path(), help="Output report file")
@click.option("--count", "-n", default=100, type=int,
              help="Number of companies to test (default: 100)")
def smoke_test(output_file, count):
    """Run a smoke test on random companies."""
    click.echo(f"Running smoke test on {count} companies...")
    click.echo(f"Output: {output_file}")
    # TODO: Implement smoke test
    click.echo("Smoke test not yet implemented. Run 'signalpost run' with a company list.")


@main.command()
@click.option("--profiles", "-p", required=True, type=click.Path(exists=True),
              help="Existing profiles JSON file to refresh")
@click.option("--output", "-o", "output_file", required=True, type=click.Path(),
              help="Output file for refreshed profiles")
def refresh(profiles, output_file):
    """Refresh existing company profiles for changes."""
    click.echo(f"Refreshing profiles from: {profiles}")
    click.echo(f"Output: {output_file}")
    # TODO: Implement refresh
    click.echo("Refresh not yet implemented.")


if __name__ == "__main__":
    main()
