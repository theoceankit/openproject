const { app, BrowserWindow, ipcMain, dialog, Menu } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

Menu.setApplicationMenu(null);

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

ipcMain.handle("documents:stat-path", async (_event, targetPath) => {
  try {
    return { isDirectory: fs.statSync(targetPath).isDirectory() };
  } catch {
    return { isDirectory: false };
  }
});

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
