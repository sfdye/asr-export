#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import sys, os, json, time, ssl, hashlib, datetime, getpass, urllib.request, urllib.error
from pathlib import Path

# ---------------- i18n (English by default; zh when ASR_EXPORT_LANG=zh or a zh_* locale) ----------------

def _detect_lang():
    v = os.environ.get("ASR_EXPORT_LANG")
    if v: return "zh" if v.strip().lower().startswith("zh") else "en"
    for k in ("LC_ALL", "LANG"):
        if (os.environ.get(k) or "").lower().startswith("zh"): return "zh"
    return "en"

LANG = _detect_lang()
def t(en, zh): return zh if LANG == "zh" else en

# Habitap's CA chain lacks the keyUsage extension; Python 3.13+/OpenSSL 3.5+
# enables VERIFY_X509_STRICT by default and rejects it. The chain is still
# fully verified — we only disable the strict linting.
_ctx = ssl.create_default_context()
_ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
ssl._create_default_https_context = lambda: _ctx

CFG = {
    "baseUrl": "https://avenuesouth.habitap.app/avenuesouth",
    "condoId": 32, "userAgent": "okhttp/4.12.0",
    "condoCode": "AVESOU", "userTypeTag": "RESIDENT", "devicePlatform": "ANDROID",
    "appId": "com.habitap.residential.avesouth", "apiVersion": "V2", "timeZone": "Asia/Singapore",
}
HOME = Path(os.environ.get("ASR_HOME", str(Path.home() / ".asr")))
SJSON = HOME / "session.json"; CKS = HOME / "cookies.json"
MANIFESTS_DIR = HOME / "manifests"

def _manifest_path(out):
    """One manifest.json per output dir, stored under ~/.asr/manifests/<key>/."""
    key = hashlib.sha256(str(out).encode()).hexdigest()[:16]
    return MANIFESTS_DIR / key / "manifest.json"

_TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
def _c(code, s): return f"\033[{code}m{s}\033[0m" if _TTY else str(s)
def B(s): return _c("1", s)
def D(s): return _c("2", s)
def G(s): return _c("32", s)
def Y(s): return _c("33", s)
def R(s): return _c("31", s)
def Cy(s): return _c("36", s)

def die(msg): print(R("✗ ") + str(msg), file=sys.stderr); sys.exit(1)

def load_session():
    if not SJSON.exists() or not CKS.exists():
        die(t("No session found. First run:  asr-export login",
              "尚未登录，先运行:  asr-export login"))
    return json.loads(SJSON.read_text())

def cookie_header():
    ck = json.loads(CKS.read_text())
    return "; ".join(f"{k}={v}" for k, v in ck.items())

def http_json(method, url, body=None, tries=3):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": CFG["userAgent"], "Cookie": cookie_header()}
    if data is not None: headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try: return e.code, json.loads(raw)
            except Exception: return e.code, {"error": raw[:200]}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == tries: return 0, {"error": str(getattr(e, "reason", e))}
            time.sleep(2 * attempt)
    return 0, {"error": "unreachable"}

def need_session():
    s = load_session()
    st, _ = http_json("GET", CFG["baseUrl"] + "/api/authentications/1")
    if st != 200: die(t("Session expired — re-run:  asr-export login",
                        "会话失效，请重新登录:  asr-export login"))
    return s

def cfg(s, *path):
    d = s
    for p in path: d = (d or {}).get(p)
    return d

def api(path): return CFG["baseUrl"] + path

def _save_cookies(ck):
    HOME.mkdir(parents=True, exist_ok=True)
    CKS.write_text(json.dumps(ck))
    try: os.chmod(CKS, 0o600)
    except Exception: pass

def _merge_set_cookie(headers):
    """Merge Set-Cookie headers from a login response into ~/.asr/cookies.json."""
    ck = json.loads(CKS.read_text()) if CKS.exists() else {}
    for sc in (headers.get_all("Set-Cookie") or []):
        kv = sc.split(";", 1)[0].strip()
        if "=" in kv:
            k, v = kv.split("=", 1)
            if v == "deleteMe": ck.pop(k, None)
            else: ck[k] = v
    _save_cookies(ck)

# ---------------- login (flow adapted from https://asrlife.vip) ----------------

