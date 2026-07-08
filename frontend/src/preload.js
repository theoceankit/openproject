const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("openproject", {
  backendUrl: process.env.OPENPROJECT_BACKEND_URL || "http://localhost:8000",
  selectPaths: () => ipcRenderer.invoke("documents:select-paths"),
  getPathForFile: (file) => webUtils.getPathForFile(file),
});
