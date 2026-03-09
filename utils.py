import json
import hashlib
from pathlib import Path
from functools import wraps

def with_disk_cache(subdir_name: str):
    """
    A decorator to cache function results to a local JSON file.
    The cache file is stored in `data/<subdir_name>/<key>.json`.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not args or not isinstance(args[0], str):
                key = hashlib.md5(str(args).encode()).hexdigest()
            else:
                val = args[0]
                # If it's a simple ID, use it for readability. Otherwise hash it to avoid invalid filename characters.
                if '/' not in val and '\\' not in val and len(val) < 50:
                    key = val
                else:
                    key = hashlib.md5(val.encode()).hexdigest()
                    
            cache_p = Path(__file__).parent / 'data' / subdir_name / f"{key}.json"
            
            if cache_p.is_file():
                try:
                    return json.loads(cache_p.read_text(encoding="utf-8"))
                except Exception:
                    pass
                
            result = func(*args, **kwargs)
            
            cache_p.parent.mkdir(parents=True, exist_ok=True)
            cache_p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        return wrapper
    return decorator
