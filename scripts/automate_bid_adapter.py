#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Optional


def run(cmd: List[str], cwd: Optional[Path] = None, check: bool = True, input_str: Optional[str] = None, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            text=True,
            input=input_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        try:
            cmd_str = " ".join(e.cmd if isinstance(e.cmd, list) else [str(e.cmd)])
        except Exception:
            cmd_str = str(e.cmd)
        sys.stderr.write("\n".join([
            "[run] Command failed",
            f"[run] cwd: {str(cwd) if cwd else os.getcwd()}",
            f"[run] cmd: {cmd_str}",
            f"[run] exit_code: {e.returncode}",
            "[run] --- stdout ---",
            e.stdout or "",
            "[run] --- stderr ---",
            e.stderr or "",
            "[run] ---------------",
        ]) + "\n")
        raise


def parse_bidders(raw: str) -> List[str]:
    s = raw.strip()
    if not s:
        return []
    if s.startswith("["):
        return [b.strip().strip('"\'') for b in json.loads(s)]
    return [b.strip() for b in s.split(",") if b.strip()]


def ensure_line_in_json_array(file_path: Path, value: str) -> bool:
    text = file_path.read_text()
    try:
        data = json.loads(text)
        if value in data:
            return False
        data.append(value)
        file_path.write_text(json.dumps(data, indent=4) + "\n")
        return True
    except json.JSONDecodeError:
        if re.search(rf"\"{re.escape(value)}\"\s*\]", text):
            return False
        text = re.sub(r"\]\s*$", f"    \"{value}\"\n]", text, flags=re.MULTILINE)
        file_path.write_text(text)
        return True


def update_prebid_modules(prebid_repo: Path, bidders: List[str]) -> bool:
    modules_file = prebid_repo / "modules.json"
    if not modules_file.exists():
        raise FileNotFoundError(f"Missing Prebid modules.json at {modules_file}")
    changed = False
    for bidder in bidders:
        changed |= ensure_line_in_json_array(modules_file, f"{bidder}BidAdapter")
    return changed


def sync_pubfig_submodule_to_prebid_sha(pubfig_repo: Path, submodule_path: str, target_sha: str) -> bool:
    gitmodules = pubfig_repo / ".gitmodules"
    if not gitmodules.exists():
        return False
    run(["git", "submodule", "update", "--init", submodule_path], cwd=pubfig_repo)
    run(["git", "-C", submodule_path, "fetch", "--all"], cwd=pubfig_repo)
    run(["git", "-C", submodule_path, "checkout", target_sha], cwd=pubfig_repo)
    run(["git", "add", submodule_path], cwd=pubfig_repo)
    status = run(["git", "status", "--porcelain"], cwd=pubfig_repo).stdout.strip()
    return bool(status)


def read_text(p: Path) -> str:
    return p.read_text()


def update_ams_helper(ams_repo: Path, bidders: List[str]) -> bool:
    helper = ams_repo / "src/main/java/io/freestar/admanagement/deployments/utils/PrebidModulesHelper.java"
    if not helper.exists():
        raise FileNotFoundError(f"Missing PrebidModulesHelper.java at {helper}")
    text = read_text(helper)

    start_pat = r"static final String\[] NETWORK_SLUGS_WITH_BID_ADAPTERS = new String\[]\{"
    end_pat = r"\};"
    m = re.search(start_pat, text)
    if not m:
        raise RuntimeError("Could not locate NETWORK_SLUGS_WITH_BID_ADAPTERS declaration")
    start_idx = m.end()
    tail = text[start_idx:]
    end_rel = re.search(end_pat, tail)
    if not end_rel:
        raise RuntimeError("Could not locate end of NETWORK_SLUGS_WITH_BID_ADAPTERS")
    end_idx = start_idx + end_rel.start()
    array_body = tail[:end_rel.start()]
    existing = re.findall(r'"([^"]+)"', array_body)
    existing_set = set(existing)
    new_items = [b for b in bidders if b not in existing_set]
    if not new_items:
        return False
    combined = existing + new_items
    lines: List[str] = []
    current = "\t\t\t"
    for i, item in enumerate(combined):
        token = f'"{item}"'
        if i < len(combined) - 1:
            token += ","
        if len(current) + len(token) > 100:
            lines.append(current.rstrip())
            current = "\t\t\t" + token + " "
        else:
            current += token + " "
    if current.strip():
        lines.append(current.rstrip())
    new_body = "\n" + "\n".join(lines) + "\n\t\t"
    new_text = text[:start_idx] + new_body + text[end_idx:]
    helper.write_text(new_text)
    return True


def gh_login_from_env() -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return
    try:
        run(["gh", "auth", "status"], check=True)
        return
    except subprocess.CalledProcessError:
        pass
    run(["gh", "auth", "login", "--with-token"], input_str=token)


def git_prepare_branch(repo: Path, base_branch: str, new_branch: str) -> None:
    run(["git", "fetch", "origin"], cwd=repo)
    run(["git", "checkout", base_branch], cwd=repo)
    run(["git", "pull", "--ff-only", "origin", base_branch], cwd=repo)
    run(["git", "checkout", "-B", new_branch], cwd=repo)


def git_commit_push(repo: Path, branch: str, title: str) -> bool:
    status = run(["git", "status", "--porcelain"], cwd=repo).stdout.strip()
    if not status:
        return False
    run(["git", "add", "-A"], cwd=repo)
    run(["git", "commit", "-m", title], cwd=repo)
    run(["git", "push", "-u", "origin", branch], cwd=repo)
    return True


def gh_open_pr(repo: Path, title: str, body: str, base_branch: str, head_branch: str) -> str:
    run(["gh", "pr", "create", "--title", title, "--body", body, "--base", base_branch, "--head", head_branch], cwd=repo)
    url = run(["gh", "pr", "view", "--json", "url", "--jq", ".url"], cwd=repo).stdout.strip()
    return url


def main():
    parser = argparse.ArgumentParser(description="Automate adding Prebid bidders across POC repos")
    parser.add_argument("--bidders", required=True, help="Comma-separated or JSON array of slugs, e.g. 'kargo, teads'")
    parser.add_argument("--prebid-repo", required=True)
    parser.add_argument("--pubfig-repo", required=True)
    parser.add_argument("--ams-repo", required=True)
    parser.add_argument("--base-branch", default="main")
    args = parser.parse_args()

    bidders = parse_bidders(args.bidders)
    if not bidders:
        print("No bidders provided", file=sys.stderr)
        sys.exit(1)

    prebid_repo = Path(args.prebid_repo).resolve()
    pubfig_repo = Path(args.pubfig_repo).resolve()
    ams_repo = Path(args.ams_repo).resolve()

    gh_login_from_env()

    prebid_changed = update_prebid_modules(prebid_repo, bidders)
    ams_changed = update_ams_helper(ams_repo, bidders)

    suffix = "-".join(sorted(set(bidders)))
    branch_name = f"chore/add-bidders-{suffix}"

    results = {}

    git_prepare_branch(prebid_repo, args.base_branch, branch_name)
    title = f"chore: add bidders {', '.join(bidders)} to Prebid modules.json"
    pr = gh_open_pr(prebid_repo, title, "Automated POC change to include new bidders in Prebid build modules.", args.base_branch, branch_name) if git_commit_push(prebid_repo, branch_name, title) else ""
    results["prebid-poc"] = {"changed": prebid_changed, "pr": pr}

    prebid_sha = run(["git", "rev-parse", "HEAD"], cwd=prebid_repo).stdout.strip()

    git_prepare_branch(pubfig_repo, args.base_branch, branch_name)
    sub_changed = sync_pubfig_submodule_to_prebid_sha(pubfig_repo, "pbjs-poc", prebid_sha)
    title = f"chore: sync pbjs-poc submodule to {prebid_sha[:7]}"
    pr = gh_open_pr(pubfig_repo, title, "Automated POC change to sync Prebid submodule to latest modules.json changes.", args.base_branch, branch_name) if git_commit_push(pubfig_repo, branch_name, title) else ""
    results["pubfig-poc"] = {"changed": sub_changed, "pr": pr, "prebid_sha": prebid_sha}

    git_prepare_branch(ams_repo, args.base_branch, branch_name)
    title = f"chore: add bidders {', '.join(bidders)} to PrebidModulesHelper"
    pr = gh_open_pr(ams_repo, title, "Automated POC change to include new bidder slugs in AMS helper.", args.base_branch, branch_name) if git_commit_push(ams_repo, branch_name, title) else ""
    results["ad-management-service-poc"] = {"changed": ams_changed, "pr": pr}

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    sys.exit(main())


