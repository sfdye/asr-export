#!/usr/bin/env python3
"""
asr-export — bulk document exporter for Avenue South Residence (Habitap)

ASR is migrating from Habitap to iCondo, and iCondo cannot serve per-unit
documents, so residents are asked to back up their documents manually. With
300+ documents per account, downloading by hand is not practical — this tool
automates it: it lists and bulk-downloads every document your account can
see, grouped by category, with resume support.

Everything runs locally: your credentials are only used to log in to Habitap
over HTTPS and are never sent anywhere else. The password is never written to
disk — only the session cookie, stored in ~/.asr with mode 0600.

The login flow is inspired by the community project at https://asrlife.vip,
which reverse-engineered the Habitap resident API.

Python 3 standard library only.
"""

import contextlib
import datetime
import getpass
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Habitap's CA chain lacks the keyUsage extension; Python 3.13+/OpenSSL 3.5+
# enables VERIFY_X509_STRICT by default and rejects it. Older Pythons don't
# have the flag at all — guard with hasattr so this works everywhere. The
# chain is still fully verified — we only disable the strict linting.
try:
    _ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        _ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    ssl._create_default_https_context = lambda: _ctx
except Exception:
    pass

CFG = {
    "baseUrl": "https://avenuesouth.habitap.app/avenuesouth",
    "condoId": 32,
    "userAgent": "okhttp/4.12.0",
    "condoCode": "AVESOU",
    "userTypeTag": "RESIDENT",
    "devicePlatform": "ANDROID",
    "appId": "com.habitap.residential.avesouth",
    "apiVersion": "V2",
    "timeZone": "Asia/Singapore",
}
HOME = Path(os.environ.get("ASR_HOME", str(Path.home() / ".asr")))
SJSON = HOME / "session.json"
CKS = HOME / "cookies.json"
MANIFESTS_DIR = HOME / "manifests"


def _manifest_path(out):
    """One manifest.json per output dir, stored under ~/.asr/manifests/<key>/."""
    key = hashlib.sha256(str(out).encode()).hexdigest()[:16]
    return MANIFESTS_DIR / key / "manifest.json"


_TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else str(s)


def B(s):
    return _c("1", s)


def D(s):
    return _c("2", s)


def G(s):
    return _c("32", s)


def Y(s):
    return _c("33", s)


def R(s):
    return _c("31", s)


def Cy(s):
    return _c("36", s)


def die(msg):
    print(R("✗ ") + str(msg), file=sys.stderr)
    sys.exit(1)


def load_session():
    if not SJSON.exists() or not CKS.exists():
        die("No session found. First run:  asr-export login")
    return json.loads(SJSON.read_text())


def cookie_header():
    ck = json.loads(CKS.read_text())
    return "; ".join(f"{k}={v}" for k, v in ck.items())


def http_json(method, url, body=None, tries=3):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": CFG["userAgent"], "Cookie": cookie_header()}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"error": raw[:200]}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == tries:
                return 0, {"error": str(getattr(e, "reason", e))}
            time.sleep(2 * attempt)
    return 0, {"error": "unreachable"}


def need_session():
    s = load_session()
    st, _ = http_json("GET", CFG["baseUrl"] + "/api/authentications/1")
    if st != 200:
        die("Session expired — re-run:  asr-export login")
    return s


def cfg(s, *path):
    d = s
    for p in path:
        d = (d or {}).get(p)
    return d


def api(path):
    return CFG["baseUrl"] + path


def _save_cookies(ck):
    HOME.mkdir(parents=True, exist_ok=True)
    CKS.write_text(json.dumps(ck))
    with contextlib.suppress(Exception):
        os.chmod(CKS, 0o600)


def _merge_set_cookie(headers):
    """Merge Set-Cookie headers from a login response into ~/.asr/cookies.json."""
    ck = json.loads(CKS.read_text()) if CKS.exists() else {}
    for sc in headers.get_all("Set-Cookie") or []:
        kv = sc.split(";", 1)[0].strip()
        if "=" in kv:
            k, v = kv.split("=", 1)
            if v == "deleteMe":
                ck.pop(k, None)
            else:
                ck[k] = v
    _save_cookies(ck)


