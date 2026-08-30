#!/usr/bin/env python3
"""Update the Docker Hub repository overview (short description + full description/README).

Docker Hub does not auto-populate these from GitHub, so we set them via the Hub API.
Expected environment variables:
  DH_USER         Docker Hub username
  DH_TOKEN        Docker Hub token (PAT works as the login password)
  RELEASE_VERSION release tag name WITHOUT the leading 'v' (e.g. "3.0.0").
                  When set, the release's "What's New" section is prepended
                  to the front of the Docker Hub overview page.
  IMAGE_NAME      image/repository name on Docker Hub (defaults to free-short-video)
"""
import os
import re
import sys
import json
import subprocess

DOCKERHUB_API = "https://hub.docker.com/v2"
UA = "free-short-video-release-bot/1.0 (https://github.com/lcy362/agnes-video-generator)"


def _load_whats_new(version: str) -> str:
    """Load the release notes' 'What's New' section for the given version.

    Reads ``docs/public/release-notes/release_notes_v{version}.md`` and returns
    everything from the ``## What's New`` heading onward (the release doc structure
    per ``docs/dev/release_process.md``). Returns "" when the file is missing or
    has no such section.
    """
    if not version:
        return ""
    note = os.path.join("docs", "public", "release-notes", f"release_notes_v{version}.md")
    if not os.path.exists(note):
        print(f"No release notes doc at {note}; skipping 'What's New' prepend.")
        return ""
    with open(note, encoding="utf-8") as f:
        lines = f.read().splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("## What's New")), None)
    if start is None:
        print(f"No '## What's New' section in {note}; skipping prepend.")
        return ""
    section = "\n".join(lines[start:]).strip()
    # Drop the trailing footer marker if the doc ends with one (e.g. *文档版本：...*).
    section = re.sub(r"\n*---\s*\n*\*.*\*\s*$", "", section).strip()
    return section


def main() -> int:
    user = os.environ["DH_USER"]
    token = os.environ["DH_TOKEN"]

    # Docker Hub caps the short `description` at 100 bytes. Exceeding it
    # rejects the ENTIRE PATCH (including full_description), so we keep this
    # concise and defensively truncate on a character boundary just in case.
    desc = "free-short-video — Self-hosted AI video generator with subtitles"
    while len(desc.encode("utf-8")) > 100:
        desc = desc[:-1]

    image = os.environ.get("IMAGE_NAME", "free-short-video")
    repo_path = f"{user}/{image}"

    # Use the repository README as the full description.
    readme = ""
    for cand in ("README.md", "readme.md", "README.MD"):
        if os.path.exists(cand):
            with open(cand, encoding="utf-8") as f:
                readme = f.read()
            break
    if not readme:
        readme = desc

    # Brand the Docker Hub overview title as "Free Short Video" without altering
    # the source README (which keeps the project name "Agnes Video Generator").
    # Only the top-level H1 line is rewritten; body mentions of "Agnes AI" stay.
    readme_lines = readme.split("\n")
    for i, line in enumerate(readme_lines):
        if line.startswith("# ") and "Agnes Video Generator" in line:
            readme_lines[i] = line.replace("Agnes Video Generator", "free-short-video", 1)
            break
    # Prepend the latest release's "What's New" section at the very front of the
    # page (right after the H1), so Docker Hub visitors see release content first.
    release_version = os.environ.get("RELEASE_VERSION", "").lstrip("v")
    what_new = _load_whats_new(release_version)
    if what_new:
        page_header = f"**Latest release: v{release_version}** — full details below.\n\n---\n\n{what_new}\n\n---\n"
        readme_lines.insert(1, page_header)
    # Prepend Docker Quick Start at the very beginning of the page, after the H1.
    docker_usage = (
        "---\n\n"
        "## Quick Start (Docker)\n\n"
        "```bash\n"
        "docker run -d -p 8765:8765 \\\n"
        "  -e AGNES_API_KEY=<your-key> \\\n"
        "  -v ~/agnes-data/working:/app/.working_dir \\\n"
        "  lcy362/free-short-video:latest\n"
        "```\n\n"
        "Then open **http://localhost:8765**.\n\n"
        "---\n"
    )
    readme_lines.insert(2, docker_usage)
    readme = "\n".join(readme_lines)

    # Docker Hub caps full_description; truncate at a newline before the limit.
    limit = 24000
    if len(readme) > limit:
        cut = readme.rfind("\n", 0, limit)
        readme = (readme[:cut] if cut > 0 else readme[:limit]) + \
            "\n\n---\nFull README: https://github.com/lcy362/agnes-video-generator"

    # 1) Log in to obtain a JWT (the Hub API accepts a PAT as the password).
    # We use curl instead of urllib: Docker Hub's WAF (Akamai) has been returning
    # HTML 403 pages for urllib's default TLS fingerprint/User-Agent, while the
    # docker CLI (and curl) pass. A PAT works as the login password.
    try:
        res = subprocess.run(
            [
                "curl", "-sS", "-m", "30", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-H", f"User-Agent: {UA}",
                "--data", json.dumps({"username": user, "password": token}),
                f"{DOCKERHUB_API}/users/login",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("curl not found on this runner; cannot update Docker Hub overview")
        return 1
    if res.returncode != 0:
        print("Docker Hub login failed (curl):", res.stderr.strip()[:300])
        return 1
    try:
        jwt = json.loads(res.stdout).get("token", "")
    except json.JSONDecodeError:
        print("Docker Hub login: unexpected response:", res.stdout[:300])
        return 1
    if not jwt:
        print("No JWT returned from Docker Hub")
        return 1

    # 2) Patch the repository description + full description.
    # full_description can reach ~24k chars; write the payload to a temp file so
    # the curl invocation stays well within ARG_MAX and avoids quoting issues.
    payload = json.dumps({"description": desc, "full_description": readme})
    tmp_payload = "/tmp/dockerhub_overview_payload.json"
    tmp_resp = "/tmp/dockerhub_overview_response.txt"
    with open(tmp_payload, "w", encoding="utf-8") as f:
        f.write(payload)
    try:
        res = subprocess.run(
            [
                "curl", "-sS", "-m", "60", "-o", tmp_resp, "-w", "%{http_code}",
                "-X", "PATCH",
                "-H", "Content-Type: application/json",
                "-H", f"User-Agent: {UA}",
                "-H", f"Authorization: JWT {jwt}",
                "--data", f"@{tmp_payload}",
                f"{DOCKERHUB_API}/repositories/{repo_path}/",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print("curl not found on this runner; cannot update Docker Hub overview")
        return 1
    os.remove(tmp_payload)
    http_code = res.stdout.strip()
    if res.returncode != 0 or http_code != "200":
        print(f"PATCH failed: exit={res.returncode} http={http_code} {res.stderr.strip()[:300]}")
        try:
            with open(tmp_resp, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError:
            body = ""
        print("=== response body (first 800 chars) ===")
        print(body[:800])
        print("=== end response body ===")
        os.remove(tmp_resp)
        return 1
    os.remove(tmp_resp)
    print(f"PATCH {repo_path} -> HTTP 200")
    print(f"description: {len(desc)} chars | full_description: {len(readme)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
