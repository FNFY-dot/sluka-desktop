"""Settings → Sync & backup in the app, end to end: the real dashboard and worker of the Sluka extension, served by the
app's real host, with its folder window answered by a folder standing in for Google Drive's (folders.py, shim.js).
The folder is chosen once, Sluka writes its backup there and reads the phone's, and after the app is started again
the folder is still Sluka's to write to -- as in Chrome, which is what syncing through Google Drive needs.

Skipped where there is no Chrome and Playwright, or no Sluka extension whole (SLUKA_EXTENSION_FULL).
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from fakes import APP as _APP  # noqa: F401  (puts the app on the path)

EXTENSION = Path(os.environ.get("SLUKA_EXTENSION_FULL", "/home/claude/untrusted/sluka-ext-0.7.4-full/sluka-extension"))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")
playwright = pytest.importorskip("playwright.sync_api")
if not CHROME:
    pytest.skip("no Chrome here", allow_module_level=True)
if not (EXTENSION / "lib" / "backup.js").is_file():
    pytest.skip("no Sluka extension to try it with", allow_module_level=True)

from sluka_desktop.config import Config  # noqa: E402
from sluka_desktop.devserver import make_host  # noqa: E402
from sluka_desktop.httpd import Server  # noqa: E402


def shown(page, id_):
    return page.evaluate("""(id) => { let n = document.getElementById(id); if (!n) return false;
      for (; n; n = n.parentElement) if (n.hidden) return false; return true; }""", id_)


def until(check, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        got = check()
        if got:
            return got
        time.sleep(0.2)
    raise AssertionError("waited in vain")


def test_the_backup_folder_in_google_drive(tmp_path):
    drive = tmp_path / "G" / "My Drive" / "Sluka"
    drive.mkdir(parents=True)
    config = Config(extension=EXTENSION, data=tmp_path / "data")
    config.ensure_dirs()
    config.write_default_config()
    host = make_host(config, as_extension=True)
    host.boot_extra = {"shell": "test", "folders": True}
    asked = []
    host.folders.picker = lambda title, remember="": asked.append(remember) or str(drive)
    server = Server(host, 0)
    server.start()
    base = server.origin
    try:
        with playwright.sync_playwright() as p:
            chrome = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            ctx = chrome.new_context()
            errors = []

            def open_pages():
                bg = ctx.new_page()
                bg.on("pageerror", lambda e: errors.append(str(e)))
                bg.goto(f"{base}/__sluka__/background.html")
                page = ctx.new_page()
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{base}/dashboard/dashboard.html#settings/sync")
                page.wait_for_function("() => !document.getElementById('backupNoFolderPc').hidden || !document.getElementById('backupHasFolderPc').hidden", timeout=20000)
                return page

            page = open_pages()
            page.evaluate("""async () => { const s = await import('/lib/settings.js');
              await s.saveSettings({ ...(await s.loadSettings()), activeLanguages: ['ja'] }); }""")
            time.sleep(1)
            page = open_pages()
            # A folder to choose, as in Chrome -- not Firefox's Downloads, which no other device can see.
            assert page.evaluate("() => typeof showDirectoryPicker") == "function"
            until(lambda: shown(page, "backupNoFolderPc"))
            assert not shown(page, "backupFirefox") and not shown(page, "backupDownloads")
            page.evaluate("() => document.getElementById('backupPickPcBtn').click()")
            until(lambda: shown(page, "backupHasFolderPc"))
            assert asked == ["pharos-backup"]
            assert page.locator("#backupFolderPc").inner_text() == "Sluka"

            # The phone's backup comes through Drive, and is merged in from the steps.
            text = page.evaluate("""async () => { const b = await import('/lib/backup.js'); const { legacyKey } = await import('/lib/drawers.js');
              const env = b.buildBackup({ device: 'phone7x', [legacyKey('ja', 'words')]: { '猫': 2, '犬': 1 } }, ['ja'], { app: 'android' });
              env.device = 'phone7x'; return b.serializeBackup(env); }""")
            (drive / "sluka-phone7x.json").write_text(text, encoding="utf-8")
            page.evaluate("() => { document.getElementById('driveGuide').open = true; document.querySelector('#driveGuide .drive-look').click(); }")
            until(lambda: page.evaluate("() => !!document.querySelector('#driveGuide .drive-devices button')"))
            page.evaluate("() => document.querySelector('#driveGuide .drive-devices button').click()")
            until(lambda: "Restored 2 words" in page.evaluate("() => document.querySelector('#driveGuide .drive-result').textContent"))

            # This computer's backup, written into the same folder for the phone to read.
            page.evaluate("() => document.getElementById('backupNowTop').click()")
            def written():
                for p in drive.glob("sluka-*.json"):
                    if p.name != "sluka-phone7x.json" and p.stat().st_size:
                        return json.loads(p.read_text(encoding="utf-8"))
                return None
            env = until(written)
            assert set(env["langs"]["ja"]["words"]) == {"猫", "犬"}
            assert not list(drive.glob("*" + "sluka-part"))

            # The app started again (its web view's profile kept): the folder is still Sluka's, and written to.
            for old in list(ctx.pages):
                old.close()
            page = open_pages()
            until(lambda: shown(page, "backupHasFolderPc"))
            assert not shown(page, "backupReconnect")
            assert page.evaluate("""async () => { const b = await import('/lib/backup.js'); const h = await b.storedFolder();
              return [h.kind, h.name, await h.queryPermission({ mode: 'readwrite' })]; }""") == ["directory", "Sluka", "granted"]
            assert not errors, errors
            chrome.close()
    finally:
        server.shutdown()
        host.close()


def test_a_large_backup_restored(tmp_path):
    """A backup of many words, merged in by "Sync with this device" or Import: Sluka writes it in one storage call
    of more than httpd's 8 MB, which the host now reads whole (it answered unread before: "Failed to fetch")."""
    config = Config(extension=EXTENSION, data=tmp_path / "data")
    config.ensure_dirs()
    config.write_default_config()
    host = make_host(config, as_extension=True)
    server = Server(host, 0)
    server.start()
    try:
        with playwright.sync_playwright() as p:
            chrome = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = chrome.new_page()
            page.goto(f"{server.origin}/dashboard/dashboard.html")
            page.wait_for_function("() => globalThis.chrome?.storage?.local")
            got = page.evaluate("""async () => {
              const words = {};
              for (let i = 0; i < 900000; i++) words['語' + i] = 2;
              await chrome.storage.local.set({ 'test:big': words });
              const back = (await chrome.storage.local.get('test:big'))['test:big'];
              return [new TextEncoder().encode(JSON.stringify(words)).length, Object.keys(back).length];
            }""")
            assert got[0] > 8 * 1024 * 1024 and got[1] == 900000
            chrome.close()
    finally:
        server.shutdown()
        host.close()
