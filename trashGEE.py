#!/usr/bin/env python3
"""
trashGEE.py — Recursively delete Google Earth Engine assets under a root path.

What it does:
  - Walks the asset tree under --root
  - Deletes leaf assets first (images, tables, etc.)
  - Optionally deletes empty containers (folders/collections) afterwards

SAFE DEFAULTS:
  - Dry-run by default (prints what it would delete)
  - Requires explicit confirmation token when --delete is used

Examples:
  # Dry run
  python trashGEE.py --root projects/blue-mts-bugnet/assets/2024-v3/A_predictor_change_img_2024

  # Actually delete contents (keeps containers by default)
  python trashGEE.py --root projects/blue-mts-bugnet/assets/2024-v3/A_predictor_change_img_2024 --delete

  # Delete contents + delete empty folders/collections (including root unless --keep-root)
  python trashGEE.py --root projects/blue-mts-bugnet/assets/2024-v3/A_predictor_change_img_2024 --delete --delete-containers

  # Explicit project (recommended on servers/HPC)
  python trashGEE.py --root projects/blue-mts-bugnet/assets/2024-v3/A_predictor_change_img_2024 --project blue-mts-bugnet --delete
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List, Optional, Tuple

import ee


# ----------------------------
# Helpers
# ----------------------------

CONTAINER_TYPES = {"FOLDER", "IMAGE_COLLECTION", "FEATURE_COLLECTION"}


def normalize_asset_id(asset_id: str) -> str:
    """Remove leading slashes and whitespace."""
    return asset_id.strip().lstrip("/")


def infer_project_from_root(root: str) -> Optional[str]:
    """
    Infer Cloud project ID from an asset root like:
      projects/<PROJECT>/assets/...
    Returns <PROJECT> or None.
    """
    root = normalize_asset_id(root)
    if root.startswith("projects/"):
        parts = root.split("/")
        if len(parts) >= 2 and parts[1]:
            return parts[1]
    return None


def gee_get_asset(asset_id: str) -> Dict:
    """Wrapper around ee.data.getAsset with a helpful error."""
    try:
        return ee.data.getAsset(asset_id)
    except Exception as e:
        raise RuntimeError(f"Failed to get asset info for '{asset_id}': {e}") from e


def gee_list_children(parent_id: str) -> List[Dict]:
    """
    List children under a parent container.
    Returns list of asset dicts (each has 'name' and 'type', etc.)
    """
    try:
        resp = ee.data.listAssets({"parent": parent_id})
        return resp.get("assets", []) or []
    except Exception as e:
        raise RuntimeError(f"Failed to list assets under '{parent_id}': {e}") from e


def is_container(asset_type: Optional[str]) -> bool:
    return (asset_type or "") in CONTAINER_TYPES


def delete_asset(asset_id: str, *, dry_run: bool, throttle_s: float) -> bool:
    """
    Delete a single asset. Returns True if deleted, False otherwise.
    """
    if dry_run:
        print(f"[DRY RUN] delete: {asset_id}")
        return True

    try:
        ee.data.deleteAsset(asset_id)
        print(f"[DELETED] {asset_id}")
        if throttle_s > 0:
            time.sleep(throttle_s)
        return True
    except Exception as e:
        print(f"[FAILED] delete: {asset_id}\n         {e}", file=sys.stderr)
        return False


def walk_tree_postorder(root: str) -> Tuple[List[str], List[str]]:
    """
    Walk asset tree under root, returning:
      - leaf_assets: list of non-container asset IDs (delete first)
      - containers_postorder: list of containers in postorder (deepest-first)
        so they can be deleted after leaves if requested.
    """
    leaf_assets: List[str] = []
    containers_postorder: List[str] = []

    def _recurse(asset_id: str) -> None:
        info = gee_get_asset(asset_id)
        a_type = info.get("type")

        if is_container(a_type):
            children = gee_list_children(asset_id)
            for child in children:
                # Earth Engine returns "name" for full asset id
                child_id = child.get("name") or child.get("id")
                if not child_id:
                    continue
                _recurse(child_id)

            containers_postorder.append(asset_id)
        else:
            leaf_assets.append(asset_id)

    _recurse(root)
    return leaf_assets, containers_postorder


# ----------------------------
# Main
# ----------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Recursively delete GEE assets under a root folder/collection.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--root",
        required=True,
        help="Asset root, e.g. users/you/folder or projects/proj/assets/path",
    )
    p.add_argument(
        "--project",
        default=None,
        help="Cloud project for ee.Initialize(project=...). If omitted, inferred from projects/<proj>/assets/...",
    )
    p.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete. If not set, runs in dry-run mode.",
    )
    p.add_argument(
        "--delete-containers",
        action="store_true",
        help="Also delete containers (folders/collections) after deleting leaves.",
    )
    p.add_argument(
        "--keep-root",
        action="store_true",
        help="Never delete the root container (only applies with --delete-containers).",
    )
    p.add_argument(
        "--throttle",
        type=float,
        default=0.05,
        help="Seconds to sleep between delete calls to reduce rate-limit issues.",
    )
    p.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip interactive confirmation when --delete is used (use with caution).",
    )
    return p


def initialize_ee(project: Optional[str], root: str) -> str:
    """
    Initialize Earth Engine with a project.
    Returns the project used.
    """
    used_project = project or infer_project_from_root(root)
    if not used_project:
        raise RuntimeError(
            "ee.Initialize: no project found. Provide --project <cloud-project>, "
            "or use a --root like projects/<project>/assets/..."
        )
    ee.Initialize(project=used_project)
    return used_project


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    root = normalize_asset_id(args.root)
    dry_run = not args.delete

    used_project = initialize_ee(args.project, root)

    root_info = gee_get_asset(root)
    root_type = root_info.get("type")

    print("==== GEE TRASH (recursive delete) ====")
    print(f"Project: {used_project}")
    print(f"Root:    {root}")
    print(f"Type:    {root_type}")
    print(f"Mode:    {'DRY RUN' if dry_run else 'DELETE'}")
    print(f"Delete containers: {args.delete_containers}")
    print(f"Keep root:         {args.keep_root}")
    print("--------------------------------------")

    # Walk and plan
    leaf_assets, containers_postorder = walk_tree_postorder(root)

    # If keep-root, remove it from container deletion list (root is last in postorder)
    if args.keep_root:
        containers_postorder = [c for c in containers_postorder if c != root]

    # If not deleting containers, we won't delete any container (but we still may need to traverse them)
    containers_to_delete = containers_postorder if args.delete_containers else []

    # Summary
    print(f"Leaf assets to delete: {len(leaf_assets)}")
    print(f"Containers to delete:  {len(containers_to_delete)}")
    if dry_run:
        print("Tip: add --delete to actually delete. Add --delete-containers to remove empty folders/collections.")
    print("--------------------------------------")

    # Confirmation
    if not dry_run and not args.no_confirm:
        token = f"DELETE {root}"
        entered = input(f"Type exactly:\n  {token}\nTo confirm: ").strip()
        if entered != token:
            print("Aborted.")
            sys.exit(1)

    # Delete leaf assets first
    failures = 0
    for asset_id in leaf_assets:
        ok = delete_asset(asset_id, dry_run=dry_run, throttle_s=args.throttle)
        if not ok:
            failures += 1

    # Delete containers deepest-first (postorder)
    if args.delete_containers:
        for container_id in containers_to_delete:
            ok = delete_asset(container_id, dry_run=dry_run, throttle_s=args.throttle)
            if not ok:
                failures += 1

    print("--------------------------------------")
    if dry_run:
        print("Done (dry run). No assets were deleted.")
    else:
        print("Done (delete mode).")
        if failures:
            print(f"WARNING: {failures} deletions failed. See stderr output above.", file=sys.stderr)


if __name__ == "__main__":
    main()
