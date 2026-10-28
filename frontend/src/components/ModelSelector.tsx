import type { Model } from '../api'

export function ModelSelector({ value, onChange, disabled }: { value: Model; onChange: (model: Model) => void; disabled: boolean }) {
  return <fieldset disabled={disabled}>
    <legend className="section-label mb-3">Escolha o modelo</legend>
    <div className="space-y-2">
      {([
        ['small', 'Whisper Small', 'Rápido', 'Menor tempo de processamento. Uma escolha prática para começar.'],
        ['medium', 'Whisper Medium', 'Detalhado', 'Maior precisão potencial, com processamento mais demorado.'],
      ] as const).map(([model, name, mode, description]) => <label key={model} className={`model-option ${value === model ? 'selected' : ''}`}>
        <input type="radio" name="model" value={model} checked={value === model} onChange={() => onChange(model)} />
        <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center justify-between gap-2"><strong className="font-medium">{name}</strong><span className="model-tag">{mode}</span></span>
          <span className="muted mt-1 block text-xs leading-relaxed">{description}</span></span>
      </label>)}
    </div>
    <p className="muted mt-3 text-xs leading-relaxed">A qualidade depende do áudio. Revise o resultado com qualquer modelo.</p>
  </fieldset>
}
