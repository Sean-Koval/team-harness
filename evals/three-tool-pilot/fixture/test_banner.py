from pathlib import Path
import subprocess
import sys
import unittest


class BannerTests(unittest.TestCase):
    def banner(self, *flags):
        product = Path(__file__).with_name("banner.py")
        return subprocess.check_output(
            [sys.executable, product, "  Ada  ", *flags], text=True
        ).removesuffix("\n")

    def test_default_trims_padding(self):
        self.assertEqual(self.banner(), "Hello, Ada!")

    def test_verbatim_preserves_padding(self):
        self.assertEqual(self.banner("--verbatim"), "Hello,   Ada  !")
