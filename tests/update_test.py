import base64
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote

from electron.private.update import channel_filename, create_feed


class UpdateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "package.json"
        self.package.write_text('{"version":"2.0.0-beta.2+build.7"}')
        self.artifact = self.root / "signed.exe"
        self.contents = bytes(range(256)) * 600 + b"final signed bytes"
        self.artifact.write_bytes(self.contents)

    def feed(self, output="feed", **kwargs):
        options = dict(
            artifacts=[{"source": self.artifact, "name": "Sample Setup 世界.exe"}],
            package_json=self.package, output=self.root / output,
            platform="windows", architecture="arm64", release_date="2026-01-02T03:04:05Z",
        )
        options.update(kwargs)
        return create_feed(**options)

    def test_final_artifact_hash_url_and_reproducible_blockmap(self):
        name = "Sample Setup 世界.exe"
        result = self.feed(blockmaps=[name], release_notes="Unicode 世界\nSecond line", staging_percentage=25)
        file = result["files"][0]
        self.assertEqual(unquote(file["url"]), name)
        self.assertEqual(base64.b64decode(file["sha512"]), hashlib.sha512(self.contents).digest())
        self.assertEqual(file["size"], len(self.contents))
        self.assertEqual((self.root / "feed" / name).read_bytes(), self.contents)
        self.assertEqual(json.loads((self.root / "feed/latest.yml").read_text()), result)
        self.assertEqual(result["stagingPercentage"], 25)
        self.assertEqual(result["version"], "2.0.0-beta.2+build.7")
        self.feed(output="repeat", blockmaps=[name], release_notes="Unicode 世界\nSecond line", staging_percentage=25)
        for path in (self.root / "feed").iterdir():
            self.assertEqual(path.read_bytes(), (self.root / "repeat" / path.name).read_bytes())
        blockmap = json.loads(gzip.decompress((self.root / "feed" / (name + ".blockmap")).read_bytes()))
        self.assertEqual(blockmap["version"], "2")
        file = blockmap["files"][0]
        offset = file["offset"]
        self.assertEqual(file["name"], "file")
        self.assertEqual(sum(file["sizes"]), len(self.contents))
        self.assertEqual(len(file["checksums"]), len(file["sizes"]))
        for size, checksum in zip(file["sizes"], file["checksums"]):
            self.assertEqual(base64.b64decode(checksum), hashlib.sha256(self.contents[offset:offset + size]).digest())
            offset += size

    def test_updater_channel_routing(self):
        for platform, arch, expected in [
            ("windows", "x64", "beta.yml"), ("windows", "arm64", "beta.yml"),
            ("macos", "arm64", "beta-mac.yml"), ("linux", "x64", "beta-linux.yml"),
            ("linux", "arm64", "beta-linux-arm64.yml"),
        ]:
            with self.subTest(platform=platform, architecture=arch):
                self.assertEqual(channel_filename(platform, arch, "beta"), expected)

    def test_blockmaps_resynchronize_after_insertions_and_deletions(self):
        name = "installer.exe"
        original = hashlib.shake_256(b"deterministic installer-like data").digest(1024 * 1024)
        self.artifact.write_bytes(original)
        self.feed(output="old", artifacts=[{"source": self.artifact, "name": name}], blockmaps=[name])
        old = json.loads(gzip.decompress((self.root / "old" / (name + ".blockmap")).read_bytes()))["files"][0]
        known = dict(zip(old["checksums"], old["sizes"]))
        for index, changed in enumerate([b"prefix" + original, original[:400000] + b"inserted" + original[400000:], original[:400000] + original[400037:]]):
            self.artifact.write_bytes(changed)
            directory = "new" + str(index)
            self.feed(output=directory, artifacts=[{"source": self.artifact, "name": name}], blockmaps=[name])
            new = json.loads(gzip.decompress((self.root / directory / (name + ".blockmap")).read_bytes()))["files"][0]
            reused = sum(size for checksum, size in zip(new["checksums"], new["sizes"]) if known.get(checksum) == size)
            with self.subTest(change=index):
                self.assertGreater(reused, len(original) * 0.75)
                self.assertEqual(sum(new["sizes"]), len(changed))
                self.assertTrue(all(16 * 1024 <= size <= 64 * 1024 for size in new["sizes"][:-1]))

    def test_invalid_release_inputs_and_output_collisions_fail(self):
        for kwargs in [
            {"artifacts": []}, {"channel": "../latest"}, {"release_date": "now"},
            {"release_date": "2026-02-30T00:00:00Z"}, {"staging_percentage": 101},
            {"blockmaps": ["undeclared.exe"]},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.feed(**kwargs)
        for name in ["../escape.exe", "CON.exe", "latest.yml", "trailing.", "nested/setup.exe"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.feed(artifacts=[{"source": self.artifact, "name": name}])
        with self.assertRaises(ValueError):
            self.feed(artifacts=[{"source": self.artifact, "name": "Setup.exe"}, {"source": self.artifact, "name": "setup.exe"}])
        for version in ["1.0", "01.0.0", "1.0.0-01", None]:
            self.package.write_text(json.dumps({"version": version}))
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.feed()


if __name__ == "__main__":
    unittest.main()
