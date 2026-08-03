# Third-Party Notices

BioVoid can interoperate with optional third-party tools. Their source code,
binary releases, model files, and data are not vendored in this repository.
The Docker recipes fetch upstream source at build time and pin the upstream
commit used by the integration.

These tools remain separate from the BioVoid canonical pipeline. Their output
is comparison or exploratory evidence only and must not be presented as a
BioVoid canonical result.

## AutoDock Vina

AutoDock Vina is developed by the Center for Computational Structural Biology
and is distributed under the Apache License, Version 2.0.

- Source: https://github.com/ccsb-scripps/AutoDock-Vina
- License: https://github.com/ccsb-scripps/AutoDock-Vina/blob/master/LICENSE
- Supported local version: 1.2.7
- Citation guidance: follow the upstream README and cited Vina publications

Install Vina separately or place a trusted local executable at
`tools/vina/vina.exe`. That path is ignored by Git. Do not commit the
executable or generated docking results.

## fpocket

The optional comparison container builds fpocket from the pinned 4.2.3 commit:
`4bb0d8447f62fee77e2c3c29f54b5fcaf5e2c066`.

- Source: https://github.com/Discngine/fpocket
- License: https://github.com/Discngine/fpocket/blob/master/LICENSE (MIT)
- Citation guidance: follow the upstream README and fpocket publications

The upstream source tree contains its own third-party notices. Any future
distribution of a built image or binary must preserve the applicable notices
from the included source and base image layers.

## P2Rank

The optional comparison container builds P2Rank from the pinned commit:
`9808a7723be9a94e2ffc21ab5f724cb6ae4ba01e`.

- Source: https://github.com/rdk/p2rank
- License: https://github.com/rdk/p2rank (MIT)
- Citation guidance: follow the upstream README and P2Rank publications

P2Rank datasets, release assets, and future model packages may have their own
distribution terms. They are not included in this repository and must be
audited separately before redistribution.

## Container Base Images

The repository contains Docker build recipes that refer to pinned base image
digests, including Node.js and Python images. These images are retrieved by
Docker and are not stored in Git. Anyone publishing a prebuilt image must
review and retain the applicable license and attribution information for every
base image and installed package layer.

## RCSB Protein Data Bank

Runtime structure downloads are not committed to this repository. RCSB PDB
data and API usage are subject to the RCSB/wwPDB policies; structure IDs,
source metadata, and the relevant structure publication should be cited when
results are shared.

- Policies: https://www.rcsb.org/pages/policies
- Data API: https://data.rcsb.org/index.html

The RCSB PDB policy states that archive data files and programmatic API data
are available under CC0 1.0 unless the data originate from an integrated
external resource with separate restrictions. Those source-specific
restrictions still apply.
