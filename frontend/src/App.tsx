import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Engine, Model } from './api'
import { AudioUploader } from './components/AudioUploader'
import { ModelSelector } from './components/ModelSelector'
import { JobStatus } from './components/JobStatus'
import { TranscriptEditor } from './components/TranscriptEditor'
import { Icon } from './components/Icon'
import { AudioPlayer } from './components/AudioPlayer'
import type { PlaybackPosition } from './components/AudioPlayer'
import { useTranscription } from './useTranscription'
import { formatDuration } from './duration'

function initialTheme(): boolean {
  try {
    const saved = localStorage.getItem('transcritor-theme')
    if (saved) return saved === 'dark'
  } catch { /* Theme remains available when storage is blocked. */ }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches || false
}

export default function App() {
  const [dark, setDark] = useState(initialTheme)
  const [file, setFile] = useState<File | null>(null)
  const [model, setModel] = useState<Model>('small')
  const [panel, setPanel] = useState<'audio' | 'transcript'>('audio')
  const [configuredEngine, setConfiguredEngine] = useState<Engine | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const [position, setPosition] = useState<PlaybackPosition | null>(null)
  const flow = useTranscription()
  const { job, busy, active, paused, missing } = flow
  const engine = job ? job.engine : configuredEngine

  useEffect(() => {
    const controller = new AbortController()
    void api.capabilities(controller.signal).then(value => {
      if (!controller.signal.aborted) setConfiguredEngine(value.engine)
    }).catch(() => { /* Unknown engine: do not guess from transcript text. */ })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    try { localStorage.setItem('transcritor-theme', dark ? 'dark' : 'light') } catch { /* Optional preference. */ }
  }, [dark])

  useEffect(() => {
    const viewport = window.visualViewport
    if (!viewport) return
    const resize = () => document.documentElement.style.setProperty('--app-height', viewport.scale === 1 ? `${viewport.height}px` : '100dvh')
    resize()
    viewport.addEventListener('resize', resize)
    return () => {
      viewport.removeEventListener('resize', resize)
      document.documentElement.style.removeProperty('--app-height')
    }
  }, [])

  useEffect(() => {
    if (job?.state !== 'completed') return
    setPanel('transcript')
    if (window.matchMedia?.('(max-width: 760px)').matches) document.getElementById('transcript-tab')?.focus()
  }, [job?.id, job?.state])

  function newTranscription() { flow.reset(); setFile(null); setPanel('audio'); setPosition(null) }

  async function seek(start: number) {
    const audio = audioRef.current
    if (!audio || !position || start >= audio.duration) throw new Error('Áudio indisponível para este trecho.')
    audio.currentTime = start
    setPosition({ time: start, duration: audio.duration })
    await audio.play()
  }

  function selectPanel(next: 'audio' | 'transcript') {
    setPanel(next)
    document.getElementById(`${next}-tab`)?.focus()
  }

  return <div className="app-shell">
    <header className="site-header"><a href="/" className="brand" aria-label="Transcritor, início"><span className="brand-symbol"><Icon name="wave" size={24} /></span>transcritor<span className="brand-dot">.</span></a>
      <div className="flex items-center gap-4">{engine && <span className="environment-badge"><span /> {engine === 'mock' ? 'Modo de teste' : 'Whisper real'}</span>}<button className="theme-toggle" aria-label={dark ? 'Ativar tema claro' : 'Ativar tema escuro'} onClick={() => setDark(value => !value)}><Icon name={dark ? 'sun' : 'moon'} /></button></div></header>
    <main id="main-content" className="workbench">
      <div className="mobile-tabs" role="tablist" aria-label="Área de trabalho" onKeyDown={event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        selectPanel(event.key === 'Home' ? 'audio' : event.key === 'End' ? 'transcript' : panel === 'audio' ? 'transcript' : 'audio')
      }}>
        <button id="audio-tab" role="tab" aria-controls="audio-panel" aria-selected={panel === 'audio'} tabIndex={panel === 'audio' ? 0 : -1} onClick={() => selectPanel('audio')}>Áudio</button>
        <button id="transcript-tab" role="tab" aria-controls="transcript-panel" aria-selected={panel === 'transcript'} tabIndex={panel === 'transcript' ? 0 : -1} onClick={() => selectPanel('transcript')}>Transcrição{job?.state === 'completed' && <Icon name="check" size={14} />}</button>
      </div>
      <div className="panel-grid">
        <section id="audio-panel" role="tabpanel" aria-labelledby="audio-tab" data-active={panel === 'audio'} className="panel audio-panel">
          <div className="panel-heading"><h1>Áudio</h1><span className="muted text-xs">Upload e processamento</span></div>
          <div className="audio-panel-body">
            {flow.error && <div className="error-message" role="alert">{flow.error}</div>}
            {flow.notice && <div className="notice" role="status">{flow.notice}</div>}
            <form id="upload-form" onSubmit={event => { event.preventDefault(); if (file && !busy && !job) void flow.start(file, model) }}>
              <AudioUploader file={file} onChange={setFile} disabled={!!busy || !!job} />
              {job || busy ? <div className="model-summary"><span className="muted">Modelo</span><strong>Whisper {(job?.model || model) === 'small' ? 'Small' : 'Medium'}</strong></div> : <ModelSelector value={model} onChange={setModel} disabled={false} />}
            </form>
            {job && <div className="model-summary"><span className="muted">Duração do áudio</span><strong className="job-time">{job.audio_duration_seconds != null ? formatDuration(job.audio_duration_seconds) : 'Indisponível'}</strong></div>}
            {(job || busy === 'upload') && <JobStatus job={job} uploading={busy === 'upload'} paused={paused} missing={missing} cancelling={busy === 'cancel'} />}
            {job?.state === 'completed' && <AudioPlayer key={job.id} jobId={job.id} audioRef={audioRef} onPositionChange={setPosition} />}
            {engine === 'mock' && <p className="mock-info"><strong>Transcritor mock.</strong> O resultado é fictício e não representa o conteúdo do áudio.</p>}
          </div>
          <div className="audio-panel-actions">
            {!job && <button type="submit" form="upload-form" className="button primary" disabled={!file || !!busy}>{busy === 'upload' ? 'Enviando áudio…' : 'Iniciar transcrição'}{busy === 'upload' ? <span className="spinner small" /> : <Icon name="arrow" size={18} />}</button>}
            {paused && !missing && <button className="button secondary" disabled={!!busy} onClick={flow.retry}>Retomar acompanhamento</button>}
            {active && !missing && <button className="button secondary" disabled={!!busy} onClick={() => void flow.cancel()}>{busy === 'cancel' ? 'Cancelando…' : 'Cancelar transcrição'}</button>}
            {(job?.state === 'failed' || missing) && <button className="button secondary" onClick={newTranscription}>Nova transcrição</button>}
            {job?.state === 'completed' && <button className="button primary" onClick={() => {
              if (window.matchMedia?.('(max-width: 760px)').matches) selectPanel('transcript')
              else {
                const editor = document.getElementById('transcript')
                if (editor?.hidden) document.querySelector<HTMLElement>('.segment-list')?.focus()
                else editor?.focus()
              }
            }}>Revisar transcrição <Icon name="arrow" size={16} /></button>}
          </div>
        </section>
        <section id="transcript-panel" role="tabpanel" aria-labelledby="transcript-tab" data-active={panel === 'transcript'} className="panel editor-panel">
          {job?.state === 'completed' ? <TranscriptEditor key={job.id} job={job} fileName={file?.name || 'transcricao'} onNew={newTranscription} position={position} onSeek={seek} /> : <div className="empty-editor">
            <div className="editor-toolbar"><h2>Transcrição</h2><div className="editor-actions"><button className="button quiet" disabled><Icon name="copy" size={16} />Copiar</button><button className="button secondary" disabled><Icon name="download" size={16} />Exportar TXT</button></div></div>
            <div className="transcript-placeholder"><Icon name="file" size={28} /><h3>{active || busy ? 'Aguardando o resultado' : 'Seu texto aparece aqui'}</h3><p>Envie um áudio no painel Áudio.<br />Depois, ouça, edite e exporte sua transcrição.</p></div>
            <p className="empty-editor-footer muted">Edições somente nesta aba · Sem salvamento automático</p>
          </div>}
        </section>
      </div>
    </main>
  </div>
}
