"""
MAIHERA GitHub Service
Polls Presence repo for new commits, marks stale nodes,
queues re-analysis when logic files change.
"""

import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from brain.schema import NodeStatus
from services.secrets_service import secrets

logger = logging.getLogger(__name__)

REPO_OWNER     = "yashpulsay-code"
REPO_NAME      = "Presence"
DEFAULT_BRANCH = "main"
GITHUB_API     = "https://api.github.com"

# File extensions that warrant re-analysis when changed
LOGIC_EXTENSIONS = {'.js', '.ts', '.jsx', '.tsx', '.py', '.html', '.css'}

# Extensions to skip entirely — no node impact
SKIP_EXTENSIONS = {'.md', '.txt', '.gitignore', '.lock', '.log'}


class GitHubService:

    def __init__(self):
        self._token = None

    def _get_token(self) -> str:
        if not self._token:
            self._token = secrets.get('GITHUB_TOKEN') or ''
        return self._token

    def _headers(self) -> dict:
        return {
            'Authorization':        f'Bearer {self._get_token()}',
            'Accept':               'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }

    async def get_latest_commit(self) -> dict:
        """Return latest commit dict from default branch."""
        url = (
            f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}"
            f"/commits?per_page=1&sha={DEFAULT_BRANCH}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            commits = r.json()
            return commits[0] if commits else {}

    async def get_commits_since(self, since_sha: str) -> list[dict]:
        """
        Return commits after since_sha, newest first.
        Capped at 20 to avoid burst on first run after long gap.
        """
        url = (
            f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}"
            f"/commits?per_page=20&sha={DEFAULT_BRANCH}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            all_commits = r.json()

        # Return only commits newer than since_sha
        new_commits = []
        for commit in all_commits:
            if commit['sha'] == since_sha:
                break
            new_commits.append(commit)

        return new_commits

    async def get_commit_diff(self, sha: str) -> list[dict]:
        """
        Return changed files for a commit.
        Filters to relevant code files only.
        """
        url = (
            f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}"
            f"/commits/{sha}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()

        changed = []
        for f in data.get('files', []):
            filename = f.get('filename', '')
            ext = Path(filename).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                continue
            # Include package.json but skip other .json
            if ext == '.json' and 'package' not in filename:
                continue
            changed.append({
                'filename': filename,
                'status':   f.get('status', 'modified'),
                'changes':  f.get('changes', 0),
            })

        return changed

    async def get_file_content(
        self, path: str, ref: str = "main"
    ) -> str:
        """Fetch raw file content from repo."""
        url = (
            f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}"
            f"/contents/{path}?ref={ref}"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()

        import base64
        content = data.get('content', '')
        return base64.b64decode(content).decode('utf-8', errors='replace')

    async def get_repo_tree(self, ref: str = "main") -> list[dict]:
        """Return full repo file tree — code files only."""
        url = (
            f"{GITHUB_API}/repos/{REPO_OWNER}/{REPO_NAME}"
            f"/git/trees/{ref}?recursive=1"
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()

        files = []
        for item in data.get('tree', []):
            if item.get('type') != 'blob':
                continue
            path = item.get('path', '')
            ext  = Path(path).suffix.lower()
            if ext in SKIP_EXTENSIONS:
                continue
            if ext not in LOGIC_EXTENSIONS:
                continue
            files.append({
                'path': path,
                'type': item.get('type'),
                'size': item.get('size', 0),
            })

        return files

    async def check_new_commits(self, brain_service) -> dict:
        """
        Main polling method. Called by GitHubWorker every 30 minutes.
        Detects new commits, marks stale nodes, stores latest SHA.
        """
        summary = {
            'new_commits':    0,
            'stale_nodes':    0,
            'needs_analysis': False,
        }

        try:
            latest = await self.get_latest_commit()
            if not latest:
                return summary

            latest_sha   = latest['sha']
            last_sha     = self._get_last_sha(brain_service)

            # First run — no stored SHA yet
            if not last_sha:
                self._store_last_sha(brain_service, latest_sha)
                logger.info(
                    "GitHubService: first run — stored SHA %s. "
                    "No diff computed.", latest_sha[:8]
                )
                return summary

            # Already up to date
            if last_sha == latest_sha:
                logger.debug("GitHubService: no new commits.")
                return summary

            # Fetch new commits
            new_commits = await self.get_commits_since(last_sha)
            summary['new_commits'] = len(new_commits)

            logger.info(
                "GitHubService: %d new commit(s) since %s.",
                len(new_commits), last_sha[:8]
            )

            # Process diffs for each new commit
            changed_files = []
            for commit in new_commits:
                sha   = commit['sha']
                files = await self.get_commit_diff(sha)
                changed_files.extend(files)

                # Check if any logic files changed
                for f in files:
                    ext = Path(f['filename']).suffix.lower()
                    if ext in LOGIC_EXTENSIONS:
                        summary['needs_analysis'] = True

            # Mark stale nodes — find nodes whose source_ref
            # references any changed file
            stale_count = 0
            for f in changed_files:
                filename = f['filename']
                # Search nodes where source_ref contains this filename
                with brain_service.driver.session() as session:
                    result = session.run("""
                        MATCH (n:Node)
                        WHERE n.source_ref CONTAINS $filename
                          AND n.is_stale = false
                        SET n.is_stale = true,
                            n.status = $stale_status,
                            n.last_touched = $now
                        RETURN count(n) as updated
                    """,
                        filename=filename,
                        stale_status=NodeStatus.STALE.value,
                        now=datetime.utcnow().isoformat()
                    )
                    record = result.single()
                    if record:
                        stale_count += record['updated']

            summary['stale_nodes'] = stale_count

            # Store new SHA
            self._store_last_sha(brain_service, latest_sha)

            logger.info(
                "GitHubService: %d stale nodes marked. "
                "needs_analysis=%s",
                stale_count, summary['needs_analysis']
            )

        except Exception as e:
            logger.error("GitHubService.check_new_commits failed: %s", e)

        return summary

    def _get_last_sha(self, brain_service) -> str | None:
        """Read last seen commit SHA from SQLite github_state table."""
        try:
            cursor = brain_service.db.connection.execute(
                "SELECT value FROM github_state WHERE key = ?",
                ("presence_last_sha",)
            )
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error("GitHubService: could not read last SHA: %s", e)
            return None

    def _store_last_sha(self, brain_service, sha: str) -> None:
        """Store latest seen commit SHA to SQLite."""
        try:
            brain_service.db.connection.execute("""
                INSERT INTO github_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, ("presence_last_sha", sha))
            brain_service.db.connection.commit()
        except Exception as e:
            logger.error("GitHubService: could not store SHA: %s", e)   

    async def create_issue(
        self,
        title: str,
        body: str = "",
        labels: list = [],
        repo: str = "Presence",
    ) -> int:
        """Create a GitHub issue. Returns issue number."""
        import httpx
        from services.secrets_service import SecretsService
        secrets = SecretsService()
        token = secrets.get("GITHUB_TOKEN")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        owner = "yashpulsay-code"
        url = f"https://api.github.com/repos/{owner}/{repo}/issues"
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()["number"]

    async def get_issue(
        self, issue_number: int, repo: str = "Presence"
    ) -> dict | None:
        """Re-fetch an issue by number — used by verification."""
        import httpx
        from services.secrets_service import SecretsService
        secrets = SecretsService()
        token = secrets.get("GITHUB_TOKEN")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        owner = "yashpulsay-code"
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                "get_issue error: %s", e
            )
            return None

# Module-level singleton
github_service = GitHubService()