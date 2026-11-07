const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  environment: { sandboxed: process.sandboxed, contextIsolated: process.contextIsolated },
  read: () => ipcRenderer.invoke('example:read'),
  complete: (value) => ipcRenderer.send('example:complete', value),
});
