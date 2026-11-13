"""核心逻辑测试：全部在临时目录里跑，不碰真实游戏。

运行：python -m unittest discover -s tests -v
"""

import http.client
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

# 必须在导入 uemm 之前指定隔离的配置目录
_TMP_HOME = tempfile.mkdtemp(prefix="uemm_test_home_")
os.environ["UEMM_HOME"] = _TMP_HOME

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uemm import detect, doctor, entry, i18n, mods, store  # noqa: E402

PAK_MAGIC = b"\xe1\x12\x6f\x5a"


def fake_pak(version=8):
    """造一个尾部带合法 FPakInfo 的 pak（版本 + magic）。"""
    return b"\x00" * 64 + PAK_MAGIC + version.to_bytes(4, "little", signed=True) + b"\x00" * 32


def make_game(root: Path, project="TestProj", iostore=False, anti_cheat=False,
              plugins_mods=False, modio=False):
    root.mkdir(parents=True, exist_ok=True)
    (root / "Engine" / "Binaries" / "Win64").mkdir(parents=True, exist_ok=True)
    paks = root / project / "Content" / "Paks"
    paks.mkdir(parents=True, exist_ok=True)
    (paks / "pakchunk0-Windows.pak").write_bytes(fake_pak())
    if iostore:
        (paks / "pakchunk0-Windows.utoc").write_bytes(b"\x00" * 32)
        (paks / "pakchunk0-Windows.ucas").write_bytes(b"\x00" * 32)
    if modio:
        (paks / "mod.io").mkdir()
    bins = root / project / "Binaries" / "Win64"
    bins.mkdir(parents=True, exist_ok=True)
    (bins / f"{project}-Win64-Shipping.exe").write_bytes(b"")
    if anti_cheat:
        (root / "EasyAntiCheat").mkdir()
        (root / "start_protected_game.exe").write_bytes(b"")
    if plugins_mods:
        (root / project / "Plugins" / "Mods").mkdir(parents=True)
    return root


class TestEngineDetect(unittest.TestCase):
    def _mk(self, name, subdirs=(), files=()):
        root = Path(tempfile.mkdtemp(prefix="eng_")) / name
        root.mkdir(parents=True)
        for d in subdirs:
            (root / d).mkdir(parents=True, exist_ok=True)
        for f in files:
            (root / f).write_bytes(b"")
        return root

    def test_ue(self):
        root = self._mk("UE game", ["Engine/Binaries/Win64", "Proj/Content/Paks"])
        self.assertEqual(detect.detect_engine(root)["engine"], "ue")

    def test_redengine(self):
        root = self._mk("CP", ["archive/pc/content", "bin/x64"])
        self.assertEqual(detect.detect_engine(root)["engine"], "redengine")

    def test_redengine_by_launcher(self):
        root = self._mk("CP2", ["bin/x64"], ["REDprelauncher.exe"])
        self.assertEqual(detect.detect_engine(root)["engine"], "redengine")

    def test_unity(self):
        root = self._mk("U", ["Game_Data"], ["UnityPlayer.dll"])
        self.assertEqual(detect.detect_engine(root)["engine"], "unity")

    def test_source2(self):
        root = self._mk("CS", ["game/bin/win64"])
        self.assertEqual(detect.detect_engine(root)["engine"], "source2")

    def test_creation(self):
        root = self._mk("Skyrim", ["Data"], ["Data/Skyrim.esm"])
        self.assertEqual(detect.detect_engine(root)["engine"], "creation")

    def test_tool_folder_is_unknown(self):
        root = self._mk("Blender", ["3.6"], ["blender.exe"])
        self.assertEqual(detect.detect_engine(root)["engine"], "unknown")

    def test_not_a_game(self):
        root = self._mk("Shared", ["stuff"])
        self.assertIsNone(detect.detect_engine(root))

    def test_scan_unsupported_skips_ue_and_unknown(self):
        base = Path(tempfile.mkdtemp(prefix="lib_"))
        (base / "UEgame" / "Engine").mkdir(parents=True)
        (base / "UEgame" / "P" / "Content" / "Paks").mkdir(parents=True)
        (base / "CP" / "archive" / "pc" / "content").mkdir(parents=True)
        (base / "Tool").mkdir()
        (base / "Tool" / "x.exe").write_bytes(b"")
        (base / "Steamworks Shared").mkdir()

        got = detect.scan_unsupported([base])
        self.assertEqual([g["name"] for g in got], ["CP"])
        self.assertEqual(got[0]["engine_label"], "REDengine")


