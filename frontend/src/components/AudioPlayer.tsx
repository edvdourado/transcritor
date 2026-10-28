import { useEffect, useState } from 'react'
import type { RefObject } from 'react'
import { api } from '../api'
import { Icon } from './Icon'

export type PlaybackPosition = { time: number; duration: number }

export function AudioPlayer({ jobId, audioRef, onPositionChange }: {
  jobId: string
  audioRef: RefObject<HTMLAudioElement | null>
  onPositionChange: (position: PlaybackPosition | null) => void
}) {
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [rate, setRate] = useState(1)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = rate
  }, [rate, attempt, audioRef])

  function updatePosition() {
    const audio = audioRef.current
    if (!audio || audio.error || audio.readyState < 1 || !Number.isFinite(audio.duration) || audio.duration <= 0) { unavailable(); return }
    setReady(true)
    onPositionChange({ time: audio.currentTime, duration: audio.duration })
  }

  function unavailable() { setReady(false); onPositionChange(null) }

  return <section className="audio-player" aria-label="Reprodutor de áudio">
    <div className="mb-3 flex items-center gap-2 text-sm font-medium"><Icon name="audio" size={18} /> Ouça e acompanhe a revisão</div>
    <audio key={attempt} ref={audioRef} controls preload="metadata" src={api.audioUrl(jobId)} aria-label="Áudio da transcrição"
      onLoadedMetadata={() => { if (audioRef.current) audioRef.current.playbackRate = rate; updatePosition() }}
      onDurationChange={updatePosition} onTimeUpdate={updatePosition} onSeeking={updatePosition} onSeeked={updatePosition} onEnded={updatePosition}
      onRateChange={event => setRate(event.currentTarget.playbackRate)}
      onEmptied={unavailable} onError={() => { setError(true); unavailable() }} className="w-full">
      Seu navegador não oferece um reprodutor de áudio.
    </audio>
    <label className="playback-speed">Velocidade de reprodução
      <select value={rate} disabled={!ready || error} onChange={event => setRate(Number(event.target.value))}>
        {![0.75, 1, 1.25, 1.5, 2].includes(rate) && <option value={rate}>{String(rate).replace('.', ',')}×</option>}
        {[0.75, 1, 1.25, 1.5, 2].map(value => <option key={value} value={value}>{String(value).replace('.', ',')}×</option>)}
      </select>
    </label>
    {error && <div role="alert" className="mt-3 text-sm"><p>Não foi possível reproduzir o áudio. O arquivo pode ter expirado, a conexão falhou ou o navegador não suporta este WAV.</p>
      <button type="button" className="text-action mt-2" onClick={() => { setError(false); unavailable(); setAttempt(value => value + 1) }}>Tentar carregar áudio novamente</button>
    </div>}
    <p className="muted mt-3 text-xs">Áudio convertido para WAV pelo servidor. A reprodução depende do suporte do navegador.</p>
  </section>
}
