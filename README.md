# Transcritor

Aplicação web gratuita e self-hosted para transcrever áudio com **whisper.cpp**, usando modelos locais Small e Medium. O áudio é processado no servidor administrado por você, sem uma API comercial de transcrição.

O ambiente de produção informado pelo mantenedor usa Oracle Cloud ARM64, Ubuntu 22.04, Python 3.10, Nginx, HTTPS com Let's Encrypt, HTTP Basic e systemd. As instruções abaixo permitem preparar outra instalação; os resultados de verificação desta cópia estão em [docs/PUBLICACAO.md](docs/PUBLICACAO.md).

## Funcionalidades

- Upload por seleção ou arrastar e soltar; escolha entre Small e Medium.
- Validação por FFprobe e conversão por FFmpeg para WAV mono, PCM 16-bit, 16 kHz.
- Fila com um trabalho em processamento e um aguardando; cancelamento com exclusão dos arquivos do trabalho.
- Acompanhamento de estado e tempos de processamento/total, sem percentual estimado.
- Player do áudio convertido, revisão do texto, cópia e exportação TXT UTF-8.
- Interface responsiva, tema claro/escuro e avisos explícitos no modo de teste `mock`.
- Expiração dos resultados e arquivos temporários.

## Tecnologias e arquitetura

Frontend React 19, Vite 7, TypeScript e Tailwind CSS 4; backend FastAPI, Starlette e Uvicorn; FFmpeg/FFprobe e executável nativo whisper.cpp em CPU.

```text
Navegador → Nginx (HTTPS + HTTP Basic)
               ├─ /         → frontend/dist
               └─ /api/     → FastAPI em 127.0.0.1:8765 (um worker)
                                → FFprobe → fila → FFmpeg → whisper-cli
                                                          → modelos locais
```

Em desenvolvimento, o Vite serve a interface e encaminha `/api` ao backend. A API usa trabalhos em memória e arquivos em um diretório temporário exclusivo; não há banco de dados. O backend não serve o build do frontend.

## Requisitos

- Python **3.10 ou superior**, com suporte a venv/pip.
- Node.js **22.12+ (linha 22) ou 24.x** e npm para desenvolvimento/build; Node não é necessário para servir o build pelo Nginx.
- FFmpeg e FFprobe acessíveis pelo PATH ou por caminhos absolutos no ambiente.
- Para transcrição real: `whisper-cli` compilado para a máquina e arquivos dos modelos multilíngues `ggml-small.bin` e `ggml-medium.bin`.
- RAM, CPU e disco suficientes para o modelo escolhido e os temporários; Medium exige mais recursos. Meça na máquina de destino antes de ajustar limites/threads.

## Desenvolvimento local

Clone o repositório após a publicação e entre na raiz:

```sh
git clone https://github.com/edvdourado/transcritor.git
cd transcritor
```

### Linux/macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e './backend[test]'
# Execute a cópia somente se .env ainda não existir.
cp -n .env.example .env
.venv/bin/python -m app.main
```

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './backend[test]'
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe -m app.main
```

O backend escuta em `127.0.0.1:8765`. Em outro terminal, na raiz:

```sh
cd frontend
npm ci
npm run dev
```

Abra a URL mostrada pelo Vite (normalmente `http://localhost:5173`). No PowerShell, use `npm.cmd` se a política local bloquear `npm.ps1`. Para encerrar os servidores, use `Ctrl+C` nos respectivos terminais.

**O padrão é `TRANSCRITOR_ENGINE=mock`: o resultado é fictício.** Mesmo nesse modo, uploads passam pelo FFprobe/FFmpeg. Configure `TRANSCRITOR_ENGINE=whisper`, `WHISPER_CLI_PATH`, `WHISPER_MODEL_SMALL` e `WHISPER_MODEL_MEDIUM` para transcrever de verdade; veja [a implantação](docs/DEPLOY.md). Não há fallback automático para mock se Whisper falhar.

O backend carrega o `.env` da raiz; variáveis do processo têm precedência. Caminhos relativos de temporários dependem do diretório de execução. Caminhos de ferramentas contêm apenas o executável, sem argumentos; use binários nativos, sem wrappers `.bat`/`.cmd`. Nunca coloque segredos em variáveis do frontend.

## Versão 1.1 — revisão sincronizada

Após concluir uma transcrição, marque **Revisão sincronizada** no painel Transcrição. A lista mostra os trechos originais com timestamps; o destaque acompanha a posição do áudio e rola somente dentro da lista. Clique em um trecho para avançar até seu início e reproduzir. Tab, setas para cima/baixo, Home e End navegam pelos botões; Enter ou Espaço iniciam o trecho. No celular, as abas Áudio e Transcrição mantêm o player e a revisão montados.

Desmarque a opção para voltar ao editor, com suas edições preservadas. **Copiar e Exportar TXT sempre usam o texto do editor**, mesmo durante a revisão sincronizada. Edições livres não são associadas aos segmentos originais. O controle de velocidade no painel Áudio oferece 0,75×, 1×, 1,25×, 1,5× e 2×; a posição e os timestamps continuam em segundos do áudio, independentemente da velocidade.

