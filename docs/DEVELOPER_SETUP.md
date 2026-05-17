Developer Setup
===============

Steps to set up a development environment for hacking on RSMM.

1. Clone the repo and create a virtual environment for Python work.

```bash
git clone https://github.com/Ovilli/RavenswatchModManager.git
cd RavenswatchModManager
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

2. Build native loader (see `src/loader/build.sh`):

```bash
cd src/loader
./build.sh
```

3. IDE configuration
- Open the workspace in VS Code. Use the CMake Tools and Python extensions.
- Configure the Python interpreter to the virtualenv `.venv`.

4. Testing
- Run unit tests for Python modules: `pytest -q` from repo root.

5. Optional: regenerate dev artifacts (none of these are committed)

```bash
# Uncooked asset mirror — 3.2 GB, readable PNGs + .gen sidecars.
# Browseable reference for what each decoded path contains.
pip install --user texture2ddecoder Pillow
python3 scripts/extract_uncooked.py
python3 scripts/decode_gen_sidecars.py
# See docs/UNCOOKED_ASSETS.md

# Pattern signatures for rsmm.resolve (Lua API for calling game fns).
# Requires the Ghidra project already imported (docs/_re/run_analysis.sh).
pip install --user capstone
bash docs/_re/run_dump_symbols.sh
python3 scripts/gen_function_patterns.py
python3 scripts/test_pattern_resolve.py --all
# See docs/_re/PIPELINE.md
```
