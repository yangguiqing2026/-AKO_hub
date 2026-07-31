"""Batch push all registered AKO spokes to git remotes (Gitee + GitHub)."""
import os, subprocess, sys

sys.path.insert(0, ".")

from registry.workflows import SPOKE_REGISTRY

# ---- Registry source_dir → E: fallback mapping ----
# Many registry entries still point to D:, actual dirs are on E:
E_ROOT = "E:/"
NAME_TO_EDIR = {
    "AKO_architect_agent": "AKO_architect_agent",
    "AKO_drawing_inspector": "AKO_drawing_inspector_agent",  # note naming diff
    "AKO_image_analyzer_agent": "AKO_image_analyzer_agent",
    "AKO工作流": "AKO_workflow",
    "AKO_chat": "AKO_chat",
    "AKO_geo": None,  # subdir of AKO_hub, already pushed
    "AKO_reports": "AKO_Report_Template-v1.0",
    "AKO_business_agent": "AKO_business_agent",
    "AKO_quote_agent": "AKO_quote_agent",
    "AKO_media_agent": "AKO_media_agent",
    "AKO_layout_agent": "AKO_layout_agent",
    "AKO_form_extractor": "AKO_form_extractor",
    "AKO_netwatch_agent": "AKO_netwatch_agent",
    "AKO_knowledge": "AKO_knowledge",
    "AKO_code_compliance": "AKO_code_compliance",
    "AKO_material_selector": "AKO_material_selector",
    "AKO_energy_analyzer": "AKO_energy_analyzer",
    "AKO_fire_safety": "AKO_fire_safety",
    "AKO_accessibility": "AKO_accessibility",
    "AKO_site_planner": "AKO_site_planner",
    "AKO_mep_engineer": "AKO_mep_engineer",
    "AKO_interior_designer": "AKO_interior_designer",
    "AKO_landscape": "AKO_landscape",
    "AKO_project_manager": "AKO_project_manager",
    "AKO_cost_estimator": "AKO_cost_estimator",
    "AKO_bim_exporter": "AKO_bim_exporter",
    "AKO_document_writer": "AKO_document_writer",
    "AKO_safety_inspector": "AKO_safety_inspector",
    "AKO_quality_inspector": "AKO_quality_inspector",
    "AKO_scheduler": "AKO_scheduler",
    "AKO_surveyor": "AKO_surveyor",
}

# ---- Helper functions ----
def run(cmd, cwd=None):
    """Run a subprocess, return (returncode, stdout, stderr)."""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def resolve_dir(spoke):
    """Try to find the actual directory for a spoke."""
    wid = spoke["workflow_id"]
    src = spoke["source_dir"].replace("\\", "/")

    # 1) source_dir as-is
    if os.path.isdir(src):
        return src

    # 2) Replace D:/ → E:/
    e_path = src.replace("D:/", "E:/")
    if os.path.isdir(e_path):
        return e_path

    # 3) Look up via mapping table
    edn = NAME_TO_EDIR.get(wid)
    if edn:
        ep = E_ROOT + edn
        if os.path.isdir(ep):
            return ep

    # 4) Try E:/ + workflow_id
    ep = E_ROOT + wid
    if os.path.isdir(ep):
        return ep

    # 5) Scan E: for matching name
    for name in os.listdir(E_ROOT):
        full = os.path.join(E_ROOT, name)
        if not os.path.isdir(full):
            continue
        # fuzzy match: workflow_id in name or vice versa
        if wid.lower().replace("_", "") in name.lower().replace("_", ""):
            return full
        if name.lower().replace("_", "") in wid.lower().replace("_", ""):
            return full

    return None

