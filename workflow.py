import json
import time
from pathlib import Path

from utils import DEFAULT_DL_DIR, DEFAULT_JELLYFIN_DIR
from utils_mteam import (
    mteam_imdb_info,
    search_mteam_torrents,
    format_mteam_torrent,
    generate_mteam_download_token,
)
from utils_qb import (
    get_qb_client,
    download_torrent,
    get_torrent_file_tree,
    get_torrent_hash,
    rename_torrent_and_folder,
    remove_tag_if_exists
)

from utils_ai import (
    select_best_torrents,
    generate_rename_mapping,
    apply_rename_mapping
)


def format_file_tree(file_tree: list) -> str:
    """Helper to convert the qB file tree output into simple relative paths for the LLM prompt"""
    lines = []
    for f in file_tree:
        lines.append(f.get("name", ""))
    return "\n".join(lines)


def prepare_file_tree_paths(file_tree: list, new_name: str, dl_dir: str) -> Path:
    """
    Strips the root directory from paths if they all start with it,
    and returns the base source directory to use for renaming mapping.
    Assumes POSIX separators (no Windows compatibility needed).
    """
    has_root_dir = False
    if file_tree:
        has_root_dir = all(
            f.get("name", "").startswith(f"{new_name}/")
            for f in file_tree
        )
        
    if has_root_dir:
        for f in file_tree:
            name = f.get("name", "")
            if name.startswith(f"{new_name}/"):
                f["name"] = "./" + name[len(f"{new_name}/"):]
        return Path(dl_dir) / new_name
    else:
        for f in file_tree:
            name = f.get("name", "")
            if not name.startswith("./"):
                f["name"] = "./" + name
        return Path(dl_dir)



def wait_for_download(qb, t_hash: str):
    """
    Blocks until the torrent with the given hash is finished downloading.
    """
    while True:
        info = qb.torrents_info(hashes=t_hash)
        if not info:
            print("Torrent disappeared from qB!")
            break
            
        t_info = info[0]
        progress = t_info.progress
        state = t_info.state
        print(f"Progress: {progress * 100:.1f}% (State: {state})")
        
        # Progress of 1.0 means 100%. Alternatively, check the state.
        if progress >= 1.0 or state in ('uploading', 'pausedUP', 'stalledUP', 'forcedUP'):
            break
        time.sleep(5)
    print("Download complete!")


def check_local_filesystem(dl_dir: str, imdb_id: str):
    """
    Checks the local download directory for any existing files or folders 
    that match the given IMDb ID. Returns the path if found.
    """
    dl_path = Path(dl_dir)
    if dl_path.exists():
        for item in dl_path.rglob('*'):
            if f"[{imdb_id}]" in item.name:
                return item
    return None

def check_qbittorrent(qb, imdb_id: str):
    """
    Checks qBittorrent for any existing torrent that has the IMDb ID in its name.
    Returns the torrent hash if found, or None.
    """
    existing_torrents = qb.torrents_info()
    for t in existing_torrents:
        if f"[{imdb_id}]" in t.name:
            return t.hash
    return None

