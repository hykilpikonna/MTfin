import json
import urllib.request
import urllib.parse
from utils import with_disk_cache

@with_disk_cache('imdbapi_info')
def get_imdb_info(imdb_id: str) -> dict:
    """
    Fetch IMDb info from imdbapi.dev as a fallback or replacement for M-Team.
    """
    query = urllib.parse.quote(imdb_id)
    url = f"https://api.imdbapi.dev/titles/{query}"
    
    req = urllib.request.Request(url, headers={
        'accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0'
    })
    
    try:
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            if data and data.get("id") == imdb_id:
                return {"code": "0", "message": "SUCCESS", "data": data}
    except Exception as e:
        print(f"Error fetching from imdbapi for {imdb_id}: {e}")
        
    return {"code": "1", "message": "NOT_FOUND", "data": {}}
