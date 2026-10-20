# Practice data

A tiny synthetic landscape for learning the RE-PEAT wizard. It is **not real data** and every value in
`practice_run/run_config.yaml` is a dummy number. Do not reuse them for a real KHG: your team decides those.

- `data/`: the input layers (EPSG:32749). One river on the west edge, two canals, two sub-KHGs, two existing sekat.
- `practice_template.yaml`: a starting config with every decision left empty. Use it as the *Starting config* when you
  create a run, then type the dummy values from the guide.
- `practice_run/run_config.yaml`: the same run with all dummy decisions filled in. In the wizard choose
  *Open an existing run* and pick this file to skip the typing.

Rebuild everything with `python scripts/make_sample_data.py`.