def search_and_download_mteam(qb, imdb_id: str, new_name: str, dl_dir: str) -> list:
    """
    Searches M-Team for the IMDb ID, uses an LLM to select the best torrents, 
    downloads them, adds them to qBittorrent, and waits for them to complete.
    Returns a list of tuples containing (torrent_hash, torrent_id).
    """
    print(f"\n=== [1] Searching Torrents for {imdb_id} ===")
    imdb_url = f"https://www.imdb.com/title/{imdb_id}/"

    # Extract the torrent list
    torrents = search_mteam_torrents(imdb_url)["data"]["data"]

    if not torrents:
        raise ValueError(f"No torrents found on M-Team for IMDb ID: {imdb_id}")

    # Format the torrents text
    formatted_torrents = []
    for t in torrents:
        if isinstance(t, dict):
            formatted_torrents.append(format_mteam_torrent(t))
    torrents_text = "\n\n".join(formatted_torrents)

    print(f"\n=== [2] Selecting best torrents using LLM ===")
    selected_ids_str = select_best_torrents(torrents_text)
    selected_ids = [tid.strip() for tid in selected_ids_str.split() if tid.strip()]
    print(f"Selected torrent IDs: {selected_ids}")

    if not selected_ids:
        raise ValueError(f"LLM did not select any torrents for IMDb ID: {imdb_id}")

    hashes_to_process = []
    for tid in selected_ids:
        print(f"\n=== [3] Downloading .torrent for ID: {tid} ===")
        torrent_bytes = generate_mteam_download_token(tid)

        print(f"\n=== [4] Adding torrent to qBittorrent ===")
        download_torrent(qb, torrent_bytes, dl_dir)

        # Parse local hash directly instead of hoping qB orders correctly
        t_hash = get_torrent_hash(torrent_bytes)
        if not t_hash:
            print(f"Could not compute hash for {tid}, skipping!")
            continue

        print(f"\n=== [5] Waiting for download to finish ===")
        # Wait slightly for qB to process the adding request
        time.sleep(3)
        
        print(f"Tracking torrent Hash: {t_hash}")

        rename_torrent_and_folder(qb, t_hash, new_name)
        wait_for_download(qb, t_hash)
        
        hashes_to_process.append((t_hash, tid))
        
    return hashes_to_process

def process_qb_torrent(qb, t_hash: str, tid: str, new_name: str, dl_dir: str, title_dir: str, imdb_id: str, jellyfin_base_dir: str):
    """
    Uses an LLM to generate a rename mapping for the files inside a completed qBittorrent download.
    Applies tags based on TV/Movie type and creates symbolic links to the Jellyfin library.
    """
    print(f"\n=== [6] Generating rename mapping using LLM ===")
    file_tree = get_torrent_file_tree(qb, t_hash)

    src_dir_for_mapping = prepare_file_tree_paths(file_tree, new_name, dl_dir)

    file_tree_str = format_file_tree(file_tree)
    
    prompt_text = f"Base directory: `{title_dir}`\n\n{file_tree_str}"
    print(f"Sending paths to LLM...")
    mapping = generate_rename_mapping(prompt_text)
    print("Generated Mapping:")
    
    is_tv = False
    for src, dst in mapping.items():
        print(f"  {src} -->> {dst}")
        if "Season " in dst or "Series " in dst:
            is_tv = True

    tag = "Jellyfin TV" if is_tv else "Jellyfin Movie"
    opposite_tag = "Jellyfin Movie" if is_tv else "Jellyfin TV"
    
    jellyfin_dir = f"{jellyfin_base_dir}/TV" if is_tv else f"{jellyfin_base_dir}/Movie"
    jellyfin_base = Path(jellyfin_dir) / f"{title_dir} [{imdb_id}]"

    print(f"\n=== [6.5] Adding '{tag}' tag to torrent ===")
    qb.torrents_add_tags(tags=tag, torrent_hashes=t_hash)
    remove_tag_if_exists(qb, t_hash, opposite_tag)

    print(f"\n=== [7] Creating symbolic links ===")
    apply_rename_mapping(mapping, base_src_dir=src_dir_for_mapping, base_dst_dir=jellyfin_base)
    print(f"Finished processing torrent: {tid}")