O contrato de `POST /api/v1/jobs` e `GET /api/v1/jobs/{id}` ganhou somente o campo aditivo `segments`:

```json
{
  "segments": [
    { "text": " Olá, ação.", "start": 0.0, "end": 1.23 },
    { "text": " Segundo trecho.", "start": 1.23, "end": 2.5 }
  ]
}
```

Os demais campos da resposta permanecem iguais. A lista é vazia antes da conclusão, no mock e quando não há tempos utilizáveis. Cada segmento exige texto não vazio, números finitos, `start >= 0` e `end > start`, com validação Pydantic. Espaços e quebras de linha do texto original são preservados.

Os offsets `from`/`to` do JSON do whisper-cli são posições absolutas no áudio em **milissegundos**: o [exportador oficial do Whisper.cpp v1.8.2](https://github.com/ggml-org/whisper.cpp/blob/v1.8.2/examples/cli/cli.cpp#L635-L643) multiplica por 10 os ticks internos de 10 ms. Por isso, o backend divide os offsets do JSON por **1.000**, não por 100. A execução atual usa o WAV completo, sem recorte temporal. Na ausência de `offsets`, aceita `timestamps` no formato `HH:MM:SS,mmm` ou com ponto. Offsets presentes prevalecem; tempos inválidos, intervalos de duração zero e textos em branco ficam fora da lista sincronizada, sem remover seu texto do editor. Saída com estrutura/texto inválidos continua falhando com mensagem segura.

Compatibilidade: clientes anteriores podem ignorar `segments`; o frontend aceita APIs antigas sem o campo. Metadados opcionais malformados são filtrados, preservando o editor. Intervalos usam `[start, end)`: silêncio entre trechos não mantém destaque; em sobreposições, vence o primeiro intervalo correspondente na ordem original. Não há estimativa de tempos para mock ou texto sem timestamps. Falhas no áudio desabilitam os saltos e a velocidade até a recarga; trechos que começam fora da duração do áudio também não permitem saltos. A velocidade retorna a 1× e o modo ao editor em uma nova transcrição.

Para conferir localmente, inicie backend e frontend conforme os comandos acima, com os binários e modelos Small/Medium **já existentes** configurados para `TRANSCRITOR_ENGINE=whisper`. Envie um áudio e verifique:

1. Edite uma frase; ative/desative a revisão e confira que o editor preservou a alteração e os trechos conservaram o original.
2. Reproduza, avance e volte pelo player; clique em um trecho e repita com Enter/Espaço.
3. Experimente as cinco velocidades, Copiar e TXT com o modo sincronizado ativo.
4. Confira desktop, abas no celular e uma tela com pouca altura; a página não deve rolar, e a lista deve rolar internamente.
5. Inicie outra transcrição e confira a limpeza do destaque e o retorno a 1×. No mock, confira a revisão desabilitada e o editor funcional.

A suíte cobre conversão e fallback de timestamps, validação do contrato, mock/API antiga, sincronização, teclado, cliques, velocidades, indisponibilidade/recarga do áudio e preservação de edições, cópia e exportação. A precisão temporal depende dos segmentos do Whisper; os testes simulam o CLI e não substituem uma conferência com fala e modelos reais.

Validação local em 28/10/2026: **144 testes backend** (Python 3.12, incluindo FFmpeg/FFprobe), **83 testes frontend** e **build TypeScript/Vite** aprovados. Conferência no navegador com áudio/segmentos sintéticos: desktop 1280×720, celular 390×844 e viewport reduzido 390×360 sem rolagem da página; Enter/Espaço, salto e velocidade conferidos. O backend apresentou apenas o aviso já existente de depreciação do httpx no TestClient do Starlette. Não houve inferência com modelos reais nesta validação. Os testes backend precisaram executar fora da restrição de rede do sandbox, que bloqueia o socket interno do asyncio no Windows; temporários ficaram dentro de `tmp/` do projeto.

## Execução, testes e build

Na raiz, com as dependências de teste instaladas:

```sh
TRANSCRITOR_ENGINE=mock .venv/bin/python -m pytest backend -q -rs
.venv/bin/python deploy/vps/test_package.py -v
```

Equivalente no PowerShell:

```powershell
$env:TRANSCRITOR_ENGINE = 'mock'
.\.venv\Scripts\python.exe -m pytest backend -q -rs
.\.venv\Scripts\python.exe deploy/vps/test_package.py -v
```

Na pasta `frontend`:

```sh
npm test
npm run build
```

O build inclui a checagem TypeScript e gera `frontend/dist/`. Os testes de integração de áudio geram entradas sintéticas e são ignorados quando FFmpeg/FFprobe estão ausentes. Os testes do adaptador Whisper simulam o CLI; não substituem um teste com os dois modelos reais. [Resultados desta preparação](docs/PUBLICACAO.md).

## Formatos e limites

| Entrada | Conteúdo aceito |
|---|---|
| `.ogg` | Opus |
| `.mp3` | MP3 |
| `.m4a` | AAC ou ALAC |
| `.wav` | Codec de áudio reconhecido pelo FFprobe e decodificável pelo FFmpeg |

O limite padrão é **50 MiB por arquivo** e **30 minutos de áudio**. Conteúdo de vídeo é recusado, exceto imagens de capa anexadas. Extensão e metadados são inspecionados; erros posteriores na decodificação também podem causar falha. O frontend fixa 50 MiB: mudanças no limite do backend exigem alinhar a interface e o proxy.

## Configuração

Todos os valores estão em [.env.example](.env.example). Principais opções:

| Variável | Padrão | Função |
|---|---|---|
| `TRANSCRITOR_ENGINE` | `mock` | `mock` ou `whisper` |
| `TRANSCRITOR_HOST` / `TRANSCRITOR_PORT` | `127.0.0.1` / `8765` | Listener do backend |
| `WHISPER_CLI_PATH` | vazio | Caminho do executável nativo |
| `WHISPER_MODEL_SMALL` / `WHISPER_MODEL_MEDIUM` | vazio | Arquivos locais dos modelos |
| `WHISPER_THREADS` / `WHISPER_LANGUAGE` | `3` / `pt` | Threads de CPU e idioma (`auto` também aceito) |
| `WHISPER_TIMEOUT_SECONDS` | `7200` | Limite por execução, incluindo carga do modelo |
| `FFMPEG_PATH` / `FFPROBE_PATH` | `ffmpeg` / `ffprobe` | Executáveis de áudio |
| `TRANSCRITOR_TEMP_DIR` | `./tmp` | Diretório exclusivo da aplicação |
| `MAX_UPLOAD_SIZE_MB` | `50` | Tamanho em MiB |
| `MAX_AUDIO_DURATION_SECONDS` | `1800` | Duração máxima |
| `FILE_RETENTION_SECONDS` | `3600` | Retenção após conclusão/falha |
| `UPLOAD_TIMEOUT_SECONDS` | `120` | Recebimento e parse do upload |
| `FFPROBE_TIMEOUT_SECONDS` / `FFMPEG_TIMEOUT_SECONDS` | `15` / `120` | Inspeção e conversão |
| `MOCK_PROCESSING_SECONDS` | `2` | Espera artificial do mock |

## Limitações e privacidade

- A transcrição pode errar palavras, pontuação e conteúdo; revise o resultado. Não há identificação de falantes, tradução, gravação de microfone, exportação SRT/VTT ou streaming de transcrição.
- Use **uma instância e um worker**. Reiniciar perde a fila e os resultados em memória. Recarregar/fechar a aba perde o ID e as edições locais; exporte antes de sair.
- O tempo de processamento inclui conversão e transcrição. O total inclui a fila, mas começa após upload/validação. Não é uma medição de latência ponta a ponta.
- O backend não implementa login nem isolamento por usuário. HTTP Basic no Nginx protege o acesso à instalação; qualquer usuário autorizado com um UUID pode acessar/excluir aquele trabalho. Não trate esta versão como um serviço multiusuário isolado.
- Áudios são enviados ao seu servidor e gravados temporariamente; texto e segmentos ficam na memória do processo. A inferência é local. Instalação e download de dependências/modelos precisam de rede.
- Originais e WAVs permanecem até exclusão ou expiração. A retenção começa após conclusão/falha e a limpeza periódica pode levar mais 60 segundos. Encerramento normal remove a sessão; após falha abrupta, diretórios abandonados são limpos quando o backend volta a executar e a retenção vence.
- A aplicação não faz apagamento seguro de disco e não controla backups, logs do proxy ou do sistema. A retenção não é uma quota agregada: monitore espaço livre e acesso aos temporários. TXT exportado fica sob responsabilidade de quem o baixou.
- Em produção, use HTTPS, HTTP Basic em toda a aplicação e listener do backend em loopback. O endpoint health indica que a API responde; não verifica os modelos nem executa transcrição.

## Documentação adicional

- [Teste real isolado da v1.1 na Oracle](docs/TESTE_V11_ORACLE.md): snapshot atual, backend em 8766, túnel SSH, Vite exclusivo e roteiro de validação sem deploy.
- [Implantação Oracle ARM64 / Ubuntu 22.04](docs/DEPLOY.md): instalação, Nginx, HTTPS, systemd, atualização e rollback.
- [Auditoria e preparação da publicação](docs/PUBLICACAO.md): escopo, resultados, limites e comandos Git.
- [Empacotamento opcional de fontes](deploy/vps/README.md): pacote determinístico com lista de arquivos permitidos.

Não foram incluídas capturas de tela: as imagens locais existentes são evidências de desenvolvimento, sem revisão para publicação.

## Licença

**A definir pelo mantenedor.** Nenhuma licença de código aberto foi escolhida nesta preparação. Gratuidade de uso da aplicação não equivale a uma licença de redistribuição do código. Dependências e modelos têm suas próprias licenças, que devem ser observadas separadamente.
