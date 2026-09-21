#!/usr/bin/env python3
"""Interactively prepare, release on GitHub, and publish a Roo module."""

from pathlib import Path

import github_release
import post_release
import pre_release


def create_argument_parser():
    """Share preparation options with the standalone pre-release command."""
    parser = pre_release.create_argument_parser()
    parser.description = "Prepare, review, and publish a Roo module interactively"
    parser.epilog = (
        "Runs pre_release.py, github_release.py, and post_release.py in order. "
        "Offers tig review before commit/push, confirms GitHub publication, "
        "waits for commit CI before GitHub publication and tag CI afterward, "
        "then asks before registry/PlatformIO publication.\n\n"
        "Example: python3 roo-registry/bin/release.py roo_display --patch"
    )
    parser.add_argument(
        "--skip-publish", action="store_true", help="Skip publishing to PlatformIO"
    )
    return parser


def release(args) -> bool:
    """Run each stage only after the preceding stage has succeeded."""
    module_name = args.module_name
    print(f"\n[1/3] Preparing {module_name} for release", flush=True)
    if not pre_release.pre_release(
        module_name,
        args.bump_type,
        skip_tests=args.skip_tests,
        latest_deps=not args.nolatest_deps,
        notes=args.notes,
        review_diff=True,
    ):
        print("Pre-release stopped. GitHub publication has not started.")
        return False
    print("\n✓ Pre-release complete: release preparation committed and pushed.", flush=True)

    print("\n[2/3] Waiting for CI, creating the GitHub release, and validating tag CI", flush=True)
    if not github_release.create_github_release(module_name, offer_post_release=False):
        print(
            "Commit CI, GitHub release, or tag CI stopped; post-release actions "
            "were not run. If the release was already created, it remains on GitHub."
        )
        return False
    print("\n✓ GitHub release published and CI passed.", flush=True)

    print("\n[3/3] Updating and pushing the registry and dependency graph")
    if args.skip_publish or module_name == post_release.ROO_TESTING_MODULE:
        print("PlatformIO publication will be skipped.")
    else:
        print("The module will also be published to PlatformIO.")
    if input("Proceed with post-release actions? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("Stopped after GitHub publication; post-release actions are pending.")
        print(f"Resume with: python3 {Path(__file__).with_name('post_release.py')} {module_name}"
              + (" --skip-publish" if args.skip_publish else ""))
        return False
    if not post_release.post_release(module_name, skip_publish=args.skip_publish):
        print("Post-release failed; earlier publication steps remain in place.")
        return False
    print(f"\n✓ Release workflow completed for {module_name}.")
    return True


def main() -> int:
    args = create_argument_parser().parse_args()
    try:
        return 0 if release(args) else 1
    except (EOFError, KeyboardInterrupt):
        print("\nRelease interrupted. Completed steps have not been rolled back.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
