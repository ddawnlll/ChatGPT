#!/usr/bin/env python3
import json
import os
from pathlib import Path

def main():
    agent_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".pi" / "agent"))
    models_file = agent_dir / "models.json"
    
    source_file = Path(__file__).parent.parent / "proxy" / "examples" / "pi-models.json"
    
    if not source_file.exists():
        print(f"Error: Source {source_file} not found. Ensure you are running from the project root.")
        return
        
    with open(source_file, "r") as f:
        source_data = json.load(f)
        
    if models_file.exists():
        try:
            with open(models_file, "r") as f:
                target_data = json.load(f)
        except Exception:
            target_data = {"providers": {}}
    else:
        target_data = {"providers": {}}
        agent_dir.mkdir(parents=True, exist_ok=True)
        
    if "providers" not in target_data:
        target_data["providers"] = {}
        
    # Merge the provider
    for provider_name, provider_config in source_data.get("providers", {}).items():
        target_data["providers"][provider_name] = provider_config
        
    with open(models_file, "w") as f:
        json.dump(target_data, f, indent=2)
        
    print(f"Successfully registered 'chatgpt-wrapper' provider to pi coding agent in:\n -> {models_file}")
    print("You can now use models 'chatgpt-playwright' and 'chatgpt-authenticated' in pi!")

if __name__ == "__main__":
    main()
