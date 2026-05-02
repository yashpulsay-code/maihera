import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from brain.brain_service import get_brain_service

brain, driver = get_brain_service()

nodes = brain.list_nodes()
deleted = []

for n in nodes:
    label = n.get('label', '')
    if label in ['API test node'] or 'tracking' in label.lower():
        with driver.session() as session:
            session.run(
                "MATCH (n:Node {id: $id}) DETACH DELETE n",
                id=n['id']
            )
        deleted.append(label)
        print(f"Deleted: {label}")

if not deleted:
    print("No cleanup nodes found.")

stats = brain.get_stats()
print(f"\nBrain after cleanup:")
print(f"  Nodes: {stats['node_count']}")
print(f"  Edges: {stats['edge_count']}")
print(f"  Types: {stats['type_counts']}")

driver.close()