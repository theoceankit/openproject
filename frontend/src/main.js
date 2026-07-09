const { app, BrowserWindow, ipcMain, dialog, Menu } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

Menu.setApplicationMenu(null);

// Mirrors backend/app/ingestion/pipeline.py's SUPPORTED_EXTENSIONS.
const SUPPORTED_EXTENSIONS = new Set([".md", ".mdx", ".pdf"]);

/** Flatten a file or folder path into the supported files it contains (recursively for folders). */
function listSupportedFiles(targetPath) {
  const stat = fs.statSync(targetPath);
  if (stat.isFile()) {
    return SUPPORTED_EXTENSIONS.has(path.extname(targetPath).toLowerCase()) ? [targetPath] : [];
  }
  const found = [];
  for (const entry of fs.readdirSync(targetPath, { withFileTypes: true })) {
    const entryPath = path.join(targetPath, entry.name);
    if (entry.isDirectory()) {
      found.push(...listSupportedFiles(entryPath));
    } else if (entry.isFile() && SUPPORTED_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
      found.push(entryPath);
    }
  }
  return found;
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    autoHideMenuBar: true,
    backgroundColor: "#0e0e0e",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, "index.html"));
  win.webContents.on("did-finish-load", () => {
    win.webContents.setZoomFactor(1.15);
  });
}

ipcMain.handle("documents:select-paths", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openFile", "openDirectory", "multiSelections"],
  });
  if (result.canceled) {
    return [];
  }
  return result.filePaths;
});

ipcMain.handle("documents:list-files", async (_event, targetPath) => {
  try {
    return listSupportedFiles(targetPath).sort();
  } catch {
    return [];
  }
});

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
