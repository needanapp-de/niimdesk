"""Publish a GitHub release (notes + files) as a release of the Forgejo mirror.

Usage: FORGEJO_TOKEN=... python3 packaging/forgejo_release.py --url https://git.example.org \\
           --repo owner/name --tag v1.0.0 --notes release.json FILE...

``release.json`` is the output of ``gh release view TAG --json name,body``. The script asks the
mirror to sync (so the tag exists), creates or updates the release and replaces files with the
same name, so running it twice is harmless.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class Api:
    def __init__(self, base: str, repo: str, token: str) -> None:
        self.base = f"{base.rstrip('/')}/api/v1/repos/{repo}"
        self.token = token

    def call(self, method: str, path: str, data: object = None, *, body: bytes | None = None,
             content_type: str = "application/json", timeout: float = 60) -> object:
        if data is not None:
            body = json.dumps(data).encode()
        request = Request(self.base + path, data=body, method=method)
        request.add_header("Authorization", f"token {self.token}")
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", content_type)
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
        return json.loads(payload) if payload else None


def wait_for_tag(api: Api, tag: str, timeout: float) -> None:
    try:
        api.call("POST", "/mirror-sync")
    except HTTPError as e:  # not fatal: the mirror also syncs on its own schedule
        print(f"Spiegel-Abgleich konnte nicht angestoßen werden (HTTP {e.code}), warte auf den nächsten Abgleich")
    deadline = time.monotonic() + timeout
    while True:
        try:
            api.call("GET", f"/tags/{quote(tag, safe='')}")
            return
        except HTTPError as e:
            if e.code != 404 or time.monotonic() > deadline:
                raise SystemExit(f"Tag {tag} ist auf dem Spiegel nicht angekommen (HTTP {e.code})") from e
        time.sleep(10)


def upload(api: Api, release_id: int, path: Path) -> None:
    boundary = uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="attachment"; filename="{path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    api.call(
        "POST", f"/releases/{release_id}/assets?name={quote(path.name)}", body=body,
        content_type=f"multipart/form-data; boundary={boundary}", timeout=900,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes", required=True, type=Path)
    parser.add_argument("--wait", type=float, default=600, help="Sekunden, die auf das Tag gewartet wird")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()

    token = os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        print("::notice::FORGEJO_TOKEN ist nicht gesetzt, das Release wird nicht nach Forgejo gespiegelt")
        return
    api = Api(args.url, args.repo, token)
    notes = json.loads(args.notes.read_text(encoding="utf-8"))

    wait_for_tag(api, args.tag, args.wait)
    fields = {"tag_name": args.tag, "name": notes.get("name") or args.tag, "body": notes.get("body", ""),
              "draft": False, "prerelease": False}
    try:
        release = api.call("GET", f"/releases/tags/{quote(args.tag, safe='')}")
        release = api.call("PATCH", f"/releases/{release['id']}", fields)
        print(f"Release {args.tag} aktualisiert")
    except HTTPError as e:
        if e.code != 404:
            raise
        release = api.call("POST", "/releases", fields)
        print(f"Release {args.tag} angelegt")

    existing = {a["name"]: a["id"] for a in release.get("assets", [])}
    for path in args.files:
        if path.name in existing:
            api.call("DELETE", f"/releases/{release['id']}/assets/{existing[path.name]}")
        print(f"Lade {path.name} hoch ({path.stat().st_size / 1e6:.1f} MB) …", flush=True)
        upload(api, release["id"], path)
    print(f"Fertig: {release['html_url']}")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as e:
        sys.exit(f"Forgejo antwortet mit HTTP {e.code}: {e.read().decode(errors='replace')[:500]}")
