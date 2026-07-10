const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("openproject", {
  backendUrl: process.env.OPENPROJECT_BACKEND_URL || "http://localhost:8000",
  selectPaths: () => ipcRenderer.invoke("documents:select-paths"),
  listFiles: (path) => ipcRenderer.invoke("documents:list-files", path),
  openFile: (path) => ipcRenderer.invoke("documents:open-file", path),
  getPathForFile: (file) => webUtils.getPathForFile(file),
});
