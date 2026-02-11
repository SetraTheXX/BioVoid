"""Quick DB health check for atlas.db."""
import sqlite3
import sys

db_path = sys.argv[1] if len(sys.argv) > 1 else "data/atlas.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

# List tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print(f"Tables: {tables}")

# Protein count
c.execute("SELECT COUNT(*) FROM proteins")
prot_count = c.fetchone()[0]
print(f"Proteins: {prot_count}")

# Pocket count (try different table names)
for tbl in ["pockets", "discoveries", "pocket_data"]:
    if tbl in tables:
        c.execute(f"SELECT COUNT(*) FROM {tbl}")
        print(f"{tbl}: {c.fetchone()[0]}")

# Top 5 by bio-score
c.execute("SELECT pdb_id, top_bio_score, total_cavities, druggable_cavities FROM proteins ORDER BY top_bio_score DESC LIMIT 5")
print("\nTop 5 Bio-Score:")
for r in c.fetchall():
    print(f"  {r[0]}: score={r[1]:.3f}, total={r[2]}, druggable={r[3]}")

# Status distribution
c.execute("SELECT status, COUNT(*) FROM proteins GROUP BY status")
print("\nStatus Distribution:")
for r in c.fetchall():
    print(f"  {r[0]}: {r[1]}")

conn.close()
print("\n✅ DB Health Check Complete")
