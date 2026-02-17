# Bio-Void Hunter Validation Report

> **Generated:** 2026-02-13T18:31:42.260330
> **Test Set:** 20 known cryptic pockets
> **Tolerance:** 8.0 Angstrom
> **Aggregation Mode:** single
> **Analysis Atom Mode:** frame_ca

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Recall (Sensitivity)** | **15.0%** (3/20) |
| Precision | 0.04% |
| F1-Score | 0.1% |
| True Positives | 3 |
| False Negatives | 17 |
| Failed Runs | 0 |
| Avg Best Distance | 18.1 A |
| Avg Frames Analyzed | 200.0 |
| Total Runtime | 128.4s |

### Decision: NEEDS IMPROVEMENT

Recall (15.0%) is below the minimum threshold (30%).
**Method improvement required before Phase 6.**

---

## Benchmark Comparison

| Method | Recall | Time/Protein | Scalability |
|--------|--------|--------------|-------------|
| Full MD | 80-90% | Days-weeks | ~10 proteins/month |
| AlphaFold+MD | 60-85% | Hours-days | ~100 proteins/month |
| AlphaFold Solo | 60% | Hours | ~1K proteins/month |
| fpocket (Voronoi) | 40-60% | Seconds | Unlimited |
| **BioVoid (NMA)** | **15%** | **Seconds** | **Unlimited** |

---

## Per-Protein Results

