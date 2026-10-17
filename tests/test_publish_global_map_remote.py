"""Publication mechanics against real reviewed bytes, with a simulated host.

These checks do not deploy, exercise the game renderer, or use player saves.
"""
import base64
import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import publish_global_map_remote as tool


class GlobalMapPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = tool.BASELINE.read_bytes()
        cls.source = (tool.BASELINE_CLIENT / "silver.dll").read_bytes()
        cls.ti = (tool.BASELINE_CLIENT / "ti.exe").read_bytes()
        cls.candidate = (tool.CANDIDATE / "silver.dll").read_bytes()
        cls.review_raw = (tool.REPORT_ROOT / "client/native-review.json").read_bytes()
        cls.review_document = json.loads(cls.review_raw)
        cls.review = tool.normalize_native_review(cls.review_document, cls.candidate)
        cls.images = {name: (tool.CANDIDATE / name).read_bytes() for name in tool.PINNED_ASSETS}
        files = [dict(path="silver.dll", source="silver.dll", sha256=tool.sha(cls.candidate),
                      size=len(cls.candidate), kind="native")]
        files += [dict(path=name, source=name, sha256=pin["sha256"], size=pin["size"],
                       kind="terrain_png" if name.endswith("/gm-v2-terrain.png") else "map_object_png")
                  for name, pin in sorted(tool.PINNED_ASSETS.items())]
        cls.package = dict(schema=1, previous_version=tool.PREVIOUS_VERSION, version=tool.VERSION,
            baseline_manifest_sha256=tool.MANIFEST_SHA,
            selection=dict(map="global-map-v2", pixel_edits=False,
                           layers="separate-native-PNGs", world_coordinates="preserved"),
            asset_manifest_sha256=tool.ASSET_MANIFEST_SHA, layout_sha256=tool.LAYOUT_SHA,
            source_catalog_sha256=tool.CATALOG_SHA,
            native_review_receipt_sha256=tool.sha(cls.review_raw), native_review=cls.review, files=files)
        cls.package_raw = (json.dumps(cls.package, indent=2) + "\n").encode()
        cls.new_obj = json.loads(cls.old)
        cls.new_obj["version"] = tool.VERSION
        next(r for r in cls.new_obj["files"] if r["path"] == "silver.dll").update(
            sha256=tool.sha(cls.candidate), size=len(cls.candidate))
        cls.new_obj["files"] += [dict(path=name, sha256=pin["sha256"], size=pin["size"], seed=False)
                                for name, pin in sorted(tool.PINNED_ASSETS.items())]
        cls.new = (json.dumps(cls.new_obj, ensure_ascii=False, indent=2) + "\n").encode()
        raws = {"silver.dll": cls.candidate, **cls.images}
        cls.updates = {item["path"]: dict(sha256=item["sha256"], size=item["size"], kind=item["kind"],
            blob=base64.b64encode(raws[item["path"]]).decode()) for item in files}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tio-map-publisher-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.live, self.private, self.game = (self.root / name for name in ("live", "private", "game"))
        for path in (self.live / "blobs", self.private, self.game):
            path.mkdir(parents=True)
        (self.live / "manifest.json").write_bytes(self.old)
        for raw in (self.source, self.ti):
            (self.live / "blobs" / tool.sha(raw)).write_bytes(raw)
        self.db = self.root / "reservation.sqlite3"
        with closing(sqlite3.connect(self.db)) as db:
            db.executescript("CREATE TABLE accounts(login TEXT,salt TEXT,digest TEXT,iterations INTEGER);"
                             "CREATE TABLE battle_checkpoints(id INTEGER);"
                             "CREATE TABLE battle_settlement_jobs(id INTEGER);")
            db.executemany("INSERT INTO accounts VALUES(?,?,?,?)",
                           [(f"account-{i}", "salt", "digest", 1) for i in range(202)])
            db.commit()
        patch.dict(sys.modules, fcntl=SimpleNamespace(LOCK_EX=1, LOCK_NB=2, flock=lambda *args: None)).start()
        patch.object(os, "O_NOFOLLOW", 0, create=True).start()
        patch.object(os, "fsync", lambda fd: None).start()
        self.addCleanup(patch.stopall)
        prior_mask = os.umask(0o077)
        os.umask(prior_mask)
        self.addCleanup(os.umask, prior_mask)
        self.scope = {}
        exec(compile(tool.REMOTE, "global-map-simulated-host", "exec"), self.scope)
        self.actual_guards = self.scope["guards"]
        self.guards = dict(services=dict(game=dict(MainPID="111", ActiveState="active"),
                                         api=dict(MainPID="222", ActiveState="active")),
                           configuration=dict(config="fixed"), launchers=dict(current_launcher="fixed"),
                           game_code=dict(code="fixed"))
        self.events = []
        self.scope.update(LIVE=self.live, PRIVATE=self.private, GAME=self.game, DB=self.db,
            guards=lambda: copy.deepcopy(self.guards), sync=lambda path: self.events.append("sync-" + path.name),
            state=self.state, private_json=self.private_json, atomic=self.atomic, immutable=self.immutable)
        self.payload = dict(action="apply", package_blob=base64.b64encode(self.package_raw).decode(),
            package_sha256=tool.sha(self.package_raw), updates=copy.deepcopy(self.updates),
            before_manifest=base64.b64encode(self.old).decode(), after_manifest=base64.b64encode(self.new).decode(),
            after_manifest_sha256=tool.sha(self.new), expected_guards=dict(state=copy.deepcopy(self.guards),
                inspected_utc=datetime.now(timezone.utc).isoformat(),
                account_credentials_sha256=self.scope["database"](self.db)[1]["account_credentials_sha256"]))

    def state(self, path):
        self.scope["regular"](path)
        raw = path.read_bytes()
        return dict(sha256=tool.sha(raw), size=len(raw), uid=0, gid=0, mode=0o644)

    def private_json(self, path, value):
        self.events.append(path.name)
        with path.open("x", encoding="utf-8") as out:
            json.dump(value, out)

    def atomic(self, raw, path, expected=None):
        if expected is not None and path.read_bytes() != expected:
            raise RuntimeError("Atomic publication target changed")
        pending = path.parent / "pending.json"
        pending.write_bytes(raw)
        os.replace(pending, path)
        self.events.append("manifest-new" if raw == self.new else "manifest-old")

    def immutable(self, raw, path):
        self.events.append("blob")
        if path.exists():
            if path.read_bytes() != raw:
                raise RuntimeError("Immutable blob differs")
        else:
            with path.open("xb") as out:
                out.write(raw)

    def publish(self, payload=None):
        return self.scope["execute"](self.payload if payload is None else payload)

    def test_exact_24_resources_preserve_all_6543_other_records_and_seed_flags(self):
        package = tool.package_identity(self.package_raw, tool.sha(self.package_raw))
        result = tool.blob_identity(package["files"][0], self.candidate, self.source, self.review)
        self.assertTrue(result["all_undeclared_native_bytes_preserved"])
        self.assertTrue(result["pe_structure"]["final_section_append_mapped"])
        self.assertEqual(result["appended_bytes"], 101888)
        self.assertEqual(result["auth_functions_preserved"], len(tool.AUTH_SPANS))
        for item in package["files"][1:]:
            self.assertTrue(tool.blob_identity(item, self.images[item["path"]])["original_bytes_preserved"])
        scope = tool.manifest_transition(self.old, self.new, package)
        self.assertEqual(scope["changed"], ["silver.dll"])
        self.assertEqual(len(scope["added"]), 23)
        self.assertEqual(scope["preserved_records"], 6543)
        self.assertEqual(scope["after_records"], 6567)
        for before, after in zip(json.loads(self.old)["files"], self.new_obj["files"]):
            if before["path"] != "silver.dll":
                self.assertEqual(before, after)

    def test_scope_rejects_xml_player_data_ti_unprefixed_names_and_duplicates(self):
        for name in ("ti.exe", "base/zones.xml", "base/config.cfg", "accounts.sqlite3",
                     "../silver.dll", "base/pda/global-map-v2/denver.png"):
            package = copy.deepcopy(self.package)
            package["files"][1].update(path=name, source=name)
            raw = json.dumps(package).encode()
            with self.subTest(name=name), self.assertRaises(ValueError):
                tool.package_identity(raw, tool.sha(raw))
        for mutate in (lambda p: p["files"].append(p["files"][0]),
                       lambda p: p.update(previous_version="2026.10.10.3"),
                       lambda p: p.update(layout_sha256="0" * 64),
                       lambda p: p["selection"].update(pixel_edits=True),
                       lambda p: p["files"][1].update(kind="map_object_png" if p["files"][1]["kind"] == "terrain_png" else "terrain_png")):
            package = copy.deepcopy(self.package)
            mutate(package)
            raw = json.dumps(package).encode()
            with self.assertRaises(ValueError):
                tool.package_identity(raw, tool.sha(raw))
        for field, value in (("sha256", "0" * 64), ("seed", True)):
            bad = copy.deepcopy(self.new_obj)
            next(r for r in bad["files"] if r["path"] == "ti.exe")[field] = value
            with self.assertRaises(ValueError):
                tool.manifest_transition(self.old, json.dumps(bad).encode(), self.package)

    def test_prepare_and_payload_require_exact_review_metadata_and_inspect_evidence(self):
        report_root = self.root / "reports"
        candidate = report_root / "client/candidate"
        baseline = report_root / "baseline/manifest.json"
        deployment = report_root / "deployment"
        for folder in (candidate, baseline.parent / "client", deployment):
            folder.mkdir(parents=True)
        baseline.write_bytes(self.old)
        (baseline.parent / "client/silver.dll").write_bytes(self.source)
        native = report_root / "client/reviewed.dll"
        native.write_bytes(self.candidate)
        review = report_root / "client/review.json"
        review.write_bytes(self.review_raw)
        for name, raw in self.images.items():
            destination = candidate / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        layout_raw = (tool.CANDIDATE / "base/pda/global-map-v2/layout.json").read_bytes()
        for name in ("manifest.json", "layout.json"):
            relative = Path("base/pda/global-map-v2") / name
            (candidate / relative).write_bytes((tool.CANDIDATE / relative).read_bytes())
        package_path = candidate / "package.json"
        with patch.multiple(tool, REPORT_ROOT=report_root, CANDIDATE=candidate, BASELINE=baseline, DEPLOYMENT=deployment):
            args = (native, tool.sha(self.candidate), len(self.candidate), review, tool.sha(self.review_raw), package_path)
            prepared = tool.prepare_package(*args)
            self.assertEqual(tool.prepare_package(*args), prepared)
            loaded, raws = tool.load_package(package_path, prepared["package_sha256"], baseline)
            self.assertEqual(len(raws), 24)
            self.assertEqual(loaded["native_review"], self.review)
            self.assertEqual(loaded["native_review_receipt_sha256"], tool.sha(self.review_raw))
            payload = tool.make_payload(package_path, prepared["package_sha256"], "inspect", baseline=baseline)
            self.assertEqual(json.loads(base64.b64decode(payload["after_manifest"])), self.new_obj)
            with self.assertRaisesRegex(ValueError, "inspect evidence"):
                tool.make_payload(package_path, prepared["package_sha256"], "apply", baseline=baseline)
            inspect = deployment / "inspect.json"
            evidence = self.publish(dict(payload, action="inspect"))
            inspect.write_text(json.dumps(evidence), encoding="utf-8")
            ready = tool.make_payload(package_path, prepared["package_sha256"], "apply", baseline=baseline, before_inspect=inspect)
            self.assertEqual(ready["expected_guards"]["state"], self.guards)
            evidence["package_sha256"] = "0" * 64
            inspect.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Inspect evidence differs"):
                tool.make_payload(package_path, prepared["package_sha256"], "apply", baseline=baseline, before_inspect=inspect)
            metadata = candidate / "base/pda/global-map-v2/layout.json"
            metadata.write_bytes(b"changed layout")
            with self.assertRaisesRegex(ValueError, "manifest/layout changed"):
                tool.load_package(package_path, prepared["package_sha256"], baseline)
            metadata.write_bytes(layout_raw)
            # A mismatched prior preparation cannot overwrite its native file.
            package_path.write_bytes(b"existing unrelated prepared package")
            (candidate / "silver.dll").write_bytes(b"prior candidate must survive")
            with self.assertRaisesRegex(ValueError, "Existing prepared package differs"):
                tool.prepare_package(*args)
            self.assertEqual((candidate / "silver.dll").read_bytes(), b"prior candidate must survive")

    def test_png_hash_alpha_format_and_crc_changes_are_refused(self):
        item = self.package["files"][1]
        raw = self.images[item["path"]]
        altered = bytearray(raw)
        altered[100] ^= 1
        with self.assertRaises(ValueError):
            tool.blob_identity(item, altered)
        with self.assertRaises(ValueError):
            tool.blob_identity(dict(item, sha256=tool.sha(altered)), altered)
        with self.assertRaises(ValueError):
            tool.png_identity(altered, tool.PINNED_ASSETS[item["path"]])
        pin = dict(tool.PINNED_ASSETS[item["path"]], mode="RGB" if raw[25] == 6 else "RGBA")
        with self.assertRaisesRegex(ValueError, "alpha format"):
            tool.png_identity(raw, pin)

    def test_native_review_and_undeclared_or_authentication_changes_are_refused(self):
        item = self.package["files"][0]
        for at in (2000, len(self.source) + 20):
            changed = bytearray(self.candidate)
            changed[at] ^= 1
            with self.assertRaises(ValueError):
                tool.blob_identity(dict(item, sha256=tool.sha(changed)), changed, self.source, self.review)
        malformed = copy.deepcopy(self.review)
        malformed["appended_size"] = 512
        with self.assertRaises(ValueError):
            tool.blob_identity(item, self.candidate, self.source, malformed)
        changed = bytearray(self.candidate)
        rva = tool.AUTH_SPANS[0][0] - 0x400000
        section = next(s for s in tool.pe_layout(self.source)["sections"] if s["rva"] <= rva < s["rva"] + s["raw_size"])
        at = section["offset"] + rva - section["rva"]
        changed[at] ^= 1
        forged = copy.deepcopy(self.review)
        forged["changes"].append(dict(offset=at, size=1, source_sha256=tool.sha(self.source[at:at+1]),
            candidate_sha256=tool.sha(changed[at:at+1]), purpose="attempted auth alteration"))
        forged["changes"].sort(key=lambda row: row["offset"])
        with self.assertRaisesRegex(ValueError, "authentication"):
            tool.blob_identity(dict(item, sha256=tool.sha(changed)), changed, self.source, forged)
        bad_receipt = dict(self.review_document, candidate_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "different source or candidate"):
            tool.normalize_native_review(bad_receipt, self.candidate)

    def test_inspect_is_read_only_and_credentials_drift_refuses_before_writes(self):
        payload = copy.deepcopy(self.payload)
        payload.update(action="inspect", expected_guards=None)
        result = self.publish(payload)
        self.assertEqual(result["remote_mutations"], 0)
        self.assertEqual(self.events, [])
        with closing(sqlite3.connect(self.db)) as db:
            db.execute("UPDATE accounts SET digest='changed' WHERE login='account-0'")
            db.commit()
        with self.assertRaisesRegex(RuntimeError, "credentials changed"):
            self.publish()
        self.assertEqual(self.events, [])
        self.assertEqual((self.live / "manifest.json").read_bytes(), self.old)

    def test_missing_stale_or_changed_inspect_guards_refuse_before_writes(self):
        for expected in (None, dict(self.payload["expected_guards"], state={}),
                         dict(self.payload["expected_guards"], inspected_utc=(datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat())):
            payload = dict(self.payload, expected_guards=expected)
            with self.assertRaises(RuntimeError):
                self.publish(payload)
            self.assertEqual(self.events, [])

    def test_online_backup_then_all_24_immutable_blobs_then_single_manifest_commit(self):
        database_bytes = self.db.read_bytes()
        result = self.publish()
        saved = Path(result["backup"])
        self.assertEqual((saved / "previous-manifest.json").read_bytes(), self.old)
        self.assertEqual((saved / "previous-blobs" / tool.SILVER_SHA).read_bytes(), self.source)
        with closing(sqlite3.connect(saved / "reservation.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM accounts").fetchone()[0], 202)
        for name in ("previous-code.tar.gz", "previous-config.tar.gz", "backup-manifest.json"):
            self.assertTrue((saved / name).is_file())
        self.assertLess(self.events.index("backup-manifest.json"), self.events.index("blob"))
        self.assertEqual(self.events.count("blob"), 24)
        self.assertLess(max(i for i, event in enumerate(self.events) if event == "blob"), self.events.index("manifest-new"))
        self.assertEqual(self.events.count("manifest-new"), 1)
        self.assertEqual(self.db.read_bytes(), database_bytes)
        self.assertEqual((self.live / "blobs" / tool.TI_SHA).read_bytes(), self.ti)
        self.assertTrue(result["account_identities_and_credentials_preserved"])
        for flag in ("server_restarted", "database_written", "local_player_data_uploaded"):
            self.assertFalse(result[flag])
        for flag in ("launcher_preserved", "code_and_config_preserved", "services_unchanged", "seed_records_preserved"):
            self.assertTrue(result[flag])

    def test_corrupt_prior_native_blob_and_stale_live_manifest_refuse_before_writes(self):
        (self.live / "blobs" / tool.SILVER_SHA).write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "prior reviewed"):
            self.publish()
        self.assertEqual(self.events, [])
        (self.live / "blobs" / tool.SILVER_SHA).write_bytes(self.source)
        (self.live / "manifest.json").write_bytes(self.new)
        with self.assertRaisesRegex(RuntimeError, "baseline changed"):
            self.publish()
        self.assertEqual(self.events, [])

    def test_postcommit_failure_rolls_back_only_manifest_and_preserves_database(self):
        before_db = self.db.read_bytes()
        original = self.scope["atomic"]
        def failure(raw, path, expected=None):
            original(raw, path, expected)
            if raw == self.new:
                self.guards["services"]["game"]["MainPID"] = "changed"
        self.scope["atomic"] = failure
        with self.assertRaises(RuntimeError):
            self.publish()
        self.assertEqual((self.live / "manifest.json").read_bytes(), self.old)
        self.assertEqual(self.db.read_bytes(), before_db)
        self.assertEqual(self.events.count("manifest-old"), 1)
        # Unreferenced immutable blobs are safe to keep; saves are not restored.
        self.assertTrue((self.live / "blobs" / tool.sha(self.candidate)).is_file())

    def test_concurrent_manifest_after_commit_is_never_overwritten_by_rollback(self):
        other = json.dumps(dict(self.new_obj, news="concurrent release")).encode()
        original = self.scope["atomic"]
        def concurrent(raw, path, expected=None):
            original(raw, path, expected)
            if raw == self.new:
                path.write_bytes(other)
        self.scope["atomic"] = concurrent
        with self.assertRaises(RuntimeError):
            self.publish()
        self.assertEqual((self.live / "manifest.json").read_bytes(), other)
        self.assertNotIn("manifest-old", self.events)

    def test_launcher_guards_inspect_actual_inventory_without_stale_version_pin(self):
        downloads = self.root / "downloads"
        downloads.mkdir()
        (downloads / "TIO-Launcher.exe").write_bytes(b"current live launcher")
        (downloads / "TIO-Launcher-0.1.6.exe").write_bytes(b"current versioned launcher")
        self.scope.update(DOWNLOADS=downloads, CONFIGS=[], services=lambda: self.guards["services"],
                          code_states=lambda: self.guards["game_code"])
        result = self.actual_guards()
        self.assertEqual(set(result["launchers"]), {"TIO-Launcher.exe", "TIO-Launcher-0.1.6.exe"})
        self.assertEqual(result["launchers"]["TIO-Launcher.exe"]["sha256"], tool.sha(b"current live launcher"))
        (downloads / "TIO-Launcher.exe").unlink()
        with self.assertRaisesRegex(RuntimeError, "launcher missing"):
            self.actual_guards()

    def test_https_checks_complete_manifest_all_24_blobs_and_unchanged_ti(self):
        contents = {"manifest.json": self.new, "blobs/" + tool.sha(self.candidate): self.candidate,
                    "blobs/" + tool.TI_SHA: self.ti,
                    **{"blobs/" + tool.sha(raw): raw for raw in self.images.values()}}
        with patch.object(tool, "fetch", side_effect=lambda path, maximum: contents[path]):
            result = tool.verify_https(self.payload)
            self.assertEqual(len(result["candidates"]), 24)
            self.assertTrue(result["ti_preserved"])
            self.assertFalse(result["graphical_validation"])
            name = next(iter(self.images))
            digest = tool.PINNED_ASSETS[name]["sha256"]
            contents["blobs/" + digest] = b"corrupt"
            with self.assertRaisesRegex(ValueError, "resource differs"):
                tool.verify_https(self.payload)
            contents["blobs/" + digest] = self.images[name]
            contents["blobs/" + tool.TI_SHA] = b"corrupt"
            with self.assertRaisesRegex(ValueError, "TI"):
                tool.verify_https(self.payload)


if __name__ == "__main__":
    unittest.main()
