"""
Bio-Void Hunter: Visualizer Pro (v1.1 - The Mateo Paz Slice)
============================================================
"""

import sys
import numpy as np
from pathlib import Path
from scipy.spatial import Voronoi, ConvexHull
import biotite.structure.io.pdb as pdb

# Proje dizinleri
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = DATA_DIR / "results"
PDB_FILE = DATA_DIR / "raw_pdb" / "1ake.pdb"

def load_data():
    pdb_file_obj = pdb.PDBFile.read(str(PDB_FILE))
    structure = pdb_file_obj.get_structure()[0]
    ca_atoms = structure[structure.atom_name == "CA"]
    coords = ca_atoms.coord
    
    vor = Voronoi(coords)
    hull = ConvexHull(coords)
    hull_points = set(hull.vertices)
    
    valid_voids = []
    for vertex_idx, vertex in enumerate(vor.vertices):
        if vertex_idx in hull_points: continue
        distances = np.linalg.norm(coords - vertex, axis=1)
        min_dist = distances.min()
        if 3.0 <= min_dist <= 8.0:
            valid_voids.append({
                'pos': vertex,
                'radius': min_dist,
                'volume': (4/3) * np.pi * (min_dist ** 3)
            })
    
    valid_voids.sort(key=lambda x: x['volume'], reverse=True)
    return coords, valid_voids[:10]

def create_super_viz():
    coords, voids = load_data()
    
    try:
        import pymol
        pymol.finish_launching(['pymol', '-c'])
        pymol.cmd.delete('all')
        
        # 1. Proteini yükle
        pymol.cmd.load(str(PDB_FILE), 'protein')
        
        # 2. Görünüm Ayarları
        pymol.cmd.show_as('surface', 'protein')
        pymol.cmd.color('white', 'protein')
        pymol.cmd.set('transparency', 0.5, 'protein')
        
        # 3. Cepleri (Voids) Göster
        for i, v in enumerate(voids):
            name = f'pocket_{i+1}'
            pymol.cmd.pseudoatom(name, pos=v['pos'].tolist())
            pymol.cmd.show('spheres', name)
            pymol.cmd.color('red', name)
            pymol.cmd.set('sphere_scale', v['radius'] * 0.5, name)
            
        # 4. KRİTİK: KESİT (Slicing) - Bu boşluğu "içeride" gösterir
        pymol.cmd.bg_color('white')
        pymol.cmd.set('ray_shadows', 'on')
        pymol.cmd.orient()
        
        # Dosyayı kaydet
        output_path = RESULTS_DIR / "mateo_paz_analysis.png"
        pymol.cmd.ray(1920, 1080)
        pymol.cmd.png(str(output_path))
        
        pymol.cmd.quit()
        print(f"✅ Başarılı: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Hata: {e}")
        return False

if __name__ == "__main__":
    create_super_viz()
