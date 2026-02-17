# False-Positive Analysis Protocol (Phase 5.5 / Phase 3)

1. Sample 50 proteins from `proteins` table with deterministic seed.
2. For each sampled protein, select high-confidence pockets (`druggable=1` and `bio_score >= 0.7`).
3. Repair missing pocket centers via cavity recomputation on local structures (frame or raw PDB).
4. Evaluate support evidence per pocket:
   - Known-cryptic set proximity (`<= 8A`)
   - Ligand proximity in raw PDB (`<= 10.0A` to non-water HETATM atoms)
   - fpocket overlap in benchmark summary (`<= 8A`)
   - Docking validation flag (`validated = 1`)
5. Compute weighted evidence score:
   - known_match: 0.2
   - ligand_nearby: 0.3
   - fpocket_match: 0.3
   - docking_validated: 0.2
   - supported if weighted_score >= 0.30
6. Apply explicit unknown handling:
   - `unknown` if center missing/recompute failed
   - `unknown` if available evidence sources are below minimum
     (`available_sources < 2`)
7. Classification:
   - `supported`: weighted threshold met
   - `unsupported`: threshold not met, sufficient evidence coverage
   - `unknown`: insufficient inputs/coverage
8. Compute:
   - Conservative FPR = unsupported / (supported + unsupported)
   - Strict FPR = (unsupported + unknown) / total
   - Unknown rate = unknown / total

Notes:
- This is an automated proxy and not a substitute for manual literature curation.
- Unknown cases are reported separately to avoid inflating conservative FPR.
