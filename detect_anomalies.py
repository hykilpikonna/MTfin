import re
from pathlib import Path
from utils import DEFAULT_DL_DIR, DEFAULT_JELLYFIN_DIR
from utils_qb import get_qb_client

def get_tt_ids_in_jellyfin(jellyfin_dir):
    """
    Scans the Jellyfin directory (and its TV/Movie subdirectories) for any folders
    that contain an IMDb ID [tt...] in their name and returns a set of those IDs.
    """
    jellyfin_path = Path(jellyfin_dir)
    found_ids = set()
    
    # Check immediate children of Jellyfin root, and children of TV/Movie folders
    dirs_to_check = []
    if jellyfin_path.exists():
        dirs_to_check.extend(jellyfin_path.iterdir())
        for subdir in ["Movie", "TV"]:
            subpath = jellyfin_path / subdir
            if subpath.exists():
                dirs_to_check.extend(subpath.iterdir())
                
    for path in dirs_to_check:
        if path.is_dir():
            match = re.search(r'\[(tt\d+)\]', path.name)
            if match:
                found_ids.add(match.group(1))
                
    return found_ids

def detect_anomalies():
    print("Gathering basic info...")
    jellyfin_tt_ids = get_tt_ids_in_jellyfin(DEFAULT_JELLYFIN_DIR)
    
    print(f"Found {len(jellyfin_tt_ids)} linked titles in Jellyfin directories.")
    
    qb = get_qb_client()
    torrents = qb.torrents_info()
    
    print(f"\n=== Anomaly 1: Torrents with missing Jellyfin links ===")
    torrents_with_missing_links = []
    
    for t in torrents:
        match = re.search(r'\[(tt\d+)\]', t.name)
        if match:
            tt_id = match.group(1)
            if tt_id not in jellyfin_tt_ids:
                torrents_with_missing_links.append((t.name, tt_id))
                
    if torrents_with_missing_links:
        for name, tt_id in torrents_with_missing_links:
            print(f"Warning: Torrent '{name}' has ID {tt_id} but no corresponding Jellyfin folder!")
    else:
        print("No torrent anomalies found.")
        
    print(f"\n=== Anomaly 2: Local DL folders with missing Jellyfin links ===")
    local_folders_with_missing_links = []
    
    dl_path = Path(DEFAULT_DL_DIR)
    if dl_path.exists():
        for path in dl_path.iterdir():
            match = re.search(r'\[(tt\d+)\]', path.name)
            if match:
                tt_id = match.group(1)
                if tt_id not in jellyfin_tt_ids:
                    local_folders_with_missing_links.append((path.name, tt_id))
                    
        if local_folders_with_missing_links:
            for name, tt_id in local_folders_with_missing_links:
                print(f"Warning: Local folder '{name}' has ID {tt_id} but no corresponding Jellyfin folder!")
        else:
            print("No local folder anomalies found.")
    else:
        print(f"Download directory {DEFAULT_DL_DIR} does not exist.")

if __name__ == "__main__":
    detect_anomalies()
