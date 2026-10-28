import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import App from './App'
import { JobStatus } from './components/JobStatus'
import { formatDuration } from './duration'
import { api } from './api'
import type { Job } from './api'
import { MAX_FILE_SIZE, validateFile } from './components/AudioUploader'
import { POLL_INTERVAL } from './useTranscription'

const id = 'c751d5db-48c7-43cc-b479-c16ad24b3342'
const job: Job = { id, model: 'small', state: 'queued', transcript: null, error: null, engine: 'mock' }
const completed: Job = { ...job, state: 'completed', transcript: '[TESTE MOCK — small] Texto fictício.\nSegunda linha.' }
const synchronizedJob: Job = { ...completed, engine: 'whisper', transcript: ' Primeiro. Segundo.\nTerceiro.', segments: [
  { text: ' Primeiro.', start: 0.25, end: 1.25 },
  { text: ' Segundo.', start: 1.25, end: 2.5 },
  { text: '\nTerceiro.', start: 3, end: 4 },
] }
const audio = new File(['audio'], 'entrevista.WAV', { type: 'audio/wav' })
const fetchMock = vi.fn<typeof fetch>()

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

function mount() { return render(<StrictMode><App /></StrictMode>) }
function select(file = audio) {
  fireEvent.change(screen.getByLabelText('Selecionar arquivo de áudio'), { target: { files: [file] } })
}
async function settle() { await act(async () => {}) }
async function tick(ms = POLL_INTERVAL) { await act(async () => { await vi.advanceTimersByTimeAsync(ms) }) }
async function start(value: Job = job) {
  fetchMock.mockResolvedValueOnce(response(value, 202))
  select()
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar transcrição' }))
  await settle()
}

function readyAudio(duration = 6) {
  const player = screen.getByLabelText('Áudio da transcrição') as HTMLAudioElement
  Object.defineProperty(player, 'duration', { configurable: true, value: duration })
  Object.defineProperty(player, 'readyState', { configurable: true, value: 1 })
  fireEvent.loadedMetadata(player)
  return player
}

function review() { fireEvent.click(screen.getByRole('checkbox', { name: 'Revisão sincronizada' })) }

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', fetchMock)
  vi.spyOn(api, 'capabilities').mockResolvedValue({ engine: 'mock' })
  localStorage.clear()
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  fetchMock.mockReset()
})