# ---------------- login (flow adapted from https://asrlife.vip) ----------------


def cmd_login(args):
    HOME.mkdir(parents=True, exist_ok=True)
    # Already logged in with a working session? Skip unless --force / -u given.
    if (
        not ("--force" in args or "-f" in args)
        and not isinstance(_opt(args, "-u"), str)
        and SJSON.exists()
        and CKS.exists()
    ):
        st, u = http_json("GET", api("/api/authentications/1"))
        if st == 200 and isinstance(u, dict):
            unit = u.get("unit") or {}
            full = (u.get("authentication") or {}).get("fullName")
            print(
                f"  {G('✓ already logged in')}  {full}  {unit.get('unitNo')}"
                + D(f"  ({unit.get('condoName')})")
            )
            print("  " + D("re-login:  asr-export login --force"))
            return
    print(
        B("ASR login")
        + D("  new devices need a one-time email OTP; session lasts ~1 year; password never stored")
    )
    user = _opt(args, "-u")
    if not isinstance(user, str):
        user = input("  Email: ").strip()
    pw = getpass.getpass("  Password: ")
    s = load_session() if SJSON.exists() else None
    # Server rejects client-made installationIds (409); empty string enters the
    # 452/OTP new-device flow. Reuse a previously-registered one if we have it.
    inst = cfg(s, "device", "installationId") or ""

    def body(otp, iid):
        b = {
            "username": user,
            "password": pw,
            "devicePlatform": CFG["devicePlatform"],
            "deviceToken": "",
            "userTypeTag": CFG["userTypeTag"],
            "condoCode": CFG["condoCode"],
            "rememberMe": "true",
            "installationId": iid,
            "appId": CFG["appId"],
            "modelName": "Google",
            "modelNumber": "Pixel 7",
        }
        if otp:
            b["otp"] = otp
        return b

    backup = json.loads(CKS.read_text()) if CKS.exists() else {}
    _save_cookies({})

    def post(b):
        data = json.dumps(b).encode()
        h = {
            "User-Agent": CFG["userAgent"],
            "Content-Type": "application/json",
            "apiVersion": CFG["apiVersion"],
        }
        req = urllib.request.Request(
            api("/api/authentications"), data=data, headers=h, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _merge_set_cookie(r.headers)
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            _merge_set_cookie(e.headers)
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"error": raw[:200]}

    otp_opt = _opt(args, "-o")
    otp0 = otp_opt if isinstance(otp_opt, str) else None
    st, j = post(body(otp0, inst))
    if st == 409 and inst:
        inst = ""
        st, j = post(body(otp0, inst))
    if st == 452:
        msg = (
            j.get("message") if isinstance(j, dict) else ""
        ) or "An OTP has been sent to your email — please check."
        print("🔐 New-device verification:")
        print("   " + msg)
        otp = input("   Email OTP: ").strip()
        st, j = post(body(otp, inst))
    if st != 200:
        _save_cookies(backup)  # keep any previously-working session intact
        hint = (
            (j.get("auth failed") or j.get("message") or str(j))[:160]
            if isinstance(j, dict)
            else str(j)[:160]
        )
        die(
            f"Login failed (HTTP {st}): {hint}\n"
            "  Check: email/password are correct · the account is at Avenue South "
            "Residence · the account is active."
        )

    _, u = http_json("GET", api("/api/authentications/1"))
    unit = (u.get("unit") or {}) if isinstance(u, dict) else {}
    sess = {
        "config": dict(CFG, condoId=unit.get("condoId") or CFG["condoId"]),
        "device": {
            "installationId": inst,
            "deviceToken": "",
            "modelName": "Google",
            "modelNumber": "Pixel 7",
        },
        "account": {
            "username": (u.get("residentAccount") or {}).get("userName"),
            "fullName": (u.get("authentication") or {}).get("fullName"),
            "unitId": unit.get("id"),
            "blockCode": unit.get("blockCode"),
            "unitNo": unit.get("unitNo"),
            "residentAccountId": (u.get("residentAccount") or {}).get("id"),
            "condoName": unit.get("condoName"),
        },
    }
    SJSON.write_text(json.dumps(sess, ensure_ascii=False, indent=2))
    with contextlib.suppress(Exception):
        os.chmod(SJSON, 0o600)
    print(
        f"  {G('✓ login ok')}  {sess['account']['fullName']}  {sess['account']['unitNo']}"
        + D(f"  ({sess['account']['condoName']})")
    )
    print("  " + D("session saved (~1 year, password never stored to disk)"))
    print("  " + D("next:  asr-export download"))


