"""
clear_folders.py

Interactive script to delete files from one or more working folders.

Run from the folder that contains inventory_pkg/:
    python -m inventory_pkg.clear_folders

You'll be shown a menu listing each folder and how many files are in it.
Files are permanently deleted — there is no undo, so the script asks
you to confirm before anything gets removed.
"""

import os
import sys

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
WORKING_DIR = os.path.dirname(SCRIPT_DIR)

CLEARABLE_FOLDERS = ["Shopee", "Lazada", "Zalora", "Ordazzle", "SAP", "RESULT"]


def _list_files(folder_path):
    """Return a list of full file paths inside folder_path (non-recursive)."""
    if not os.path.isdir(folder_path):
        return []
    return [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
    ]


def _delete_files(folder_path):
    """
    Delete every file in folder_path.

    Returns (deleted_count, error_count). Prints each filename as it goes
    so you can see what was removed.
    """
    files   = _list_files(folder_path)
    deleted = 0
    errors  = 0
    for fp in files:
        try:
            os.remove(fp)
            print(f"    deleted  {os.path.basename(fp)}")
            deleted += 1
        except Exception as e:
            print(f"    ERROR    {os.path.basename(fp)} — {e}")
            errors += 1
    return deleted, errors


def _folder_summary(name):
    """Return a one-line summary like 'Zalora       (3 files)'."""
    path  = os.path.join(WORKING_DIR, name)
    count = len(_list_files(path))
    label = "file" if count == 1 else "files"
    extra = "" if os.path.isdir(path) else "  [folder not found]"
    return f"  {name:<12} ({count} {label}){extra}"


def main():
    print("\nINVENTORY FOLDER CLEANUP")

    print("Current folder contents:\n")
    for name in CLEARABLE_FOLDERS:
        print(_folder_summary(name))

    print()
    print("Which folder(s) do you want to clear?\n")
    for i, name in enumerate(CLEARABLE_FOLDERS, 1):
        print(f"  [{i}] {name}")
    print(f"  [A] All folders")
    print(f"  [Q] Quit — do nothing\n")

    choice = input("Enter number(s) separated by commas, A, or Q: ").strip().upper()

    if choice in ("Q", ""):
        print("\nCancelled. No files deleted.\n")
        sys.exit(0)

    if choice == "A":
        selected = list(CLEARABLE_FOLDERS)
    else:
        selected = []
        for part in choice.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(CLEARABLE_FOLDERS):
                    selected.append(CLEARABLE_FOLDERS[idx])
                else:
                    print(f"  Skipping unknown option: {part}")
            else:
                print(f"  Skipping unknown option: {part}")

    if not selected:
        print("\nNo valid folder selected. Nothing deleted.\n")
        sys.exit(0)

    total_files = sum(
        len(_list_files(os.path.join(WORKING_DIR, name)))
        for name in selected
    )

    print(f"\nYou are about to permanently delete {total_files} file(s) from:")
    for name in selected:
        print(f"  • {name}")
    print()

    if total_files == 0:
        print("All selected folders are already empty. Nothing to do.\n")
        sys.exit(0)

    confirm = input("Type YES to confirm: ").strip().upper()
    if confirm != "YES":
        print("\nCancelled. No files deleted.\n")
        sys.exit(0)

    print()
    total_deleted = 0
    total_errors  = 0
    for name in selected:
        folder_path = os.path.join(WORKING_DIR, name)
        print(f"  Clearing {name}/")
        if not os.path.isdir(folder_path):
            print(f"    (folder not found — skipped)")
            continue
        d, e = _delete_files(folder_path)
        total_deleted += d
        total_errors  += e

    print()
    print(f"Done.  {total_deleted} file(s) deleted", end="")
    if total_errors:
        print(f",  {total_errors} error(s)")
    else:
        print(".")
    print()


if __name__ == "__main__":
    main()
