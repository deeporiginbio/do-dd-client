"""
File utility functions for drug discovery workflows.

Provides helpers for safe file removal and conflict-aware file moving
with extension changes.
"""

import os
import shutil


def move_file_with_extension(file_path, extension):
    """
    Move a file to a new location with a different extension, handling name conflicts.

    If a file with the target extension already exists, it will be renamed with
    an incrementing counter (e.g., file_#1.ext, file_#2.ext).

    Args:
        file_path (str): Path to the source file
        extension (str): New extension to use for the file (without the dot)
    """
    dir_path = os.path.dirname(file_path)
    file_name = os.path.basename(file_path)
    file_base_name = os.path.splitext(file_name)[0]
    target_file_path = os.path.join(dir_path, f"{file_base_name}.{extension}")

    if os.path.isfile(target_file_path):
        existing_files = [
            f
            for f in os.listdir(dir_path)
            if f.startswith(f"{file_base_name}_#") and f.endswith(f".{extension}")
        ]
        counter = len(existing_files) + 1
        new_file_path = os.path.join(
            dir_path, f"{file_base_name}_#{counter}.{extension}"
        )

        shutil.move(target_file_path, new_file_path)


def remove_file(file_path):
    """
    Remove a file if it exists.

    Args:
        file_path (str): Path to the file to be removed
    """
    if os.path.isfile(file_path):
        os.remove(file_path)
