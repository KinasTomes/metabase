"""Push edited Metabot prompt templates into the running container.

The templates live in resources/metabot/prompts/ and ship inside the uberjar, so
normally a prompt edit means a full image rebuild — about 17 minutes. They are
just files in a zip, though, so this rewrites the jar in place instead and
restarts the container.

`java -jar` ignores -cp, which rules out the usual trick of putting an override
directory earlier on the classpath, and load-system-prompt-template resolves the
template through io/resource. Patching the archive is what is left.

Templates are cached in memory by get-cached-system-prompt, so the container has
to restart; reloading the page is not enough.

The pristine jar is copied out once and kept under .cache/. Every patch is built
from that copy rather than from whatever is currently deployed, so repeated runs
cannot pile edits on top of each other, and reverting a template is just a
matter of editing it back and re-running.

Usage:
    python dev/metabot-poc/patch_prompts.py                 # patch, restart, wait
    python dev/metabot-poc/patch_prompts.py --dry-run       # show what differs
    python dev/metabot-poc/patch_prompts.py --no-restart    # patch only
    python dev/metabot-poc/patch_prompts.py --refresh-cache # re-copy pristine jar
"""

import argparse
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CACHE_DIR = HERE / ".cache"
PRISTINE_JAR = CACHE_DIR / "metabase.pristine.jar"
WORKING_JAR = CACHE_DIR / "metabase.patched.jar"

PROMPT_ROOT = REPO_ROOT / "resources" / "metabot" / "prompts"
# Path prefix inside the jar, mirroring the resources/ layout.
JAR_PREFIX = "metabot/prompts/"

CONTAINER = "metabot-poc-metabase-1"
JAR_IN_CONTAINER = "/app/metabase.jar"
HEALTH_URL = "http://localhost:3000/api/health"


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"$ {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def container_running():
    out = run("docker", "ps", "--filter", f"name={CONTAINER}", "--format", "{{.Names}}")
    return CONTAINER in out


def ensure_pristine(refresh=False):
    if PRISTINE_JAR.exists() and not refresh:
        return
    CACHE_DIR.mkdir(exist_ok=True)
    if not container_running():
        raise SystemExit(
            f"{CONTAINER} is not running, and no cached jar exists yet.\n"
            "Start the stack once so the pristine jar can be copied out."
        )
    print(f"Copying pristine jar out of {CONTAINER} (one time, ~700 MB)...")
    run("docker", "cp", f"{CONTAINER}:{JAR_IN_CONTAINER}", str(PRISTINE_JAR))
    print(f"  cached at {PRISTINE_JAR.relative_to(REPO_ROOT)}")


def local_templates():
    """Map jar entry name -> bytes for every prompt file in the working tree."""
    out = {}
    for path in sorted(PROMPT_ROOT.rglob("*.selmer")):
        entry = JAR_PREFIX + path.relative_to(PROMPT_ROOT).as_posix()
        out[entry] = path.read_bytes()
    return out


def diff_against_jar(jar_path, templates):
    """Which templates differ from what is currently in the jar."""
    changed, missing = [], []
    with zipfile.ZipFile(jar_path) as z:
        names = set(z.namelist())
        for entry, content in templates.items():
            if entry not in names:
                missing.append(entry)
            elif z.read(entry) != content:
                changed.append(entry)
    return changed, missing


def rewrite_jar(src, dest, replacements):
    """Copy the jar, swapping in the replacement entries.

    zipfile cannot replace an entry in place, so the archive is streamed through
    once. Compression is copied per-entry rather than forced, so the untouched
    99.9% of the jar keeps whatever it already had.
    """
    written = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dest, "w") as zout:
        for item in zin.infolist():
            if item.filename in replacements:
                zout.writestr(item, replacements[item.filename])
                written += 1
            else:
                zout.writestr(item, zin.read(item.filename))
    return written


def wait_healthy(timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(5)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument(
        "--only", nargs="+", metavar="NAME",
        help="Patch only templates whose jar path contains one of these substrings. "
             "Use this whenever the deployed jar is behind the working tree.")
    parser.add_argument(
        "--all", action="store_true",
        help="Patch every differing template, including ones you did not edit.")
    parser.add_argument(
        "--restore", action="store_true",
        help="Put the cached pristine jar back and restart. Use after a bad edit — "
             "reverting the working tree alone leaves the broken jar deployed.")
    args = parser.parse_args()

    ensure_pristine(refresh=args.refresh_cache)

    if args.restore:
        if not container_running():
            raise SystemExit(f"{CONTAINER} is not running.")
        print("Restoring pristine jar...")
        run("docker", "cp", str(PRISTINE_JAR), f"{CONTAINER}:{JAR_IN_CONTAINER}")
        run("docker", "restart", CONTAINER)
        print("  healthy" if wait_healthy() else "  did not come back healthy")
        return 0

    templates = local_templates()
    if not templates:
        raise SystemExit(f"No .selmer files under {PROMPT_ROOT}")

    changed, missing = diff_against_jar(PRISTINE_JAR, templates)

    if missing:
        print("Not present in the jar (new templates need a real rebuild):")
        for entry in missing:
            print(f"  {entry}")

    if not changed:
        print(f"No prompt changes against the pristine jar ({len(templates)} templates checked).")
        return 0

    print(f"Changed vs pristine ({len(changed)}):")
    for entry in changed:
        print(f"  {entry}")

    if args.only:
        selected = [e for e in changed if any(s in e for s in args.only)]
        skipped = len(changed) - len(selected)
        print(f"\n--only matched {len(selected)}, skipping {skipped}")
        changed = selected
        if not changed:
            raise SystemExit("--only matched nothing.")
    elif (len(changed) > 1 or missing) and not args.all:
        # A pile of templates differing when you edited one means the deployed
        # jar is built from a different commit than the working tree. Shipping
        # them all would import unrelated upstream prompt changes, and a newer
        # template can reference variables the jar's older prompts.clj never
        # puts in the render context.
        raise SystemExit(
            "\nThe deployed jar looks out of sync with the working tree — more templates\n"
            "differ than you are likely to have edited.\n\n"
            "Rebuilding the image from the current tree is the clean fix. To patch anyway,\n"
            "narrow it with --only <name>, or force the lot with --all."
        )

    if args.dry_run:
        return 0

    print("\nRewriting jar...")
    started = time.time()
    replacements = {e: templates[e] for e in changed}
    count = rewrite_jar(PRISTINE_JAR, WORKING_JAR, replacements)
    size_mb = WORKING_JAR.stat().st_size / 1_048_576
    print(f"  {count} entries replaced, {size_mb:.0f} MB, {time.time() - started:.0f}s")

    if not container_running():
        print(f"\n{CONTAINER} is not running — patched jar left at "
              f"{WORKING_JAR.relative_to(REPO_ROOT)}")
        return 0

    print("Copying into container...")
    run("docker", "cp", str(WORKING_JAR), f"{CONTAINER}:{JAR_IN_CONTAINER}")

    if args.no_restart:
        print("Skipping restart — templates are cached in memory, so the running "
              "instance still serves the old prompts.")
        return 0

    print("Restarting...")
    run("docker", "restart", CONTAINER)
    if wait_healthy():
        print("  healthy")
        return 0
    print("  did not come back healthy in time — check `docker logs`")
    return 1


if __name__ == "__main__":
    sys.exit(main())
