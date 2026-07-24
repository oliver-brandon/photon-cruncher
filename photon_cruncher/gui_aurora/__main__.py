from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> int:
    from photon_cruncher.aurora_main import main as aurora_main

    return aurora_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
