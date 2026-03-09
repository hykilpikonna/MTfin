import os
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


def download_torrent(qb_client: Client, torrent_source: str, save_path: str) -> str:
    """
    4. Calls qb api to download a torrent to a messy directory.
    
    :param qb_client: Authenticated qbittorrentapi.Client
    :param torrent_source: File path to a .torrent file, or a magnet link / URL.
    :param save_path: The directory where the torrent should be downloaded (e.g. the messy folder).
    :return: Response from the API.
    """
    if os.path.isfile(torrent_source):
        # It's a local .torrent file
        return qb_client.torrents_add(torrent_files=torrent_source, save_path=save_path)
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
