import json
import time
from pathlib import Path

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
    get_torrent_hash
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


def process_imdb_workflow(imdb_id: str, dl_dir: str = "/data/qb", jellyfin_base_dir: str = "/data/Jellyfin"):
    """
    Workflow to automatically find, download, and map torrents for an IMDb ID into a Jellyfin library.
    """
    print(f"=== [0] Fetching IMDB info for {imdb_id} ===")
    imdb_info = mteam_imdb_info(imdb_id)
    if 'data' not in imdb_info:
        print("Failed to get IMDB info")
        return
    
    title = imdb_info['data'].get('title', 'Unknown_Title')
    year = imdb_info['data'].get('year', '')
    title_dir = f"{title} ({year})"
    print(f"Found Title: {title_dir}")

    movietype = imdb_info['data'].get('movietype', 'Movie')
    if movietype == 'TV Series':
        jellyfin_dir = f"{jellyfin_base_dir}/TV"
    else:
        jellyfin_dir = f"{jellyfin_base_dir}/Movie"

    print(f"\n=== [1] Searching Torrents for {imdb_id} ===")
    imdb_url = f"https://www.imdb.com/title/{imdb_id}/"
    search_res = search_mteam_torrents(imdb_url)

    # Extract the torrent list
    if "data" in search_res and isinstance(search_res["data"], dict) and "data" in search_res["data"]:
        torrents = search_res["data"]["data"]
    elif "data" in search_res and isinstance(search_res["data"], list):
        torrents = search_res["data"]
    elif isinstance(search_res, list):
        torrents = search_res
    else:
        torrents = []

    if not torrents:
        print("No torrents found.")
        return

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
        print("No torrents selected.")
        return

    qb = get_qb_client()
    jellyfin_base = Path(jellyfin_dir) / f"{title_dir} [{imdb_id}]"

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

        print(f"\n=== [6] Generating rename mapping using LLM ===")
        file_tree = get_torrent_file_tree(qb, t_hash)
        file_tree_str = format_file_tree(file_tree)
        
        prompt_text = f"Base directory: `{title_dir}`\n\n{file_tree_str}"
        print(f"Sending paths to LLM...")
        mapping = generate_rename_mapping(prompt_text)
        print("Generated Mapping:")
        for src, dst in mapping.items():
            print(f"  {src} -->> {dst}")

        print(f"\n=== [7] Creating symbolic links ===")
        apply_rename_mapping(mapping, base_src_dir=dl_dir, base_dst_dir=jellyfin_base)
        print(f"Finished processing torrent: {tid}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Workflow to automatically find, download, and map torrents for an IMDb ID into Jellyfin.")
    parser.add_argument("imdb_id", type=str, help="The IMDb ID to process (e.g., tt38872297)")
    parser.add_argument("--dl-dir", type=str, default="/data/qb", help="The qBittorrent download directory")
    parser.add_argument("--jellyfin-dir", type=str, default="/data/Jellyfin", help="The base Jellyfin library directory")
    
    args = parser.parse_args()
    
    process_imdb_workflow(args.imdb_id, dl_dir=args.dl_dir, jellyfin_base_dir=args.jellyfin_dir)