def cmd_login(args):
    HOME.mkdir(parents=True, exist_ok=True)
    # Already logged in with a working session? Skip unless --force / -u given.
    if not ("--force" in args or "-f" in args) and not isinstance(_opt(args, "-u"), str) \
            and SJSON.exists() and CKS.exists():
        st, u = http_json("GET", api("/api/authentications/1"))
        if st == 200 and isinstance(u, dict):
            unit = u.get("unit") or {}
            full = (u.get("authentication") or {}).get("fullName")
            print(f"  {G(t('✓ already logged in', '✓ 已登录'))}  {full}  {unit.get('unitNo')}"
                  + D(f"  ({unit.get('condoName')})"))
            print("  " + D(t("re-login:  asr-export login --force",
                            "重新登录:  asr-export login --force")))
            return
    print(B(t("ASR login", "ASR 登录"))
          + D(t("  new devices need a one-time email OTP; session lasts ~1 year; password never stored",
                "  首次/新设备需邮箱 OTP（仅一次；之后约 1 年免登录，密码不落盘）")))
    user = _opt(args, "-u")
    if not isinstance(user, str): user = input(t("  Email: ", "  邮箱: ")).strip()
    pw = getpass.getpass(t("  Password: ", "  密码: "))
    s = load_session() if SJSON.exists() else None
    # Server rejects client-made installationIds (409); empty string enters the
    # 452/OTP new-device flow. Reuse a previously-registered one if we have it.
    inst = cfg(s, "device", "installationId") or ""

    def body(otp, iid):
        b = {"username": user, "password": pw, "devicePlatform": CFG["devicePlatform"],
             "deviceToken": "", "userTypeTag": CFG["userTypeTag"], "condoCode": CFG["condoCode"],
             "rememberMe": "true", "installationId": iid, "appId": CFG["appId"],
             "modelName": "Google", "modelNumber": "Pixel 7"}
        if otp: b["otp"] = otp
        return b

    backup = json.loads(CKS.read_text()) if CKS.exists() else {}
    _save_cookies({})

    def post(b):
        data = json.dumps(b).encode()
        h = {"User-Agent": CFG["userAgent"], "Content-Type": "application/json",
             "apiVersion": CFG["apiVersion"]}
        req = urllib.request.Request(api("/api/authentications"), data=data, headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                _merge_set_cookie(r.headers)
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            _merge_set_cookie(e.headers)
            raw = e.read().decode("utf-8", "replace")
            try: return e.code, json.loads(raw)
            except Exception: return e.code, {"error": raw[:200]}

    otp_opt = _opt(args, "-o")
    otp0 = otp_opt if isinstance(otp_opt, str) else None
    st, j = post(body(otp0, inst))
    if st == 409 and inst:
        inst = ""
        st, j = post(body(otp0, inst))
    if st == 452:
        msg = (j.get("message") if isinstance(j, dict) else "") \
            or t("An OTP has been sent to your email — please check.", "已向你的邮箱发送 OTP，请查收。")
        print(t("🔐 New-device verification:", "🔐 新设备验证:"))
        print("   " + msg)
        otp = input(t("   Email OTP: ", "   邮箱 OTP: ")).strip()
        st, j = post(body(otp, inst))
    if st != 200:
        _save_cookies(backup)  # keep any previously-working session intact
        hint = (j.get("auth failed") or j.get("message") or str(j))[:160] if isinstance(j, dict) else str(j)[:160]
        die(t(f"Login failed (HTTP {st}): {hint}\n"
              "  Check: email/password are correct · the account is at Avenue South Residence · the account is active.",
              f"登录失败 (HTTP {st}): {hint}\n"
              "  检查: 邮箱/密码是否正确 · 账号是否在 Avenue South Residence · 是否已激活未停用。"))

    st2, u = http_json("GET", api("/api/authentications/1"))
    unit = (u.get("unit") or {}) if isinstance(u, dict) else {}
    sess = {
        "config": dict(CFG, condoId=unit.get("condoId") or CFG["condoId"]),
        "device": {"installationId": inst, "deviceToken": "", "modelName": "Google", "modelNumber": "Pixel 7"},
        "account": {
            "username": (u.get("residentAccount") or {}).get("userName"),
            "fullName": (u.get("authentication") or {}).get("fullName"),
            "unitId": unit.get("id"), "blockCode": unit.get("blockCode"),
            "unitNo": unit.get("unitNo"), "residentAccountId": (u.get("residentAccount") or {}).get("id"),
            "condoName": unit.get("condoName"),
        },
    }
    SJSON.write_text(json.dumps(sess, ensure_ascii=False, indent=2))
    try: os.chmod(SJSON, 0o600)
    except Exception: pass
    print(f"  {G(t('✓ login ok', '✓ 登录成功'))}  {sess['account']['fullName']}  {sess['account']['unitNo']}"
          + D(f"  ({sess['account']['condoName']})"))
    print("  " + D(t("session saved (~1 year, password never stored to disk)",
                    "会话已保存（~1 年免登录，密码不落盘）")))
    print("  " + D(t("next:  asr-export download", "下一步:  asr-export download")))

# ---------------- ASR data ----------------

def fetch_catalog(s):
    """Returns [(category, [doc, ...]), ...] for this account's block, deduped by doc id."""
    cid, block = cfg(s, "config", "condoId"), cfg(s, "account", "blockCode")
    st, j = http_json("GET", api(f"/api/condos/{cid}/document-categories?viewFormat=PUB&condoBlockCode={block}"))
    if st != 200: die(f"Failed to list categories (HTTP {st}): {str(j)[:160]}")
    cats = sorted((j.get("entities") or []), key=lambda c: (c.get("sequenceOrder") or 0, c.get("id")))
    seen, result = {}, []
    for c in cats:
        st, j = http_json("GET", api(f"/api/condos/{cid}/documents?viewFormat=PUB"
                                     f"&categoryId={c['id']}&condoBlockCode={block}"))
        if st != 200: die(f"Failed to list documents for '{c['name']}' (HTTP {st}): {str(j)[:160]}")
        docs = []
        for e in (j.get("entities") or []):
            if e["id"] not in seen:
                seen[e["id"]] = e
                docs.append(e)
        if docs: result.append((c, docs))
    return result

def sanitize(name, maxlen=120):
    name = str(name or "").strip().replace("\t", " ")
    name = "".join("-" if ch in '/\\:*?"<>|' else ch for ch in name)
    name = " ".join(name.split())
    return (name[:maxlen] or "untitled").rstrip(". ")

MIME_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
    "text/plain": ".txt", "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

def doc_filename(doc):
    url = doc.get("filePath") or ""
    for ext in (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".txt", ".doc", ".docx", ".xls", ".xlsx"):
        if url.lower().split("?")[0].endswith(ext): return sanitize(doc["caption"]) + ext
    return sanitize(doc["caption"]) + MIME_EXT.get(doc.get("fileType") or "", ".bin")

def unique_path(directory, stem, doc_id):
    p = directory / stem
    if not p.exists(): return p
    return directory / f"{p.stem} [{doc_id}]{p.suffix}"

# ---------------- commands ----------------

LIST_PREVIEW = 10  # per category; more than this shows a preview (--all for full)

def _cat_match(c, flt):
    """--cat accepts a category id (exact digits) or a name substring."""
    if str(flt).strip().isdigit(): return str(c["id"]) == str(flt).strip()
    return str(flt).lower() in c["name"].lower()

def cmd_list(args):
    s = need_session()
    flt = _opt(args, "--cat")
    show_all = "--all" in args
    cat = fetch_catalog(s)
    total = hidden = 0
    head = B(t("ASR documents", "ASR 文档")) \
        + D(f"  unit {cfg(s,'account','unitNo')} · block {cfg(s,'account','blockCode')}")
    print(head)
    for c, docs in cat:
        if flt is not None and not _cat_match(c, flt): continue
        total += len(docs)
        print(f"\n  {B(c['name'])}  {D(f'({len(docs)} docs, id {c["id"]})')}")
        shown = docs if show_all or len(docs) <= LIST_PREVIEW else docs[:LIST_PREVIEW]
        for e in shown:
            tag = Cy("↗") if e.get("externalUrl") and not e.get("filePath") else D("·")
            print(f"    {tag} {e['caption'].strip()}  {D(f'[{e["id"]}]')}")
        if len(shown) < len(docs):
            more = len(docs) - len(shown)
            hidden += more
            print(f"    {D('…')} {Y(t(f'{more} more not shown', f'其余 {more} 个未显示'))}  "
                  f"{D(f'(asr-export list --cat \"{c["name"].strip()}\" --all)')}")
    tail = D(t("  (deduped; a doc may show under one category only)",
               "  （已去重；同一文档只显示在一个类别下）"))
    if hidden: tail += Y(t(f"  · {hidden} hidden in preview — add --all to show everything",
                           f"  · 预览中隐藏 {hidden} 条 — 加 --all 显示全部"))
    print(f"\n  {G(t('total:', '合计:'))} {total} {t('documents', '个文档')}{tail}")

def _choose_categories(catalog):
    """Interactive category picker. Returns the chosen [(cat, docs)] or [] to abort."""
    print(B(t("Categories available for download:", "可下载的类别:")))
    for i, (c, docs) in enumerate(catalog, 1):
        print(f"  {Cy(str(i).rjust(2))})  {c['name']}  {D(f'({len(docs)} docs)')}")
    total = sum(len(d) for _, d in catalog)
    print(D(t(f"  {total} documents total", f"  合计 {total} 个文档")))
    while True:
        try:
            raw = input(f"{B(t('select', '选择'))} "
                        f"{D(t('(e.g. 1,3-5; Enter=all; a=all; q=quit)',
                               '(如 1,3-5；回车=全部；a=全部；q=退出)'))}: ").strip()
        except EOFError:
            die(t("non-interactive session — use:  asr-export download --cat <name> --yes",
                  "非交互环境 — 请使用:  asr-export download --cat <名称> --yes"))
        low = raw.lower()
        if low in ("q", "quit", "exit"): return []
        if raw == "" or low in ("a", "all"): return catalog
        picks = set()
        try:
            for tok in raw.replace(" ", "").split(","):
                if not tok: continue
                if "-" in tok:
                    a, b = tok.split("-", 1); a, b = int(a), int(b)
                    if not (1 <= a <= b <= len(catalog)): raise ValueError
                    picks.update(range(a, b + 1))
                else:
                    n = int(tok)
                    if not (1 <= n <= len(catalog)): raise ValueError
                    picks.add(n)
            if picks: return [catalog[i - 1] for i in sorted(picks)]
        except ValueError:
            pass
        print(Y(t("  invalid selection, try again", "  输入无效，请重试")))

