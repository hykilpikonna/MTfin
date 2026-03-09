import os
import json
from pathlib import Path
from openai import OpenAI

from utils import with_disk_cache

client = OpenAI()

@with_disk_cache('select_best_torrents')
def select_best_torrents(torrents_text: str) -> str:
    """
    Calls the OpenAI API to select the best torrent IDs using a predefined prompt.
    
    :param torrents_text: A string containing formatted torrent information.
    :return: A string containing the selected torrent IDs, separated by space.
    """
    prompt_path = Path(__file__).parent / "prompt_select_torrents.json"
    with open(prompt_path, "r", encoding="utf-8") as f:
        messages = json.load(f)
        
    messages.append({
        "role": "user",
        "content": torrents_text
    })

    response = client.chat.completions.create(
        model="gpt-5.4",
        messages=messages,
        response_format={"type": "text"},
        verbosity="medium",
        reasoning_effort="medium",
        store=True
    )
    return response.choices[0].message.content


@with_disk_cache('generate_rename_mapping')
def generate_rename_mapping(directory_text: str) -> dict[str, str]:
    """
    Calls the OpenAI API to generate a renaming mapping for files 
    into a Jellyfin-compatible library format.
    
    :param directory_text: A string containing the base directory and list of files.
    :return: A dictionary mapping source paths to destination paths.
    """
    prompt_path = Path(__file__).parent / "prompt_generate_mapping.json"
    with open(prompt_path, "r", encoding="utf-8") as f:
        messages = json.load(f)
        
    messages.append({
        "role": "user",
        "content": directory_text
    })
    
    response = client.chat.completions.create(
        model="gpt-5.1-codex-mini",
        messages=messages,
        response_format={"type": "text"},
        reasoning_effort="low",
        store=True
    )
    raw_response = response.choices[0].message.content
    
    mapping = {}
    for line in raw_response.splitlines():
        if " -->> " in line:
            parts = line.split(" -->> ", 1)
            if len(parts) == 2:
                mapping[parts[0].strip()] = parts[1].strip()
            else:
                print(f"Invalid line: {line}")
    return mapping


def apply_rename_mapping(mapping: dict[str, str], base_src_dir: str | Path, base_dst_dir: str | Path) -> None:
    """
    Creates symbolic links from source files to their destinations based on the provided mapping.
    Missing directories in the destination paths will be created automatically.
    
    :param mapping: Dictionary where keys are source paths and values are destination paths. 
                    These can be relative to the provided base directories.
    :param base_src_dir: The base directory where the source files reside.
    :param base_dst_dir: The base directory where the symbolic links will be created.
    """
    src_base = Path(base_src_dir).resolve()
    dst_base = Path(base_dst_dir).resolve()
    
    for src_rel, dst_rel in mapping.items():
        src_path = src_base / Path(src_rel)
        dst_path = dst_base / Path(dst_rel)
        
        # Ensure the source actually exists before creating a link to it
        if not src_path.exists():
            print(f"Warning: Source path does not exist, skipping: {src_path}")
            continue
            
        # Create parent directories for the destination if they don't exist
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create the symbolic link. If it already exists, gracefully ignore or overwrite.
        try:
            if dst_path.exists() or dst_path.is_symlink():
                dst_path.unlink()
            os.symlink(src_path, dst_path)
            print(f"Linked: {dst_path.relative_to(dst_base)} -> {src_path.name}")
        except Exception as e:
            print(f"Failed to link {src_rel} to {dst_rel}: {e}")
