import json
import hashlib
from pathlib import Path
from functools import wraps

def _disk_cache_decorator(subdir_name: str, ext: str, read_func, write_func):
    """
    Generic internal caching decorator handling filename hashing and io abstraction.
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
                    
            cache_p = Path(__file__).parent / 'data' / subdir_name / f"{key}{ext}"
            
            if cache_p.is_file():
                try:
                    return read_func(cache_p)
                except Exception:
                    pass
                
            result = func(*args, **kwargs)
            
            cache_p.parent.mkdir(parents=True, exist_ok=True)
            write_func(cache_p, result)
            
            # Write arguments to a .txt file for easy lookup
            txt_p = cache_p.with_suffix('.txt')
            txt_p.write_text(f"Args: {args}\nKwargs: {kwargs}", encoding="utf-8")
            
            return result
        return wrapper
    return decorator


def with_disk_cache(subdir_name: str):
    """
    A decorator to cache function results to a local JSON file.
    The cache file is stored in `data/<subdir_name>/<key>.json`.
    """
    return _disk_cache_decorator(
        subdir_name, 
        ".json",
        read_func=lambda p: json.loads(p.read_text(encoding="utf-8")),
        write_func=lambda p, res: p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    )


def with_binary_disk_cache(subdir_name: str, ext: str = ".bin"):
    """
    A decorator to cache binary function results to a local file.
    The cache file is stored in `data/<subdir_name>/<key><ext>`.
    """
    return _disk_cache_decorator(
        subdir_name,
        ext,
        read_func=lambda p: p.read_bytes(),
        write_func=lambda p, res: p.write_bytes(res)
    )