def _confirm(prompt):
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False

def cmd_download(args):
    s = need_session()
    o = _opt(args, "-o")
    default_out = Path(os.environ.get("ASR_EXPORT_DIR")
                       or str(Path(__file__).resolve().parent / "asr-export"))
    out = Path(o if isinstance(o, str) else default_out).expanduser().absolute()
    flt = _opt(args, "--cat")
    dry = "--dry-run" in args
    force = "--force" in args
    auto = "-y" in args or "--yes" in args
    catalog = fetch_catalog(s)
    if flt: catalog = [(c, d) for c, d in catalog if _cat_match(c, flt)]
    if not catalog: die(t("No documents matched.", "没有匹配的文档。"))

    if auto:
        chosen = catalog
    else:
        chosen = _choose_categories(catalog)
        if not chosen:
            print("  " + D(t("nothing selected, bye", "未选择任何类别，退出")))
            return
    total = sum(len(d) for _, d in chosen)
    if not total:
        print("  " + D(t("selected categories are empty, bye", "所选类别暂无文档")))
        return

    if not (auto or dry):
        if not _confirm(f"{B(t('confirm', '确认'))} "
                        f"{Y(t(f'download {total} documents to {out} ?', f'下载 {total} 个文档到 {out} ?'))} "
                        f"{D('[y/N]')}: "):
            print("  " + D(t("cancelled", "已取消")))
            return
    print(B(t("Download", "下载")) + D(f"  {total} docs -> {out}" + ("  (dry-run)" if dry else "")))

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
        if not dry: cdir.mkdir(parents=True, exist_ok=True)
        for e in docs:
            n += 1
            rel = f"{cdir.name}/{doc_filename(e)}"
            m = manifest.get(str(e["id"]))
            done_file = (cdir / doc_filename(e)).exists() or (
                m and (out / m.get("file", "missing")).exists())
            if not force and m and done_file:
                skip += 1
                if m.get("categories") and c["name"] not in m["categories"]:
                    m["categories"].append(c["name"])
                continue
            if dry:
                print(f"  {Cy(t('would download', '将下载'))}  {rel}  {D(e.get('filePath') or e.get('externalUrl') or '')}")
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
                print(f"  {R(t('✗ no url', '✗ 无下载链接'))}  {e['caption']}  {D(f'[{e["id"]}]')}")
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
    print(f"\n  {G('✓')} {t('done', '完成')}  {t('downloaded', '已下载')} {ok}  "
          f"{t('skipped', '已跳过')} {skip}  {t('failed', '失败')} {fail}"
          + (f"  links {ext}" if ext else "") + D(f"  in {dt:.0f}s"))
    if dry: print(D(t("  re-run without --dry-run to actually download",
                      "  去掉 --dry-run 重新运行即可实际下载")))

