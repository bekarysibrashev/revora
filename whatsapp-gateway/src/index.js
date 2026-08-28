import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { Boom } from '@hapi/boom'
import makeWASocket, {
  DisconnectReason,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'
import express from 'express'
import QRCode from 'qrcode'

const port = Number(process.env.PORT || 3100)
const backendUrl = String(process.env.REVORA_API_URL || '').replace(/\/$/, '')
const gatewaySecret = String(process.env.WHATSAPP_QR_GATEWAY_SECRET || '')
const authDir = path.join(os.tmpdir(), 'revora-whatsapp-auth')

if (!backendUrl || !gatewaySecret) {
  throw new Error('REVORA_API_URL and WHATSAPP_QR_GATEWAY_SECRET are required')
}

let socket = null
let connecting = null
let authRestored = false
let authWatcher = null
let backupTimer = null
let backupRunning = false
let reconnectTimer = null
let gatewayState = 'starting'
let qrDataUrl = null
let connectedPhone = null
let lastMessage = 'Запускаем QR-шлюз…'
const botMessageIds = new Set()

function authorized(request) {
  const supplied = String(request.get('X-Gateway-Secret') || '')
  const expected = Buffer.from(gatewaySecret)
  const actual = Buffer.from(supplied)
  return expected.length === actual.length && crypto.timingSafeEqual(expected, actual)
}

function statusPayload() {
  return {
    state: gatewayState,
    connected: gatewayState === 'connected',
    qr_data_url: qrDataUrl,
    phone: connectedPhone,
    message: lastMessage,
  }
}

async function backendRequest(relativePath, options = {}, attempts = 3) {
  let lastError
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(`${backendUrl}/api/v1${relativePath}`, {
        ...options,
        signal: AbortSignal.timeout(60_000),
        headers: {
          'Content-Type': 'application/json',
          'X-Gateway-Secret': gatewaySecret,
          ...(options.headers || {}),
        },
      })
      if (!response.ok) {
        throw new Error(`Revora returned HTTP ${response.status}`)
      }
      return response.status === 204 ? null : response.json()
    } catch (error) {
      lastError = error
      if (attempt < attempts) {
        await new Promise((resolve) => setTimeout(resolve, attempt * 1000))
      }
    }
  }
  throw lastError
}

async function serializeAuthDirectory() {
  const files = {}
  for (const name of await fs.readdir(authDir)) {
    const filePath = path.join(authDir, name)
    const stat = await fs.stat(filePath)
    if (stat.isFile()) {
      files[name] = (await fs.readFile(filePath)).toString('base64')
    }
  }
  return Buffer.from(JSON.stringify(files), 'utf8').toString('base64')
}

async function restoreAuthDirectory() {
  if (authRestored) return
  authRestored = true
  await fs.rm(authDir, { recursive: true, force: true })
  await fs.mkdir(authDir, { recursive: true })
  try {
    const stored = await backendRequest('/webhooks/whatsapp-qr/session', { method: 'GET' })
    if (!stored?.archive) return
    const files = JSON.parse(Buffer.from(stored.archive, 'base64').toString('utf8'))
    for (const [name, content] of Object.entries(files)) {
      if (path.basename(name) !== name || typeof content !== 'string') continue
      await fs.writeFile(path.join(authDir, name), Buffer.from(content, 'base64'))
    }
    lastMessage = 'Сохранённая WhatsApp-сессия восстановлена'
  } catch (error) {
    lastMessage = `Не удалось восстановить сессию: ${error.message}`
  }
}

async function backupAuthDirectory() {
  if (backupRunning) return
  backupRunning = true
  try {
    const archive = await serializeAuthDirectory()
    await backendRequest('/webhooks/whatsapp-qr/session', {
      method: 'PUT',
      body: JSON.stringify({ archive }),
    })
  } catch (error) {
    lastMessage = `WhatsApp подключён, но сохранение сессии не удалось: ${error.message}`
  } finally {
    backupRunning = false
  }
}

