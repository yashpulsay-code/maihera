import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load environment variables
load_dotenv('backend/.env')

# Get Neo4j credentials
uri = os.getenv('NEO4J_URI')
user = os.getenv('NEO4J_USER')
password = os.getenv('NEO4J_PASSWORD')

print(f"URI: {uri}")
print(f"User: {user}")
print(f"Password set: {'Yes' if password else 'No'}")

# Create driver
driver = GraphDatabase.driver(uri, auth=(user, password))

# Verify connectivity
driver.verify_connectivity()
print("Connection verified.")

# Check constraints and indexes
with driver.session() as session:
    constraints = session.run('SHOW CONSTRAINTS').data()
    indexes = session.run('SHOW INDEXES').data()
    print(f'Constraints found: {len(constraints)}')
    for c in constraints:
        print(f'  - {c.get("name", c)}')
    print(f'Indexes found: {len(indexes)}')
    for i in indexes:
        print(f'  - {i.get("name", i)}')

driver.close()
print("Done.")