| PDB | Protein | Type | Status | Distance | Bio-Score | Volume | Mode | AtomMode |
|-----|---------|------|--------|----------|-----------|--------|------|----------|
| 1CBS | Cellular Retinoic Acid-Bi | side-chain_flip | HIT | 2.8 | 0.799 | 1313 | single | frame_ca |
| 3C79 | TEM-1 Beta-Lactamase | loop_rearrangement | MISS | 33.3 | 0.830 | 2033 | single | frame_ca |
| 1F41 | Interleukin-2 (IL-2) | side-chain_flip | MISS | 19.6 | 0.856 | 2751 | single | frame_ca |
| 1YET | Bcl-xL | helix_displacement | MISS | 11.0 | 0.848 | 2489 | single | frame_ca |
| 1G4E | p38 MAP Kinase | DFG-out | MISS | 24.8 | 0.812 | 2017 | single | frame_ca |
| 1OHR | Plasmepsin II | flap_opening | MISS | 27.7 | 0.884 | 1947 | single | frame_ca |
| 2BXR | Niemann-Pick C2 | domain_motion | MISS | 33.0 | 0.851 | 2126 | single | frame_ca |
| 2VTA | Adenylate Kinase (Adk) -  | domain_motion | MISS | 13.6 | 0.753 | 2336 | single | frame_ca |
| 1AKE | Adenylate Kinase (Adk) -  | domain_motion | MISS | 12.8 | 0.870 | 2720 | single | frame_ca |
| 1STP | Streptavidin | loop_closure | HIT | 5.7 | 0.669 | 1288 | single | frame_ca |
| 1LI2 | Lipocalin-type Prostaglan | side-chain_flip | MISS | 9.4 | 0.655 | 1027 | single | frame_ca |
| 3ERT | Estrogen Receptor alpha | helix_displacement | MISS | 21.4 | 0.760 | 1996 | single | frame_ca |
| 1T46 | HIV-1 Reverse Transcripta | allosteric | MISS | 18.0 | 0.806 | 2528 | single | frame_ca |
| 1M17 | EGFR Kinase | DFG-out | MISS | 39.8 | 0.827 | 1906 | single | frame_ca |
| 2HYY | Chk1 Kinase | side-chain_flip | MISS | 13.0 | 0.827 | 1507 | single | frame_ca |
| 3K5V | PDK1 Kinase | PIF pocket | HIT | 3.6 | 0.820 | 1920 | single | frame_ca |
| 1GWR | Cytochrome c Peroxidase | loop_rearrangement | MISS | 27.6 | 0.806 | 1891 | single | frame_ca |
| 2P2I | Glutamate Receptor (iGluR | domain_motion | MISS | 12.1 | 0.919 | 2306 | single | frame_ca |
| 1JWP | Fatty Acid Binding Protei | portal_opening | MISS | 13.6 | 0.879 | 2391 | single | frame_ca |
| 1RX4 | Immunophilin FKBP12 | loop_rearrangement | MISS | 18.6 | 0.811 | 1731 | single | frame_ca |

---

## Failure Analysis

### Missed Pockets

- **3C79** (TEM-1 Beta-Lactamase): loop_rearrangement
  - Best distance: 33.3A (threshold: 8.0A)
  - Reference: Horn & Bhagat 2009, Horn & Shoichet 2010

- **1F41** (Interleukin-2 (IL-2)): side-chain_flip
  - Best distance: 19.6A (threshold: 8.0A)
  - Reference: Arkin et al. 2003, PNAS

- **1YET** (Bcl-xL): helix_displacement
  - Best distance: 11.0A (threshold: 8.0A)
  - Reference: Oltersdorf et al. 2005, Nature

- **1G4E** (p38 MAP Kinase): DFG-out
  - Best distance: 24.8A (threshold: 8.0A)
  - Reference: Pargellis et al. 2002, Nature Struct Biol

- **1OHR** (Plasmepsin II): flap_opening
  - Best distance: 27.7A (threshold: 8.0A)
  - Reference: Meller et al. 2023

- **2BXR** (Niemann-Pick C2): domain_motion
  - Best distance: 33.0A (threshold: 8.0A)
  - Reference: Meller et al. 2023, AlphaFold successful case

- **2VTA** (Adenylate Kinase (Adk) - closed): domain_motion
  - Best distance: 13.6A (threshold: 8.0A)
  - Reference: Henzler-Wildman et al. 2007, Nature

- **1AKE** (Adenylate Kinase (Adk) - open): domain_motion
  - Best distance: 12.8A (threshold: 8.0A)
  - Reference: Muller et al. 1996, Structure

- **1LI2** (Lipocalin-type Prostaglandin D Synthase): side-chain_flip
  - Best distance: 9.4A (threshold: 8.0A)
  - Reference: Inoue et al. 2008

- **3ERT** (Estrogen Receptor alpha): helix_displacement
  - Best distance: 21.4A (threshold: 8.0A)
  - Reference: Shiau et al. 1998, Cell

- **1T46** (HIV-1 Reverse Transcriptase): allosteric
  - Best distance: 18.0A (threshold: 8.0A)
  - Reference: Ren et al. 2001

- **1M17** (EGFR Kinase): DFG-out
  - Best distance: 39.8A (threshold: 8.0A)
  - Reference: Stamos et al. 2002

- **2HYY** (Chk1 Kinase): side-chain_flip
  - Best distance: 13.0A (threshold: 8.0A)
  - Reference: Converso et al. 2009

- **1GWR** (Cytochrome c Peroxidase): loop_rearrangement
  - Best distance: 27.6A (threshold: 8.0A)
  - Reference: Bowman Lab benchmark

- **2P2I** (Glutamate Receptor (iGluR)): domain_motion
  - Best distance: 12.1A (threshold: 8.0A)
  - Reference: Bhatt et al. 2016

- **1JWP** (Fatty Acid Binding Protein): portal_opening
  - Best distance: 13.6A (threshold: 8.0A)
  - Reference: Richieri et al. 2000

- **1RX4** (Immunophilin FKBP12): loop_rearrangement
  - Best distance: 18.6A (threshold: 8.0A)
  - Reference: Van Duyne et al. 1993

### Performance by Pocket Type

| Pocket Type | Hits | Total | Rate |
|-------------|------|-------|------|
| DFG-out | 0 | 2 | 0% |
| PIF pocket | 1 | 1 | 100% |
| allosteric | 0 | 1 | 0% |
| domain_motion | 0 | 4 | 0% |
| flap_opening | 0 | 1 | 0% |
| helix_displacement | 0 | 2 | 0% |
| loop_closure | 1 | 1 | 100% |
| loop_rearrangement | 0 | 3 | 0% |
| portal_opening | 0 | 1 | 0% |
| side-chain_flip | 1 | 4 | 25% |

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