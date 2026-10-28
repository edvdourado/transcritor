import { useEffect, useRef, useState } from 'react'
import type { Job } from '../api'
import type { PlaybackPosition } from './AudioPlayer'
import { Icon } from './Icon'
import { formatDuration } from '../duration'

export function TranscriptEditor({ job, fileName, onNew, position, onSeek }: {
  job: Job; fileName: string; onNew: () => void
  position: PlaybackPosition | null; onSeek: (start: number) => Promise<void>
}) {
  const [text, setText] = useState(job.transcript || '')
  const [feedback, setFeedback] = useState('')
  const [copied, setCopied] = useState(false)
  const [copying, setCopying] = useState(false)
  const [confirmNew, setConfirmNew] = useState(false)
  const [synchronized, setSynchronized] = useState(false)
  const segmentList = useRef<HTMLUListElement>(null)
  const edited = text !== job.transcript
  const mock = job.engine === 'mock'
  const segments = mock ? [] : job.segments || []
  // ponytail: O(n) per media event; index intervals if very long transcripts need it.
  // Half-open intervals leave silence unselected; the first match wins overlaps.
  const activeSegment = position ? segments.findIndex(segment => segment.start <= position.time && position.time < segment.end) : -1

  useEffect(() => {
    const list = segmentList.current
    const current = list?.querySelector<HTMLElement>(`[data-segment-index="${activeSegment}"]`)
    if (!synchronized || !list || !current) return
    const bounds = list.getBoundingClientRect()
    const item = current.getBoundingClientRect()
    // Scroll only the list, never the page, and never move keyboard focus.
    if (item.top < bounds.top) list.scrollTop += item.top - bounds.top
    else if (item.bottom > bounds.bottom) list.scrollTop += item.bottom - bounds.bottom
  }, [activeSegment, synchronized])

  useEffect(() => {
    if (!edited) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [edited])

  async function copy() {
    setCopying(true); setCopied(false); setFeedback('')
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true); setFeedback('Texto copiado para a área de transferência.')
    } catch {
      setFeedback('Não foi possível copiar. Selecione o texto e copie pelo teclado ou exporte o TXT.')
    } finally { setCopying(false) }
  }

  function download() {
    let url: string | undefined
    try {
      url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `${fileName.replace(/\.[^.]+$/, '') || 'transcricao'}.txt`
      document.body.appendChild(link); link.click(); link.remove()
      setFeedback('Exportação TXT solicitada ao navegador.')
    } catch { setFeedback('Não foi possível exportar. Copie o texto para preservar suas edições.') }
    finally {
      if (url) { const downloadUrl = url; setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000) }
    }
  }

  return <section className="result-sheet">
    <div className="editor-toolbar"><h2><label htmlFor="transcript">Transcrição</label></h2><div className="editor-actions">
      <button className="button quiet" onClick={copy} disabled={copying}><Icon name={copied ? 'check' : 'copy'} size={16} />{copied ? 'Copiado' : copying ? 'Copiando…' : 'Copiar'}</button>
      <button className="button secondary" onClick={download}><Icon name="download" size={16} />Exportar TXT</button>
      <button className="button secondary" onClick={() => edited ? setConfirmNew(true) : onNew()}>Nova transcrição</button></div></div>
    <div className="editor-notices">
      {confirmNew && <div role="alert" className="notice"><p>Iniciar outra transcrição descarta suas edições nesta aba. Copie ou exporte antes de continuar.</p>
        <div className="mt-3 flex flex-wrap gap-3"><button className="button secondary" onClick={onNew}>Descartar e iniciar nova</button><button className="button quiet" onClick={() => setConfirmNew(false)}>Continuar revisão</button></div></div>}
      {mock && <p className="mock-notice"><strong>Resultado de teste (mock).</strong> Este texto é fictício. Nenhum conteúdo do áudio foi transcrito.</p>}
    </div>
    <div className="review-mode">
      <label><input type="checkbox" checked={synchronized} disabled={!segments.length} onChange={event => setSynchronized(event.target.checked)} /> Revisão sincronizada</label>
      <p id="review-help" className="muted">{!segments.length ? 'Sem timestamps válidos para sincronizar.' : synchronized ? 'Trechos originais com timestamps. Edições, Copiar e TXT usam o texto do editor. Tab e setas navegam; Enter ou Espaço ouvem o trecho.' : 'Edite livremente; a revisão sincronizada mantém o original.'}</p>
      {synchronized && !position && <p role="status">Carregue ou tente novamente o áudio no painel Áudio para ouvir os trechos.</p>}
    </div>
    <div className="editor-body">
      <textarea id="transcript" hidden={synchronized} value={text} spellCheck lang="pt-BR" onChange={event => { setText(event.target.value); setCopied(false); setFeedback('') }} />
      {synchronized && <ul ref={segmentList} className="segment-list" aria-label="Trechos da transcrição original" aria-describedby="review-help" tabIndex={0} onKeyDown={event => {
        if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key) || !(event.target instanceof HTMLButtonElement)) return
        const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
        const index = buttons.indexOf(event.target)
        event.preventDefault()
        buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)))]?.focus()
      }}>
        {segments.map((segment, index) => <li key={index} data-segment-index={index}>
          <button type="button" className="segment" aria-current={index === activeSegment ? 'true' : undefined} disabled={!position || segment.start >= position.duration}
            onClick={() => { setFeedback(''); void onSeek(segment.start).catch(() => setFeedback('Não foi possível iniciar a reprodução. Tente os controles no painel Áudio.')) }}>
            <span className="segment-time">{formatDuration(segment.start)}–{formatDuration(segment.end)}</span><span>{segment.text}</span>
          </button>
        </li>)}
      </ul>}
    </div>
    <div className="editor-footer"><p className="muted text-xs">{edited ? 'Texto editado' : 'Texto original'} · Edições somente nesta aba</p><p role="status" className="text-sm">{feedback}</p></div>
  </section>
}
