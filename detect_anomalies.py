import re
import argparse
from pathlib import Path
from utils import DEFAULT_DL_DIR, DEFAULT_JELLYFIN_DIR
from utils_qb import get_qb_client
from utils_imdb import get_imdb_info

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

def detect_anomalies(expected_tt_ids=None):
    print("Gathering basic info...")
    jellyfin_tt_ids = get_tt_ids_in_jellyfin(DEFAULT_JELLYFIN_DIR)
    
    print(f"Found {len(jellyfin_tt_ids)} linked titles in Jellyfin directories.")
    
    qb = get_qb_client()
    torrents = qb.torrents_info()
    
    print(f"\n=== Anomaly 1: Torrents with missing Jellyfin links ===")
    torrents_with_missing_links = set()
    
    for t in torrents:
        match = re.search(r'\[(tt\d+)\]', t.name)
        if match:
            tt_id = match.group(1)
            if tt_id not in jellyfin_tt_ids:
                torrents_with_missing_links.add((t.name, tt_id))
                
    if torrents_with_missing_links:
        for name, tt_id in torrents_with_missing_links:
            print(f"Warning: Torrent '{name}' has ID {tt_id} but no corresponding Jellyfin folder!")
    else:
        print("No torrent anomalies found.")
        
    print(f"\n=== Anomaly 2: Local DL folders with missing Jellyfin links ===")
    local_folders_with_missing_links = set()
    
    dl_path = Path(DEFAULT_DL_DIR)
    if dl_path.exists():
        for path in dl_path.iterdir():
            match = re.search(r'\[(tt\d+)\]', path.name)
            if match:
                tt_id = match.group(1)
                if tt_id not in jellyfin_tt_ids:
                    local_folders_with_missing_links.add((path.name, tt_id))
                    
        if local_folders_with_missing_links:
            for name, tt_id in local_folders_with_missing_links:
                print(f"Warning: Local folder '{name}' has ID {tt_id} but no corresponding Jellyfin folder!")
        else:
            print("No local folder anomalies found.")
    else:
        print(f"Download directory {DEFAULT_DL_DIR} does not exist.")
        
    print(f"\n=== Anomaly 3: TV series with < 6 episodes (Possible Movies) ===")
    tv_path = Path(DEFAULT_JELLYFIN_DIR) / "TV"
    short_series = []
    video_exts = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".webm"}
    
    if tv_path.exists():
        for series_dir in tv_path.iterdir():
            if series_dir.is_dir():
                video_count = sum(1 for p in series_dir.rglob('*') if p.is_file() and p.suffix.lower() in video_exts)
                if 0 < video_count < 6:
                    short_series.append((series_dir.name, video_count))
                    
        if short_series:
            for name, count in short_series:
                print(f"Warning: TV series '{name}' has only {count} video file(s).")
        else:
            print("No short TV series anomalies found.")
    else:
        print(f"TV directory {tv_path} does not exist.")
        
    print(f"\n=== Anomaly 5: Broken links in Jellyfin directories ===")
    broken_links = []
    linked_real_paths = []
    jellyfin_path = Path(DEFAULT_JELLYFIN_DIR)
    if jellyfin_path.exists():
        for p in jellyfin_path.rglob('*'):
            if p.is_symlink():
                if not p.exists():
                    broken_links.append(p)
                else:
                    linked_real_paths.append(str(p.resolve()))
                
        if broken_links:
            for p in broken_links:
                print(f"Warning: Broken link found: {p}")
        else:
            print("No broken links found.")
    else:
        print(f"Jellyfin directory {jellyfin_path} does not exist.")
        
    print(f"\n=== Anomaly 6: Torrents with TT IDs but NO files linked ===")
    torrents_without_file_links = []
    for t in torrents:
        match = re.search(r'\[(tt\d+)\]', t.name)
        if match:
            tt_id = match.group(1)
            # Some torrents might not have finished downloading or have no content_path yet
            if hasattr(t, 'content_path') and t.content_path:
                content_path = str(Path(t.content_path).resolve())
                has_link = False
                for rp in linked_real_paths:
                    if rp == content_path or rp.startswith(content_path + "/") or rp.startswith(content_path + "\\"):
                        has_link = True
                        break
                
                if not has_link:
                    torrents_without_file_links.append((t.name, tt_id))
                    
    if torrents_without_file_links:
        for name, tt_id in torrents_without_file_links:
            try:
                info = get_imdb_info(tt_id)
                title = info.get('data', {}).get('primaryTitle', 'Unknown Title')
            except Exception:
                title = "Unknown Title"
            print(f"Warning: Torrent '{name}' (ID {tt_id} - {title}) has zero files linked in Jellyfin!")
    else:
        print("All downloaded torrents have at least one file linked in Jellyfin.")
        
    if expected_tt_ids:
        print(f"\n=== Anomaly 4: Provided IMDb IDs missing from Jellyfin ===")
        unique_expected = set(expected_tt_ids)
        missing_ids = [tt_id for tt_id in unique_expected if tt_id not in jellyfin_tt_ids]
        if missing_ids:
            for tt_id in missing_ids:
                try:
                    info = get_imdb_info(tt_id)
                    title = info.get('data', {}).get('primaryTitle', 'Unknown Title')
                except Exception:
                    title = "Unknown Title"
                print(f"Warning: Expected ID '{tt_id}' ({title}) is not linked in Jellyfin!")
        else:
            print("All provided IMDb IDs are present in Jellyfin.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find anomalies between torrents, local downloads, and Jellyfin folders.")
    parser.add_argument("tt_ids", nargs="*", help="Optional space-separated list of IMDb IDs (e.g., tt1234567 tt7654321) to verify their presence in Jellyfin.")
    args = parser.parse_args()
    
    detect_anomalies(expected_tt_ids=args.tt_ids)
