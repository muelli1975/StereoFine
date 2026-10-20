import sys


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == '--check-inputs':
        from pathlib import Path
        from stereofine.input_checks import check_inputs
        check_inputs(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        from stereofine.gui import run
        run()
