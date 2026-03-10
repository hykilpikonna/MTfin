import json
from pathlib import Path

def clean_cache():
    cache_dir = Path(__file__).parent / 'data' / 'imdbapi_info'
    if not cache_dir.exists():
        print(f"Cache directory not found: {cache_dir}")
        return
        
    count = 0
    for file_p in cache_dir.glob("*.json"):
        try:
            data = json.loads(file_p.read_text(encoding="utf-8"))
            if data.get("code") == "1":
                print(f"Removing invalid cache: {file_p.name}")
                file_p.unlink()
                
                # Also remove the corresponding args/kwargs text file
                txt_p = file_p.with_suffix('.txt')
                if txt_p.exists():
                    txt_p.unlink()
                count += 1
        except Exception as e:
            print(f"Error processing {file_p.name}: {e}")
            
    print(f"Done. Removed {count} 'code=1' cache files.")

if __name__ == "__main__":
    clean_cache()
