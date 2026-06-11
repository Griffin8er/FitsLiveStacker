const { app, BrowserWindow, dialog, ipcMain } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
let backendProcess = null;

// Resolve backend executable path robustly for packaged and dev modes.
function resolveBackendPath() {
  if (app.isPackaged) {
    const candidates = [
      path.join(process.resourcesPath, "backend", "FitsLiveStackerBackend.exe"),
      path.join(process.resourcesPath, "backend", "FitsLiveStackerBackend", "FitsLiveStackerBackend.exe"),
      path.join(process.resourcesPath, "backend", "FitsLiveStackerBackend")
    ];

    for (const p of candidates) {
      if (fs.existsSync(p)) return p;
    }

    console.error("Backend executable not found in resources. Searched:", candidates);
    return null;
  }

  // Development: use local venv python
  return "C:\\Users\\Grcar\\OneDrive\\Desktop\\AstroLiveStacker\\backend\\.venv\\Scripts\\python.exe";
}

const backendPath = resolveBackendPath();

function startBackend() {
  if (!backendPath) {
    console.error("Cannot start backend: executable not found.");
    return;
  }

  if (app.isPackaged) {
    // If the backendPath is an exe file, spawn it directly. Use the parent
    // directory as cwd when available so relative data files resolve.
    backendProcess = spawn(backendPath, [], {
      cwd: path.dirname(backendPath) || undefined,
      windowsHide: true,
    });
  } else {
    backendProcess = spawn(
      backendPath,
      ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
      {
        cwd: "C:\\Users\\Grcar\\OneDrive\\Desktop\\AstroLiveStacker\\backend",
        windowsHide: true,
      }
    );
  }

  backendProcess.stdout.on("data", data => {
    console.log(`[BACKEND] ${data}`);
  });

  backendProcess.stderr.on("data", data => {
    console.error(`[BACKEND ERROR] ${data}`);
  });
}

function getWindowIconPath() {
  if (app.isPackaged) {
    return path.join(__dirname, "..", "dist", "fits.ico");
  }

  return path.join(__dirname, "..", "public", "fits.ico");
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1100,
    height: 800,
    title: "FitsLiveStacker",
    icon: getWindowIconPath(),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (app.isPackaged) {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  } else {
    win.loadURL("http://localhost:5173");
  }
}

ipcMain.handle("select-folder", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openDirectory"],
  });

  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }

  return result.filePaths[0];
});

app.whenReady().then(() => {
  startBackend();

  setTimeout(() => {
    createWindow();
  }, 3000);
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
  }
});