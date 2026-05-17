import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from services.github_service import github_service
from brain.brain_service import get_brain_service

brain, driver = get_brain_service()

async def main():
    print("Testing GitHub poll directly...")
    
    # Test 1 — latest commit
    print("\n[1] Latest commit...")
    commit = await github_service.get_latest_commit()
    print(f"    SHA: {commit.get('sha', 'NONE')[:8]}")
    
    # Test 2 — read SHA from DB
    print("\n[2] Read last SHA from DB...")
    sha = github_service._get_last_sha(brain)
    print(f"    Stored SHA: {sha}")
    
    # Test 3 — store SHA
    print("\n[3] Store SHA to DB...")
    github_service._store_last_sha(brain, "test_sha_12345")
    sha2 = github_service._get_last_sha(brain)
    print(f"    Retrieved after store: {sha2}")
    
    # Test 4 — full check
    print("\n[4] Full check_new_commits...")
    # Clear stored SHA first to force first-run path
    brain.db.connection.execute(
        "DELETE FROM github_state WHERE key = 'presence_last_sha'"
    )
    brain.db.connection.commit()
    summary = await github_service.check_new_commits(brain)
    print(f"    Summary: {summary}")
    
    # Test 5 — verify SHA stored
    print("\n[5] Verify SHA stored after check...")
    sha3 = github_service._get_last_sha(brain)
    print(f"    Stored SHA: {sha3}")

asyncio.run(main())
driver.close()