# ---------------- ASR data ----------------


def fetch_catalog(s):
    """Returns [(category, [doc, ...]), ...] for this account's block, deduped by doc id."""
    cid, block = cfg(s, "config", "condoId"), cfg(s, "account", "blockCode")
    st, j = http_json(
        "GET", api(f"/api/condos/{cid}/document-categories?viewFormat=PUB&condoBlockCode={block}")
    )
    if st != 200:
        die(f"Failed to list categories (HTTP {st}): {str(j)[:160]}")
    cats = sorted(
        (j.get("entities") or []), key=lambda c: (c.get("sequenceOrder") or 0, c.get("id"))
    )
    seen, result = {}, []
    for c in cats:
        st, j = http_json(
            "GET",
            api(
                f"/api/condos/{cid}/documents?viewFormat=PUB"
                f"&categoryId={c['id']}&condoBlockCode={block}"
            ),
        )
        if st != 200:
            die(f"Failed to list documents for '{c['name']}' (HTTP {st}): {str(j)[:160]}")
        docs = []
        for e in j.get("entities") or []:
            if e["id"] not in seen:
                seen[e["id"]] = e
                docs.append(e)
        if docs:
            result.append((c, docs))
    return result


def sanitize(name, maxlen=120):
    name = str(name or "").strip().replace("\t", " ")
    name = "".join("-" if ch in '/\\:*?"<>|' else ch for ch in name)
    name = " ".join(name.split())
    return (name[:maxlen] or "untitled").rstrip(". ")


MIME_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "text/plain": ".txt",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


def doc_filename(doc):
    url = doc.get("filePath") or ""
    for ext in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".txt", ".doc", ".docx", ".xls", ".xlsx"):
        if url.lower().split("?")[0].endswith(ext):
            return sanitize(doc["caption"]) + ext
    return sanitize(doc["caption"]) + MIME_EXT.get(doc.get("fileType") or "", ".bin")


def unique_path(directory, stem, doc_id):
    p = directory / stem
    if not p.exists():
        return p
    return directory / f"{p.stem} [{doc_id}]{p.suffix}"


# ---------------- commands ----------------

LIST_PREVIEW = 10  # per category; more than this shows a preview (--all for full)


def _cat_match(c, flt):
    """--cat accepts a category id (exact digits) or a name substring."""
    if str(flt).strip().isdigit():
        return str(c["id"]) == str(flt).strip()
    return str(flt).lower() in c["name"].lower()


def cmd_list(args):
    s = need_session()
    flt = _opt(args, "--cat")
    show_all = "--all" in args
    cat = fetch_catalog(s)
    total = hidden = 0
    head = B("ASR documents") + D(
        f"  unit {cfg(s, 'account', 'unitNo')} · block {cfg(s, 'account', 'blockCode')}"
    )
    print(head)
    for c, docs in cat:
        if flt is not None and not _cat_match(c, flt):
            continue
        total += len(docs)
        print(f"\n  {B(c['name'])}  " + D(f"({len(docs)} docs, id {c['id']})"))
        shown = docs if show_all or len(docs) <= LIST_PREVIEW else docs[:LIST_PREVIEW]
        for e in shown:
            tag = Cy("↗") if e.get("externalUrl") and not e.get("filePath") else D("·")
            print(f"    {tag} {e['caption'].strip()}  " + D(f"[{e['id']}]"))
        if len(shown) < len(docs):
            more = len(docs) - len(shown)
            hidden += more
            hint = f'(asr-export list --cat "{c["name"].strip()}" --all)'
            print(f"    {D('…')} {Y(f'{more} more not shown')}  " + D(hint))
    tail = D("  (deduped; a doc may show under one category only)")
    if hidden:
        tail += Y(f"  · {hidden} hidden in preview — add --all to show everything")
    print(f"\n  {G('total:')} {total} documents{tail}")


