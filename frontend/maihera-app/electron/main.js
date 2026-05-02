const { app, BrowserWindow, ipcMain, Tray, Menu } = require('electron')
const path = require('path')
const fs = require('fs')

const isDev = process.env.NODE_ENV === 'development'
const AUDIO_OUT_DIR = path.join(__dirname, '..', '..', '..', 'backend', 'audio_out')

let mainWindow = null
let tray = null
let audioWatcher = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#080c14',
    titleBarStyle: 'hidden',
    frame: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
      webSecurity: false
    }
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function startAudioWatcher() {
  if (!fs.existsSync(AUDIO_OUT_DIR)) {
    fs.mkdirSync(AUDIO_OUT_DIR, { recursive: true })
  }

  audioWatcher = fs.watch(AUDIO_OUT_DIR, (eventType, filename) => {
    if (eventType === 'rename' && filename && filename.endsWith('.mp3')) {
      const filepath = path.join(AUDIO_OUT_DIR, filename)
      // Small delay to ensure file is fully written
      setTimeout(() => {
        if (fs.existsSync(filepath)) {
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('audio-file-ready', filepath)
          }
        }
      }, 100)
    }
  })
}

// IPC — window controls (frameless window needs these)
ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize()
  } else {
    mainWindow?.maximize()
  }
})
ipcMain.on('window-close', () => mainWindow?.close())

app.whenReady().then(() => {
  createWindow()
  startAudioWatcher()
})

app.on('window-all-closed', () => {
  if (audioWatcher) audioWatcher.close()
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})