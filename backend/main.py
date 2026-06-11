from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from _livestack_utils import LiveStacker
import threading
import time


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    # Allow requests from the dev server and packaged app. Packaged Electron apps
    # often use the file:// origin (or no origin), so allow all origins when
    # running inside the packaged app to avoid CORS blocking renderer requests.
    allow_origins=["*"],
    # Note: when using allow_origins=["*"] set allow_credentials to False per
    # Starlette requirements. This app does not rely on cookies/credentials.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


watch_directory = None
observer = None
stacker = None

stack_lock = threading.Lock()
processed_files = set()

APP_DATA_DIR = Path.home() / "AppData" / "Local" / "FitsLiveStacker"
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)

DISPLAY_PATH = APP_DATA_DIR / "current_stack.png"

stack_progress = {
    "running": False,
    "watching": False,
    "current": 0,
    "total": 0,
    "done": False,
    "error": None,
    "output": None,
    "last_file": None,
    "image_version": 0,
}


class DirectoryRequest(BaseModel):
    path: str


def is_fits_file(path):
    return Path(path).suffix.lower() in [".fit", ".fits"]


def wait_for_file_ready(path, checks=8, delay=0.5):
    path = Path(path)
    last_size = -1

    for _ in range(checks):
        if not path.exists():
            return False

        try:
            size = path.stat().st_size
        except OSError:
            time.sleep(delay)
            continue

        if size == last_size and size > 0:
            return True

        last_size = size
        time.sleep(delay)

    return False


def get_existing_fits_files(folder):
    folder = Path(folder)

    files = []

    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in [".fit", ".fits"]:
            files.append(p)

    return sorted(files, key=lambda p: p.stat().st_mtime)


def stack_one_file(path):
    global stacker, processed_files, stack_progress

    path = Path(path)
    path_str = str(path.resolve())

    if not is_fits_file(path):
        return

    with stack_lock:
        if path_str in processed_files:
            return

    if not wait_for_file_ready(path):
        stack_progress["error"] = f"File was not ready: {path.name}"
        return

    with stack_lock:
        if path_str in processed_files:
            return

        try:
            result = stacker.add_fits(path_str)

            if result is None:
                processed_files.add(path_str)
                stack_progress["last_file"] = f"Skipped: {path.name}"
                return

            stacker.configure_image(str(DISPLAY_PATH))

            processed_files.add(path_str)
            stack_progress["current"] += 1
            stack_progress["output"] = str(DISPLAY_PATH)
            stack_progress["last_file"] = path.name
            stack_progress["image_version"] += 1

        except Exception as e:
            stack_progress["error"] = f"{path.name}: {repr(e)}"


class FitsCreatedHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)

        if is_fits_file(path):
            threading.Thread(
                target=stack_one_file,
                args=(path,),
                daemon=True,
            ).start()

    def on_moved(self, event):
        if event.is_directory:
            return

        path = Path(event.dest_path)

        if is_fits_file(path):
            threading.Thread(
                target=stack_one_file,
                args=(path,),
                daemon=True,
            ).start()


def stack_existing_files(folder):
    try:
        folder = Path(folder)

        files = get_existing_fits_files(folder)

        stack_progress["total"] = len(files)

        for file in files:
            if not stack_progress["watching"]:
                break

            stack_one_file(file)

    except Exception as e:
        stack_progress["error"] = f"stack_existing_files error: {e}"


@app.get("/")
def root():
    return {"message": "Backend running"}


@app.get("/status")
def status():
    return {
        "watch_directory": watch_directory,
        "progress": stack_progress
    }


@app.post("/set-directory")
def set_directory(request: DirectoryRequest):
    global watch_directory

    path = Path(request.path)

    if not path.exists():
        return {"success": False, "error": "Directory does not exist"}

    if not path.is_dir():
        return {"success": False, "error": "Path is not a directory"}

    watch_directory = str(path.resolve())

    return {"success": True, "watch_directory": watch_directory}


@app.post("/start-watch-stack")
def start_watch_stack():
    global observer, stacker, processed_files, stack_progress

    if watch_directory is None:
        return {"success": False, "error": "No directory selected"}

    folder = Path(watch_directory)

    if not folder.exists():
        return {"success": False, "error": "Directory does not exist"}

    if observer is not None and observer.is_alive():
        return {"success": False, "error": "Already watching"}

    stacker = LiveStacker()
    processed_files = set()

    stack_progress = {
        "running": True,
        "watching": True,
        "current": 0,
        "total": 0,
        "done": False,
        "error": None,
        "output": None,
        "last_file": None,
        "image_version": 0,
    }

    handler = FitsCreatedHandler()
    observer = Observer()
    observer.schedule(handler, str(folder), recursive=False)
    observer.start()

    threading.Thread(
        target=stack_existing_files,
        args=(folder,),
        daemon=True,
    ).start()

    return {"success": True, "watching": str(folder)}


@app.post("/stop-watch-stack")
def stop_watch_stack():
    global observer, stack_progress

    stack_progress["watching"] = False
    stack_progress["running"] = False
    stack_progress["done"] = True

    if observer is not None:
        observer.stop()
        observer.join(timeout=3)
        observer = None

    return {"success": True, "message": "Stopped watcher"}


@app.get("/stack-progress")
def get_stack_progress():
    return stack_progress


@app.get("/stacked-image")
def stacked_image():
    output = stack_progress.get("output")

    if output is None:
        return {"success": False, "error": "No stacked image yet"}

    output = Path(output)

    if not output.exists():
        return {"success": False, "error": "Stacked image file does not exist"}

    return FileResponse(output, media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info"
    )