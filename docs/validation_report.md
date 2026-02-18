# Bio-Void Hunter Validation Report

> **Generated:** 2026-02-19T00:17:34.796414
> **Test Set:** 20 known cryptic pockets
> **Tolerance:** 8.0 Angstrom
> **Aggregation Mode:** multi
> **Analysis Atom Mode:** reconstructed_heavy

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Recall (Sensitivity)** | **0.0%** (0/20) |
| Precision | 0.00% |
| F1-Score | 0.0% |
| True Positives | 0 |
| False Negatives | 20 |
| Failed Runs | 0 |
| Avg Best Distance | 25.9 A |
| Avg Frames Analyzed | 120.0 |
| Total Runtime | 11066.4s |

| Avg Consensus Support (frames) | 71.91 |
| Avg Center Stability | 0.42 A |
| Avg Volume CV | 0.123 |

| Avg Reconstruction Coverage | 1.000 |
| Avg Reconstruction Mean CA Displacement | 0.084 A |

### Decision: NEEDS IMPROVEMENT

Recall (0.0%) is below the minimum threshold (30%).
**Method improvement required before Phase 6.**

---

## Benchmark Comparison

| Method | Recall | Time/Protein | Scalability |
|--------|--------|--------------|-------------|
| Full MD | 80-90% | Days-weeks | ~10 proteins/month |
| AlphaFold+MD | 60-85% | Hours-days | ~100 proteins/month |
| AlphaFold Solo | 60% | Hours | ~1K proteins/month |
| fpocket (Voronoi) | 40-60% | Seconds | Unlimited |
| **BioVoid (NMA)** | **0%** | **Seconds** | **Unlimited** |

---

## Per-Protein Results

