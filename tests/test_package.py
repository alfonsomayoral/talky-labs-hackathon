import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from kalmora.package import register_package


class PackageTests(unittest.TestCase):
    def test_inventory_preservation_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, dest = Path(tmp)/'input.zip', Path(tmp)/'registered'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('participant/phase_dev/tasks/close.json', '{"month":"2026-07"}')
                z.writestr('participant/score.py', b'original\x00bytes')
                z.writestr('__MACOSX/junk', 'ignored')
            original = archive.read_bytes()
            manifest = register_package(archive, dest)
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(manifest['archive_sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(len(manifest['files']), 2)
            self.assertEqual((dest/'participant/score.py').read_bytes(), b'original\x00bytes')
            self.assertEqual(json.loads((dest/'manifest.json').read_text()), manifest)
            (dest/'participant/score.py').write_text('tampered')
            with self.assertRaises(FileExistsError): register_package(archive, dest)
            self.assertEqual((dest/'participant/score.py').read_text(), 'tampered')

    def test_unsafe_paths_and_symlinks_leave_no_destination(self):
        for name in ['../escape', '/absolute', 'participant/../../escape', 'participant\\escape', 'participant/link']:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                archive, dest = Path(tmp)/'input.zip', Path(tmp)/'registered'
                with zipfile.ZipFile(archive, 'w') as z:
                    item = zipfile.ZipInfo(name)
                    if name.endswith('link'): item.external_attr = 0o120777 << 16
                    z.writestr(item, 'payload')
                with self.assertRaises(ValueError): register_package(archive, dest)
                self.assertFalse(dest.exists())
