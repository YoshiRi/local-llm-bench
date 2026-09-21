from datetime import datetime
from pathlib import Path
from huggingface_hub import snapshot_download

destination = Path('/Volumes/ExtremeSSD/LocalLLM/MLX/Jundot--Qwen3.6-35B-A3B-oQ4e-mtp')
if not Path('/Volumes/ExtremeSSD').is_mount():
    raise RuntimeError('External SSD is not mounted')
print(f'Started: {datetime.now().isoformat()}', flush=True)
snapshot_download(
    repo_id='Jundot/Qwen3.6-35B-A3B-oQ4e-mtp',
    local_dir=str(destination),
    max_workers=4,
)
print(f'Completed: {datetime.now().isoformat()} {destination}', flush=True)
