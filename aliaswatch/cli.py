"""Single entry point: `aliaswatch <command>`.

Thin dispatcher so the console script and `python3 -m aliaswatch.<module>` both
work and stay in step.
"""

from __future__ import annotations

import sys

COMMANDS = {
    "run": ("aliaswatch.runner", "run the sealed battery against the model aliases"),
    "build": ("aliaswatch.site", "build the static site into dist/"),
    "card": ("aliaswatch.card", "generate today's share cards"),
    "log": ("aliaswatch.log", "keygen / append / verify the signed record"),
    "battery": ("build_battery", "rebuild and re-seal the prompt battery"),
}


def usage(code=0):
    print("aliaswatch — a daily public record of whether model aliases changed\n")
    print("usage: aliaswatch <command> [options]\n")
    width = max(len(c) for c in COMMANDS)
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<{width}}  {desc}")
    print("\n  test      run the grader tests and the false-alarm simulation")
    print("\nEvery command accepts --help.")
    sys.exit(code)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage(0)

    cmd = argv[0]

    if cmd == "test":
        import runpy
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent / "tests" / "test_all.py"
        if not path.exists():
            sys.exit("tests/test_all.py not found — run from a source checkout")
        sys.argv = [str(path)]
        runpy.run_path(str(path), run_name="__main__")
        return

    if cmd not in COMMANDS:
        print(f"unknown command: {cmd}\n", file=sys.stderr)
        usage(2)

    module = COMMANDS[cmd][0]
    sys.argv = [f"aliaswatch {cmd}"] + argv[1:]
    import importlib
    mod = importlib.import_module(module)
    mod.main()


if __name__ == "__main__":
    main()
