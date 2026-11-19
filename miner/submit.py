"""Check an entry locally, then submit it to the central API (default https://conjectures.io).

  python miner/submit.py check entry.c                    the gate, as the validator runs it
  python miner/submit.py submit entry.c --hotkey FILE     sign and upload; prints the submission id
  python miner/submit.py status ID | report ID
  python miner/submit.py boards | leaderboard [--board overall]

`check` needs the harness (requirements.txt, gcc); everything else needs only
requirements-miner.txt. Each subnet registration buys one submission, and a rejected entry still
uses it, so run `check` first.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import sig  # noqa: E402
from eik.config import CAP_SOURCE_BYTES, SOURCE_FILENAME  # noqa: E402

DEFAULT_URL = "https://conjectures.io"
TIMEOUT = 60


def base(url: str) -> str:
    return f"{url.rstrip('/')}/v1/competitions/{sig.COMPETITION}"


def source_of(path: Path) -> bytes:
    """The one file a submission is: non-empty UTF-8, within the source cap."""
    if not path.is_file():
        sys.exit(f"{path} is not a file")
    with path.open("rb") as f:
        content = f.read(CAP_SOURCE_BYTES + 1)
    if not content:
        sys.exit(f"{path} is empty")
    if len(content) > CAP_SOURCE_BYTES:
        sys.exit(f"{path} is larger than {CAP_SOURCE_BYTES} bytes")
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        sys.exit(f"{path} is not UTF-8")
    return content


def refused(what: str, r) -> str:
    """One line a miner can act on, from the platform's problem body {reason_code, detail}."""
    if r.headers.get("content-type", "").startswith(("application/json", "application/problem+json")):
        body = r.json()
        code, detail = body.get("reason_code"), body.get("detail")
        if code == "DUPLICATE_SUBMISSION" and body.get("submission") is not None:
            detail = f"{detail} Existing submission {body['submission']} ({body.get('state', 'unknown')})."
        if code or detail:
            return f"{what} refused ({r.status_code}{f' {code}' if code else ''}): {detail}"
    return f"{what} refused ({r.status_code}): {r.text[:300]}"


def signed_headers(kp, *, digest: str, timestamp: int) -> dict:
    message = sig.submit_message(competition=sig.COMPETITION, digest=digest, hotkey=kp.ss58_address,
                                 timestamp=timestamp)
    return {"X-Conjectures-Hotkey": kp.ss58_address, "X-Conjectures-Timestamp": str(timestamp),
            "X-Conjectures-Signature": sig.sign(kp, message)}


def cmd_check(a):
    source_of(Path(a.file))
    p = subprocess.run([sys.executable, "-m", "eik", "gate", str(Path(a.file).resolve())], cwd=ROOT,
                       capture_output=True, text=True)
    try:
        r = json.loads(p.stdout)
    except json.JSONDecodeError:
        sys.exit(f"the gate did not run: {p.stderr.strip()[-2000:]}")
    if r.get("kind") == "error":
        sys.exit(f"the gate could not run here ({r['error']}): {r['detail']}")
    if r["verdict"] != "accepted":
        print(f"REJECTED at {r['stage']}")
        for reason in r["reasons"][:20]:
            print("  -", reason)
        sys.exit(1)
    print(f"accepted by the gate: {r['bytes']} bytes of code and tables per target")
    print("Next: python -m eik evaluate", a.file, " (scores it against the local champion and runs the full check)")


def cmd_submit(a):
    import requests
    content = source_of(Path(a.file))
    kp = sig.load_keypair(a.hotkey)
    digest = sig.digest_of(content)
    r = requests.post(f"{base(a.url)}/submissions",
                      headers=signed_headers(kp, digest=digest, timestamp=int(time.time())),
                      files={SOURCE_FILENAME: (SOURCE_FILENAME, content)}, timeout=TIMEOUT)
    if r.status_code != 201:
        sys.exit(refused("submit", r))
    v = r.json()
    print(f"submission {v['submission']}; state: {v.get('state') or v.get('proof_state')}; digest {digest}")
    if v.get("intake_mode") == "dev":
        print("dev intake: subnet registration was not required")
    print("check with:", shlex.join([sys.executable, "miner/submit.py", "status", str(v["submission"]), "--url", a.url]))


def show(what, url, path, params=None):
    import requests
    r = requests.get(f"{base(url)}{path}", params=params, timeout=TIMEOUT)
    if r.status_code != 200:
        sys.exit(refused(what, r))
    print(json.dumps(r.json(), indent=2))


CMDS = {
    "check": cmd_check,
    "submit": cmd_submit,
    "status": lambda a: show("status", a.url, f"/submissions/{a.id}"),
    "report": lambda a: show("report", a.url, f"/submissions/{a.id}/report"),
    "boards": lambda a: show("boards", a.url, "/boards"),
    "leaderboard": lambda a: show("leaderboard", a.url, "/leaderboard", {"board": a.board}),
}


def main():
    ap = argparse.ArgumentParser(prog="submit.py", description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def url(p):
        p.add_argument("--url", default=DEFAULT_URL, help=f"API origin (default {DEFAULT_URL})")

    c = sub.add_parser("check", help="run the validator's gate on the file locally")
    c.add_argument("file")
    s = sub.add_parser("submit", help=f"sign and upload one {SOURCE_FILENAME}")
    s.add_argument("file")
    s.add_argument("--hotkey", required=True, help="Bittensor hotkey file (or //Alice for tests)")
    url(s)
    for name in ("status", "report"):
        p = sub.add_parser(name)
        p.add_argument("id", type=int)
        url(p)
    url(sub.add_parser("boards"))
    lb = sub.add_parser("leaderboard")
    lb.add_argument("--board", default="overall", help="rv32im, thumbv6m or overall")
    url(lb)
    a = ap.parse_args()
    try:
        CMDS[a.cmd](a)
    except ImportError as e:
        sys.exit(f"{e}: pip install -r requirements-miner.txt")
    except (OSError, ValueError) as e:
        sys.exit(str(e))
    except Exception as e:  # requests.RequestException, without importing requests for `check`
        if type(e).__module__.startswith("requests"):
            sys.exit(f"API request failed: {e}")
        raise


if __name__ == "__main__":
    main()