def _mrec(e, c, relpath, kind="file"):
    return {"caption": e["caption"].strip(), "description": (e.get("description") or "").strip(),
            "categories": [c["name"]], "url": e.get("filePath") or e.get("externalUrl"),
            "file": str(relpath), "kind": kind,
            "downloadedAt": datetime.datetime.now().isoformat(timespec="seconds")}

def _download(url, path):
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": CFG["userAgent"]})
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                f.write(r.read())
            return True
        except Exception as e:
            if attempt == 3:
                print(f"  {R(t('✗ failed', '✗ 失败'))}  {path.name}  {D(str(e)[:120])}")
                if path.exists(): path.unlink()
                return False
            time.sleep(1.5 * attempt)

def _opt(args, flag, default=None):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args) and not args[i + 1].startswith("-"): return args[i + 1]
        return default if default is not None else True
    return default

HELP_EN = """ASR · asr-export — bulk document downloader for Avenue South Residence (Habitap)
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

Language: English by default; set ASR_EXPORT_LANG=zh for Chinese.

Files land in <dir>/<category>/<caption>.<ext>. A per-directory manifest.json
(stored under ~/.asr/manifests/, not in the output folder) records every
download — saved after each file, so Ctrl+C + re-run resumes. Downloads are
paced (~0.4s apart).
"""

