# asr-export

Bulk document exporter for **Avenue South Residence** (the Habitap app).

## Background

ASR is migrating from Habitap to iCondo. iCondo cannot serve per-unit documents (unit layouts, appliance manuals, warranties, …), so residents are asked to back up their Habitap documents manually. With 300+ documents per account, downloading them one by one from a phone is not practical.

`asr-export` automates that: it logs in with your own account, lists every document visible to you (which is block/unit-specific, exactly like in the app), and bulk-downloads them into category folders — with confirmation before anything is written, resume support, and polite request pacing.

## Credentials & privacy

Everything runs **locally** on your machine:

- Your email and password are used only to log in to Habitap over HTTPS, and are **never sent to any other server** — the tool talks to nothing except Habitap's own API and file CDN.
- The password is **never written to disk** — it lives in memory only during login. Only the resulting session cookie is stored, in `~/.asr/` with `0600` permissions (valid ~1 year, so you log in once).
- Files are downloaded straight from Habitap's CDN to the folder you choose.

## Install

Requires Python 3. Then either:

```bash
curl -fsSL https://sfdye.github.io/asr-export/install.sh | bash
```

or, from a checkout: `bash install.sh`, or just run it in place: `python3 asr-export.py <command>`.

## Usage

```bash
asr-export login                 # log in (new devices: one-time email OTP)
asr-export list                  # browse documents by category (large categories previewed)
asr-export list --cat Circulars --all
asr-export download              # pick categories -> confirm -> download
asr-export download --cat Circulars
asr-export download --dry-run    # show what would be downloaded
```

- Output: `<dir>/<category>/<caption>.pdf` (default dir: `asr-export/` next to the script; the installed command defaults to `~/Documents/asr-export`; override with `-o`).
- Resume: re-running skips already-downloaded files (tracked via a per-directory manifest under `~/.asr/manifests/`). `--force` re-downloads.
- Interrupt any time with Ctrl+C — progress is saved after every file.

## Acknowledgements

The login flow and API patterns are inspired by the community project at [asrlife.vip](https://asrlife.vip), which reverse-engineered the Habitap resident API for facility booking.

## Notes

- The document set you see is exactly what your account sees in the app (filtered by your block) — different units get different documents.
- Downloads are paced (~0.4s apart). Please don't parallelize or hammer the server; download only what your own account can access, for personal archival.

## FAQ

- **`SSL: CERTIFICATE_VERIFY_FAILED` (CA cert does not include key usage extension)** — Python 3.13+ enables stricter certificate checking that rejects Habitap's CA chain. The script handles this internally (the chain is still fully verified).
- **Already logged in?** `asr-export login` detects a working session and exits immediately; use `--force` to re-login or switch accounts.