def process_local_file(fs_path: Path, dl_dir: str, title_dir: str, imdb_id: str, jellyfin_base_dir: str):
    """
    Generates an LLM rename mapping for purely local files/folders (skipping qBittorrent) 
    and creates symbolic links to the Jellyfin library.
    """
    print(f"\n=== [6] Generating rename mapping using LLM for local path ===")
    
    # Mock file tree logic for local files
    file_tree = []
    if fs_path.is_file():
        file_tree.append({"name": fs_path.name})
    else:
        for p in fs_path.rglob('*'):
            if p.is_file():
                # relative to fs_path's parent so it starts with fs_path.name
                rel_path = p.relative_to(fs_path.parent)
                file_tree.append({"name": str(rel_path.as_posix())})
                
    src_dir_for_mapping = prepare_file_tree_paths(file_tree, fs_path.name, dl_dir)
    file_tree_str = format_file_tree(file_tree)
    
    prompt_text = f"Base directory: `{title_dir}`\n\n{file_tree_str}"
    print(f"Sending paths to LLM...")
    mapping = generate_rename_mapping(prompt_text)
    print("Generated Mapping:")
    
    is_tv = False
    for src, dst in mapping.items():
        print(f"  {src} -->> {dst}")
        if "Season " in dst or "Series " in dst:
            is_tv = True

    jellyfin_dir = f"{jellyfin_base_dir}/TV" if is_tv else f"{jellyfin_base_dir}/Movie"
    jellyfin_base = Path(jellyfin_dir) / f"{title_dir} [{imdb_id}]"

    print(f"\n=== [7] Creating symbolic links ===")
    apply_rename_mapping(mapping, base_src_dir=src_dir_for_mapping, base_dst_dir=jellyfin_base)
    print(f"Finished processing local file: {fs_path.name}")

def process_imdb_workflow(imdb_id: str, dl_dir: str = DEFAULT_DL_DIR, jellyfin_base_dir: str = DEFAULT_JELLYFIN_DIR):
    """
    Workflow to automatically find, download, and map torrents for an IMDb ID into a Jellyfin library.
    """
    print(f"=== [0] Fetching IMDB info for {imdb_id} ===")
    imdb_info = mteam_imdb_info(imdb_id)
    if 'data' not in imdb_info:
        raise ValueError(f"Failed to get IMDB info from M-Team: {imdb_info}")
    
    title = imdb_info['data'].get('title', 'Unknown_Title')
    year = imdb_info['data'].get('year', '')
    title_dir = f"{title} ({year})"
    print(f"Found Title: {title_dir}")

    print(f"\n=== [0.2] Checking if already exists in file system ===")
    fs_match_dir = check_local_filesystem(dl_dir, imdb_id)
    new_name = f"{year} {title} [{imdb_id}]".strip()

    if fs_match_dir:
        print(f"Found existing file/directory in file system: {fs_match_dir.name}, skipping qBit check, search, and download.")
        process_local_file(fs_match_dir, dl_dir, title_dir, imdb_id, jellyfin_base_dir)
        return

    print(f"\n=== [0.5] Checking if torrent already exists in qBittorrent ===")
    qb = get_qb_client()
    existing_t_hash = check_qbittorrent(qb, imdb_id)

    hashes_to_process = []

    if existing_t_hash:
        print(f"Found existing torrent with hash {existing_t_hash}, skipping search and download.")
        rename_torrent_and_folder(qb, existing_t_hash, new_name)
        
        print(f"\n=== [0.6] Waiting for existing download to finish ===")
        wait_for_download(qb, existing_t_hash)
        
        hashes_to_process.append((existing_t_hash, "existing"))
    else:
        hashes_to_process = search_and_download_mteam(qb, imdb_id, new_name, dl_dir)

    # Process qB torrents
    for t_hash, tid in hashes_to_process:
        process_qb_torrent(qb, t_hash, tid, new_name, dl_dir, title_dir, imdb_id, jellyfin_base_dir)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Workflow to automatically find, download, and map torrents for an IMDb ID into Jellyfin.")
    parser.add_argument("imdb_id", type=str, help="The IMDb ID to process (e.g., tt38872297)")
    parser.add_argument("--dl-dir", type=str, default=DEFAULT_DL_DIR, help="The qBittorrent download directory")
    parser.add_argument("--jellyfin-dir", type=str, default=DEFAULT_JELLYFIN_DIR, help="The base Jellyfin library directory")
    
    args = parser.parse_args()
    
    process_imdb_workflow(args.imdb_id, dl_dir=args.dl_dir, jellyfin_base_dir=args.jellyfin_dir)
