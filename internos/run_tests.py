"""Run portable unit tests, optionally adding regressions with source PDFs."""
import argparse
import unittest
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fuentes',action='store_true',help='Incluye las pruebas que requieren PDF originales no distribuidos.')
    args=parser.parse_args()
    folder=Path(__file__).resolve().parent
    loader=unittest.TestLoader();suite=unittest.TestSuite()
    for path in sorted(folder.glob('test_*.py')):
        if path.name=='test_source_samples.py' and not args.fuentes:continue
        suite.addTests(loader.discover(str(folder),pattern=path.name))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