test('seleciona, substitui e remove o arquivo; Small é o padrão', () => {
  mount()
  const submit = screen.getByRole('button', { name: 'Iniciar transcrição' }) as HTMLButtonElement
  expect(submit.disabled).toBe(true)
  expect((screen.getByRole('radio', { name: /Whisper Small/ }) as HTMLInputElement).checked).toBe(true)
  const click = vi.spyOn(HTMLInputElement.prototype, 'click')
  fireEvent.click(screen.getByRole('button', { name: /Selecionar arquivo$/ }))
  expect(click).toHaveBeenCalledOnce()
  select()
  expect(screen.getByText(audio.name)).toBeTruthy()
  expect(screen.getByText(/KiB · Pronto/)).toBeTruthy()
  expect(submit.disabled).toBe(false)
  fireEvent.click(screen.getByRole('button', { name: 'Substituir arquivo' }))
  expect(click).toHaveBeenCalledTimes(2)
  select(new File(['new'], 'outra.mp3'))
  expect(screen.getByText('outra.mp3')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Remover' }))
  expect(submit.disabled).toBe(true)
  expect(screen.queryByText('outra.mp3')).toBeNull()
})

test('arrastar e soltar aceita um arquivo e recusa seleção múltipla', () => {
  mount()
  const zone = screen.getByTestId('drop-zone')
  fireEvent.dragEnter(zone, { dataTransfer: { files: [audio] } })
  expect(zone.className).toContain('dragging')
  fireEvent.drop(zone, { dataTransfer: { files: [audio] } })
  expect(screen.getByText(audio.name)).toBeTruthy()
  expect(zone.className).not.toContain('dragging')
  fireEvent.drop(zone, { dataTransfer: { files: [audio, audio] } })
  expect(screen.getByRole('alert').textContent).toContain('um áudio por vez')
})

test.each([
  [new File(['x'], 'arquivo.exe'), 'Formato inválido'],
  [new File([], 'vazio.wav'), 'está vazio'],
])('recusa arquivo inválido %s antes do upload', (file, message) => {
  mount(); select(file)
  expect(screen.getByRole('alert').textContent).toContain(message)
  expect((screen.getByRole('button', { name: 'Iniciar transcrição' }) as HTMLButtonElement).disabled).toBe(true)
  expect(fetchMock).not.toHaveBeenCalled()
})

test('limite exato de 50 MiB e extensões sem depender de MIME', () => {
  const file = new File(['x'], 'voz.M4A', { type: 'application/octet-stream' })
  Object.defineProperty(file, 'size', { value: MAX_FILE_SIZE, configurable: true })
  expect(validateFile(file)).toBeNull()
  Object.defineProperty(file, 'size', { value: MAX_FILE_SIZE + 1 })
  expect(validateFile(file)).toContain('excede 50 MiB')
  mount(); select(file)
  expect(screen.getByRole('alert').textContent).toContain('excede 50 MiB')
})

test('envia multipart real com Medium e bloqueia envios duplicados', async () => {
  mount(); select()
  fireEvent.click(screen.getByRole('radio', { name: /Whisper Medium/ }))
  const pending = deferred<Response>()
  fetchMock.mockReturnValueOnce(pending.promise)
  const button = screen.getByRole('button', { name: 'Iniciar transcrição' })
  fireEvent.click(button); fireEvent.click(button)
  expect(fetchMock).toHaveBeenCalledOnce()
  const [url, options] = fetchMock.mock.calls[0]
  expect(url).toBe('/api/v1/jobs')
  expect(options?.method).toBe('POST')
  const body = options?.body as FormData
  expect(body.get('model')).toBe('medium')
  expect((body.get('file') as File).name).toBe(audio.name)
  expect(screen.getByText('Enviando e validando')).toBeTruthy()
  await act(async () => pending.resolve(response({ ...job, model: 'medium' }, 202)))
  expect(screen.getByText('Na fila')).toBeTruthy()
})

test('percorre fila → processamento → resultado e para o polling', async () => {
  mount(); await start()
  fetchMock.mockResolvedValueOnce(response({ ...job, state: 'processing' }))
  await tick()
  expect(screen.getByText('Processando')).toBeTruthy()
  fetchMock.mockResolvedValueOnce(response(completed))
  await tick()
  expect(screen.getByText('Concluído')).toBeTruthy()
  expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe(completed.transcript)
  expect(screen.getByText('Resultado de teste (mock).')).toBeTruthy()
  const calls = fetchMock.mock.calls.length
  await tick(100 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(calls)
})

test('não sobrepõe consultas quando a API demora', async () => {
  mount(); await start()
  const pending = deferred<Response>()
  fetchMock.mockReturnValueOnce(pending.promise)
  await tick()
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
  await act(async () => pending.resolve(response({ ...job, state: 'processing' })))
  expect(fetchMock).toHaveBeenCalledTimes(2)
  fetchMock.mockResolvedValueOnce(response(completed))
  await tick()
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

test.each([413, 422, 429, 503, 504, 500])('apresenta erro HTTP %i e permite reenviar', async status => {
  mount(); select()
  fetchMock.mockResolvedValueOnce(response({ detail: `Erro do servidor ${status}` }, status))
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar transcrição' }))
  await settle()
  expect(screen.getByRole('alert').textContent).toContain(`Erro do servidor ${status}`)
  expect((screen.getByRole('button', { name: 'Iniciar transcrição' }) as HTMLButtonElement).disabled).toBe(false)
})

test('fila cheia com resposta sem JSON usa mensagem clara', async () => {
  mount(); select()
  fetchMock.mockResolvedValueOnce(new Response('upstream', { status: 429 }))
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar transcrição' })); await settle()
  expect(screen.getByRole('alert').textContent).toContain('fila está cheia')
})

test('API inacessível no upload informa erro e mantém arquivo selecionado', async () => {
  mount(); select()
  fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar transcrição' })); await settle()
  expect(screen.getByRole('alert').textContent).toContain('conectar à API')
  expect(screen.getByText(audio.name)).toBeTruthy()
})

test('falha de consulta pausa polling; retoma sem reenviar arquivo', async () => {
  mount(); await start()
  fetchMock.mockRejectedValueOnce(new TypeError('offline'))
  await tick()
  expect(screen.getByText('Acompanhamento interrompido')).toBeTruthy()
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Retomar acompanhamento' }))
  fetchMock.mockResolvedValueOnce(response(completed))
  await tick()
  expect(screen.getByRole('textbox', { name: 'Transcrição' })).toBeTruthy()
  expect(fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
})

test('resposta fora do contrato é tratada sem publicar transcrição inválida', async () => {
  mount(); await start()
  fetchMock.mockResolvedValueOnce(response({ state: 'completed', text: 'campo errado' }))
  await tick()
  expect(screen.getByRole('alert').textContent).toContain('resposta inesperada')
  expect(screen.queryByRole('textbox', { name: 'Transcrição' })).toBeNull()
})

test('trabalho expirado para consultas e permite iniciar novamente', async () => {
  mount(); await start()
  fetchMock.mockResolvedValueOnce(response({ detail: 'Trabalho não encontrado.' }, 404))
  await tick()
  expect(screen.getByRole('alert').textContent).toContain('expirou ou não existe')
  expect(screen.queryByRole('button', { name: 'Cancelar transcrição' })).toBeNull()
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
  fireEvent.click(screen.getByRole('button', { name: 'Nova transcrição' }))
  expect((screen.getByRole('button', { name: 'Iniciar transcrição' }) as HTMLButtonElement).disabled).toBe(true)
})

test('falha terminal exibe erro do trabalho e interrompe polling', async () => {
  mount(); await start()
  fetchMock.mockResolvedValueOnce(response({ ...job, state: 'failed', error: 'Não foi possível processar o áudio.' }))
  await tick()
  expect(screen.getByText('Erro no processamento')).toBeTruthy()
  expect(screen.getByText('Não foi possível processar o áudio.')).toBeTruthy()
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test.each(['queued', 'processing'] as const)('cancela trabalho %s via DELETE e para polling', async state => {
  mount(); await start({ ...job, state })
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
  fireEvent.click(screen.getByRole('button', { name: 'Cancelar transcrição' })); await settle()
  expect(fetchMock.mock.calls[1][0]).toBe(`/api/v1/jobs/${id}`)
  expect(fetchMock.mock.calls[1][1]?.method).toBe('DELETE')
  expect(screen.getByText(/Transcrição cancelada/)).toBeTruthy()
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test('cancelamento aborta consulta em voo e ignora resultado atrasado', async () => {
  mount(); await start()
  const pending = deferred<Response>()
  fetchMock.mockReturnValueOnce(pending.promise)
  await tick()
  const signal = fetchMock.mock.calls[1][1]?.signal
  fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }))
  fireEvent.click(screen.getByRole('button', { name: 'Cancelar transcrição' })); await settle()
  expect(signal?.aborted).toBe(true)
  await act(async () => pending.resolve(response(completed)))
  expect(screen.queryByRole('textbox', { name: 'Transcrição' })).toBeNull()
  expect(screen.getByText(/Transcrição cancelada/)).toBeTruthy()
})

test('cancelamento não confirmado mantém controle do trabalho e permite tentar de novo', async () => {
  mount(); await start()
  fetchMock.mockRejectedValueOnce(new TypeError('offline'))
  fireEvent.click(screen.getByRole('button', { name: 'Cancelar transcrição' })); await settle()
  expect(screen.getByRole('alert').textContent).toContain('Não foi possível confirmar o cancelamento')
  expect(screen.queryByText(/Transcrição cancelada/)).toBeNull()
  expect(screen.getByRole('button', { name: 'Cancelar transcrição' })).toBeTruthy()
  fetchMock.mockResolvedValueOnce(response({ ...job, state: 'processing' }))
  await tick()
  expect(screen.getByText('Processando')).toBeTruthy()
})

test('DELETE 404 informa indisponibilidade sem afirmar que cancelou', async () => {
  mount(); await start()
  fetchMock.mockResolvedValueOnce(response({ detail: 'not found' }, 404))
  fireEvent.click(screen.getByRole('button', { name: 'Cancelar transcrição' })); await settle()
  expect(screen.getByText('Trabalho indisponível')).toBeTruthy()
  expect(screen.queryByText(/Transcrição cancelada/)).toBeNull()
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test('desmontagem aborta consulta em voo e elimina timers', async () => {
  const view = mount(); await start()
  const pending = deferred<Response>()
  fetchMock.mockReturnValueOnce(pending.promise)
  await tick()
  const signal = fetchMock.mock.calls[1][1]?.signal
  view.unmount()
  expect(signal?.aborted).toBe(true)
  await act(async () => pending.resolve(response(completed)))
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledTimes(2)
})

test('desmontagem aborta upload', async () => {
  const view = mount(); select()
  const pending = deferred<Response>()
  fetchMock.mockReturnValueOnce(pending.promise)
  fireEvent.click(screen.getByRole('button', { name: 'Iniciar transcrição' }))
  const signal = fetchMock.mock.calls[0][1]?.signal
  view.unmount()
  expect(signal?.aborted).toBe(true)
  await act(async () => pending.resolve(response(job, 202)))
  await tick(10 * POLL_INTERVAL)
  expect(fetchMock).toHaveBeenCalledOnce()
})

test.each([false, true])('edita, copia e exporta texto local com quebras de linha; modo sincronizado: %s', async synchronized => {
  mount(); await start(synchronizedJob)
  const text = 'Minha revisão.\n\n' + Array.from({ length: 500 }, (_, line) => `Linha ${line + 1}: ação, voz e atenção.`).join('\n')
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  fireEvent.change(screen.getByRole('textbox', { name: 'Transcrição' }), { target: { value: text } })
  if (synchronized) review()
  fireEvent.click(screen.getByRole('button', { name: 'Copiar' })); await settle()
  expect(writeText).toHaveBeenCalledWith(text)
  expect(screen.getByRole('button', { name: 'Copiado' })).toBeTruthy()
  expect(screen.getByText('Texto copiado para a área de transferência.')).toBeTruthy()
  const create = vi.fn().mockReturnValue('blob:download')
  const revoke = vi.fn()
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = create
    static revokeObjectURL = revoke
  })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe('entrevista.txt')
    expect(this.href).toBe('blob:download')
  })
  fireEvent.click(screen.getByRole('button', { name: 'Exportar TXT' }))
  expect(click).toHaveBeenCalledOnce()
  const blob = create.mock.calls[0][0] as Blob
  expect(blob.type).toBe('text/plain;charset=utf-8')
  await tick(1000)
  expect(revoke).toHaveBeenCalledWith('blob:download')
  // FileReader's native I/O is not a polling timer; read without a timed wait.
  vi.useRealTimers()
  const reader = new FileReader()
  const read = new Promise(resolve => { reader.onload = () => resolve(reader.result) })
  reader.readAsText(blob)
  expect(await read).toBe(text)
})

test('falha de clipboard informa alternativa e preserva texto', async () => {
  mount(); await start(completed)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) }, configurable: true })
  fireEvent.click(screen.getByRole('button', { name: 'Copiar' })); await settle()
  expect(screen.getByText(/Não foi possível copiar/)).toBeTruthy()
  expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe(completed.transcript)
})