def _choose_categories(catalog):
    """Interactive category picker. Returns the chosen [(cat, docs)] or [] to abort."""
    print(B("Categories available for download:"))
    for i, (c, docs) in enumerate(catalog, 1):
        print(f"  {Cy(str(i).rjust(2))})  {c['name']}  {D(f'({len(docs)} docs)')}")
    total = sum(len(d) for _, d in catalog)
    print(D(f"  {total} documents total"))
    hint = "(e.g. 1,3-5; Enter=all; a=all; q=quit)"
    while True:
        try:
            raw = input(f"{B('select')} {D(hint)}: ").strip()
        except EOFError:
            die("non-interactive session — use:  asr-export download --cat <name> --yes")
        low = raw.lower()
        if low in ("q", "quit", "exit"):
            return []
        if raw == "" or low in ("a", "all"):
            return catalog
        picks = set()
        try:
            for tok in raw.replace(" ", "").split(","):
                if not tok:
                    continue
                if "-" in tok:
                    a, b = tok.split("-", 1)
                    a, b = int(a), int(b)
                    if not (1 <= a <= b <= len(catalog)):
                        raise ValueError
                    picks.update(range(a, b + 1))
                else:
                    n = int(tok)
                    if not (1 <= n <= len(catalog)):
                        raise ValueError
                    picks.add(n)
            if picks:
                return [catalog[i - 1] for i in sorted(picks)]
        except ValueError:
            pass
        print(Y("  invalid selection, try again"))


def _confirm(prompt):
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_download(args):
    s = need_session()
    o = _opt(args, "-o")
    default_out = Path(
        os.environ.get("ASR_EXPORT_DIR") or str(Path(__file__).resolve().parent / "asr-export")
    )
    out = Path(o if isinstance(o, str) else default_out).expanduser().absolute()
    flt = _opt(args, "--cat")
    dry = "--dry-run" in args
    force = "--force" in args
    auto = "-y" in args or "--yes" in args
    catalog = fetch_catalog(s)
    if flt:
        catalog = [(c, d) for c, d in catalog if _cat_match(c, flt)]
    if not catalog:
        die("No documents matched.")

    if auto:
        chosen = catalog
    else:
        chosen = _choose_categories(catalog)
        if not chosen:
            print("  " + D("nothing selected, bye"))
            return
    total = sum(len(d) for _, d in chosen)
    if not total:
        print("  " + D("selected categories are empty, bye"))
        return

    if not (auto or dry) and not _confirm(
        f"{B('confirm')} {Y(f'download {total} documents to {out} ?')} {D('[y/N]')}: "
    ):
        print("  " + D("cancelled"))
        return
    print(B("Download") + D(f"  {total} docs -> {out}" + ("  (dry-run)" if dry else "")))

    manifest_path = _manifest_path(out)
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.setdefault("_outputDir", str(out))

    def save_manifest():
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    ok, skip, fail, ext, n = 0, 0, 0, 0, 0
    t0 = time.time()
    for c, docs in chosen:
        cdir = out / sanitize(c["name"], 60)
        if not dry:
            cdir.mkdir(parents=True, exist_ok=True)
        for e in docs:
            n += 1
            rel = f"{cdir.name}/{doc_filename(e)}"
            m = manifest.get(str(e["id"]))
            done_file = (cdir / doc_filename(e)).exists() or (
                m and (out / m.get("file", "missing")).exists()
            )
            if not force and m and done_file:
                skip += 1
                if m.get("categories") and c["name"] not in m["categories"]:
                    m["categories"].append(c["name"])
                continue
            if dry:
                url_hint = e.get("filePath") or e.get("externalUrl") or ""
                print(f"  {Cy('would download')}  {rel}  {D(url_hint)}")
                ok += 1
                continue
            url = e.get("filePath")
            if not url:
                url = e.get("externalUrl")
                if url and url.startswith("http"):
                    p = unique_path(cdir, sanitize(e["caption"]) + ".url", e["id"])
                    p.write_text(url + "\n")
                    ext += 1
                    manifest[str(e["id"])] = _mrec(e, c, p.relative_to(out), kind="link")
                    save_manifest()
                    continue
                print(f"  {R('✗ no url')}  {e['caption']}  " + D(f"[{e['id']}]"))
                fail += 1
                continue
            p = unique_path(cdir, doc_filename(e), e["id"])
            r = _download(url, p)
            if r:
                ok += 1
                manifest[str(e["id"])] = _mrec(e, c, p.relative_to(out))
                save_manifest()
                print(f"  {D(f'[{n}/{total}]')} {G('✓')} {rel}")
            else:
                fail += 1
            time.sleep(0.4)
    dt = time.time() - t0
    print(
        f"\n  {G('✓')} done  downloaded {ok}  skipped {skip}  failed {fail}"
        + (f"  links {ext}" if ext else "")
        + D(f"  in {dt:.0f}s")
    )
    if dry:
        print(D("  re-run without --dry-run to actually download"))