HELP_ZH = """ASR · asr-export — Avenue South Residence (Habitap) 文档批量下载
登录会话存于 ~/.asr（约 1 年有效）。

用法:
  asr-export login [-u <邮箱>] [-o <otp>] [--force]
        登录（已登录则跳过；首次/新设备需邮箱 OTP，仅一次）
  asr-export list [--cat <关键词|id>] [--all]
        按类别查看文档（大类别默认只预览前 10 条）
  asr-export download [选项]
        交互式选择类别 → 确认 → 批量下载

选项:
  -o <目录>       输出目录 (默认: 脚本旁的 asr-export/；安装后的命令默认 ~/Documents/asr-export)
  --cat <词|id>   只处理名称含关键词或 id 匹配的类别 (如 --cat Circulars)
  --yes, -y       跳过选择/确认直接下载 (--cat 过滤后的全部) — 脚本用
  --dry-run       只列出将要下载的内容，不实际下载
  --force         重新下载已存在的文件 (默认跳过/断点续传)
  -h, --help      本帮助

语言: 默认英文；设 ASR_EXPORT_LANG=zh 切换中文。

文件保存在 <目录>/<类别>/<文件名>.<扩展名>。每个输出目录一份 manifest.json
（存于 ~/.asr/manifests/，不在输出文件夹里）记录每次下载 — 每个文件下载后
立即保存，Ctrl+C 中断后重跑可续传。下载有 ~0.4s 间隔限速。
"""

def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    rest = args[1:]
    try:
        if cmd in ("-h", "--help", "help"): print(HELP_ZH if LANG == "zh" else HELP_EN)
        elif cmd == "login": cmd_login(rest)
        elif cmd == "list": cmd_list(rest)
        elif cmd == "download": cmd_download(rest)
        else: die(t(f"unknown command '{cmd}' — asr-export help",
                    f"未知命令 '{cmd}' — asr-export help"))
    except KeyboardInterrupt:
        print("\n" + D(t("interrupted — re-run to resume", "已中断 — 重新运行可续传")))
        sys.exit(130)

if __name__ == "__main__":
    main()