test('player usa endpoint real e permite tentar novamente em falha', async () => {
  mount(); await start(completed)
  const player = screen.getByLabelText('Áudio da transcrição') as HTMLAudioElement
  expect(player.getAttribute('src')).toBe(api.audioUrl(id))
  expect(player.controls).toBe(true)
  expect(player.preload).toBe('metadata')
  fireEvent.error(player)
  expect(screen.getByRole('alert').textContent).toContain('Não foi possível reproduzir')
  fireEvent.click(screen.getByRole('button', { name: 'Tentar carregar áudio novamente' }))
  expect(screen.queryByRole('alert')).toBeNull()
  expect(screen.getByLabelText('Áudio da transcrição')).not.toBe(player)
})

test('nova transcrição preserva revisão até descarte explícito', async () => {
  mount(); await start(completed)
  fireEvent.change(screen.getByRole('textbox', { name: 'Transcrição' }), { target: { value: 'Editado' } })
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: 'Nova transcrição' }))
  expect(screen.getByRole('alert').textContent).toContain('descarta suas edições')
  fireEvent.click(screen.getByRole('button', { name: 'Continuar revisão' }))
  expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe('Editado')
  fireEvent.click(screen.getByRole('button', { name: 'Nova transcrição' }))
  fireEvent.click(screen.getByRole('button', { name: 'Descartar e iniciar nova' }))
  expect(screen.queryByRole('textbox', { name: 'Transcrição' })).toBeNull()
  expect(screen.getByRole('button', { name: 'Iniciar transcrição' })).toBeTruthy()
})

