"""TEST ONLY: compare Pyrefly executables on projects outside the PGO corpus.

    python bench.py --rounds 10 plain=<exe> pgo=<exe> [pgo+bolt=<exe>]

Runs are interleaved (every round runs every executable on every project, in a
rotating order) so that drift on a shared runner affects all of them alike.
Reports the median wall time and CPU time (user + system) of each, relative to
the first executable, plus a language-server session on Django.
"""

import argparse
import ctypes
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pgo  # noqa: E402

WORK = ROOT / "bench-work"
# name, repository, revision, working directory, paths to check
PROJECTS = [
    ("black", "psf/black", "b4f1fcae48826790b6f93ca9226d20003bce0eaa", "", ["src/black"]),
    ("django", "django/django", "8e3dec67c42f1557fe0ecb11b620ed707b01f498", "", ["django"]),
    ("pandas", "pandas-dev/pandas", "5db5929d07629538ddba99853696bc3c42dc8e0a", "", ["pandas"]),
    ("sympy", "sympy/sympy", "a1e6fd3993dae123441783a9f995527bb064932b", "", ["sympy"]),
    ("prefect", "PrefectHQ/prefect", "802fc9435423bed0d16fe30862de25a8df62493f", "", ["src/prefect"]),
    ("discord.py", "Rapptz/discord.py", "65232c38702be5844cf2ce865a4777eb1928b5d0", "", ["discord"]),
    ("mypy", "python/mypy", "0719acc5503b228859757a20038f28cbe6b06d8b", "", ["mypy"]),
    ("jinja", "pallets/jinja", "5ef70112a1ff19c05324ff889dd30405b1002044", "", ["src/jinja2"]),
    ("pandas-stubs", "pandas-dev/pandas-stubs", "96c49cbe8918f14da9bd7e0dfde6fc7767f72f58", "", []),
    ("torchtitan", "pytorch/torchtitan", "5f055ce6efe09dbfc718478f96b2443230bdb924", "", []),
    ("agent-framework", "microsoft/agent-framework", "1c3264b065ef4b2b9b3614b19394bdd49d98334f", "python", ["packages"]),
]
DEPENDENCIES = [
    "aiohttp", "anyio", "attrs", "click", "fastapi", "httpx", "jinja2", "mypy-extensions",
    "numpy", "opentelemetry-api", "packaging", "pathspec", "platformdirs", "pydantic",
    "pygments", "pytest", "sqlalchemy", "typing-extensions",
]
DJANGO_SESSION = pgo.LanguageServerSession(
    open_files=(
        "django/db/models/fields/__init__.py",
        "django/db/models/query.py",
        "django/forms/models.py",
    ),
    error_edit=('return "%s.%s" % (model._meta.label, self.name)', "return 1 + ''"),
)


def prepare() -> Path:
    for name, repository, revision, _, _ in PROJECTS:
        checkout = WORK / name
        if (checkout / ".git").is_dir():
            continue
        checkout.mkdir(parents=True)
        git = ["git", "-c", "core.longpaths=true", "-C", str(checkout)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "remote", "add", "origin", f"https://github.com/{repository}.git"], check=True)
        for attempt in range(3):
            if subprocess.run([*git, "fetch", "-q", "--depth=1", "origin", revision]).returncode == 0:
                break
            time.sleep(5 * 2**attempt)
        subprocess.run([*git, "checkout", "-q", "--detach", revision], check=True)
    # The language-server session needs a project, which Django does not configure.
    (WORK / "django" / "pyrefly.toml").write_text('project-includes = ["django"]\n')
    venv = WORK / "venv"
    if not venv.is_dir():
        subprocess.run(["uv", "venv", "-q", "--python", "3.12", str(venv)], check=True)
        subprocess.run(
            ["uv", "pip", "install", "-q", "--python", str(venv), "--exclude-newer", "2026-11-01T00:00:00Z", *DEPENDENCIES],
            check=True,
        )
    return venv


def run(command: list[str], cwd: Path, env: dict[str, str]) -> tuple[float, float]:
    """Return the wall time and CPU time (user + system) of `command`."""
    if os.name == "nt":
        start = time.perf_counter()
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait()
        wall = time.perf_counter() - start
        times = [ctypes.c_ulonglong() for _ in range(4)]
        ctypes.windll.kernel32.GetProcessTimes(int(process._handle), *(ctypes.byref(t) for t in times))
        cpu = (times[2].value + times[3].value) / 1e7
    else:
        import resource

        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        process = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wall = time.perf_counter() - start
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = after.ru_utime - before.ru_utime + after.ru_stime - before.ru_stime
    if process.returncode not in (0, 1):
        raise RuntimeError(f"{command} exited with {process.returncode}")
    return wall, cpu


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--lsp-rounds", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("bench.json"))
    parser.add_argument("executables", nargs="+", help="label=path")
    args = parser.parse_args()
    executables = dict(e.split("=", 1) for e in args.executables)
    labels = list(executables)
    venv = prepare()
    env = pgo.corpus_environment(venv)
    results = {name: {label: [] for label in labels} for name, *_ in PROJECTS}
    results["lsp-django"] = {label: [] for label in labels}

    for round_number in range(args.rounds + 1):  # The first round warms up.
        for name, _, _, subdir, paths in PROJECTS:
            order = labels[round_number % len(labels):] + labels[: round_number % len(labels)]
            for label in order:
                command = [executables[label], "check", "--output-format=min-text", "--summary=none", *paths]
                measurement = run(command, WORK / name / subdir, env)
                if round_number:
                    results[name][label].append(measurement)
        print(f"round {round_number} done", flush=True)
    for round_number in range(args.lsp_rounds + 1):
        for label in labels[round_number % len(labels):] + labels[: round_number % len(labels)]:
            start = time.perf_counter()
            pgo.language_server_session(Path(executables[label]), WORK / "django", env, DJANGO_SESSION)
            if round_number:
                results["lsp-django"][label].append((time.perf_counter() - start, 0.0))

    args.output.write_text(json.dumps(results))
    base = labels[0]
    lines = [
        "| project | " + f"{base} wall | " + " | ".join(f"{label} wall | {label} CPU" for label in labels[1:]) + " |",
        "| --- | ---: | " + " | ".join("---: | ---:" for _ in labels[1:]) + " |",
    ]
    ratios = {label: ([], []) for label in labels[1:]}
    for name, by_label in results.items():
        base_wall = statistics.median(w for w, _ in by_label[base])
        base_cpu = statistics.median(c for _, c in by_label[base])
        row = f"| {name} | {base_wall:.2f}s | "
        cells = []
        for label in labels[1:]:
            wall = statistics.median(w for w, _ in by_label[label]) / base_wall
            if name == "lsp-django":
                cells.append(f"{100 * (wall - 1):+.1f}% | ")
                continue
            cpu = statistics.median(c for _, c in by_label[label]) / base_cpu
            ratios[label][0].append(wall)
            ratios[label][1].append(cpu)
            cells.append(f"{100 * (wall - 1):+.1f}% | {100 * (cpu - 1):+.1f}%")
        lines.append(row + " | ".join(cells) + " |")
    lines.append(
        "| **geomean** | | "
        + " | ".join(
            f"**{100 * (statistics.geometric_mean(w) - 1):+.1f}%** | **{100 * (statistics.geometric_mean(c) - 1):+.1f}%**"
            for w, c in ratios.values()
        )
        + " |"
    )
    table = "\n".join(lines)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(f"### {os.environ.get('BENCH_NAME', '')}\n\n{table}\n\n")


if __name__ == "__main__":
    main()