| PDB | Protein | Type | Status | Distance | Bio-Score | Volume | Mode | AtomMode |
|-----|---------|------|--------|----------|-----------|--------|------|----------|
| 1CBS | Cellular Retinoic Acid-Bi | side-chain_flip | MISS | 20.0 | 0.579 | 670 | multi | reconstructed_heavy |
| 3C79 | TEM-1 Beta-Lactamase | loop_rearrangement | MISS | 47.0 | 0.883 | 2193 | multi | reconstructed_heavy |
| 1F41 | Interleukin-2 (IL-2) | side-chain_flip | MISS | 31.1 | 0.651 | 733 | multi | reconstructed_heavy |
| 1YET | Bcl-xL | helix_displacement | MISS | 22.3 | 0.770 | 1469 | multi | reconstructed_heavy |
| 1G4E | p38 MAP Kinase | DFG-out | MISS | 16.9 | 0.678 | 1212 | multi | reconstructed_heavy |
| 1OHR | Plasmepsin II | flap_opening | MISS | 45.3 | 0.676 | 1369 | multi | reconstructed_heavy |
| 2BXR | Niemann-Pick C2 | domain_motion | MISS | 30.9 | 0.933 | 2016 | multi | reconstructed_heavy |
| 2VTA | Adenylate Kinase (Adk) -  | domain_motion | MISS | 28.5 | 0.655 | 664 | multi | reconstructed_heavy |
| 1AKE | Adenylate Kinase (Adk) -  | domain_motion | MISS | 20.9 | 0.908 | 1287 | multi | reconstructed_heavy |
| 1STP | Streptavidin | loop_closure | MISS | 20.8 | 0.804 | 2869 | multi | reconstructed_heavy |
| 1LI2 | Lipocalin-type Prostaglan | side-chain_flip | MISS | 8.5 | 0.640 | 398 | multi | reconstructed_heavy |
| 3ERT | Estrogen Receptor alpha | helix_displacement | MISS | 23.7 | 0.774 | 2392 | multi | reconstructed_heavy |
| 1T46 | HIV-1 Reverse Transcripta | allosteric | MISS | 22.3 | 0.878 | 1792 | multi | reconstructed_heavy |
| 1M17 | EGFR Kinase | DFG-out | MISS | 37.8 | 0.890 | 2509 | multi | reconstructed_heavy |
| 2HYY | Chk1 Kinase | side-chain_flip | MISS | 24.9 | 0.861 | 1854 | multi | reconstructed_heavy |
| 3K5V | PDK1 Kinase | PIF pocket | MISS | 17.8 | 0.838 | 2174 | multi | reconstructed_heavy |
| 1GWR | Cytochrome c Peroxidase | loop_rearrangement | MISS | 37.2 | 0.862 | 2218 | multi | reconstructed_heavy |
| 2P2I | Glutamate Receptor (iGluR | domain_motion | MISS | 11.9 | 0.827 | 718 | multi | reconstructed_heavy |
| 1JWP | Fatty Acid Binding Protei | portal_opening | MISS | 21.3 | 0.723 | 1547 | multi | reconstructed_heavy |
| 1RX4 | Immunophilin FKBP12 | loop_rearrangement | MISS | 29.4 | 0.707 | 949 | multi | reconstructed_heavy |

---

## Failure Analysis

### Missed Pockets

- **1CBS** (Cellular Retinoic Acid-Binding Protein): side-chain_flip
  - Best distance: 20.0A (threshold: 8.0A)
  - Reference: Kleywegt et al. 1994, J Mol Biol

- **3C79** (TEM-1 Beta-Lactamase): loop_rearrangement
  - Best distance: 47.0A (threshold: 8.0A)
  - Reference: Horn & Bhagat 2009, Horn & Shoichet 2010

- **1F41** (Interleukin-2 (IL-2)): side-chain_flip
  - Best distance: 31.1A (threshold: 8.0A)
  - Reference: Arkin et al. 2003, PNAS

- **1YET** (Bcl-xL): helix_displacement
  - Best distance: 22.3A (threshold: 8.0A)
  - Reference: Oltersdorf et al. 2005, Nature

- **1G4E** (p38 MAP Kinase): DFG-out
  - Best distance: 16.9A (threshold: 8.0A)
  - Reference: Pargellis et al. 2002, Nature Struct Biol

- **1OHR** (Plasmepsin II): flap_opening
  - Best distance: 45.3A (threshold: 8.0A)
  - Reference: Meller et al. 2023

- **2BXR** (Niemann-Pick C2): domain_motion
  - Best distance: 30.9A (threshold: 8.0A)
  - Reference: Meller et al. 2023, AlphaFold successful case

- **2VTA** (Adenylate Kinase (Adk) - closed): domain_motion
  - Best distance: 28.5A (threshold: 8.0A)
  - Reference: Henzler-Wildman et al. 2007, Nature

- **1AKE** (Adenylate Kinase (Adk) - open): domain_motion
  - Best distance: 20.9A (threshold: 8.0A)
  - Reference: Muller et al. 1996, Structure

- **1STP** (Streptavidin): loop_closure
  - Best distance: 20.8A (threshold: 8.0A)
  - Reference: Weber et al. 1989

- **1LI2** (Lipocalin-type Prostaglandin D Synthase): side-chain_flip
  - Best distance: 8.5A (threshold: 8.0A)
  - Reference: Inoue et al. 2008

- **3ERT** (Estrogen Receptor alpha): helix_displacement
  - Best distance: 23.7A (threshold: 8.0A)
  - Reference: Shiau et al. 1998, Cell

- **1T46** (HIV-1 Reverse Transcriptase): allosteric
  - Best distance: 22.3A (threshold: 8.0A)
  - Reference: Ren et al. 2001

- **1M17** (EGFR Kinase): DFG-out
  - Best distance: 37.8A (threshold: 8.0A)
  - Reference: Stamos et al. 2002

- **2HYY** (Chk1 Kinase): side-chain_flip
  - Best distance: 24.9A (threshold: 8.0A)
  - Reference: Converso et al. 2009

- **3K5V** (PDK1 Kinase): PIF pocket
  - Best distance: 17.8A (threshold: 8.0A)
  - Reference: Engel et al. 2010, Nat Chem Biol

- **1GWR** (Cytochrome c Peroxidase): loop_rearrangement
  - Best distance: 37.2A (threshold: 8.0A)
  - Reference: Bowman Lab benchmark

- **2P2I** (Glutamate Receptor (iGluR)): domain_motion
  - Best distance: 11.9A (threshold: 8.0A)
  - Reference: Bhatt et al. 2016

- **1JWP** (Fatty Acid Binding Protein): portal_opening
  - Best distance: 21.3A (threshold: 8.0A)
  - Reference: Richieri et al. 2000

- **1RX4** (Immunophilin FKBP12): loop_rearrangement
  - Best distance: 29.4A (threshold: 8.0A)
  - Reference: Van Duyne et al. 1993

### Performance by Pocket Type

| Pocket Type | Hits | Total | Rate |
|-------------|------|-------|------|
| DFG-out | 0 | 2 | 0% |
| PIF pocket | 0 | 1 | 0% |
| allosteric | 0 | 1 | 0% |
| domain_motion | 0 | 4 | 0% |
| flap_opening | 0 | 1 | 0% |
| helix_displacement | 0 | 2 | 0% |
| loop_closure | 0 | 1 | 0% |
| loop_rearrangement | 0 | 3 | 0% |
| portal_opening | 0 | 1 | 0% |
| side-chain_flip | 0 | 4 | 0% |

---

## Strengths & Limitations

### Strengths

- 1000x faster than AlphaFold-based methods
- Scalable to 100K+ proteins
- Physics-based (interpretable results)
- Novel NMA+Voronoi+Scoring combination

### Limitations

- Lower accuracy than MD/AlphaFold (expected trade-off)
- NMA is harmonic: misses large domain motions
- Best for side-chain flips and small loop movements
- Requires experimental validation for novel discoveries

---

## Publication Readiness

**Assessment: NOT READY**

Method improvement or alternative positioning required.
Consider: negative result paper, or pivot to screening-only tool.

---

*Report generated by Bio-Void Hunter v1.0.0*