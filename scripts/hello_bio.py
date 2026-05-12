import Bio
from Bio.PDB import PDBList, PDBParser
import os
import warnings
import sys

# Suppress PDB construction warnings
warnings.simplefilter('ignore')

print("="*50)
print("🧬 BIO-VOID HUNTER SYSTEM CHECK")
print("="*50)

# Check Biopython version
try:
    print(f"[OK] Biopython version: {Bio.__version__}")
    print("[OK] Biopython library detected.")
except ImportError:
    print("[ERROR] Biopython not found!")
    sys.exit(1)

# Initialize PDB connection
print("\n[INFO] Connecting to RCSB Protein Data Bank...")
pdbl = PDBList()

# Define target protein (1cbs - Cellular Retinoic Acid Binding Protein)
target_pdb_id = '1cbs'
download_dir = os.getcwd()

# Download the file
print(f"[INFO] Downloading structure for ID: {target_pdb_id}...")
# retrieve_pdb_file returns the filename of the downloaded file
filename = pdbl.retrieve_pdb_file(target_pdb_id, pdir=download_dir, file_format='pdb')

print(f"[OK] File downloaded: {filename}")

# Check if file exists and parse it
if os.path.exists(filename):
    print("\n[INFO] Parsing molecular structure...")
    parser = PDBParser()
    try:
        structure = parser.get_structure(target_pdb_id, filename)
        
        # Count atoms
        atom_count = 0
        residue_count = 0
        chain_count = 0
        
        for model in structure:
            for chain in model:
                chain_count += 1
                for residue in chain:
                    residue_count += 1
                    for atom in residue:
                        atom_count += 1
        
        print("-" * 30)
        print(f"📊 ANALYSIS RESULT FOR {target_pdb_id.upper()}")
        print("-" * 30)
        print(f"   • Chains (Zincir): {chain_count}")
        print(f"   • Residues (Amino Asit): {residue_count}")
        print(f"   • Total Atoms (Atom Sayısı): {atom_count}")
        print("-" * 30)
        
        print("\n✅ SYSTEM TEST SUCCESSFUL: 'Bio-Void Hunter' is ready for Phase 1!")
        print(f"   Local file saved at: {os.path.abspath(filename)}")
        
    except Exception as e:
        print(f"[ERROR] Failed to parse PDB file: {e}")
else:
    print(f"[ERROR] expected file {filename} not found.")
