"""核心逻辑测试：全部在临时目录里跑，不碰真实游戏。

运行：python -m unittest discover -s tests -v
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

# 必须在导入 uemm 之前指定隔离的配置目录
_TMP_HOME = tempfile.mkdtemp(prefix="uemm_test_home_")
os.environ["UEMM_HOME"] = _TMP_HOME

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uemm import detect, i18n, mods, store  # noqa: E402

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
    def setUp(self):
        from uemm import server
        self.server = server
        self.tmp = Path(tempfile.mkdtemp(prefix="uemm_dl_"))
        self.old = server.VORTEX_DOWNLOADS
        server.VORTEX_DOWNLOADS = self.tmp

    def tearDown(self):
        self.server.VORTEX_DOWNLOADS = self.old
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

    def test_missing_folder(self):
        self.server.VORTEX_DOWNLOADS = self.tmp / "nope"
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