function scheduleAuthBackup() {
  clearTimeout(backupTimer)
  backupTimer = setTimeout(() => void backupAuthDirectory(), 1500)
}

function watchAuthDirectory() {
  if (authWatcher) return
  authWatcher = fsSync.watch(authDir, () => scheduleAuthBackup())
}

function unwrapMessage(message) {
  let current = message || {}
  for (let index = 0; index < 4; index += 1) {
    const wrapper =
      current.ephemeralMessage ||
      current.viewOnceMessage ||
      current.viewOnceMessageV2 ||
      current.documentWithCaptionMessage
    if (!wrapper?.message) break
    current = wrapper.message
  }
  return current
}

function messageContent(message) {
  const value = unwrapMessage(message)
  if (value.conversation) return { type: 'text', body: value.conversation }
  if (value.extendedTextMessage?.text) {
    return { type: 'text', body: value.extendedTextMessage.text }
  }
  if (value.imageMessage) {
    return { type: 'image', body: value.imageMessage.caption || '[Изображение]' }
  }
  if (value.videoMessage) {
    return { type: 'video', body: value.videoMessage.caption || '[Видео]' }
  }
  if (value.audioMessage) return { type: 'audio', body: '[Голосовое сообщение]' }
  if (value.documentMessage) {
    return {
      type: 'document',
      body: value.documentMessage.caption || value.documentMessage.fileName || '[Документ]',
    }
  }
  if (value.contactMessage || value.contactsArrayMessage) {
    return { type: 'contacts', body: '[Контакт]' }
  }
  if (value.locationMessage || value.liveLocationMessage) {
    return { type: 'location', body: '[Геолокация]' }
  }
  return null
}

function timestampSeconds(value) {
  if (typeof value === 'number') return Math.trunc(value)
  if (typeof value === 'bigint') return Number(value)
  if (value?.toNumber) return value.toNumber()
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null
}

function contactFromJid(jid) {
  if (!jid) return null
  const local = String(jid).split('@')[0].split(':')[0]
  const digits = local.replace(/\D/g, '')
  return digits.length >= 5 ? digits : null
}

function usableJid(message) {
  const candidates = [message.key?.remoteJidAlt, message.key?.remoteJid]
  return candidates.find((jid) => String(jid || '').endsWith('@s.whatsapp.net')) || candidates[1]
}

function eventFromMessage(message, history = false) {
  const jid = usableJid(message)
  if (!jid || jid.endsWith('@g.us') || jid === 'status@broadcast') return null
  const content = messageContent(message.message)
  const chatId = contactFromJid(jid)
  const id = String(message.key?.id || '')
  if (!content || !chatId || !id) return null
  return {
    id,
    chat_id: chatId,
    direction: message.key?.fromMe ? 'out' : 'in',
    message_type: content.type,
    body: content.body,
    timestamp: timestampSeconds(message.messageTimestamp),
    history,
  }
}

