import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { Boom } from '@hapi/boom'
import makeWASocket, {
  downloadContentFromMessage,
  DisconnectReason,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'
import express from 'express'
import QRCode from 'qrcode'

const port = Number(process.env.PORT || 3100)
const backendUrl = String(process.env.REVORA_API_URL || '').replace(/\/$/, '')
const gatewaySecret = String(process.env.WHATSAPP_QR_GATEWAY_SECRET || '')
const authDir = path.join(os.tmpdir(), 'revora-whatsapp-auth')
const gatewayVersion = '1.1.0'
const instanceId = process.env.RENDER_INSTANCE_ID || crypto.randomUUID()
const startedAt = Math.floor(Date.now() / 1000)
const maxMediaBytes = Number(process.env.WHATSAPP_MAX_MEDIA_BYTES || 8_000_000)

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
const sentCommands = new Map()
const pendingLogs = []
let lastMessageAt = null
let lastHistorySyncAt = null
let messagesForwarded = 0
let historyMessagesForwarded = 0
let reconnectCount = 0
let lastError = null

function logEvent(level, event, message) {
  const value = String(message || '').slice(0, 500)
  pendingLogs.push({ level, event, message: value, timestamp: Math.floor(Date.now() / 1000) })
  if (pendingLogs.length > 100) pendingLogs.splice(0, pendingLogs.length - 100)
  const writer = level === 'error' ? console.error : level === 'warn' ? console.warn : console.log
  writer(`[${event}] ${value}`)
}

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
    last_error: lastError,
  }
}

function heartbeatPayload(logs) {
  return {
    state: gatewayState,
    connected: gatewayState === 'connected',
    phone: connectedPhone,
    gateway_version: gatewayVersion,
    instance_id: instanceId,
    started_at: startedAt,
    last_message_at: lastMessageAt,
    last_history_sync_at: lastHistorySyncAt,
    messages_forwarded: messagesForwarded,
    history_messages_forwarded: historyMessagesForwarded,
    reconnect_count: reconnectCount,
    last_error: lastError,
    logs,
  }
}