class TestDialogs(unittest.TestCase):
    def test_disabled_by_env(self):
        from uemm import dialogs
        old = os.environ.get("UEMM_NO_DIALOG")
        os.environ["UEMM_NO_DIALOG"] = "1"
        try:
            self.assertFalse(dialogs.available())
            self.assertIsNone(dialogs.pick_folder())
        finally:
            if old is None:
                os.environ.pop("UEMM_NO_DIALOG", None)
            else:
                os.environ["UEMM_NO_DIALOG"] = old


class TestI18n(unittest.TestCase):
    def test_all_langs_have_same_keys(self):
        base = set(i18n.T["zh-CN"])
        for lang, table in i18n.T.items():
            missing = base - set(table)
            self.assertFalse(missing, f"{lang} 缺少键：{sorted(missing)[:8]}")

    def test_pick(self):
        self.assertEqual(i18n.pick("zh-CN,zh;q=0.9"), "zh-CN")
        self.assertEqual(i18n.pick("ja-JP,ja;q=0.9"), "ja")
        self.assertEqual(i18n.pick("de-DE,de;q=0.9"), "en", "不支持的语言应回落英文")
        self.assertEqual(i18n.pick(""), i18n.DEFAULT_LANG)

    def test_render_has_no_placeholder(self):
        from uemm import web
        for lang in i18n.T:
            html = web.render(lang)
            self.assertNotIn("__I18N__", html)
            self.assertNotIn("__LANGS__", html)
            self.assertNotIn("__LANG__", html)


class TestVortexArchives(unittest.TestCase):
    """Vortex 下载目录的扫描（探测在 detect，格式化在 server 那层）。"""

    def setUp(self):
        from uemm import server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_dl_"))
        self.old = detect.VORTEX_DOWNLOADS
        detect.VORTEX_DOWNLOADS = self.tmp

    def tearDown(self):
        detect.VORTEX_DOWNLOADS = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lists_only_supported_and_newest_first(self):
        import time
        old = self.tmp / "old.zip"
        old.write_bytes(b"x" * 10)
        time.sleep(0.01)
        new = self.tmp / "new.pak"
        new.write_bytes(b"x" * 20)
        (self.tmp / "ignore.7z").write_bytes(b"x")
        (self.tmp / "note.txt").write_text("hi", encoding="utf-8")

        sub = self.tmp / "readyornot"
        sub.mkdir()
        nested = sub / "nested.zip"
        nested.write_bytes(b"x" * 30)

        items = self.server.vortex_archives()
        self.assertEqual([i["name"] for i in items], ["nested.zip", "new.pak", "old.zip"])
        self.assertEqual(items[0]["size"], "30 B", "server 负责把字节数变成可读大小")

    def test_missing_folder(self):
        detect.VORTEX_DOWNLOADS = self.tmp / "nope"
        self.assertEqual(self.server.vortex_archives(), [])


class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_detect_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_ue_game(self):
        root = make_game(self.tmp / "My Game", project="MyProj")
        info = detect.detect_ue(root)
        self.assertIsNotNone(info)
        self.assertEqual(info["project"], "MyProj")
        self.assertTrue(info["mods"].endswith("~mods"))
        self.assertTrue(info["exe"].endswith("-Win64-Shipping.exe"))

    def test_rejects_non_ue(self):
        plain = self.tmp / "NotAGame"
        plain.mkdir()
        self.assertIsNone(detect.detect_ue(plain))

    def test_rejects_engine_without_paks(self):
        only_engine = self.tmp / "HalfGame"
        (only_engine / "Engine").mkdir(parents=True)
        self.assertIsNone(detect.detect_ue(only_engine))

    def test_iostore_flag(self):
        plain = make_game(self.tmp / "A", iostore=False)
        io = make_game(self.tmp / "B", iostore=True)
        self.assertFalse(detect.game_uses_iostore(plain / "TestProj" / "Content" / "Paks"))
        self.assertTrue(detect.game_uses_iostore(io / "TestProj" / "Content" / "Paks"))

    def test_iostore_missing_dir_is_false(self):
        self.assertFalse(detect.game_uses_iostore(self.tmp / "nope"))

    def test_support_levels(self):
        plain = make_game(self.tmp / "Plain")
        io = make_game(self.tmp / "Io", iostore=True)
        ac = make_game(self.tmp / "Ac", anti_cheat=True)
        plug = make_game(self.tmp / "Plug", plugins_mods=True)

        self.assertEqual(detect.probe_capabilities(detect.detect_ue(plain))["level"], "ok")
        self.assertEqual(detect.probe_capabilities(detect.detect_ue(io))["level"], "limited")
        self.assertEqual(detect.probe_capabilities(detect.detect_ue(ac))["level"], "limited")
        self.assertEqual(detect.probe_capabilities(detect.detect_ue(plug))["level"], "unsupported")

    def test_missing_paks_key_does_not_scan_cwd(self):
        info = {"path": str(self.tmp), "project": "TestProj"}
        cap = detect.probe_capabilities(info)
        self.assertIn(cap["level"], ("ok", "limited", "unsupported"))


