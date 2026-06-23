from __future__ import annotations

import argparse
import secrets
import string
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PASSWORD_PLACEHOLDER = "replace-with-a-strong-postgres-password"
DEFAULT_PASSWORD_LENGTH = 32


@dataclass(frozen=True)
class BootstrapResult:
    status: str
    env_path: Path
    detail: str
    next_steps: tuple[str, ...]


def generate_password(length: int = DEFAULT_PASSWORD_LENGTH) -> str:
    alphabet = string.ascii_letters + string.digits + "_-"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def render_env_template(template: str, password: str) -> str:
    lines: list[str] = []
    replaced = False
    for line in template.splitlines():
        if line.startswith("RAGRIG_POSTGRES_PASSWORD="):
            lines.append(f"RAGRIG_POSTGRES_PASSWORD={password}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(f"RAGRIG_POSTGRES_PASSWORD={password}")
    return "\n".join(lines).rstrip() + "\n"


def bootstrap_env(
    *,
    project_root: Path,
    env_path: Path | None = None,
    template_path: Path | None = None,
    force: bool = False,
    password: str | None = None,
) -> BootstrapResult:
    root = project_root.resolve()
    target = (env_path or root / ".env").resolve()
    template = (template_path or root / ".env.example").resolve()
    next_steps = (
        "docker compose up",
        "open http://localhost:8000",
    )

    if target.exists() and not force:
        return BootstrapResult(
            status="exists",
            env_path=target,
            detail=f"{target} already exists; pass --force to regenerate it.",
            next_steps=next_steps,
        )

    if not template.exists():
        raise FileNotFoundError(f"template not found: {template}")

    generated_password = password or generate_password()
    rendered = render_env_template(template.read_text(encoding="utf-8"), generated_password)
    target.write_text(rendered, encoding="utf-8")
    return BootstrapResult(
        status="created" if not force else "regenerated",
        env_path=target,
        detail=f"Wrote {target} with a generated local Postgres password.",
        next_steps=next_steps,
    )


def render_result(result: BootstrapResult) -> str:
    lines = [
        "RAGRig init",
        "",
        f"Status: {result.status}",
        f"Env:    {result.env_path}",
        f"Detail: {result.detail}",
        "",
        "Next steps:",
    ]
    lines.extend(f"  {index}. {step}" for index, step in enumerate(result.next_steps, start=1))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a local RAGRig .env file.")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current directory.",
    )
    parser.add_argument("--env-path", type=Path, default=None, help="Path to write .env.")
    parser.add_argument(
        "--template-path",
        type=Path,
        default=None,
        help="Path to read .env.example.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing .env.")
    args = parser.parse_args(argv)

    result = bootstrap_env(
        project_root=args.project_root,
        env_path=args.env_path,
        template_path=args.template_path,
        force=args.force,
    )
    print(render_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