async function sendHeartbeat() {
  const logs = pendingLogs.splice(0, pendingLogs.length)
  try {
    await backendRequest('/webhooks/whatsapp-qr/heartbeat', {
      method: 'POST',
      body: JSON.stringify(heartbeatPayload(logs)),
    }, 1)
  } catch (error) {
    pendingLogs.unshift(...logs.slice(-50))
    console.warn(`[heartbeat] ${error.message}`)
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
    try {
      const commands = JSON.parse(await fs.readFile(path.join(authDir, 'revora-sent-commands.json'), 'utf8'))
      for (const [key, value] of Object.entries(commands || {})) sentCommands.set(key, value)
    } catch {}
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

async function mediaContent(node, type) {
  const expectedSize = Number(node?.fileLength || 0)
  if (expectedSize > maxMediaBytes) {
    logEvent('warn', 'media_too_large', `${type}: ${expectedSize} bytes`)
    return {}
  }
  try {
    const stream = await downloadContentFromMessage(node, type)
    const chunks = []
    let size = 0
    for await (const chunk of stream) {
      size += chunk.length
      if (size > maxMediaBytes) throw new Error(`attachment exceeds ${maxMediaBytes} bytes`)
      chunks.push(chunk)
    }
    return { media_base64: Buffer.concat(chunks).toString('base64') }
  } catch (error) {
    logEvent('warn', 'media_download_failed', `${type}: ${error.message}`)
    return {}
  }
}

async function messageContent(message) {
  const value = unwrapMessage(message)
  if (value.conversation) return { type: 'text', body: value.conversation }
  if (value.extendedTextMessage?.text) {
    return { type: 'text', body: value.extendedTextMessage.text }
  }
  if (value.imageMessage) {
    return {
      type: 'image', body: value.imageMessage.caption || '[Изображение]',
      media_mime_type: value.imageMessage.mimetype || 'image/jpeg',
      ...await mediaContent(value.imageMessage, 'image'),
    }
  }
  if (value.videoMessage) {
    return {
      type: 'video', body: value.videoMessage.caption || '[Видео]',
      media_mime_type: value.videoMessage.mimetype || 'video/mp4',
      ...await mediaContent(value.videoMessage, 'video'),
    }
  }
  if (value.audioMessage) return {
    type: 'audio', body: '[Голосовое сообщение]',
    media_mime_type: value.audioMessage.mimetype || 'audio/ogg',
    media_filename: 'voice.ogg',
    ...await mediaContent(value.audioMessage, 'audio'),
  }
  if (value.documentMessage) {
    return {
      type: 'document',
      body: value.documentMessage.caption || value.documentMessage.fileName || '[Документ]',
      media_mime_type: value.documentMessage.mimetype || 'application/octet-stream',
      media_filename: value.documentMessage.fileName || 'document',
      ...await mediaContent(value.documentMessage, 'document'),
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

function attributionFromMessage(message) {
  const payload = message?.message || {}
  const context = payload.extendedTextMessage?.contextInfo
    || payload.imageMessage?.contextInfo
    || payload.videoMessage?.contextInfo
    || payload.documentMessage?.contextInfo
    || payload.buttonsResponseMessage?.contextInfo
    || payload.listResponseMessage?.contextInfo
    || payload.messageContextInfo
  const reply = context?.externalAdReply
  if (!reply) return null
  const attribution = { kind: 'meta_whatsapp_click' }
  if (reply.sourceId) attribution.ad_id = String(reply.sourceId).slice(0, 120)
  if (reply.ctwaClid) attribution.ctwa_clid = String(reply.ctwaClid).slice(0, 300)
  if (reply.sourceUrl) attribution.source_url = String(reply.sourceUrl).slice(0, 1000)
  return Object.keys(attribution).length > 1 ? attribution : null
}

async function eventFromMessage(message, history = false) {
  const jid = usableJid(message)
  if (!jid || jid.endsWith('@g.us') || jid === 'status@broadcast') return null
  const content = await messageContent(message.message)
  const chatId = contactFromJid(jid)
  const id = String(message.key?.id || '')
  if (!content || !chatId || !id) return null
  return {
    id,
    chat_id: chatId,
    direction: message.key?.fromMe ? 'out' : 'in',
    message_type: content.type,
    body: content.body,
    media_base64: content.media_base64 || null,
    media_mime_type: content.media_mime_type || null,
    media_filename: content.media_filename || null,
    timestamp: timestampSeconds(message.messageTimestamp),
    history,
    attribution: attributionFromMessage(message),
  }
}

async function forwardMessages(messages, history = false) {
  connectedPhone ||= contactFromJid(socket?.user?.id)
  if (!connectedPhone) return
  const events = []
  for (const message of messages) {
    const event = await eventFromMessage(message, history)
    if (!event) continue
    if (!history && event.direction === 'out' && botMessageIds.delete(event.id)) continue
    events.push(event)
  }
  const batchSize = events.some((event) => event.media_base64) ? 1 : 100
  for (let index = 0; index < events.length; index += batchSize) {
    const batch = events.slice(index, index + batchSize)
    await backendRequest('/webhooks/whatsapp-qr/events', {
      method: 'POST',
      body: JSON.stringify({
        phone: connectedPhone,
        display_name: `WhatsApp +${connectedPhone}`,
        messages: batch,
      }),
    })
    messagesForwarded += batch.length
    if (history) historyMessagesForwarded += batch.length
  }
  if (events.length) {
    lastMessageAt = Math.floor(Date.now() / 1000)
    if (history) lastHistorySyncAt = lastMessageAt
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
        logEvent('info', 'qr_ready', 'Новый QR-код готов')
      }
      if (connection === 'open') {
        gatewayState = 'connected'
        qrDataUrl = null
        connectedPhone = contactFromJid(socket.user?.id)
        lastMessage = 'WhatsApp Business подключён'
        lastError = null
        logEvent('info', 'connected', 'WhatsApp Business подключён')
        scheduleAuthBackup()
      }
      if (connection === 'close') {
        const code = new Boom(lastDisconnect?.error).output?.statusCode
        socket = null
        connecting = null
        connectedPhone = null
        qrDataUrl = null
        reconnectCount += 1
        lastError = String(lastDisconnect?.error?.message || lastDisconnect?.error || 'connection closed').slice(0, 500)
        if (code === DisconnectReason.loggedOut) {
          gatewayState = 'logged_out'
          lastMessage = 'Связанное устройство удалено. Получите новый QR-код.'
          logEvent('error', 'logged_out', lastMessage)
          authWatcher?.close()
          authWatcher = null
          await fs.rm(authDir, { recursive: true, force: true })
          await fs.mkdir(authDir, { recursive: true })
          watchAuthDirectory()
          scheduleAuthBackup()
        } else {
          gatewayState = 'reconnecting'
          lastMessage = 'Переподключаемся к WhatsApp…'
          logEvent('warn', 'reconnecting', lastError)
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
        lastError = lastMessage
        logEvent('error', 'message_forward_failed', lastMessage)
      }
    })
    socket.ev.on('messaging-history.set', async ({ messages }) => {
      try {
        await forwardMessages(messages || [], true)
      } catch (error) {
        lastMessage = `Часть истории не синхронизировалась: ${error.message}`
        lastError = lastMessage
        logEvent('error', 'history_forward_failed', lastMessage)
      }
    })
    connecting = null
    return statusPayload()
  })().catch((error) => {
    socket = null
    connecting = null
    gatewayState = 'error'
    lastMessage = `Ошибка запуска WhatsApp: ${error.message}`
    lastError = lastMessage
    logEvent('error', 'startup_failed', lastMessage)
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
  const commandId = String(request.body?.command_id || '').trim()
  if (!socket || gatewayState !== 'connected') {
    response.status(503).json({ error: 'WhatsApp is not connected' })
    return
  }
  if (to.length < 5 || !text || text.length > 20_000) {
    response.status(422).json({ error: 'Invalid recipient or text' })
    return
  }
  if (commandId && sentCommands.has(commandId)) {
    response.json({ id: sentCommands.get(commandId), status: 'sent', duplicate: true })
    return
  }
  try {
    const sent = await socket.sendMessage(`${to}@s.whatsapp.net`, { text })
    if (sent?.key?.id) botMessageIds.add(String(sent.key.id))
    if (commandId) {
      sentCommands.set(commandId, sent?.key?.id || null)
      while (sentCommands.size > 1000) sentCommands.delete(sentCommands.keys().next().value)
      await fs.writeFile(
        path.join(authDir, 'revora-sent-commands.json'),
        JSON.stringify(Object.fromEntries(sentCommands)),
      )
      scheduleAuthBackup()
    }
    response.json({ id: sent?.key?.id || null, status: 'sent' })
    logEvent('info', 'message_sent', `Сообщение отправлено: ${sent?.key?.id || 'без id'}`)
  } catch (error) {
    lastError = `Ошибка отправки: ${error.message}`
    logEvent('error', 'send_failed', lastError)
    response.status(502).json({ error: error.message })
  }
})

app.listen(port, '0.0.0.0', () => {
  logEvent('info', 'started', `Revora WhatsApp gateway ${gatewayVersion} listening on ${port}`)
  void connectSocket()
  setInterval(() => void sendHeartbeat(), 30_000).unref()
  setTimeout(() => void sendHeartbeat(), 5_000).unref()
})

async function shutdown(signal) {
  logEvent('info', 'shutdown', `Получен ${signal}, сохраняем сессию`)
  await sendHeartbeat()
  await backupAuthDirectory().catch(() => {})
  socket?.end?.(new Error(signal))
  process.exit(0)
}

process.on('SIGTERM', () => void shutdown('SIGTERM'))
process.on('SIGINT', () => void shutdown('SIGINT'))