test('alterna tema e restaura preferência ao abrir a interface', () => {
  localStorage.setItem('transcritor-theme', 'dark')
  mount()
  expect(document.documentElement.dataset.theme).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: 'Ativar tema claro' }))
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(localStorage.getItem('transcritor-theme')).toBe('light')
})

test('abas mantêm editor, texto e player montados ao alternar', async () => {
  mount(); await start(completed)
  const editor = screen.getByRole('textbox', { name: 'Transcrição' })
  const player = screen.getByLabelText('Áudio da transcrição')
  fireEvent.change(editor, { target: { value: 'Revisão preservada entre abas.' } })
  fireEvent.click(screen.getByRole('tab', { name: 'Áudio' }))
  expect(screen.getByRole('tab', { name: 'Áudio' }).getAttribute('aria-selected')).toBe('true')
  expect(screen.getByRole('tabpanel', { name: 'Transcrição' }).getAttribute('data-active')).toBe('false')
  fireEvent.click(screen.getByRole('tab', { name: 'Transcrição' }))
  expect(screen.getByRole('textbox', { name: 'Transcrição' })).toBe(editor)
  expect((editor as HTMLTextAreaElement).value).toBe('Revisão preservada entre abas.')
  expect(screen.getByLabelText('Áudio da transcrição')).toBe(player)
})

test('abas suportam setas, Home e End com foco e tabIndex corretos', () => {
  mount()
  const audioTab = screen.getByRole('tab', { name: 'Áudio' })
  const transcriptTab = screen.getByRole('tab', { name: 'Transcrição' })
  fireEvent.keyDown(audioTab, { key: 'ArrowRight' })
  expect(document.activeElement).toBe(transcriptTab)
  expect(transcriptTab.tabIndex).toBe(0)
  expect(audioTab.tabIndex).toBe(-1)
  fireEvent.keyDown(transcriptTab, { key: 'ArrowLeft' })
  expect(document.activeElement).toBe(audioTab)
  fireEvent.keyDown(audioTab, { key: 'End' })
  expect(document.activeElement).toBe(transcriptTab)
  fireEvent.keyDown(transcriptTab, { key: 'Home' })
  expect(document.activeElement).toBe(audioTab)
})

test('conclusão abre aba de transcrição e foca sua aba em telas móveis', async () => {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
  mount(); await start(completed)
  const transcriptTab = screen.getByRole('tab', { name: 'Transcrição' })
  expect(transcriptTab.getAttribute('aria-selected')).toBe('true')
  expect(document.activeElement).toBe(transcriptTab)
  fireEvent.click(screen.getByRole('tab', { name: 'Áudio' }))
  fireEvent.click(screen.getByRole('button', { name: /Revisar transcrição/ }))
  expect(document.activeElement).toBe(transcriptTab)
  fireEvent.click(screen.getByRole('button', { name: 'Nova transcrição' }))
  expect(screen.getByRole('tab', { name: 'Áudio' }).getAttribute('aria-selected')).toBe('true')
})

