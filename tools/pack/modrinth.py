"""Small Modrinth API client with an on-disk cache, shared by the pack tools."""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

API = "https://api.modrinth.com/v2"
UA = {"User-Agent": "cobbleverse-cm18-port (personal use)"}
CACHE = os.path.join(os.path.dirname(__file__), "..", "..", ".cache", "modrinth")


def get(path, cache=True, **params):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode({k: json.dumps(v) for k, v in params.items()})
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if cache and os.path.exists(key):
        return json.load(open(key))
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                data = json.load(r)
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))
    os.makedirs(CACHE, exist_ok=True)
    json.dump(data, open(key, "w"))
    return data


def version(vid):
    return get(f"/version/{vid}")


def primary_file(v):
    return next((f for f in v["files"] if f["primary"]), v["files"][0])


def download(url, dest, sha512=None):
    if os.path.exists(dest) and (not sha512 or hashlib.sha512(open(dest, "rb").read()).hexdigest() == sha512):
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(dest + ".part", "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if sha512 and hashlib.sha512(open(dest + ".part", "rb").read()).hexdigest() != sha512:
        raise ValueError(f"sha512 mismatch for {url}")
    os.replace(dest + ".part", dest)
    return dest


def index_entry(v, env=None):
    """A modrinth.index.json file entry for a version's primary file."""
    pf = primary_file(v)
    return {"path": f"mods/{pf['filename']}",
            "hashes": {"sha1": pf["hashes"]["sha1"], "sha512": pf["hashes"]["sha512"]},
            "env": env or {"client": "required", "server": "required"},
            "downloads": [pf["url"]], "fileSize": pf["size"]}
