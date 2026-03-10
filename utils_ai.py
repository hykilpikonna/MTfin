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
        inputs = json.load(f)
        
    inputs.append({
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": torrents_text
            }
        ]
    })

    response = client.responses.create(
        model="gpt-5.4",
        input=inputs,
        text={"format": {"type": "text"}, "verbosity": "medium"},
        reasoning={"effort": "medium", "summary": "auto"},
        store=True,
        include=["reasoning.encrypted_content", "web_search_call.action.sources"]
    )
    assert (output := response.output[-1]).type == "message"
    assert len(contents := output.content) == 1
    return contents[0].text


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
        inputs = json.load(f)
        
    inputs.append({
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": directory_text
            }
        ]
    })
    
    response = client.responses.create(
        model="gpt-5.1-codex-mini",
        input=inputs,
        text={"format": {"type": "text"}},
        reasoning={"effort": "low"},
        store=True,
        include=["reasoning.encrypted_content", "web_search_call.action.sources"]
    )
    assert (output := response.output[-1]).type == "message"
    assert len(contents := output.content) == 1
    raw_response = contents[0].text
    
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
