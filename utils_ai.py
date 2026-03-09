import os
from pathlib import Path
from openai import OpenAI

from utils import with_disk_cache

client = OpenAI()

def _call_openai_with_prompt(prompt_id: str, prompt_version: str, input_text: str) -> str:
    """Helper method to execute a prompt."""
    response = client.responses.create(
        prompt={
            "id": prompt_id,
            "version": prompt_version
        },
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": input_text
                    }
                ]
            }
        ],
        reasoning={
            "summary": "auto"
        },
        store=True,
        include=[
            "reasoning.encrypted_content",
            "web_search_call.action.sources"
        ]
    )
    
    # Try to extract the text response based on the new API format
    try:
        # If response is a Pydantic model
        if hasattr(response, 'output') and response.output:
            for out_msg in response.output:
                if getattr(out_msg, 'type', '') == 'message':
                    return out_msg.content[0].text
            return response.output[-1].content[0].text
        # If response is a dictionary
        elif isinstance(response, dict) and "output" in response:
            for out_msg in response["output"]:
                if out_msg.get("type") == "message":
                    return out_msg["content"][0]["text"]
            return response["output"][-1]["content"][0]["text"]
        # Fallback for choices (if API changes slightly)
        elif hasattr(response, 'choices') and response.choices:
            return response.choices[0].message.content
        return str(response)
    except Exception as e:
        print(f"Error parsing response: {e}")
        return str(response)


@with_disk_cache('select_best_torrents')
def select_best_torrents(torrents_text: str) -> str:
    """
    Calls the OpenAI API to select the best torrent IDs using a predefined prompt.
    
    :param torrents_text: A string containing formatted torrent information.
    :return: A string containing the selected torrent IDs, separated by space.
    """
    return _call_openai_with_prompt(
        prompt_id="pmpt_69ae323e0cf4819082be215f3439bed50122fe479d6e0f2f",
        prompt_version="3",
        input_text=torrents_text
    )


@with_disk_cache('generate_rename_mapping')
def generate_rename_mapping(directory_text: str) -> dict[str, str]:
    """
    Calls the OpenAI API to generate a renaming mapping for files 
    into a Jellyfin-compatible library format.
    
    :param directory_text: A string containing the base directory and list of files.
    :return: A dictionary mapping source paths to destination paths.
    """
    raw_response = _call_openai_with_prompt(
        prompt_id="pmpt_69ae4175ba248195acf5b828bcc3360707d31714c556743d",
        prompt_version="6",
        input_text=directory_text
    )
    
    mapping = {}
    for line in raw_response.splitlines():
        if " -->> " in line:
            parts = line.split(" -->> ", 1)
            if len(parts) == 2:
                mapping[parts[0].strip()] = parts[1].strip()
            else:
                print(f"Invalid line: {line}")
    return mapping


def apply_rename_mapping(mapping: dict[str, str], base_src_dir: str | Path, base_dst_dir: str | Path) -> None:
    """
    Creates symbolic links from source files to their destinations based on the provided mapping.
    Missing directories in the destination paths will be created automatically.
    
    :param mapping: Dictionary where keys are source paths and values are destination paths. 
                    These can be relative to the provided base directories.
    :param base_src_dir: The base directory where the source files reside.
    :param base_dst_dir: The base directory where the symbolic links will be created.
    """
    src_base = Path(base_src_dir).resolve()
    dst_base = Path(base_dst_dir).resolve()
    
    for src_rel, dst_rel in mapping.items():
        src_path = src_base / Path(src_rel)
        dst_path = dst_base / Path(dst_rel)
        
        # Ensure the source actually exists before creating a link to it
        if not src_path.exists():
            print(f"Warning: Source path does not exist, skipping: {src_path}")
            continue
            
        # Create parent directories for the destination if they don't exist
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create the symbolic link. If it already exists, gracefully ignore or overwrite.
        try:
            if dst_path.exists() or dst_path.is_symlink():
                dst_path.unlink()
            os.symlink(src_path, dst_path)
            print(f"Linked: {dst_path.relative_to(dst_base)} -> {src_path.name}")
        except Exception as e:
            print(f"Failed to link {src_rel} to {dst_rel}: {e}")
