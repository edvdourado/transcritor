import { useState } from 'react'
import { api } from '../api'
import { Icon } from './Icon'

export function AudioPlayer({ jobId }: { jobId: string }) {
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  return <section className="audio-player" aria-label="Reprodutor de áudio">
    <div className="mb-3 flex items-center gap-2 text-sm font-medium"><Icon name="audio" size={18} /> Ouça e acompanhe a revisão</div>
    <audio key={attempt} controls preload="metadata" src={api.audioUrl(jobId)} aria-label="Áudio da transcrição" onError={() => setError(true)} className="w-full">
      Seu navegador não oferece um reprodutor de áudio.
    </audio>
    {error && <div role="alert" className="mt-3 text-sm"><p>Não foi possível reproduzir o áudio. O arquivo pode ter expirado, a conexão falhou ou o navegador não suporta este WAV.</p>
      <button type="button" className="text-action mt-2" onClick={() => { setError(false); setAttempt(value => value + 1) }}>Tentar carregar áudio novamente</button>
    </div>}
    <p className="muted mt-3 text-xs">Áudio convertido para WAV pelo servidor. A reprodução depende do suporte do navegador.</p>
  </section>
}
