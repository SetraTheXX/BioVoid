# False-Positive Analysis Protocol (Phase 5.5 / Phase 3)

1. Sample 50 proteins from `proteins` table with deterministic seed.
2. For each sampled protein, select high-confidence pockets (`druggable=1` and `bio_score >= 0.7`).
3. Repair missing pocket centers via cavity recomputation on local structures (frame or raw PDB).
4. Evaluate support evidence per pocket:
   - Known-cryptic set proximity (`<= 8A`)
   - Ligand proximity in raw PDB (`<= 10A` to non-water HETATM atoms)
   - fpocket overlap in benchmark summary (`<= 8A`)
5. Classify pockets:
   - `supported`: at least one evidence source
   - `unsupported`: no evidence despite available checks
   - `unknown`: insufficient evidence inputs (e.g., unresolved center)
6. Compute:
   - Conservative FPR = unsupported / (supported + unsupported)
   - Strict FPR = (unsupported + unknown) / total
   - Unknown rate = unknown / total

Notes:
- This is an automated proxy and not a substitute for manual literature curation.
- Unknown cases are reported separately to avoid inflating conservative FPR.
