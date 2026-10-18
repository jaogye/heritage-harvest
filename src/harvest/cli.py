"""Command-line entry point.

harvest wikidata --limit 2000
harvest europeana --query "Bruegel" --limit 500
harvest crawl https://example-museum.be/collection --detail '/object/\\d+' --follow '[?&]page='
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from .http import PoliteClient
from .sinks import JsonlSink
from .sources import EuropeanaSource, JsonLdCrawler, WikidataSource

app = typer.Typer(add_completion=False, help="Harvest cultural-heritage records into data/raw.")

OUT = typer.Option(Path("data/raw"), help="Raw zone root directory")
CACHE = typer.Option(Path(".cache/http"), help="HTTP cache directory (resume support)")


async def _run(source, sink: JsonlSink, limit: int | None) -> None:
    async for record in source.records(limit=limit):
        sink.write(record)
    s = sink.stats
    typer.echo(f"{source.name}: {s.written} new/changed, {s.unchanged} unchanged -> {sink.path}")
    typer.echo(f"http: {source.client.stats}")


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command()
def wikidata(limit: int = typer.Option(None), out: Path = OUT, cache: Path = CACHE) -> None:
    """Artworks in Belgian collections from the Wikidata Query Service."""

    async def go():
        async with PoliteClient(min_interval=1.0, cache_dir=cache) as client:
            await _run(WikidataSource(client), JsonlSink(out, "wikidata"), limit)

    asyncio.run(go())


@app.command()
def europeana(
    query: str = typer.Option("*"),
    limit: int = typer.Option(None),
    out: Path = OUT,
    cache: Path = CACHE,
) -> None:
    """Image records from Belgian providers in Europeana."""

    async def go():
        async with PoliteClient(min_interval=0.5, cache_dir=cache) as client:
            await _run(EuropeanaSource(client, query=query), JsonlSink(out, "europeana"), limit)

    asyncio.run(go())


@app.command()
def crawl(
    start_url: list[str] = typer.Argument(...),
    detail: str = typer.Option(..., help="Regex matching artwork detail-page URLs"),
    follow: str = typer.Option(None, help="Regex for listing/pagination URLs to follow"),
    name: str = typer.Option("web", help="Source name used in the raw zone"),
    max_pages: int = typer.Option(200),
    limit: int = typer.Option(None),
    delay: float = typer.Option(2.0, help="Seconds between requests to the same host"),
    out: Path = OUT,
    cache: Path = CACHE,
) -> None:
    """Crawl a museum website and extract artworks from JSON-LD / OpenGraph."""

    async def go():
        async with PoliteClient(min_interval=delay, cache_dir=cache) as client:
            crawler = JsonLdCrawler(
                client, start_url, detail, follow, max_pages=max_pages, source_name=name
            )
            await _run(crawler, JsonlSink(out, name), limit)
            if crawler.skipped:
                typer.echo(f"skipped {len(crawler.skipped)} pages (first: {crawler.skipped[:3]})")

    asyncio.run(go())


if __name__ == "__main__":
    app()
