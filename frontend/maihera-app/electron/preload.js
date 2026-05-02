const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('maihera', {
  onAudioFile: (callback) => {
    ipcRenderer.on('audio-file-ready', (_, filepath) => callback(filepath))
  },
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  maximizeWindow: () => ipcRenderer.send('window-maximize'),
  closeWindow: () => ipcRenderer.send('window-close'),
  getAppPath: () => ipcRenderer.invoke('get-app-path')
})