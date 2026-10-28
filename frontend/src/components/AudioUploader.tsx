import { useId, useRef, useState } from 'react'
import { Icon } from './Icon'

export const MAX_FILE_SIZE = 50 * 1024 * 1024
export const ACCEPT = '.ogg,.mp3,.m4a,.wav'

export function validateFile(file: File): string | null {
  if (!/\.(ogg|mp3|m4a|wav)$/i.test(file.name)) return 'Formato inválido. Escolha um arquivo OGG, MP3, M4A ou WAV.'
  if (!file.size) return 'O arquivo está vazio. Escolha um áudio com conteúdo.'
  if (file.size > MAX_FILE_SIZE) return 'O arquivo excede 50 MiB. Escolha um arquivo menor.'
  return null
}

export function formatSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${(bytes / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} KiB` :
    `${(bytes / 1024 / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MiB`
}

export function AudioUploader({ file, onChange, disabled }: { file: File | null; onChange: (file: File | null) => void; disabled: boolean }) {
  const id = useId()
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)

  function select(files: FileList | null) {
    if (disabled || !files?.length) return
    const invalid = files.length > 1 ? 'Envie um áudio por vez.' : validateFile(files[0])
    setError(invalid || '')
    if (!invalid) onChange(files[0])
  }

  return <div>
    <input ref={input} id={id} type="file" accept={ACCEPT} className="sr-only" tabIndex={-1} aria-label="Selecionar arquivo de áudio" disabled={disabled}
      onChange={event => { select(event.target.files); event.target.value = '' }} />
    <div className={`drop-zone ${disabled && file ? 'compact' : ''} ${dragging ? 'dragging' : ''}`} data-testid="drop-zone"
      onDragEnter={event => { event.preventDefault(); if (!disabled) setDragging(true) }}
      onDragOver={event => { event.preventDefault(); event.dataTransfer.dropEffect = disabled ? 'none' : 'copy' }}
      onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false) }}
      onDrop={event => { event.preventDefault(); setDragging(false); select(event.dataTransfer.files) }}>
      <div className="upload-symbol"><Icon name={file ? 'file' : 'upload'} size={28} /></div>
      {file ? <>
        <p className="file-name" title={file.name}>{file.name}</p>
        <p className="muted text-sm">{formatSize(file.size)} · {disabled ? 'Arquivo selecionado' : 'Pronto para enviar'}</p>
        {!disabled && <div className="mt-3 flex flex-wrap justify-center gap-3">
          <button type="button" className="button secondary" disabled={disabled} onClick={() => input.current?.click()}>Substituir arquivo</button>
          <button type="button" className="button quiet" disabled={disabled} onClick={() => { onChange(null); setError('') }}>Remover</button>
        </div>}
      </> : <>
        <p className="font-medium">Solte seu áudio aqui</p>
        <p className="muted mt-1 text-sm">ou escolha um arquivo do seu dispositivo</p>
        <button type="button" className="button secondary mt-3" disabled={disabled} onClick={() => input.current?.click()}>Selecionar arquivo <Icon name="arrow" size={16} /></button>
      </>}
      {!(disabled && file) && <p className="muted mt-3 text-xs">OGG, MP3, M4A ou WAV · Até 50 MiB</p>}
    </div>
    {error && <p role="alert" className="error-message mt-3">{error}</p>}
  </div>
}
