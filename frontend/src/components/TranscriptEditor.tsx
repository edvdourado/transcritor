import { useEffect, useState } from 'react'
import type { Job } from '../api'
import { Icon } from './Icon'

export function TranscriptEditor({ job, fileName, onNew }: { job: Job; fileName: string; onNew: () => void }) {
  const [text, setText] = useState(job.transcript || '')
  const [feedback, setFeedback] = useState('')
  const [copied, setCopied] = useState(false)
  const [copying, setCopying] = useState(false)
  const [confirmNew, setConfirmNew] = useState(false)
  const edited = text !== job.transcript
  const mock = job.engine === 'mock'

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
    <div className="editor-body"><textarea id="transcript" value={text} spellCheck lang="pt-BR" onChange={event => { setText(event.target.value); setCopied(false); setFeedback('') }} /></div>
    <div className="editor-footer"><p className="muted text-xs">{edited ? 'Texto editado' : 'Texto original'} · Edições somente nesta aba</p><p role="status" className="text-sm">{feedback}</p></div>
  </section>
}
