# Pipeline scripts

These are the data-processing scripts that build family-data.json and the
deployed index.html files, version-controlled here so they're not a
single-machine point of failure. They're meant to be run from the project
root (one level up from `site/`), same as always — copy them back there,
or point PYTHONPATH/cwd accordingly. Config, credentials, and generated
data/review files (fs_config.json, fs_*.json, library.json, etc.) are
deliberately NOT included here.
