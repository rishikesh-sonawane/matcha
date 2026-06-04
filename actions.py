import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".job-finder"


SAVED_FILE = CONFIG_DIR / "saved.json"


def _ensure():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _saved_ids():
    _ensure()
    if SAVED_FILE.exists():
        with open(SAVED_FILE) as f:
            return json.load(f)
    return {}


def _write_saved(data):
    _ensure()
    with open(SAVED_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_saved_jobs():
    return _saved_ids()


def is_job_saved(job_url, saved_ids=None):
    if saved_ids is None:
        saved_ids = _saved_ids()
    return job_url in saved_ids


def save_job(job, saved_ids=None):
    if saved_ids is None:
        saved_ids = _saved_ids()
    saved_ids[job.get("url", "")] = {
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "url": job.get("url", ""),
        "source": job.get("source", ""),
    }
    _write_saved(saved_ids)


def unsave_job(job_url, saved_ids=None):
    if saved_ids is None:
        saved_ids = _saved_ids()
    saved_ids.pop(job_url, None)
    _write_saved(saved_ids)
