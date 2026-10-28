import { useEffect, useState } from 'react'
import type { Job } from '../api'
import { formatDuration } from '../duration'
import { Icon } from './Icon'

export function JobStatus({ job, uploading, paused, missing, cancelling = false }: { job: Job | null; uploading: boolean; paused: boolean; missing: boolean; cancelling?: boolean }) {
  const state = uploading ? 'upload' : missing ? 'missing' : paused ? 'paused' : job?.state
  const [elapsed, setElapsed] = useState({ id: job?.id, seconds: job?.processing_seconds ?? 0 })
  const running = state === 'processing' && !cancelling && job?.processing_seconds != null
  useEffect(() => {
    if (!running || !job) return
    const seconds = job.processing_seconds!
    const anchor = performance.now()
    const update = () => setElapsed(previous => ({ id: job.id, seconds: Math.max(
      previous.id === job.id ? previous.seconds : 0, seconds + (performance.now() - anchor) / 1000) }))
    update()
    const timer = setInterval(update, 250)
    return () => clearInterval(timer)
  }, [job, running])
  const processing = job?.processing_seconds
  const time = state === 'processing' && processing != null
    ? formatDuration(Math.max(processing, elapsed.id === job?.id ? elapsed.seconds : 0)) : null
  const content = {
    upload: ['Enviando e validando', 'O servidor está recebendo e verificando seu arquivo.'],
    queued: ['Na fila', 'Seu áudio está aguardando uma vaga para processamento.'],
    processing: ['Processando', 'Estamos preparando o áudio e aguardando o transcritor. O tempo varia conforme o arquivo e o modelo.'],
    completed: ['Concluído', 'O resultado está pronto para ouvir, revisar e exportar.'],
    failed: ['Erro no processamento', job?.error || 'Não foi possível processar o áudio. Tente novamente.'],
    missing: ['Trabalho indisponível', 'Ele pode ter expirado, sido removido ou a API pode ter reiniciado.'],
    paused: ['Acompanhamento interrompido', 'O trabalho pode continuar no servidor. Retome a consulta ou tente cancelar.'],
  }[state || 'queued']!
  const working = ['upload', 'queued', 'processing'].includes(state || '')
  return <div role="status" className={`job-status ${state === 'failed' ? 'failed' : ''}`}>
    <span className={working ? 'spinner' : 'status-symbol'}>{!working && <Icon name={state === 'completed' ? 'check' : 'close'} />}</span>
    <div><p className="font-medium job-time">{state === 'completed' && processing != null
      ? `Concluído em ${formatDuration(processing)}` : <>{content[0]}{time && <span aria-live="off"> · {time}</span>}</>}</p>
      <p className="muted mt-1 text-sm leading-relaxed">{content[1]}</p>
      {job && <div className="timing-details muted" title="Processamento inclui preparação e transcrição. Total inclui a fila; exclui envio e validação.">
        <p>Processamento{job.engine === 'mock' ? ' simulado' : ''}: <span className="job-time" aria-live="off">{time ?? (processing != null ? formatDuration(processing) : '—')}</span></p>
        <p>Total{job.state === 'queued' || job.state === 'processing' ? ' na última consulta' : ''}: <span className="job-time">{job.total_seconds != null ? formatDuration(job.total_seconds) : '—'}</span></p>
        <p>Preparação + transcrição. Total inclui a fila.</p>
        {job.state === 'failed' && <p>Tempos até a falha; transcrição não concluída.</p>}
      </div>}
    </div>
  </div>
}
