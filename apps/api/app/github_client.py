from github import Github
from github.Repository import Repository
from github.GithubException import GithubException
import os


def get_gh() -> Github:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set")
    return Github(token)


def get_owner_login() -> str:
    owner = os.getenv("GITHUB_OWNER")
    if not owner:
        raise RuntimeError("GITHUB_OWNER is not set")
    return owner


def ensure_repo(repo_name: str, private: bool = True) -> Repository:
    gh = get_gh()
    owner_login = get_owner_login()

    # Try user repo lookup first (works for both user and org if accessible)
    try:
        return gh.get_repo(f"{owner_login}/{repo_name}")
    except GithubException as e:
        if e.status != 404:
            raise

    # Create repo under the correct account/org
    authed_user = gh.get_user()  # authenticated identity

    # If owner_login matches authed user -> create under user
    if authed_user.login.lower() == owner_login.lower():
        return authed_user.create_repo(
            name=repo_name,
            private=private,
            auto_init=True,
            description="Created by AI Software Factory",
        )

    # Else try to create under org
    org = gh.get_organization(owner_login)
    return org.create_repo(
        name=repo_name,
        private=private,
        auto_init=True,
        description="Created by AI Software Factory",
    )

def create_branch_from_default(repo: Repository, default_branch: str, new_branch: str) -> None:
    base_ref = repo.get_git_ref(f"heads/{default_branch}")
    repo.create_git_ref(ref=f"refs/heads/{new_branch}", sha=base_ref.object.sha)

def upsert_file(repo: Repository, branch: str, path: str, content: str, message: str) -> None:
    try:
        existing = repo.get_contents(path, ref=branch)
        repo.update_file(path, message, content, existing.sha, branch=branch)
    except GithubException as e:
        if e.status == 404:
            repo.create_file(path, message, content, branch=branch)
        else:
            raise

def open_pr(repo, title: str, body: str, head_branch: str, base_branch: str) -> str:
    """
    Idempotent PR opener:
    - If an open PR already exists for head_branch -> return its URL
    - Else create it and return its URL
    """
    # 1) Return existing PR if present
    for pr in repo.get_pulls(state="open", base=base_branch):
        if pr.head.ref == head_branch:
            return pr.html_url

    # 2) Otherwise create new PR
    try:
        pr = repo.create_pull(title=title, body=body, head=head_branch, base=base_branch)
        return pr.html_url
    except GithubException as e:
        # 422 can also happen due to race conditions; re-check and return existing
        if e.status == 422:
            for pr in repo.get_pulls(state="open", base=base_branch):
                if pr.head.ref == head_branch:
                    return pr.html_url
        raise