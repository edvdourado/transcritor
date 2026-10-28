import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import type { Job, Model } from './api'

export const POLL_INTERVAL = 1500

export function useTranscription() {
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState<'upload' | 'cancel' | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [paused, setPaused] = useState(false)
  const [missing, setMissing] = useState(false)
  const operation = useRef<AbortController | null>(null)
  const polling = useRef<AbortController | null>(null)
  const active = job?.state === 'queued' || job?.state === 'processing'

  useEffect(() => () => { operation.current?.abort() }, [])

  useEffect(() => {
    if (!job || !active || busy || paused || missing) return
    const controller = new AbortController()
    polling.current = controller
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const updated = await api.get(job.id, controller.signal)
        if (controller.signal.aborted) return
        setJob(updated)
        if (updated.state === 'queued' || updated.state === 'processing') timer = setTimeout(poll, POLL_INTERVAL)
      } catch (failure) {
        if (controller.signal.aborted) return
        setError((failure as Error).message)
        setMissing(failure instanceof ApiError && failure.status === 404)
        setPaused(true)
      }
    }
    timer = setTimeout(poll, POLL_INTERVAL)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [job?.id, active, busy, paused, missing])

  async function start(file: File, model: Model) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setBusy('upload'); setError(''); setNotice(''); setMissing(false); setPaused(false)
    try {
      const created = await api.create(file, model, controller.signal)
      if (!controller.signal.aborted) setJob(created)
    } catch (failure) {
      if (!controller.signal.aborted) setError((failure as Error).message)
    } finally {
      if (!controller.signal.aborted) { operation.current = null; setBusy(null) }
    }
  }

  async function cancel() {
    if (!job || operation.current) return
    const controller = new AbortController()
    operation.current = controller
    polling.current?.abort()
    setBusy('cancel'); setError('')
    try {
      await api.remove(job.id, controller.signal)
      if (controller.signal.aborted) return
      setJob(null); setPaused(false); setMissing(false)
      setNotice('Transcrição cancelada. O trabalho e seus arquivos foram removidos.')
    } catch (failure) {
      if (controller.signal.aborted) return
      if (failure instanceof ApiError && failure.status === 404) { setMissing(true); setPaused(true) }
      setError(`Não foi possível confirmar o cancelamento. ${(failure as Error).message}`)
    } finally {
      if (!controller.signal.aborted) { operation.current = null; setBusy(null) }
    }
  }

  function reset() {
    polling.current?.abort()
    setJob(null); setError(''); setNotice(''); setMissing(false); setPaused(false)
  }

  return { job, busy, active, error, notice, paused, missing, start, cancel, reset,
    retry: () => { setError(''); setPaused(false) } }
}
