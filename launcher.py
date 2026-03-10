import argparse
import subprocess
import concurrent.futures
import os
from pathlib import Path
from datetime import datetime
import time
import tomllib
from utils import DEFAULT_DL_DIR, DEFAULT_JELLYFIN_DIR

def run_workflow(imdb_id: str, dl_dir: str, jellyfin_dir: str, logs_dir: Path, errors_dir: Path):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{imdb_id}_{timestamp}.log"
    
    cmd = [
        "uv", "run", "workflow.py",
        imdb_id,
        "--dl-dir", dl_dir,
        "--jellyfin-dir", jellyfin_dir
    ]
    
    print(f"Starting workflow for {imdb_id}... (Logging to {log_file})")
    with open(log_file, "w", encoding="utf-8") as f:
        process = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True
        )
        process.wait()
        
    status = "SUCCESS" if process.returncode == 0 else f"FAILED (code {process.returncode})"
    if process.returncode != 0:
        error_file = errors_dir / log_file.name
        log_file.rename(error_file)
        print(f"[{status}] Workflow for {imdb_id} failed. Check {error_file} for details.")
    else:
        print(f"[{status}] Workflow for {imdb_id} completed. Check {log_file} for details.")
    return imdb_id, process.returncode

def main():
    parser = argparse.ArgumentParser(description="Multithreading launcher for IMDB workflow.")
    parser.add_argument("imdb_ids", nargs="+", help="The IMDb IDs to process (e.g., tt38872297 tt0903747)")
    parser.add_argument("--dl-dir", type=str, default=DEFAULT_DL_DIR, help="The qBittorrent download directory")
    parser.add_argument("--jellyfin-dir", type=str, default=DEFAULT_JELLYFIN_DIR, help="The base Jellyfin library directory")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers")
    parser.add_argument("--delay", type=float, default=5.0, help="Delay in seconds between starting each workflow")
    
    args = parser.parse_args()
    
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    errors_dir = Path("errors")
    errors_dir.mkdir(exist_ok=True)
    
    print(f"Launching processing for {len(args.imdb_ids)} IMDB IDs across {args.workers} workers...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = []
        for i, imdb_id in enumerate(args.imdb_ids):
            if i > 0:
                time.sleep(args.delay)
            futures.append(
                executor.submit(run_workflow, imdb_id, args.dl_dir, args.jellyfin_dir, logs_dir, errors_dir)
            )
            
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Worker generated an exception: {e}")
                
    print("All tasks finished.")

if __name__ == "__main__":
    main()