test('altura acompanha viewport reduzido pelo teclado sem bloquear zoom', () => {
  const viewport = Object.assign(new EventTarget(), { height: 800, scale: 1 })
  vi.stubGlobal('visualViewport', viewport)
  const view = mount()
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('800px')
  viewport.height = 360
  viewport.dispatchEvent(new Event('resize'))
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('360px')
  viewport.scale = 2
  viewport.dispatchEvent(new Event('resize'))
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('100dvh')
  view.unmount()
  expect(document.documentElement.style.getPropertyValue('--app-height')).toBe('')
})

test.each(['mock', 'whisper'] as const)('identifica %s pelas capacidades antes do upload', async engine => {
  vi.mocked(api.capabilities).mockResolvedValue({ engine })
  mount(); await settle()
  expect(screen.queryByText('Modo de teste') !== null).toBe(engine === 'mock')
  expect(screen.queryByText('Transcritor mock.') !== null).toBe(engine === 'mock')
  expect(screen.queryByText('Whisper real') !== null).toBe(engine === 'whisper')
})

test('mecanismo do trabalho prevalece e texto não determina se é mock', async () => {
  mount(); await settle()
  expect(screen.getByText('Modo de teste')).toBeTruthy()
  await start({ ...completed, engine: 'whisper' })
  expect(screen.getByText('Whisper real')).toBeTruthy()
  expect(screen.queryByText('Modo de teste')).toBeNull()
  expect(screen.queryByText('Transcritor mock.')).toBeNull()
  expect(screen.queryByText('Resultado de teste (mock).')).toBeNull()
  expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe(completed.transcript)
})

test('mock fornecido pela API é identificado mesmo sem prefixo no texto', async () => {
  vi.mocked(api.capabilities).mockResolvedValue({ engine: 'whisper' })
  mount(); await start({ ...completed, engine: 'mock', transcript: 'Texto sem marca especial.' })
  expect(screen.getByText('Modo de teste')).toBeTruthy()
  expect(screen.getByText('Resultado de teste (mock).')).toBeTruthy()
  expect(screen.queryByText('Whisper real')).toBeNull()
})

test('API antiga sem campo engine continua funcional sem adivinhar origem pelo prefixo', async () => {
  vi.mocked(api.capabilities).mockRejectedValue(new Error('404'))
  mount(); await settle()
  expect(screen.queryByText('Modo de teste')).toBeNull()
  expect(screen.queryByText('Whisper real')).toBeNull()
  const { engine: _engine, ...legacy } = completed
  await start(legacy)
  expect(screen.getByRole('textbox', { name: 'Transcrição' })).toBeTruthy()
  expect(screen.queryByText('Resultado de teste (mock).')).toBeNull()
})

test('rejeita engine inválido no contrato do trabalho', async () => {
  mount(); await start()
  fetchMock.mockResolvedValueOnce(response({ ...completed, engine: 'external' }))
  await tick()
  expect(screen.getByRole('alert').textContent).toContain('resposta inesperada')
  expect(screen.queryByRole('textbox', { name: 'Transcrição' })).toBeNull()
})

test('consulta endpoint de capacidades e rejeita mecanismo inválido', async () => {
  vi.mocked(api.capabilities).mockRestore()
  const controller = new AbortController()
  fetchMock.mockResolvedValueOnce(response({ engine: 'whisper' }))
  expect(await api.capabilities(controller.signal)).toEqual({ engine: 'whisper' })
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/capabilities')
  expect(fetchMock.mock.calls[0][1]?.signal).toBe(controller.signal)
  fetchMock.mockResolvedValueOnce(response({ engine: 'external' }))
  await expect(api.capabilities(controller.signal)).rejects.toThrow('mecanismo inesperado')
})

test('ignora capacidades atrasadas após desmontar', async () => {
  const pending = deferred<{ engine: 'mock' }>()
  vi.mocked(api.capabilities).mockReturnValue(pending.promise)
  const view = mount()
  const signals = vi.mocked(api.capabilities).mock.calls.map(([signal]) => signal)
  view.unmount()
  expect(signals.every(signal => signal.aborted)).toBe(true)
  await act(async () => pending.resolve({ engine: 'mock' }))
})


test.each([
  [0, '00:00'], [59.99, '00:59'], [60, '01:00'], [3599, '59:59'],
  [3600, '1:00:00'], [3661, '1:01:01'], [360000, '100:00:00'],
  [-1, '00:00'], [NaN, '00:00'], [Infinity, '00:00'],
])('formata duração %s como %s', (seconds, expected) => {
  expect(formatDuration(seconds)).toBe(expected)
})

test('contador cresce, não recua entre consultas e termina com o valor real', async () => {
  const processing: Job = { ...job, state: 'processing', processing_seconds: 150, total_seconds: 160 }
  const view = render(<JobStatus job={processing} uploading={false} paused={false} missing={false} />)
  expect(screen.getByText(/Processando/).textContent).toBe('Processando · 02:30')
  await tick(5000)
  expect(screen.getByText(/Processando/).textContent).toBe('Processando · 02:35')
  view.rerender(<JobStatus job={{ ...processing, processing_seconds: 152 }} uploading={false} paused={false} missing={false} />)
  expect(screen.getByText(/Processando/).textContent).toBe('Processando · 02:35')
  view.rerender(<JobStatus job={{ ...completed, processing_seconds: 156, total_seconds: 166 }} uploading={false} paused={false} missing={false} />)
  expect(screen.getByText('Concluído em 02:36')).toBeTruthy()
  expect(vi.getTimerCount()).toBe(0)
  await tick(10000)
  expect(screen.getByText('Concluído em 02:36')).toBeTruthy()
})