def push_project(project_dir, workflow_id):
    """Add, commit, push a single project to all remotes."""
    print(f"\n{'='*60}")
    print(f"  [{workflow_id}]  {project_dir}")
    print(f"{'='*60}")

    # --- git init if needed ---
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        print("  → git init")
        rc, out, err = run(["git", "init"], cwd=project_dir)
        if rc != 0:
            print(f"  ✗ git init FAILED: {err}")
            return False

    # --- check remotes ---
    rc, remotes, _ = run(["git", "remote", "-v"], cwd=project_dir)
    if "origin" not in remotes and "gitee" not in remotes:
        # Try to guess gitee repo name from dir name
        dirname = os.path.basename(project_dir)
        gitee_url = f"git@gitee.com:yangguiqing1970/{dirname}.git"
        print(f"  → Adding origin (gitee): {gitee_url}")
        rc2, _, err2 = run(["git", "remote", "add", "origin", gitee_url], cwd=project_dir)
        if rc2 != 0:
            print(f"  ⚠ Could not add origin: {err2}")

    if "github" not in remotes:
        dirname = os.path.basename(project_dir)
        github_url = f"git@github.com:yangguiqing2026/{dirname}.git"
        print(f"  → Adding github: {github_url}")
        rc2, _, err2 = run(["git", "remote", "add", "github", github_url], cwd=project_dir)
        if rc2 != 0:
            print(f"  ⚠ Could not add github: {err2}")

    # --- git status ---
    rc, status, _ = run(["git", "status", "--short"], cwd=project_dir)
    if status:
        print(f"  Changes:\n{status}")
        # --- git add + commit ---
        print("  → git add .")
        rc1, _, err1 = run(["git", "add", "."], cwd=project_dir)
        if rc1 != 0:
            print(f"  ⚠ git add: {err1}")

        commit_msg = f"chore: sync {workflow_id} - auto commit by AKO_hub push_all"
        print(f"  → git commit: {commit_msg}")
        rc2, out2, err2 = run(["git", "commit", "-m", commit_msg], cwd=project_dir)
        if rc2 != 0:
            if "nothing to commit" not in err2:
                print(f"  ⚠ git commit: {err2}")
    else:
        print("  Status: clean (no changes)")

    # --- push to origin (gitee) ---
    print("  → git push origin master")
    rc, out, err = run(["git", "push", "-u", "origin", "master"], cwd=project_dir)
    if rc != 0:
        # Try main branch
        rc, out, err = run(["git", "push", "-u", "origin", "main"], cwd=project_dir)
    print(f"  origin push: {'✓' if rc == 0 else '✗ ' + err[:200]}")

    # --- push to github ---
    print("  → git push github master")
    rc, out, err = run(["git", "push", "-u", "github", "master"], cwd=project_dir)
    if rc != 0:
        rc, out, err = run(["git", "push", "-u", "github", "main"], cwd=project_dir)
    print(f"  github push: {'✓' if rc == 0 else '✗ ' + err[:200]}")

    return True


# ===================== MAIN =====================
if __name__ == "__main__":
    results = {"ok": [], "skip": [], "fail": []}

    for spoke in SPOKE_REGISTRY:
        wid = spoke["workflow_id"]

        # Skip AKO_hub (already pushed)
        if wid == "AKO_hub":
            results["skip"].append((wid, "already pushed"))
            continue

        # Skip AKO_geo (subdir of hub, already pushed as part of hub)
        if wid == "AKO_geo":
            results["skip"].append((wid, "part of AKO_hub"))
            continue

        proj_dir = resolve_dir(spoke)
        if not proj_dir:
            print(f"\n  ✗ [{wid}] directory NOT FOUND (source_dir: {spoke['source_dir']})")
            results["fail"].append((wid, "dir not found"))
            continue

        try:
            success = push_project(proj_dir, wid)
        except Exception as e:
            print(f"  ✗ Exception: {e}")
            results["fail"].append((wid, str(e)))
            continue

        if success:
            results["ok"].append(wid)
        else:
            results["fail"].append((wid, "push failed"))

    # ---- Summary ----
    print(f"\n\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  ✓ Pushed:  {len(results['ok'])}")
    for w in results["ok"]:
        print(f"    - {w}")
    print(f"  ⊘ Skipped: {len(results['skip'])}")
    for w, reason in results["skip"]:
        print(f"    - {w}  ({reason})")
    print(f"  ✗ Failed:  {len(results['fail'])}")
    for w, reason in results["fail"]:
        print(f"    - {w}  ({reason})")