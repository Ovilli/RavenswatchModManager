"""rsmm backend - point the game at a self-hosted online backend.

    rsmm backend http://85.214.117.164:8090    set it (and check everything)
    rsmm backend                               show the current state
    rsmm backend off                           go back to the official servers

One command instead of `setx` + a Steam restart: the loader reads the address
from <game>/mods/.rsmm_backend at every game start. The output is as much the
point as the write - each line below is something that, when wrong, makes the
redirect silently do nothing.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from rsmm.engine import backend_redirect as br
from rsmm.engine.paths import default_game_dir

# Plain ASCII on purpose: this is read in cmd.exe, whose code page cannot show
# an em dash or a check mark.
_OK, _INFO, _WARN, _BAD = "[ok]  ", "[info]", "[warn]", "[FAIL]"


def _resolve_game_dir(arg: Path | None) -> tuple[Path, str]:
    """The game folder and where that answer came from.

    The origin is printed because the likeliest reason for "the log never
    updates" is that rsmm is looking at a different install than the one being
    played - two Steam libraries is enough to cause it.
    """
    if arg is not None:
        return arg, "--game-dir"
    if os.environ.get("RSMM_GAME_DIR", "").strip():
        return default_game_dir(), "RSMM_GAME_DIR"
    return default_game_dir(), "auto-detected"


def _age(seconds: float) -> str:
    if seconds < 90:
        return f"{int(seconds)} s"
    if seconds < 5400:
        return f"{int(seconds // 60)} min"
    if seconds < 172800:
        return f"{int(seconds // 3600)} h"
    return f"{int(seconds // 86400)} days"


def _report(game_dir: Path, url: str | None, check_server: bool) -> int:
    """Print every check. Returns 1 if something will stop the redirect working."""
    blocking = False

    if url is None:
        print(f"{_INFO} backend: none set - the game uses the official servers")
    else:
        print(f"{_OK} backend: {url}  (mods{os.sep}.rsmm_backend)")

    env = br.env_override()
    if env:
        if url is None or env.rstrip("/") != url:
            print(f"{_WARN} the environment variable {br.ENV_VAR}={env} is set and "
                  "takes priority over the file above")
            print("       remove it:  reg delete \"HKCU\\Environment\" /v "
                  f"{br.ENV_VAR} /f   (Windows), then open a new terminal")
        else:
            print(f"{_OK} {br.ENV_VAR} is also set, to the same address")

    loader = br.inspect_loader(game_dir)
    if loader.can_redirect:
        print(f"{_OK} loader: {loader.summary}")
    else:
        print(f"{_BAD} loader: {loader.summary}")
        blocking = True

    if url is not None and check_server:
        fed = br.probe_federation(url)
        if not fed.reachable:
            print(f"{_WARN} server: not reachable ({fed.error})")
            print("       is the server running, and are TCP 8090 and UDP 30100 open?")
        elif br.advertises_loopback(url, fed):
            print(f"{_BAD} server: reachable, but it tells players to connect to "
                  f"{', '.join(fed.endpoints)}")
            print("       its publicIp / loadBalancedIp in grid/default.json are still 'localhost'")
            blocking = True
        else:
            print(f"{_OK} server: reachable, advertises {', '.join(fed.endpoints) or '(nothing)'}")

    log = br.last_backend_log(game_dir)
    if not log.exists:
        print(f"{_WARN} last launch: no loader log yet at {log.path}")
        print("       start Ravenswatch from Steam, then run `rsmm backend` again")
    else:
        age = _age(time.time() - (log.modified or 0))
        print(f"{_OK} last launch: log {log.path} (updated {age} ago)")
        for line in log.lines:
            print(f"       {line}")
        if url is not None and not log.lines:
            print(f"{_WARN} the last launch logged nothing about the backend - it ran before "
                  "the address was set, or with a loader that cannot redirect")
    return 1 if blocking else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rsmm backend",
        description="Point the game at a self-hosted online backend, and check it works.",
    )
    ap.add_argument("target", nargs="?", metavar="URL|off",
                    help="address like http://host:8090, or 'off' to use the official servers; "
                         "omit to show the current state")
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="Ravenswatch folder (default: RSMM_GAME_DIR, else auto-detected)")
    ap.add_argument("--no-check", action="store_true",
                    help="do not contact the server")
    args = ap.parse_args(argv)

    game_dir, origin = _resolve_game_dir(args.game_dir)
    print(f"game folder: {game_dir}  ({origin})")
    if not game_dir.is_dir():
        print(f"{_BAD} that folder does not exist. Pass the Ravenswatch folder with --game-dir, "
              "or set RSMM_GAME_DIR once so every rsmm command uses it.")
        return 1
    if not (game_dir / "Ravenswatch.exe").exists():
        print(f"{_WARN} Ravenswatch.exe is not in that folder - is it the right one?")

    if args.target is not None and args.target.strip().lower() == "off":
        removed = br.clear_marker(game_dir)
        print(f"{_OK} " + ("removed the backend address - the game uses the official servers"
                           if removed else "no backend address was set"))
        # Still print the checks: an RSMM_BACKEND_URL left over from `setx` keeps the
        # redirect on even though the file is gone, and that is worth saying here.
        # Going back to the official servers is what was asked, so it is not a failure.
        _report(game_dir, None, check_server=False)
        return 0

    if args.target is not None:
        try:
            url = br.normalize_url(args.target)
        except br.BackendUrlError as exc:
            print(f"{_BAD} {exc}")
            return 2
        path = br.write_marker(game_dir, url)
        print(f"{_OK} wrote {path}")
    else:
        stored = br.read_marker(game_dir)
        url = None
        if stored:
            try:
                url = br.normalize_url(stored)
            except br.BackendUrlError as exc:
                print(f"{_BAD} {br.marker_path(game_dir)} holds {stored!r}, which the loader "
                      f"would ignore: {exc}")
                return 1

    return _report(game_dir, url, check_server=not args.no_check)


if __name__ == "__main__":
    raise SystemExit(main())
