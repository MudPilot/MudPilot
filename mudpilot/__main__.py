import sys

if "--overview" in sys.argv[1:]:
    # (0.8.201) the All characters window on its own: python -m mudpilot --overview
    from .overview import main
else:
    from .app import main

main()
