"""
Bio-Void Hunter: Visualization Engine
=====================================

Advanced 3D visualization using Plotly for interactive web reports.
Generates HTML reports showing protein structure and detected cavities.

Author: Bio-Void Hunter Team
Version: 0.1.0 (Phase 2.6)
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

class BioVoidVisualizer:
    """Hybrid visualization engine (Plotly + PyMOL Scripting)"""
    
    def __init__(self, output_dir: str = "data/results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def create_interactive_view(self, pdb_file: str, 
                              cavities: List[Dict], 
                              pdb_id: str) -> str:
        """
        Create structured interactive 3D view using Plotly.
        Returns path to generated HTML file.
        """
        logger.info("[VIS] Generating interactive view for %s...", pdb_id)
        
        # 1. Parse PDB for visualization (Simple CA trace)
        atoms = self._parse_pdb_for_vis(pdb_file)
        
        # Create figure
        fig = go.Figure()
        
        # 2. Draw Protein Backbone (Grey Trace)
        fig.add_trace(go.Scatter3d(
            x=atoms['x'], y=atoms['y'], z=atoms['z'],
            mode='lines',
            line=dict(
                color='darkgrey', # Darker for better contrast
                width=5           # Thicker backbone
            ),
            name='Protein Backbone (CA)',
            hoverinfo='none'
        ))
        
        # 3. Draw Cavities (Colored by Volume)
        # Sort cavities by volume for better coloring
        sorted_cavities = sorted(cavities, key=lambda c: c['volume'], reverse=True)
        
        # Color helper function
        def get_color(volume, is_druggable):
            # Clamp volume between 200 and 2000 for color scaling
            norm = min(max(volume, 200), 2000) / 2000.0
            
            if is_druggable:
                # Warm scale: Gold (low) -> Deep Red (high)
                r = 255
                g = int(215 * (1 - norm)) # 215 -> 0
                b = 0
                return f"rgb({r},{g},{b})"
            else:
                # Cool/Neutral scale: LightSlateGray -> DeepPurple
                # Better than invisible blue
                r = int(119 + (80 * norm)) # 119 -> 199 (Purple-ish)
                g = int(136 - (80 * norm)) # 136 -> 56
                b = int(153 + (80 * norm)) # 153 -> 233
                return f"rgb({r},{g},{b})"

        for i, cavity in enumerate(sorted_cavities):
            # Extract points
            points = np.array(cavity['vertices'])
            
            # Skip empty cavities
            if points.size == 0:
                continue
                
            # Handle single point case (1D array -> 2D array)
            if points.ndim == 1:
                points = points.reshape(1, -1)
            
            # Extract properties
            vol = cavity['volume']
            is_druggable = cavity.get('druggable', False)
            
            # Determine style
            color = get_color(vol, is_druggable)
            
            if is_druggable:
                opacity = 0.8
                size = 5
                status_text = "✅ DRUGGABLE"
                border_width = 0
            else:
                opacity = 0.4 # Increased from 0.15 to 0.4 for visibility
                size = 3
                status_text = "❌ Non-druggable"
                border_width = 0
            
            # Draw Cavity Points
            fig.add_trace(go.Scatter3d(
                x=points[:, 0], y=points[:, 1], z=points[:, 2],
                mode='markers',
                marker=dict(
                    size=size,
                    color=color,
                    opacity=opacity,
                    line=dict(width=border_width)
                ),
                name=f"Cavity {cavity['id']}",
                hovertemplate=f"<b>ID: {cavity['id']}</b><br>Vol: {vol:.1f} Å³<br>{status_text}<extra></extra>"
            ))
            
            # Draw Centroid (Center of Mass) - Only for druggable
            if is_druggable:
                center = cavity['center']
                fig.add_trace(go.Scatter3d(
                    x=[center[0]], y=[center[1]], z=[center[2]],
                    mode='markers+text',
                    marker=dict(size=4, color='black', symbol='x'),
                    text=[str(cavity['id'])],
                    textposition="top center",
                    textfont=dict(color='black', size=11, family='Arial Black'),
                    name=f"Center {cavity['id']}",
                    showlegend=False
                ))

        # 4. Layout Settings
        fig.update_layout(
            title=f"Bio-Void Hunter Report: {pdb_id}",
            scene=dict(
                aspectmode='data',
                xaxis_title='X (Å)',
                yaxis_title='Y (Å)',
                zaxis_title='Z (Å)',
                camera=dict(
                    eye=dict(x=1.5, y=1.5, z=1.5)
                )
            ),
            margin=dict(l=0, r=0, b=0, t=40),
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.01
            )
        )
        
        # Save HTML
        output_path = self.output_dir / f"{pdb_id.lower()}_view.html"
        fig.write_html(str(output_path))
        logger.info("[VIS] Analysis saved: %s", output_path)
        
        return str(output_path)

    def _parse_pdb_for_vis(self, pdb_file: str) -> pd.DataFrame:
        """Simple PDB parser for visualization (Extract CA atoms)"""
        coords = []
        with open(pdb_file, 'r') as f:
            for line in f:
                if line.startswith("ATOM") and "CA" in line[12:16]:
                    try:
                        coords.append({
                            'x': float(line[30:38]),
                            'y': float(line[38:46]),
                            'z': float(line[46:54])
                        })
                    except ValueError:
                        continue
        return pd.DataFrame(coords)

    def generate_pymol_script(self, pdb_file: str, cavities: List[Dict], pdb_id: str) -> str:
        """
        Generate a PyMOL script (.pml) for high-quality rendering.
        This script can be run manually in PyMOL: @1cbs_render.pml
        """
        pml_path = self.output_dir / f"{pdb_id.lower()}_render.pml"
        abs_pdb_path = Path(pdb_file).resolve()
        
        with open(pml_path, 'w') as f:
            # Load Protein
            f.write(f"load {abs_pdb_path}, protein\n")
            f.write("hide everything\n")
            f.write("show cartoon, protein\n")
            f.write("color grey80, protein\n")
            f.write("bg_color white\n\n")
            
            # Draw Cavities as Pseudoatoms
            for cavity in cavities:
                is_druggable = cavity.get('druggable', False)
                color = "red" if is_druggable else "cyan"
                obj_name = f"cavity_{cavity['id']}"
                
                # Create pseudoatoms for each vertex (Downsample for performance if needed)
                points = cavity['vertices']
                # Limit points for script size (take every 2nd point if too many)
                step = 2 if len(points) > 500 else 1
                
                f.write(f"# Cavity {cavity['id']} (Vol: {cavity['volume']:.1f})\n")
                for i in range(0, len(points), step):
                    p = points[i]
                    f.write(f"pseudoatom {obj_name}, pos=[{p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}]\n")
                
                # Style the cavity object
                f.write(f"show spheres, {obj_name}\n")
                f.write(f"set sphere_scale, 0.5, {obj_name}\n")
                f.write(f"color {color}, {obj_name}\n")
                if not is_druggable:
                    f.write(f"set transparency, 0.7, {obj_name}\n")
                f.write("\n")
            
            # View settings
            f.write("zoom protein\n")
            f.write("ray 1200, 1000\n")
            f.write(f"png {pdb_id.lower()}_render.png\n")
        
        logger.info("[VIS] PyMOL script generated: %s", pml_path)
        return str(pml_path)

if __name__ == "__main__":
    # Test stub
    pass
