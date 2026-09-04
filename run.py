"""Runner for the code review agent. Usage:
python run.py --path samples --out findings.md --out findings.json
"""
import sys
from cragent.cli import main

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
