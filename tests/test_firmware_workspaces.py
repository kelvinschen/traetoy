import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('firmware',ROOT/'scripts/firmware.py')
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)

class Workspaces(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        shutil.copytree(ROOT/'templates',self.root/'templates')
        board=self.root/'shared/boards/ai-passport';board.mkdir(parents=True)
        for name in ('sdkconfig.defaults','partitions.csv'):
            shutil.copy2(ROOT/'shared/boards/ai-passport'/name,board/name)
    def test_independent_creation_and_no_overwrite(self):
        p=f.create('clock',self.root)
        self.assertNotIn('companion_ui.c',[x.name for x in (p/'main').iterdir()])
        self.assertFalse((p/'sdkconfig.defaults').is_symlink())
        self.assertTrue((p/'bootloader_components').is_symlink())
        self.assertEqual(f.metadata('clock',self.root)[1]['kind'],'blank')
        with self.assertRaises(ValueError):f.create('clock',self.root)
    def test_reject_path_escape(self):
        for name in ('../escape','/tmp/escape','UPPER','a/b',''):
            with self.assertRaises(ValueError):f.create(name,self.root)
    def test_receipt_rejects_modified_or_wrong_workspace_image(self):
        p=f.create('clock',self.root)/'build';p.mkdir()
        image=p/f.IMAGE;image.write_bytes(b'verified image')
        receipt=dict(workspace='clock',sha256=hashlib.sha256(image.read_bytes()).hexdigest())
        (p/'validated.json').write_text(json.dumps(receipt))
        self.assertEqual(f.verified_image('clock',self.root),image)
        image.write_bytes(b'changed')
        with self.assertRaises(ValueError):f.verified_image('clock',self.root)
        receipt['sha256']=hashlib.sha256(image.read_bytes()).hexdigest();receipt['workspace']='other'
        (p/'validated.json').write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):f.verified_image('clock',self.root)

if __name__=='__main__':unittest.main()
