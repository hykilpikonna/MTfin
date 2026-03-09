import os
import hashlib
import bencodepy
from qbittorrentapi import Client
import tomllib
from pathlib import Path

config = tomllib.loads(Path("config.toml").read_text())

def get_qb_client() -> Client:
    """
    Initializes and returns an authenticated qBittorrent client.
    Based on existing implementations in TrackerEditor.
    """
    qb = Client(host=config["qb"]["host"], username=config["qb"]["username"], password=config["qb"]["password"])
    qb.auth_log_in()
    return qb


def download_torrent(qb_client: Client, torrent_source: str | bytes, save_path: str) -> str:
    """
    4. Calls qb api to download a torrent to a messy directory.
    
    :param qb_client: Authenticated qbittorrentapi.Client
    :param torrent_source: File path to a .torrent file, a magnet link / URL, or raw bytes.
    :param save_path: The directory where the torrent should be downloaded (e.g. the messy folder).
    :return: Response from the API.
    """
    if isinstance(torrent_source, bytes):
        return qb_client.torrents_add(torrent_files={"upload.torrent": torrent_source}, save_path=save_path)
    elif os.path.isfile(torrent_source):
        # Open and read the bytes explicitly so that qb uploads the file data,
        # negating local path security issues on the remote instance
        with open(torrent_source, "rb") as f:
            torrent_filename = os.path.basename(torrent_source)
            # Pass dictionary mappings to `torrent_files` to upload binary streams directly
            return qb_client.torrents_add(torrent_files={torrent_filename: f.read()}, save_path=save_path)
    else:
        # It's a magnet link or URL
        return qb_client.torrents_add(urls=torrent_source, save_path=save_path)


def get_torrent_file_tree(qb_client: Client, torrent_hash: str) -> list:
    """
    5. Calls qb api to view the file tree inside the torrent.
    
    :param qb_client: Authenticated qbittorrentapi.Client
    :param torrent_hash: The hash of the target torrent.
    :return: A list of dicts representing the files inside the torrent, 
             which includes their relative paths reflecting the file tree.
    """
    try:
        files = qb_client.torrents_files(torrent_hash=torrent_hash)
        
        # The API returns a list of dictionaries containing file info (name with path separators, size, etc.)
        file_tree = []
        for f in files:
            file_tree.append({
                "id": getattr(f, "id", None),
                "name": getattr(f, "name", ""),
                "size": getattr(f, "size", 0),
                "progress": getattr(f, "progress", 0)
            })
        return file_tree
    except Exception as e:
        print(f"Error fetching file tree for {torrent_hash}: {e}")
        return []

def get_torrent_hash(source: str | bytes) -> str:
    """
    Parses a local .torrent file or raw bytes and computes its info hash directly.
    """
    try:
        if isinstance(source, bytes):
            torrent_data = bencodepy.decode(source)
        else:
            with open(source, "rb") as f:
                torrent_data = bencodepy.decode(f.read())
            
        # Info dictionary is under b"info" 
        info_data = torrent_data[b"info"]
        info_encoded = bencodepy.encode(info_data)
        
        # Calculate SHA1 hash of the bencoded info dictionary
        return hashlib.sha1(info_encoded).hexdigest()
    except Exception as e:
        print(f"Could not parse torrent hash: {e}")
        return ""

def rename_torrent_and_folder(qb_client: Client, torrent_hash: str, new_name: str) -> None:
    """
    Renames the torrent display name and the top-level folder on disk to the given `new_name`.
    """
    info = qb_client.torrents_info(hashes=torrent_hash)
    if not info:
        print(f"Torrent {torrent_hash} not found to rename.")
        return
        
    t_info = info[0]
    old_name = t_info.name
    
    print(f"Renaming torrent and top-level dir from '{old_name}' to '{new_name}'")
    try:
        qb_client.torrents_rename(torrent_hash=torrent_hash, new_torrent_name=new_name)
    except Exception as e:
        print(f"Failed to rename torrent: {e}")
        
    try:
        qb_client.torrents_rename_folder(torrent_hash=torrent_hash, old_path=old_name, new_path=new_name)
    except Exception as e:
        # Might be a single-file torrent or no root folder
        print(f"Failed to rename folder: {e}")

    import time
    print("Waiting for rename to take effect...")
    for _ in range(15):  # wait up to 15 seconds
        info = qb_client.torrents_info(hashes=torrent_hash)
        if not info:
            break
            
        current_name = info[0].name
        
        # Check files to see if root path matches
        files = qb_client.torrents_files(torrent_hash=torrent_hash)
        if not files:
            time.sleep(1)
            continue
            
        all_match_or_single = True
        has_root_dir = all("/" in getattr(f, "name", "") or "\\" in getattr(f, "name", "") for f in files)
        
        if has_root_dir:
            if not all(getattr(f, "name", "").startswith(f"{new_name}/") or getattr(f, "name", "").startswith(f"{new_name}\\") for f in files):
                all_match_or_single = False
                
        if current_name == new_name and all_match_or_single:
            print("Rename confirmed by qBittorrent.")
            return
            
        time.sleep(1)
        
    print("Warning: Rename may not have fully propagated yet.")

def remove_tag_if_exists(qb_client: Client, torrent_hash: str, tag_to_remove: str) -> None:
    """
    Checks if a tag exists on a torrent, and removes it if it does.
    """
    info = qb_client.torrents_info(hashes=torrent_hash)
    if not info:
        return
        
    t_info = info[0]
    tags = getattr(t_info, "tags", "")
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        if tag_to_remove in tag_list:
            print(f"Removing existing tag '{tag_to_remove}' from torrent.")
            qb_client.torrents_remove_tags(tags=tag_to_remove, torrent_hashes=torrent_hash)