def _mrec(e, c, relpath, kind="file"):
    return {
        "caption": e["caption"].strip(),
        "description": (e.get("description") or "").strip(),
        "categories": [c["name"]],
        "url": e.get("filePath") or e.get("externalUrl"),
        "file": str(relpath),
        "kind": kind,
        "downloadedAt": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def _download(url, path):
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": CFG["userAgent"]})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
            return True
        except Exception as e:
            if attempt == 3:
                print(f"  {R('✗ failed')}  {path.name}  {D(str(e)[:120])}")
                if path.exists():
                    path.unlink()
                return False
            time.sleep(1.5 * attempt)


def _opt(args, flag, default=None):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args) and not args[i + 1].startswith("-"):
            return args[i + 1]
        return default if default is not None else True
    return default


HELP = """ASR · asr-export — bulk document downloader for Avenue South Residence (Habitap)
The login session lives in ~/.asr and lasts about a year.

Usage:
  asr-export login [-u <email>] [-o <otp>] [--force]
        Log in (skipped if already logged in; new devices need a one-time email OTP)
  asr-export list [--cat <keyword|id>] [--all]
        Show documents grouped by category (large categories are previewed, first 10)
  asr-export download [options]
        Interactively pick categories -> confirm -> bulk download

Options:
  -o <dir>        Output directory (default: asr-export/ next to the script;
                  the installed command defaults to ~/Documents/asr-export)
  --cat <kw|id>   Only categories matching a name substring or id (e.g. --cat Circulars)
  --yes, -y       Skip selection/confirmation, download everything (--cat filtered) — for scripts
  --dry-run       Show what would be downloaded without downloading
  --force         Re-download files that already exist (default: skip/resume)
  -h, --help      This help

Files land in <dir>/<category>/<caption>.<ext>. A per-directory manifest.json
(stored under ~/.asr/manifests/, not in the output folder) records every
download — saved after each file, so Ctrl+C + re-run resumes. Downloads are
paced (~0.4s apart).
"""


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    rest = args[1:]
    try:
        if cmd in ("-h", "--help", "help"):
            print(HELP)
        elif cmd == "login":
            cmd_login(rest)
        elif cmd == "list":
            cmd_list(rest)
        elif cmd == "download":
            cmd_download(rest)
        else:
            die(f"unknown command '{cmd}' — asr-export help")
    except KeyboardInterrupt:
        print("\n" + D("interrupted — re-run to resume"))
        sys.exit(130)


if __name__ == "__main__":
    main()
