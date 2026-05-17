"""Command-line entry points for Symphony."""

from __future__ import annotations

import typer

app = typer.Typer(help="Python implementation of Symphony.")


@app.callback()
def root() -> None:
    """Run the Symphony command-line interface."""


def main() -> None:
    """Run the Symphony command-line interface."""
    app()


if __name__ == "__main__":
    main()
