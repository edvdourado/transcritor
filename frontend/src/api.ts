export type Model = 'small' | 'medium'
export type Engine = 'mock' | 'whisper'
export type Segment = { text: string; start: number; end: number }
export type Job = {
  id: string
  model: Model
  state: 'queued' | 'processing' | 'completed' | 'failed'
  transcript: string | null
  error: string | null
  engine?: Engine | null
  total_seconds?: number | null
  processing_seconds?: number | null
  audio_duration_seconds?: number | null
  segments?: Segment[]
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

const messages: Record<number, string> = {
  404: 'Este trabalho expirou ou não existe mais. Inicie uma nova transcrição.',
  408: 'O envio demorou demais. Tente novamente.',
  413: 'O arquivo excede o limite de tamanho do servidor.',
  422: 'Arquivo inválido. Verifique o formato e o conteúdo do áudio.',
  429: 'A fila está cheia. Aguarde um pouco e tente novamente.',
  503: 'O serviço está indisponível no momento. Tente novamente.',
  504: 'O servidor demorou demais para responder. Tente novamente.',
}

async function request(path: string, options: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, options)
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new ApiError('Não foi possível conectar à API. Verifique a conexão e se o backend está em execução.', 0)
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? body.detail : null
    throw new ApiError(response.status === 404 ? messages[404] :
      typeof detail === 'string' ? detail : messages[response.status] || `Falha na solicitação (HTTP ${response.status}).`, response.status)
  }
  return response
}

async function readJob(response: Response): Promise<Job> {
  const value: unknown = await response.json().catch(() => null)
  if (!value || typeof value !== 'object' || !('id' in value) || typeof value.id !== 'string' ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.id) ||
      !('model' in value) || !['small', 'medium'].includes(String(value.model)) ||
      !('state' in value) || !['queued', 'processing', 'completed', 'failed'].includes(String(value.state)) ||
      !('transcript' in value) || !(value.transcript === null || typeof value.transcript === 'string') ||
      !('error' in value) || !(value.error === null || typeof value.error === 'string') ||
      ('engine' in value && value.engine !== null && value.engine !== 'mock' && value.engine !== 'whisper') ||
      ['total_seconds', 'processing_seconds', 'audio_duration_seconds'].some(key => {
        const duration = (value as Record<string, unknown>)[key]
        return duration != null && (typeof duration !== 'number' || !Number.isFinite(duration) || duration < 0)
      }) ||
      (value.state === 'completed' && typeof value.transcript !== 'string')) {
    throw new ApiError('A API retornou uma resposta inesperada. Tente consultar novamente.', 502)
  }
  // Optional review metadata must never prevent access to the editable text.
  const segments = 'segments' in value && Array.isArray(value.segments) ? value.segments.filter((segment): segment is Segment =>
    segment !== null && typeof segment === 'object' &&
    typeof segment.text === 'string' && segment.text.trim().length > 0 &&
    typeof segment.start === 'number' && Number.isFinite(segment.start) && segment.start >= 0 &&
    typeof segment.end === 'number' && Number.isFinite(segment.end) && segment.end > segment.start,
  ) : []
  return { ...value, segments } as Job
}

export const api = {
  async capabilities(signal: AbortSignal): Promise<{ engine: Engine | null }> {
    const value: unknown = await (await request('/capabilities', { signal })).json()
    if (!value || typeof value !== 'object' || !('engine' in value) ||
        ![null, 'mock', 'whisper'].includes(value.engine as Engine | null)) {
      throw new ApiError('A API retornou um mecanismo inesperado.', 502)
    }
    return value as { engine: Engine | null }
  },
  async create(file: File, model: Model, signal: AbortSignal) {
    const body = new FormData()
    body.append('file', file)
    body.append('model', model)
    return readJob(await request('/jobs', { method: 'POST', body, signal }))
  },
  async get(id: string, signal: AbortSignal) {
    return readJob(await request(`/jobs/${encodeURIComponent(id)}`, { signal }))
  },
  async remove(id: string, signal: AbortSignal) {
    await request(`/jobs/${encodeURIComponent(id)}`, { method: 'DELETE', signal })
  },
  audioUrl: (id: string) => `/api/v1/jobs/${encodeURIComponent(id)}/audio`,
}