test.each(['cancel', 'paused', 'missing', 'failed'] as const)('contador para em %s e limpa na desmontagem', async mode => {
  const processing: Job = { ...job, state: 'processing', processing_seconds: 10 }
  const props = { uploading: false, paused: false, missing: false }
  const view = render(<JobStatus {...props} job={processing} />)
  expect(vi.getTimerCount()).toBe(1)
  view.rerender(<JobStatus {...props} job={mode === 'failed' ? { ...processing, state: 'failed' } : processing}
    cancelling={mode === 'cancel'} paused={mode === 'paused'} missing={mode === 'missing'} />)
  expect(vi.getTimerCount()).toBe(0)
  view.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

test('painel apresenta duração do áudio, modelo e métricas distintas', async () => {
  mount(); await start({ ...completed, model: 'medium', audio_duration_seconds: 3661, processing_seconds: 236, total_seconds: 250 })
  expect(screen.getByText('Whisper Medium')).toBeTruthy()
  expect(screen.getByText('1:01:01')).toBeTruthy()
  expect(screen.getByText('Concluído em 03:56')).toBeTruthy()
  expect(screen.getByText('04:10')).toBeTruthy()
  expect(screen.getByText(/Total inclui a fila/)).toBeTruthy()
})

test.each(['total_seconds', 'processing_seconds', 'audio_duration_seconds'])('rejeita duração inválida em %s', async key => {
  for (const invalid of [-1, '12', {}]) {
    fetchMock.mockResolvedValueOnce(response({ ...completed, [key]: invalid }))
    await expect(api.get(id, new AbortController().signal)).rejects.toThrow('resposta inesperada')
  }
})


test('fila não inventa processamento e desmontagem limpa contador ativo', async () => {
  const props = { uploading: false, paused: false, missing: false }
  const view = render(<StrictMode><JobStatus {...props} job={{ ...job, total_seconds: 120, processing_seconds: null }} /></StrictMode>)
  expect(screen.getByText('Na fila')).toBeTruthy()
  expect(vi.getTimerCount()).toBe(0)
  view.rerender(<StrictMode><JobStatus {...props} job={{ ...job, state: 'processing', processing_seconds: 0 }} /></StrictMode>)
  await tick(2000)
  expect(screen.getByText(/Processando/).textContent).toBe('Processando · 00:02')
  expect(vi.getTimerCount()).toBe(1)
  view.unmount()
  expect(vi.getTimerCount()).toBe(0)
})

test.each([undefined, null, [], {}, 'invalid'])(
  'metadados de segmentos ausentes ou inutilizáveis (%s) preservam o editor', async segments => {
    mount(); await start({ ...synchronizedJob, segments } as Job)
    expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe(synchronizedJob.transcript)
    expect((screen.getByRole('checkbox', { name: 'Revisão sincronizada' }) as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByText('Sem timestamps válidos para sincronizar.')).toBeTruthy()
  },
)

test('valida segmentos opcionais sem perder texto ou aceitar valores inválidos', async () => {
  const invalid = [null, 1, [], {}, { text: '', start: 0, end: 1 }, { text: ' \n', start: 0, end: 1 },
    { text: 3, start: 0, end: 1 }, { text: 'a', start: -1, end: 1 }, { text: 'a', start: '0', end: 1 },
    { text: 'a', start: true, end: 1 }, { text: 'a', start: 1, end: 1 }, { text: 'a', start: 2, end: 1 },
    { text: 'a', start: NaN, end: 1 }, { text: 'a', start: 0, end: Infinity }, { text: 'a', start: 0 }]
  fetchMock.mockResolvedValueOnce(response({ ...synchronizedJob, segments: [...invalid, ...synchronizedJob.segments!] }))
  const result = await api.get(id, new AbortController().signal)
  expect(result.segments).toEqual(synchronizedJob.segments)
  expect(result.transcript).toBe(synchronizedJob.transcript)
})

test('mock nunca associa seus segmentos ao áudio', async () => {
  mount(); await start({ ...synchronizedJob, engine: 'mock' })
  expect((screen.getByRole('checkbox', { name: 'Revisão sincronizada' }) as HTMLInputElement).disabled).toBe(true)
  expect(screen.getByRole('textbox', { name: 'Transcrição' })).toBeTruthy()
})

test('sincroniza limites, lacunas, avanço e retorno do player sem mudar o texto', async () => {
  mount(); await start(synchronizedJob)
  expect((screen.getByRole('checkbox', { name: 'Revisão sincronizada' }) as HTMLInputElement).checked).toBe(false)
  const player = readyAudio()
  review()
  const segments = screen.getAllByRole('button', { name: /Primeiro\.|Segundo\.|Terceiro\./ })
  for (const [time, index] of [[0, -1], [0.25, 0], [1.249, 0], [1.25, 1], [2.5, -1], [2.9, -1], [3, 2], [4, -1], [0.5, 0]]) {
    player.currentTime = time
    fireEvent.timeUpdate(player)
    expect(segments.map(button => button.getAttribute('aria-current'))).toEqual(segments.map((_, i) => i === index ? 'true' : null))
  }
  player.currentTime = 3.5
  fireEvent.seeking(player)
  expect(segments[2].getAttribute('aria-current')).toBe('true')
  player.currentTime = 6
  fireEvent.ended(player)
  expect(segments.every(button => !button.hasAttribute('aria-current'))).toBe(true)
  review()
  expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe(synchronizedJob.transcript)
})

test('clicar em trecho avança em segundos, reproduz e destaca imediatamente', async () => {
  mount(); await start(synchronizedJob)
  const player = readyAudio()
  const play = vi.spyOn(player, 'play').mockResolvedValue(undefined)
  review()
  const second = screen.getByRole('button', { name: /Segundo\./ })
  fireEvent.click(second)
  await settle()
  expect(player.currentTime).toBe(1.25)
  expect(play).toHaveBeenCalledOnce()
  expect(second.getAttribute('aria-current')).toBe('true')
})

test('trechos são botões nativos e setas, Home e End navegam sem reproduzir', async () => {
  mount(); await start(synchronizedJob)
  const player = readyAudio()
  const play = vi.spyOn(player, 'play').mockResolvedValue(undefined)
  review()
  const first = screen.getByRole('button', { name: /Primeiro\./ }) as HTMLButtonElement
  const second = screen.getByRole('button', { name: /Segundo\./ })
  const third = screen.getByRole('button', { name: /Terceiro\./ })
  expect(first.type).toBe('button') // Native Enter/Space activation; no custom key interception.
  expect(first.tabIndex).toBe(0)
  first.focus()
  fireEvent.keyDown(first, { key: 'ArrowDown' })
  expect(document.activeElement).toBe(second)
  fireEvent.keyDown(second, { key: 'End' })
  expect(document.activeElement).toBe(third)
  fireEvent.keyDown(third, { key: 'ArrowUp' })
  expect(document.activeElement).toBe(second)
  fireEvent.keyDown(second, { key: 'Home' })
  expect(document.activeElement).toBe(first)
  expect(play).not.toHaveBeenCalled()
  player.currentTime = 3.5
  fireEvent.timeUpdate(player)
  expect(document.activeElement).toBe(first)
})

test('segue trecho ativo rolando apenas o painel interno', async () => {
  mount(); await start(synchronizedJob)
  const player = readyAudio()
  review()
  const list = screen.getByRole('list', { name: 'Trechos da transcrição original' })
  vi.spyOn(list, 'getBoundingClientRect').mockReturnValue({ top: 10, bottom: 110 } as DOMRect)
  vi.spyOn(list.children[2], 'getBoundingClientRect').mockReturnValue({ top: 150, bottom: 190 } as DOMRect)
  player.currentTime = 3.5
  fireEvent.timeUpdate(player)
  expect(list.scrollTop).toBe(80)
  expect(document.documentElement.scrollTop).toBe(0)
  expect(document.body.scrollTop).toBe(0)
})

test('velocidades solicitadas afetam o áudio e sobrevivem à recarga, sem alterar timestamps', async () => {
  mount(); await start(synchronizedJob)
  const speed = screen.getByRole('combobox', { name: 'Velocidade de reprodução' }) as HTMLSelectElement
  expect(speed.disabled).toBe(true)
  let player = readyAudio()
  expect(speed.disabled).toBe(false)
  expect(player.playbackRate).toBe(1)
  expect(Array.from(speed.options, option => option.textContent)).toEqual(['0,75×', '1×', '1,25×', '1,5×', '2×'])
  review()
  player.currentTime = 1.5
  fireEvent.timeUpdate(player)
  for (const rate of [0.75, 1, 1.25, 1.5, 2]) {
    fireEvent.change(speed, { target: { value: String(rate) } })
    expect(player.playbackRate).toBe(rate)
    expect(screen.getByRole('button', { name: /Segundo\./ }).getAttribute('aria-current')).toBe('true')
  }
  fireEvent.error(player)
  expect(speed.disabled).toBe(true)
  expect(screen.getByRole('button', { name: /Segundo\./ }).getAttribute('aria-current')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Tentar carregar áudio novamente' }))
  player = readyAudio()
  expect(player.playbackRate).toBe(2)
  expect(speed.value).toBe('2')
  player.playbackRate = 0.5 // A browser's native controls may offer other rates.
  fireEvent.rateChange(player)
  expect(speed.value).toBe('0.5')
  expect(screen.getByRole('option', { name: '0,5×' })).toBeTruthy()
})

test('áudio indisponível e trechos fora da duração não permitem saltos inválidos', async () => {
  mount(); await start(synchronizedJob)
  review()
  const first = screen.getByRole('button', { name: /Primeiro\./ }) as HTMLButtonElement
  expect(first.disabled).toBe(true)
  const player = readyAudio(3)
  expect(first.disabled).toBe(false)
  expect((screen.getByRole('button', { name: /Terceiro\./ }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.error(player)
  expect(first.disabled).toBe(true)
  expect(screen.getByText(/Carregue ou tente novamente/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Tentar carregar áudio novamente' }))
  readyAudio()
  expect(first.disabled).toBe(false)
})

test('falha ao iniciar reprodução informa alternativa e preserva revisão', async () => {
  mount(); await start(synchronizedJob)
  const player = readyAudio()
  vi.spyOn(player, 'play').mockRejectedValue(new Error('blocked'))
  review()
  fireEvent.click(screen.getByRole('button', { name: /Segundo\./ }))
  await settle()
  expect(screen.getByText(/Não foi possível iniciar a reprodução/)).toBeTruthy()
  review()
  expect((screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement).value).toBe(synchronizedJob.transcript)
})

test('alternar modo e abas preserva editor e áudio; novo trabalho reinicia sincronização e velocidade', async () => {
  mount(); await start(synchronizedJob)
  const player = readyAudio()
  const editor = screen.getByRole('textbox', { name: 'Transcrição' }) as HTMLTextAreaElement
  fireEvent.change(editor, { target: { value: 'Revisão independente.' } })
  review()
  expect(screen.getByRole('button', { name: /Primeiro\./ }).textContent).toContain('Primeiro.')
  expect(screen.queryByRole('textbox', { name: 'Transcrição' })).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'Áudio' }))
  fireEvent.click(screen.getByRole('tab', { name: 'Transcrição' }))
  expect(screen.getByLabelText('Áudio da transcrição')).toBe(player)
  review()
  expect(screen.getByRole('textbox', { name: 'Transcrição' })).toBe(editor)
  expect(editor.value).toBe('Revisão independente.')
  fireEvent.change(screen.getByRole('combobox', { name: 'Velocidade de reprodução' }), { target: { value: '2' } })
  review()
  fireEvent.click(screen.getByRole('button', { name: 'Nova transcrição' }))
  fireEvent.click(screen.getByRole('button', { name: 'Descartar e iniciar nova' }))
  const nextId = 'd751d5db-48c7-43cc-b479-c16ad24b3342'
  await start({ ...synchronizedJob, id: nextId })
  expect((screen.getByRole('checkbox', { name: 'Revisão sincronizada' }) as HTMLInputElement).checked).toBe(false)
  expect((screen.getByRole('combobox', { name: 'Velocidade de reprodução' }) as HTMLSelectElement).value).toBe('1')
  expect(screen.getByLabelText('Áudio da transcrição').getAttribute('src')).toBe(api.audioUrl(nextId))
  review()
  expect((screen.getByRole('button', { name: /Primeiro\./ }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.queryByText('Revisão independente.')).toBeNull()
})

test('intervalos sobrepostos ou fora de ordem escolhem o primeiro trecho correspondente', async () => {
  mount(); await start({ ...synchronizedJob, segments: [
    { text: 'Sobreposição', start: 1, end: 3 }, { text: 'Anterior', start: 0, end: 2 },
  ] })
  const player = readyAudio()
  review()
  player.currentTime = 1.5
  fireEvent.timeUpdate(player)
  expect(screen.getByRole('button', { name: /Sobreposição/ }).getAttribute('aria-current')).toBe('true')
  expect(screen.getByRole('button', { name: /Anterior/ }).getAttribute('aria-current')).toBeNull()
  player.currentTime = 0.5
  fireEvent.timeUpdate(player)
  expect(screen.getByRole('button', { name: /Anterior/ }).getAttribute('aria-current')).toBe('true')
})

test('atalho de revisão no desktop foca a lista quando o editor está oculto', async () => {
  mount(); await start(synchronizedJob)
  readyAudio()
  review()
  fireEvent.click(screen.getByRole('button', { name: /Revisar transcrição/ }))
  expect(document.activeElement).toBe(screen.getByRole('list', { name: 'Trechos da transcrição original' }))
  review()
  fireEvent.click(screen.getByRole('button', { name: /Revisar transcrição/ }))
  expect(document.activeElement).toBe(screen.getByRole('textbox', { name: 'Transcrição' }))
})

test('metadados de áudio inválidos limpam a posição e bloqueiam os controles até recuperar', async () => {
  mount(); await start(synchronizedJob)
  const player = readyAudio()
  review()
  const first = screen.getByRole('button', { name: /Primeiro\./ }) as HTMLButtonElement
  const speed = screen.getByRole('combobox', { name: 'Velocidade de reprodução' }) as HTMLSelectElement
  for (const duration of [NaN, Infinity, 0]) {
    Object.defineProperty(player, 'duration', { configurable: true, value: duration })
    fireEvent.durationChange(player)
    expect(first.disabled).toBe(true)
    expect(speed.disabled).toBe(true)
    readyAudio()
    expect(first.disabled).toBe(false)
  }
  fireEvent.emptied(player)
  expect(first.disabled).toBe(true)
  expect(speed.disabled).toBe(true)
})
