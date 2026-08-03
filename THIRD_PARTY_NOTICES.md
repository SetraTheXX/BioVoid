# Third-Party Tools

BioVoid can interoperate with optional tools that are not distributed in this
repository.

## AutoDock Vina

AutoDock Vina is developed by the Center for Computational Structural Biology
and is licensed under Apache-2.0.

- Source: https://github.com/ccsb-scripps/AutoDock-Vina
- Supported recovery version: 1.2.7

Install Vina separately or place a trusted local executable at
`tools/vina/vina.exe`. That path is ignored by Git.

## fpocket

The optional comparison container builds fpocket from the pinned 4.2.3 commit:
`4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066`.

- Source: https://github.com/Discngine/fpocket

External tool outputs are baseline evidence only and do not become BioVoid
canonical results.