class TestEpic(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_epic_"))
        self.man = self.tmp / "Manifests"
        self.man.mkdir()
        self.game = make_game(self.tmp / "EpicGame")
        old = detect.EPIC_MANIFEST_DIRS
        self.addCleanup(lambda: setattr(detect, "EPIC_MANIFEST_DIRS", old))
        detect.EPIC_MANIFEST_DIRS = [self.man]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_install_location(self):
        (self.man / "a.item").write_text(json.dumps({
            "DisplayName": "Epic Game",
            "InstallLocation": str(self.game),
        }), encoding="utf-8")
        dirs = detect.epic_install_dirs()
        self.assertEqual(len(dirs), 1)
        self.assertEqual(Path(dirs[0]["path"]), self.game)

    def test_skips_missing_install_location(self):
        (self.man / "b.item").write_text(json.dumps({"DisplayName": "Gone",
                                                     "InstallLocation": ""}), encoding="utf-8")
        (self.man / "c.item").write_text("{ broken json", encoding="utf-8")
        self.assertEqual(detect.epic_install_dirs(), [])


class TestVortexStaging(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_vortex_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_marker_folder(self):
        staging = self.tmp / "readyornot"
        mod = staging / "SomeMod"
        mod.mkdir(parents=True)
        (mod / "x.pak").write_bytes(fake_pak())
        (staging / detect.STAGING_MARKER).write_text("x", encoding="utf-8")
        self.assertTrue(detect.looks_like_staging(staging))

    def test_rejects_profiles_like_folder(self):
        fake = self.tmp / "readyornot"
        (fake / "profiles").mkdir(parents=True)
        (fake / "profiles" / "p.xml").write_text("<x/>", encoding="utf-8")
        (fake / "snapshots").mkdir()
        self.assertFalse(detect.looks_like_staging(fake))


class TestPakAndAnalyze(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_pak_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_and_invalid_pak(self):
        good = self.tmp / "good.pak"
        good.write_bytes(fake_pak())
        bad = self.tmp / "bad.pak"
        bad.write_bytes(b"not a pak" * 50)
        tiny = self.tmp / "tiny.pak"
        tiny.write_bytes(b"\x00")
        self.assertTrue(mods.pak_info(good)["valid"])
        self.assertFalse(mods.pak_info(bad)["valid"])
        self.assertFalse(mods.pak_info(tiny)["valid"])

    def test_analyze_verdicts(self):
        ok_dir = self.tmp / "ok"
        ok_dir.mkdir()
        (ok_dir / "a.pak").write_bytes(fake_pak())
        self.assertEqual(mods.analyze_mod(ok_dir, False)["verdict"], "ok")
        self.assertEqual(mods.analyze_mod(ok_dir, True)["note_key"], "iostore")

        with_container = self.tmp / "c"
        with_container.mkdir()
        (with_container / "a.pak").write_bytes(fake_pak())
        (with_container / "a.utoc").write_bytes(b"\x00" * 8)
        self.assertEqual(mods.analyze_mod(with_container, True)["verdict"], "ok")

        empty = self.tmp / "empty"
        empty.mkdir()
        (empty / "readme.txt").write_text("hi", encoding="utf-8")
        self.assertEqual(mods.analyze_mod(empty, False)["note_key"], "no_pak")


class TestDeploy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_deploy_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        self.info = detect.detect_ue(self.root)
        self.key = store.add_game(self.info)
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        self.game["staging"] = str(self.tmp / "staging")
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        Path(self.game["staging"]).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _add_mod(self, name, pak_name="pakchunk99-Test_P.pak"):
        d = Path(self.game["staging"]) / name
        d.mkdir(parents=True, exist_ok=True)
        (d / pak_name).write_bytes(fake_pak())
        return d

    def test_deploy_creates_hardlink(self):
        self._add_mod("ModA")
        res = mods.deploy_mod(self.game, "ModA")
        self.assertTrue(res["ok"], res)
        target = mods.mods_target(self.game) / "ModA" / "pakchunk99-Test_P.pak"
        self.assertTrue(target.is_file())
        src = Path(self.game["staging"]) / "ModA" / "pakchunk99-Test_P.pak"
        same_inode = target.stat().st_ino == src.stat().st_ino
        self.assertTrue(same_inode, "应该是硬链接而不是复制")

    def test_toggle_off_removes_dir_keeps_source(self):
        self._add_mod("ModB")
        mods.deploy_mod(self.game, "ModB")
        mods.undeploy_mod(self.game, "ModB")
        self.assertFalse((mods.mods_target(self.game) / "ModB").exists())
        self.assertTrue((Path(self.game["staging"]) / "ModB" / "pakchunk99-Test_P.pak").is_file())

    def test_deploy_cleans_stale_files(self):
        mod_dir = self._add_mod("ModC")
        mods.deploy_mod(self.game, "ModC")
        (mod_dir / "pakchunk99-Test_P.pak").rename(mod_dir / "pakchunk98-New_P.pak")
        mods.deploy_mod(self.game, "ModC")
        deployed = list((mods.mods_target(self.game) / "ModC").iterdir())
        names = [p.name for p in deployed]
        self.assertEqual(names, ["pakchunk98-New_P.pak"], f"旧链接没清掉：{names}")

    def test_deploy_all_removes_orphans(self):
        self._add_mod("ModD")
        mods.deploy_mod(self.game, "ModD")
        shutil.rmtree(Path(self.game["staging"]) / "ModD")
        res = mods.deploy_all(self.game)
        self.assertEqual(res["stats"]["orphans"], 1)
        self.assertFalse((mods.mods_target(self.game) / "ModD").exists())

    def test_rejects_path_traversal(self):
        for bad in ("..", ".", "../outside", "a/b", "a\\b"):
            self.assertFalse(mods.valid_mod_id(bad), bad)
            res = mods.deploy_mod(self.game, bad)
            self.assertFalse(res["ok"], f"{bad} 竟然通过了")

    def test_conflict_detection(self):
        self._add_mod("M1", "pakchunk99-A_P.pak")
        self._add_mod("M2", "pakchunk99-B_P.pak")
        mods_list = mods.list_mods(self.game)
        flagged = {m["id"] for m in mods_list if m["conflicts"]}
        self.assertEqual(flagged, {"M1", "M2"})
        kind = mods_list[0]["conflicts"][0]
        self.assertEqual(kind["kind"], "same_chunk")
        self.assertEqual(kind["n"], 99)

    def test_load_order_sorted(self):
        self._add_mod("M1", "pakchunk10-A_P.pak")
        self._add_mod("M2", "pakchunk99-B_P.pak")
        order = mods.load_order(self.game)
        self.assertEqual([o["pak"] for o in order],
                         ["pakchunk10-A_P.pak", "pakchunk99-B_P.pak"])


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_install_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        self.key = store.add_game(detect.detect_ue(self.root))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _zip(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
        return buf.getvalue()

    def test_zip_hoists_pak_to_root(self):
        raw = self._zip({
            "MyMod/Content/Paks/pakchunk101-MyMod_P.pak": fake_pak(),
            "MyMod/readme.txt": "hi",
        })
        res = mods.install_archive(self.game, raw, "MyMod.zip")
        self.assertTrue(res["ok"], res)
        mod_dir = Path(self.game["staging"]) / res["id"]
        self.assertTrue((mod_dir / "pakchunk101-MyMod_P.pak").is_file())
        self.assertTrue((mod_dir / "readme.txt").is_file())
        self.assertTrue((mods.mods_target(self.game) / res["id"]).is_dir(), "装完应当自动部署")

    def test_duplicate_pak_names_not_overwritten(self):
        raw = self._zip({
            "a/same.pak": fake_pak(),
            "b/same.pak": fake_pak(9),
        })
        res = mods.install_archive(self.game, raw, "Dup.zip")
        mod_dir = Path(self.game["staging"]) / res["id"]
        found = list(mod_dir.rglob("same.pak"))
        self.assertEqual(len(found), 2, "同名 pak 被覆盖了")

    def test_rejects_7z(self):
        res = mods.install_archive(self.game, b"x" * 100, "bad.7z")
        self.assertFalse(res["ok"])
        self.assertIn("7z", res["error"])

    def test_rejects_zip_slip(self):
        raw = self._zip({"../../evil.txt": "x"})
        res = mods.install_archive(self.game, raw, "evil.zip")
        self.assertFalse(res["ok"])
        self.assertFalse((self.tmp / "evil.txt").exists())


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_store_"))
        store.CONFIG_PATH = self.tmp / "config.json"
        store.STATE_PATH = self.tmp / "state.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_add_update_remove(self):
        root = make_game(self.tmp / "G")
        info = detect.detect_ue(root)
        key = store.add_game(info)
        self.assertIn(key, store.config()["games"])
        self.assertTrue(store.update_game(key, staging=str(self.tmp / "s")))
        self.assertEqual(store.get_game(key)["staging"], str(self.tmp / "s"))
        store.remove_game(key)
        self.assertIsNone(store.get_game(key))

    def test_enabled_state(self):
        store.set_enabled("k", "mod", False)
        self.assertFalse(store.enabled_map("k")["mod"])
        store.set_enabled("k", "mod", True)
        self.assertTrue(store.enabled_map("k")["mod"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doc_"))
        self.root = self.tmp / "Game"
        make_game(self.root)
        info = detect.detect_ue(self.root)
        key = store.add_game(info)
        store.update_game(key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(key)
        self.game["key"] = key
        self.staging = Path(self.game["staging"])
        self.target = mods.mods_target(self.game)
        self.staging.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mod(self, name, files):
        d = self.staging / name
        for rel, data in files.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return d

    def _kinds(self):
        return [i["kind"] for i in doctor.diagnose(self.game)["issues"]]

    def test_clean(self):
        self._mod("Good", {"a.pak": fake_pak()})
        mods.deploy_all(self.game)
        self.assertEqual(self._kinds(), [])

    def test_not_ue_detected_and_disabled(self):
        self._mod("VortexExt", {"index.js": b"x", "info.json": b"{}"})
        mods.deploy_all(self.game)
        self.assertIn("not_ue", self._kinds())

        rep = doctor.diagnose(self.game)
        issue = [i for i in rep["issues"] if i["kind"] == "not_ue"][0]
        res = doctor.apply_fix(self.game, issue["fix"])
        self.assertTrue(res["ok"])
        self.assertFalse((self.target / "VortexExt").exists())

    def test_nested_pak_hoisted(self):
        self._mod("Nest", {"Content/Paks/x.pak": fake_pak()})
        mods.deploy_all(self.game)
        self.assertIn("nested", self._kinds())
        self.assertTrue((self.target / "Nest" / "Content" / "Paks" / "x.pak").exists())

        rep = doctor.diagnose(self.game)
        issue = [i for i in rep["issues"] if i["kind"] == "nested"][0]
        doctor.apply_fix(self.game, issue["fix"])

        self.assertTrue((self.target / "Nest" / "x.pak").exists())
        self.assertFalse((self.target / "Nest" / "Content").exists())
        self.assertNotIn("nested", self._kinds())

    def test_chunk_conflict_renumbered(self):
        self._mod("ModA", {"pakchunk99-a.pak": fake_pak()})
        self._mod("ModB", {"pakchunk99-b.pak": fake_pak()})
        mods.deploy_all(self.game)

        rep = doctor.diagnose(self.game)
        issue = [i for i in rep["issues"] if i["kind"] == "chunk"][0]
        self.assertEqual(issue["params"]["n"], 99)
        doctor.apply_fix(self.game, issue["fix"])

        names = []
        for mid in ("ModA", "ModB"):
            for f in (self.target / mid).iterdir():
                names.append(f.name)
        chunks = {mods.chunk_of(n) for n in names}
        self.assertEqual(len(chunks), 2, f"改名后仍撞车：{names}")

    def test_orphan_cleaned(self):
        self._mod("Gone", {"a.pak": fake_pak()})
        mods.deploy_all(self.game)
        shutil.rmtree(self.staging / "Gone")

        rep = doctor.diagnose(self.game)
        issue = [i for i in rep["issues"] if i["kind"] == "orphan"][0]
        self.assertEqual(issue["params"]["n"], 1)
        doctor.apply_fix(self.game, issue["fix"])
        self.assertFalse((self.target / "Gone").exists())

    def test_copy_detected_and_relinked(self):
        self._mod("Copied", {"a.pak": fake_pak()})
        mods.deploy_all(self.game)
        src = self.staging / "Copied" / "a.pak"
        dst = self.target / "Copied" / "a.pak"
        dst.unlink()
        shutil.copy2(src, dst)
        self.assertFalse(mods.same_file(src, dst))

        rep = doctor.diagnose(self.game)
        issue = [i for i in rep["issues"] if i["kind"] == "copy"][0]
        doctor.apply_fix(self.game, issue["fix"])
        self.assertTrue(mods.same_file(src, dst))

    def test_running_blocks_fix(self):
        self._mod("Bad", {"readme.txt": b"x"})
        mods.deploy_all(self.game)
        orig = mods.running
        mods.running = lambda exe: True
        try:
            res = doctor.apply_fix(self.game, {"kind": "disable", "ids": ["Bad"]})
        finally:
            mods.running = orig
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "game_running")


class TestEntry(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="entry_"))
        self.old = (os.environ.get("UEMM_DESKTOP"), os.environ.get("UEMM_STARTUP"))
        os.environ["UEMM_DESKTOP"] = str(self.tmp / "Desktop")
        os.environ["UEMM_STARTUP"] = str(self.tmp / "Startup")

    def tearDown(self):
        for k, v in zip(("UEMM_DESKTOP", "UEMM_STARTUP"), self.old):
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cmd(self, path):
        """把 sh.Run 那一行按 VBScript 规则解回真实命令行。"""
        line = [l for l in path.read_text(encoding="ascii").splitlines()
                if l.startswith("sh.Run ")][0]
        literal = line[len("sh.Run "):].rsplit(", 0, False", 1)[0]
        self.assertTrue(literal.startswith('"') and literal.endswith('"'), literal)
        inner = literal[1:-1]
        self.assertNotIn('"', inner.replace('""', ""), "有未转义的引号")
        return inner.replace('""', '"')

    def test_install_and_remove_desktop(self):
        self.assertFalse(entry.status()["desktop"])
        path = Path(entry.install_desktop())
        self.assertTrue(path.is_file())
        cmd = self._run_cmd(path)
        self.assertTrue(cmd.endswith("--open"), cmd)
        self.assertIn(".exe", cmd.lower())
        self.assertTrue(entry.status()["desktop"])

        entry.remove_desktop()
        self.assertFalse(entry.status()["desktop"])

    def test_autostart_has_no_browser(self):
        body = Path(entry.install_autostart()).read_text(encoding="ascii")
        self.assertNotIn("--open", body)
        self.assertFalse(self._run_cmd(Path(entry.startup_file())).endswith("--open"))
        self.assertTrue(entry.status()["autostart"])

    def test_paths_use_env_override(self):
        self.assertEqual(entry.desktop_file().parent, self.tmp / "Desktop")
        self.assertEqual(entry.startup_file().parent, self.tmp / "Startup")


class TestToggleRollback(unittest.TestCase):
    """开/关失败时必须把状态退回去，否则界面显示开着、磁盘上没有文件。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_rollback_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        self.key = store.add_game(detect.detect_ue(self.root))
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        Path(self.game["staging"]).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rollback_when_mod_missing(self):
        self.assertFalse(store.enabled_map(self.key).get("Ghost", False))
        res = mods.set_mod(self.game, "Ghost", True)      # 暂存目录里没有这个 mod
        self.assertFalse(res["ok"])
        self.assertTrue(res.get("rolled_back"))
        self.assertFalse(store.enabled_map(self.key).get("Ghost", False),
                         "部署失败后开关不能停在“开”")

    def test_failed_rollback_preserves_previous_true(self):
        d = Path(self.game["staging"]) / "Real"
        d.mkdir(parents=True)
        (d / "pakchunk99-A_P.pak").write_bytes(fake_pak())
        mods.set_mod(self.game, "Real", True)
        self.assertTrue(store.enabled_map(self.key)["Real"])

        shutil.rmtree(d)                                   # 暂存目录被用户删了
        res = mods.set_mod(self.game, "Real", True)        # 再点一次“开”会失败
        self.assertFalse(res["ok"])
        self.assertTrue(store.enabled_map(self.key)["Real"],
                        "回滚应保留操作前的“开”，而不是翻成“关”")


class TestManifestAtomic(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_manifest_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        self.key = store.add_game(detect.detect_ue(self.root))
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        Path(self.game["staging"]).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tmp_file_left_behind(self):
        d = Path(self.game["staging"]) / "M"
        d.mkdir(parents=True)
        (d / "pakchunk99-A_P.pak").write_bytes(fake_pak())
        mods.deploy_mod(self.game, "M")
        target = mods.mods_target(self.game)
        self.assertTrue((target / mods.MANIFEST).is_file())
        self.assertFalse((target / (mods.MANIFEST + ".tmp")).exists(),
                         "临时文件没被替换掉")
        data = json.loads((target / mods.MANIFEST).read_text(encoding="utf-8"))
        self.assertIn("M", data["mods"])


class TestRenumberAvoidsBaseGame(unittest.TestCase):
    """重编号不能撞上游戏自带的 pakchunk，否则会把原版资源顶掉。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_renumber_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        paks = self.root / "Proj" / "Content" / "Paks"
        (paks / "pakchunk100-Windows.pak").write_bytes(fake_pak())
        self.key = store.add_game(detect.detect_ue(self.root))
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        staging = Path(self.game["staging"])
        staging.mkdir(parents=True)
        for name, pak in (("A", "pakchunk99-A_P.pak"), ("B", "pakchunk99-B_P.pak")):
            (staging / name).mkdir(parents=True)
            (staging / name / pak).write_bytes(fake_pak())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_skips_chunk_used_by_game(self):
        used = doctor._used_chunks(self.game)
        self.assertIn(100, used, "游戏自带的 pakchunk100 应该算已占用")
        self.assertIn(0, used)

        report = doctor.diagnose(self.game)
        fix = next(i["fix"] for i in report["issues"] if i["kind"] == "chunk")
        doctor.apply_fix(self.game, fix)

        names = [rel for m in mods.list_mods(self.game, include_conflicts=False)
                 for rel in m["pak_names"]]
        chunks = {mods.chunk_of(n) for n in names if mods.chunk_of(n) is not None}
        self.assertNotIn(100, chunks, f"重编号撞上了游戏自带 pak：{names}")


class TestServerGuards(unittest.TestCase):
    """本地服务只接受本机界面的请求：Host / Origin / Content-Type 三道闸。"""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from uemm import server
        cls.server_mod = server
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _req(self, method, path, body=b"", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_host_guard(self):
        st, _ = self._req("GET", "/api/ping", headers={"Host": "evil.example"})
        self.assertEqual(st, 403)

    def test_origin_guard_on_post(self):
        good = f"127.0.0.1:{self.port}"
        body = b'{"key":"nope"}'
        st, _ = self._req("POST", "/api/state", body, {
            "Host": good, "Content-Type": "application/json",
            "Origin": "https://evil.example"})
        self.assertEqual(st, 403)

    def test_content_type_guard(self):
        good = f"127.0.0.1:{self.port}"
        st, _ = self._req("POST", "/api/state", b"{}", {
            "Host": good, "Content-Type": "text/plain"})
        self.assertEqual(st, 415, "text/plain 可以被跨站表单伪造，必须拒绝")

    def test_legit_request_passes(self):
        good = f"127.0.0.1:{self.port}"
        st, data = self._req("POST", "/api/state", b'{"key":"nope"}', {
            "Host": good, "Content-Type": "application/json",
            "Origin": f"http://{good}"})
        self.assertEqual(st, 200)
        self.assertIn("game_not_found", data.decode())

    def test_origin_allowed_helper(self):
        self.assertTrue(self.server_mod.origin_allowed("127.0.0.1:8780", None, 8780))
        self.assertTrue(self.server_mod.origin_allowed("localhost:8780", "http://localhost:8780", 8780))
        self.assertFalse(self.server_mod.origin_allowed("127.0.0.1:8780", "http://127.0.0.1:9999", 8780))
        self.assertFalse(self.server_mod.origin_allowed("0.0.0.0:8780", None, 8780))


class TestLauncherArgs(unittest.TestCase):
    """打包入口不能把参数写死，否则 UEMM.exe --port / --scan 全部失效。"""

    def _run_with(self, argv):
        import launcher
        from uemm import __main__ as entry_main
        captured = {}
        original_main, original_argv = entry_main.main, sys.argv
        entry_main.main = lambda args=None: captured.setdefault("args", args)
        try:
            sys.argv = argv
            launcher.main()
        finally:
            entry_main.main, sys.argv = original_main, original_argv
        return captured.get("args")

    def test_passes_arguments_through(self):
        self.assertEqual(self._run_with(["UEMM.exe", "--port", "8795"]),
                         ["--port", "8795"])

    def test_double_click_opens_browser(self):
        self.assertEqual(self._run_with(["UEMM.exe"]), ["--open"])


class TestPakOrdering(unittest.TestCase):
    """UE 的挂载规则：_P 优先；同组按完整路径字母序；chunk 号不参与排序。

    这些断言是照着引擎行为写的，用来防止再出现"改 chunk 号 = 改顺序"的错误假设。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_order_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        self.key = store.add_game(detect.detect_ue(self.root))
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        Path(self.game["staging"]).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mod(self, name, pak):
        d = Path(self.game["staging"]) / name
        d.mkdir(parents=True, exist_ok=True)
        (d / pak).write_bytes(fake_pak())
        return d

    def test_priority_numbers(self):
        self.assertEqual(mods.pak_priority("plain.pak"), 3)
        self.assertEqual(mods.pak_priority("thing_P.pak"), 103)
        self.assertEqual(mods.pak_priority("thing_2_P.pak"), 303)
        self.assertEqual(mods.pak_priority("pakchunk99-WindowsNoEditor_P.pak"), 103)
        self.assertFalse(mods.is_patch_pak("pakchunk99-x.pak"))
        self.assertTrue(mods.is_patch_pak("x_P.pak"))

    def test_patch_suffix_beats_later_name(self):
        self._mod("AMod", "pakchunk99-x.pak")
        self._mod("ZMod", "zzz-plain.pak")     # 字母序更靠后，但不是补丁包
        self._mod("BMod", "x_P.pak")           # 补丁包，优先级 103
        order = mods.load_order(self.game)
        self.assertEqual(order[-1]["mod"], "BMod", "带 _P 的必须最后挂载")
        self.assertTrue(order[-1]["patch"])
        self.assertTrue(order[-1]["winner"])

    def test_folder_name_decides_not_chunk_number(self):
        # Alpha 的 chunk 号更大，但目录名在字母序更前 → 先挂载，被 Zulu 覆盖
        self._mod("Alpha", "pakchunk999-a.pak")
        self._mod("Zulu", "pakchunk1-z.pak")
        order = mods.load_order(self.game)
        self.assertEqual([o["mod"] for o in order], ["Alpha", "Zulu"])
        self.assertEqual(order[-1]["mod"], "Zulu")

    def test_renumber_does_not_change_mount_order(self):
        """改 chunk 号只是为了避开重复索引，不能假设它会改顺序。"""
        self._mod("Alpha", "pakchunk99-a.pak")
        self._mod("Zulu", "pakchunk99-z.pak")
        before = [o["mod"] for o in mods.load_order(self.game)]

        report = doctor.diagnose(self.game)
        fix = next(i["fix"] for i in report["issues"] if i["kind"] == "chunk")
        doctor.apply_fix(self.game, fix)

        after = [o["mod"] for o in mods.load_order(self.game)]
        self.assertEqual(before, after, "重编号不应该改变挂载顺序")

    def test_chunk_collision_is_only_informational(self):
        self._mod("Alpha", "pakchunk99-a.pak")
        self._mod("Zulu", "pakchunk99-z.pak")
        report = doctor.diagnose(self.game)
        chunk = next(i for i in report["issues"] if i["kind"] == "chunk")
        self.assertEqual(chunk["severity"], "info", "同 chunk 号多数情况无害，不该报成警告")


class TestUnknownVersion(unittest.TestCase):
    """版本号读不准时宁可说"不知道"，也不能判成坏包让人把好 mod 撤了。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_ver_"))
        self.root = make_game(self.tmp / "Game", project="Proj")
        self.key = store.add_game(detect.detect_ue(self.root))
        store.update_game(self.key, staging=str(self.tmp / "staging"))
        self.game = store.get_game(self.key)
        self.game["key"] = self.key
        Path(self.game["staging"]).mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mod(self, name, payload):
        d = Path(self.game["staging"]) / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "thing.pak").write_bytes(payload)
        return d

    def test_future_version_is_unknown_not_broken(self):
        d = self._mod("Future", fake_pak(version=37))
        self.assertIsNone(mods.pak_info(d / "thing.pak")["valid"])
        verdict = mods.analyze_mod(d, iostore=False)
        self.assertEqual(verdict["verdict"], "warn")
        self.assertEqual(verdict["note_key"], "unknown_version")
        self.assertEqual(verdict["version"], 37)

    def test_unknown_version_has_no_destructive_fix(self):
        self._mod("Future", fake_pak(version=37))
        report = doctor.diagnose(self.game)
        issue = next((i for i in report["issues"] if i["kind"] == "unknown_version"), None)
        self.assertIsNotNone(issue, f"应该报出未知版本：{report['issues']}")
        self.assertFalse(issue["fixable"], "未知版本不能提供一键撤下")
        self.assertEqual(issue["severity"], "info")

    def test_broken_pak_still_fixable(self):
        self._mod("Broken", b"\x00" * 200)          # 尾部没有 pak 魔数
        report = doctor.diagnose(self.game)
        issue = next(i for i in report["issues"] if i["kind"] == "bad_pak")
        self.assertTrue(issue["fixable"], "彻底坏掉的包仍然可以一键撤下")
