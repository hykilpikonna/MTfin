import requests
import tomllib
from pathlib import Path

config = tomllib.loads(Path("config.toml").read_text())

def _get_mteam_headers() -> dict:
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'x-api-key': config["mt"]["api_key"],
        'Origin': 'https://kp.m-team.cc/',
        'Sec-GPC': '1',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin'
    }


def search_mteam_torrents(imdb_url: str, page_number: int = 1, page_size: int = 100) -> dict:
    """
    Search M-Team for torrents using IMDb URL.
    
    :param imdb_url: The IMDb URL (e.g. 'https://www.imdb.com/title/tt7742120/')
    :param page_number: The page number to fetch.
    :param page_size: The number of results per page.
    :return: Parsed JSON response from the API.
    """
    headers = _get_mteam_headers()
    headers['Content-Type'] = 'application/json'
    headers['Alt-Used'] = 'api.m-team.cc'
    
    data = {
        "pageNumber": page_number,
        "pageSize": page_size,
        "imdb": imdb_url
    }
    
    response = requests.post(
        'https://api.m-team.cc/api/torrent/search',
        headers=headers,
        json=data
    )
    response.raise_for_status()
    return response.json()


def mteam_imdb_info(id: str) -> dict:
    """
    Search M-Team for torrents using IMDb URL.
    
    :param id: The IMDb ID (e.g. 'tt7742120')
    :return: Parsed JSON response from the API.
    """
    headers = _get_mteam_headers()
    
    # Using 'files' forces requests to encode as multipart/form-data
    files = {"code": (None, id)}
    
    response = requests.post(
        'https://api.m-team.cc/api/media/imdb/info',
        headers=headers,
        files=files
    )
    response.raise_for_status()
    
    return response.json()


def generate_mteam_download_token(torrent_id: str) -> bytes:
    """
    Generate an M-Team download token for a specific torrent ID and download the torrent content.
    
    :param torrent_id: The ID of the torrent.
    :return: Torrent download content as bytes
    """
    headers = _get_mteam_headers()
    
    # Using 'files' forces requests to encode as multipart/form-data
    target_id_str = str(torrent_id)
    files = {"id": (None, target_id_str)}
    
    response = requests.post(
        'https://api.m-team.cc/api/torrent/genDlToken',
        headers=headers,
        files=files
    )
    response.raise_for_status()
    
    download_url = response.json().get("data")
    if not download_url:
        raise ValueError(f"Could not find download URL in response: {response.text}")
        
    dl_response = requests.get(download_url, headers=headers)
    dl_response.raise_for_status()
    return dl_response.content


def format_size(size_bytes: int) -> str:
    """Format bytes to a human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} B"


def format_mteam_torrent(t: dict) -> str:
    """
    Convert a single M-Team torrent dictionary to a readable string format.
    Useful info included: id, createdDate, name, smallDescr, numfiles, size, 
    labelsNew, status.views, status.seeders, status.leechers, status.timesCompleted, 
    status.promotionRule.discount, status.discount
    """
    size_bytes = int(t.get("size", 0))
    size_str = format_size(size_bytes)

    status = t.get("status", {})
    promo = status.get("promotionRule") or {}
    
    promo_discount = promo.get("discount", "NONE")
    base_discount = status.get("discount", "NONE")
    
    labels = t.get("labelsNew") or []

    lines = [
        f"[{t.get('id')}] {t.get('name')}",
        f"  {t.get('smallDescr')}",
        f"  {size_str} ({t.get('numfiles')} files) | Created {t.get('createdDate')}" 
        + (f" | Tags: {', '.join(labels)}" if labels else ""),
        f"  {status.get('seeders', 0)} seeder(s), {status.get('leechers', 0)} leecher(s), "
        f"{status.get('timesCompleted', 0)} snatched, {status.get('views', 0)} views",
        # f"    Discount:    Promo: {promo_discount} | Base: {base_discount}"
    ]
    
    return "\n".join(lines)


if __name__ == "__main__":
    print(mteam_imdb_info('tt38872297'))
