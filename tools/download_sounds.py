#!/usr/bin/env python3
"""Download MIT/CC0 mechanical keyboard & mouse sound packs from ayangweb/BongoCat."""

import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_RAW = "https://raw.githubusercontent.com/ayangweb/BongoCat/master/plugins/key-sounds/resources"
TARGET_IDS = {"ink-black", "holy-panda", "blue-abs", "alpaca", "orochi-v2"}


def fetch_bytes(url: str, retries: int = 4, timeout: int = 30) -> bytes:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Failed to download {url}: {last_err}")


def main() -> None:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_root = os.path.join(project_root, "assets", "sounds")
    os.makedirs(out_root, exist_ok=True)

    idx = json.loads(fetch_bytes(f"{BASE_RAW}/index.json"))
    manifest: list[str] = []
    tasks: list[tuple[str, str]] = []

    for pack in idx["packs"]:
        pid = pack["id"]
        if pid not in TARGET_IDS:
            continue
        cat = pack["category"]
        pdir = os.path.join(out_root, cat, pid)
        os.makedirs(pdir, exist_ok=True)

        for fname in pack["files"]:
            dst = os.path.join(pdir, fname)
            if not os.path.exists(dst) or os.path.getsize(dst) == 0:
                tasks.append((f"{BASE_RAW}/packs/{cat}/{pid}/{fname}", dst))

        with open(os.path.join(pdir, "pack.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": pid,
                    "name": pack["name"],
                    "brand": pack["brand"],
                    "author": pack["author"],
                    "license": pack["license"],
                    "groups": pack["groups"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        manifest.append(
            f"{cat}/{pid}: {pack['brand']} {pack['name']} by {pack['author']} "
            f"({pack['license']['type']} - {pack['license']['url']})"
        )

    print(f"Downloading {len(tasks)} sound files...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(fetch_bytes, url): (url, dst) for url, dst in tasks}
        for fut in as_completed(futs):
            url, dst = futs[fut]
            data = fut.result()
            with open(dst, "wb") as f:
                f.write(data)
            print(f"  OK: {os.path.relpath(dst, out_root)} ({len(data)} bytes)", flush=True)

    with open(os.path.join(out_root, "LICENSE.txt"), "w", encoding="utf-8") as f:
        f.write(
            "Open-source mechanical keyboard & mouse sound packs sourced from "
            "ayangweb/BongoCat (thock-soundpacks registry):\n\n"
        )
        f.write("\n".join(manifest) + "\n")
    print("All sound packs ready!", flush=True)


if __name__ == "__main__":
    main()
