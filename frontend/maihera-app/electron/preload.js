const { contextBridge, ipcRenderer } = require('electron')
const path = require('path')

contextBridge.exposeInMainWorld('maihera', {
  // Audio file ready from backend audio_out watcher
  onAudioFile: (callback) => {
    ipcRenderer.on('audio-file-ready', (_, filepath) => callback(filepath))
  },

  // Window controls for frameless window
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  maximizeWindow: () => ipcRenderer.send('window-maximize'),
  closeWindow: () => ipcRenderer.send('window-close'),

  // App path helper
  getAppPath: () => ipcRenderer.invoke('get-app-path')
})