async function forwardMessages(messages, history = false) {
  connectedPhone ||= contactFromJid(socket?.user?.id)
  if (!connectedPhone) return
  const events = []
  for (const message of messages) {
    const event = eventFromMessage(message, history)
    if (!event) continue
    if (!history && event.direction === 'out' && botMessageIds.delete(event.id)) continue
    events.push(event)
  }
  for (let index = 0; index < events.length; index += 100) {
    await backendRequest('/webhooks/whatsapp-qr/events', {
      method: 'POST',
      body: JSON.stringify({
        phone: connectedPhone,
        display_name: `WhatsApp +${connectedPhone}`,
        messages: events.slice(index, index + 100),
      }),
    })
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(() => {
    socket = null
    connecting = null
    void connectSocket()
  }, 3000)
}

async function connectSocket() {
  if (socket || connecting) return connecting || statusPayload()
  connecting = (async () => {
    await restoreAuthDirectory()
    const { state, saveCreds } = await useMultiFileAuthState(authDir)
    watchAuthDirectory()
    gatewayState = state.creds.registered ? 'connecting' : 'waiting_for_qr'
    lastMessage = state.creds.registered
      ? 'Восстанавливаем соединение с WhatsApp…'
      : 'Готовим QR-код…'
    socket = makeWASocket({
      auth: state,
      markOnlineOnConnect: false,
      syncFullHistory: true,
      generateHighQualityLinkPreview: false,
    })
    socket.ev.on('creds.update', async () => {
      await saveCreds()
      scheduleAuthBackup()
    })
    socket.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
      if (qr) {
        gatewayState = 'waiting_for_qr'
        qrDataUrl = await QRCode.toDataURL(qr, { width: 360, margin: 2 })
        lastMessage = 'Отсканируйте QR-код в WhatsApp Business'
      }
      if (connection === 'open') {
        gatewayState = 'connected'
        qrDataUrl = null
        connectedPhone = contactFromJid(socket.user?.id)
        lastMessage = 'WhatsApp Business подключён'
        scheduleAuthBackup()
      }
      if (connection === 'close') {
        const code = new Boom(lastDisconnect?.error).output?.statusCode
        socket = null
        connecting = null
        connectedPhone = null
        qrDataUrl = null
        if (code === DisconnectReason.loggedOut) {
          gatewayState = 'logged_out'
          lastMessage = 'Связанное устройство удалено. Получите новый QR-код.'
          authWatcher?.close()
          authWatcher = null
          await fs.rm(authDir, { recursive: true, force: true })
          await fs.mkdir(authDir, { recursive: true })
          watchAuthDirectory()
          scheduleAuthBackup()
        } else {
          gatewayState = 'reconnecting'
          lastMessage = 'Переподключаемся к WhatsApp…'
          scheduleReconnect()
        }
      }
    })
    socket.ev.on('messages.upsert', async ({ messages, type }) => {
      if (type !== 'notify') return
      try {
        await forwardMessages(messages, false)
      } catch (error) {
        lastMessage = `Ошибка передачи сообщения в Revora: ${error.message}`
      }
    })
    socket.ev.on('messaging-history.set', async ({ messages }) => {
      try {
        await forwardMessages(messages || [], true)
      } catch (error) {
        lastMessage = `Часть истории не синхронизировалась: ${error.message}`
      }
    })
    connecting = null
    return statusPayload()
  })().catch((error) => {
    socket = null
    connecting = null
    gatewayState = 'error'
    lastMessage = `Ошибка запуска WhatsApp: ${error.message}`
    throw error
  })
  return connecting
}

const app = express()
app.use(express.json({ limit: '16mb' }))

app.get('/health', (_request, response) => {
  response.json({ status: 'ok', state: gatewayState })
})

app.use((request, response, next) => {
  if (!authorized(request)) {
    response.status(401).json({ error: 'unauthorized' })
    return
  }
  next()
})

app.get('/status', (_request, response) => response.json(statusPayload()))

app.post('/connect', async (_request, response) => {
  try {
    await connectSocket()
    response.json(statusPayload())
  } catch (error) {
    response.status(503).json({ ...statusPayload(), error: error.message })
  }
})

app.post('/send', async (request, response) => {
  const to = String(request.body?.to || '').replace(/\D/g, '')
  const text = String(request.body?.text || '').trim()
  if (!socket || gatewayState !== 'connected') {
    response.status(503).json({ error: 'WhatsApp is not connected' })
    return
  }
  if (to.length < 5 || !text || text.length > 20_000) {
    response.status(422).json({ error: 'Invalid recipient or text' })
    return
  }
  try {
    const sent = await socket.sendMessage(`${to}@s.whatsapp.net`, { text })
    if (sent?.key?.id) botMessageIds.add(String(sent.key.id))
    response.json({ id: sent?.key?.id || null, status: 'sent' })
  } catch (error) {
    response.status(502).json({ error: error.message })
  }
})

app.listen(port, '0.0.0.0', () => {
  console.log(`Revora WhatsApp QR gateway listening on ${port}`)
  void connectSocket()
})
