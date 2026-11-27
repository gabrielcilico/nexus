"""Command-line interface for local Nexus operations."""

import json
import shutil
from functools import wraps
from pathlib import Path
from subprocess import SubprocessError
from typing import Annotated

import typer
import yaml

from . import config, installation
from .discovery import discover, project_root
from .storage import checked, installation_data, locked, project_data, write_json

app = typer.Typer(no_args_is_help=True)
skills = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(skills, name="skills")
app.add_typer(config_app, name="config")


def guarded(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, SubprocessError, yaml.YAMLError) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(1) from error

    return invoke


def emit(data):
    typer.echo(json.dumps(data, indent=2, ensure_ascii=True))


@skills.command("list")
@guarded
def list_skills(
    source: Annotated[Path, typer.Option(help="Nexus checkout")] = Path("."),
):
    """List skills from a local Nexus checkout."""
    emit(list(installation.catalog(source)))


@app.command()
def doctor():
    """Report local prerequisites without making network requests."""
    emit({program: shutil.which(program) for program in ("git", "claude", "uv")})


@app.command("discover")
@guarded
def inspect(
    domain: Annotated[str, typer.Option()],
    project: Annotated[Path, typer.Option()] = Path("."),
):
    """Save local discovery evidence outside the project and print a summary."""
    root = project_root(project)
    state = project_data(root, domain)
    report = discover(root)
    write_json(checked(state, Path("discovery.json")), report)
    emit(report)


@config_app.command("get")
@guarded
def get_config(
    fields: Annotated[list[str], typer.Argument()],
    domain: Annotated[str, typer.Option()],
    project: Annotated[Path, typer.Option()] = Path("."),
):
    """Read specific approved conventions for a project."""
    if set(fields) - config.Conventions.model_fields.keys():
        raise ValueError("Unknown convention field")
    values = config.effective(project_data(project_root(project), domain))
    emit({field: values.get(field) for field in fields})


@config_app.command("set")
@guarded
def set_config(
    field: str,
    value: str,
    domain: Annotated[str, typer.Option()],
    project: Annotated[Path, typer.Option()] = Path("."),
    approve: Annotated[bool, typer.Option("--approve")] = False,
):
    """Store a convention approved for this project."""
    if not approve:
        raise ValueError("Review the convention and pass --approve to save it")
    state = project_data(project_root(project), domain)
    with locked(checked(state, Path("config.lock"))):
        config.set_convention(state, field, value)


def install_version(action, source, project, names):
    root = project_root(project)
    installation.change(root, installation_data(root), action, source, names)


@app.command()
@guarded
def install(
    source: Annotated[Path, typer.Option(help="Nexus checkout")] = Path("."),
    project: Annotated[Path, typer.Option()] = Path("."),
    skill: Annotated[list[str] | None, typer.Option("--skill")] = None,
):
    """Install selected skills into a project's Claude Code directory."""
    install_version("install", source, project, skill)


@app.command()
@guarded
def update(
    source: Annotated[Path, typer.Option(help="Nexus checkout")] = Path("."),
    project: Annotated[Path, typer.Option()] = Path("."),
    skill: Annotated[list[str] | None, typer.Option("--skill")] = None,
):
    """Update installed skills from the specified local checkout."""
    install_version("update", source, project, skill)


@app.command()
@guarded
def uninstall(project: Annotated[Path, typer.Option()] = Path(".")):
    """Remove unmodified Nexus-managed skills from the project."""
    root = project_root(project)
    installation.change(root, installation_data(root), "uninstall")


@app.command()
@guarded
def rollback(project: Annotated[Path, typer.Option()] = Path(".")):
    """Restore the previous installation for the project."""
    root = project_root(project)
    installation.change(root, installation_data(root), "rollback")


@app.command()
@guarded
def status(project: Annotated[Path, typer.Option()] = Path(".")):
    """Report which managed skills are installed, modified or missing."""
    root = project_root(project)
    emit(installation.status(root, installation_data(root)))


def main():
    app()


if __name__ == "__main__":
    main()
