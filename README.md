# foto-ritocco

Skill per [Claude Code](https://claude.com/claude-code) che diagnostica e ritocca in locale foto di giochi da tavolo (carte, plance, scatole, segnalini, miniature) per pubblicarle su un blog.

L'obiettivo è un miglioramento visibile che non falsa il gioco: forme, testo, icone e tinte dei componenti restano quelli reali.

## Cosa fa

- Bilancia il bianco su un'area neutra e dà lo stesso bianco alle foto scattate sulla stessa superficie.
- Regola luminosità, contrasto, saturazione e nitidezza, e controlla che i bianchi non si brucino.
- Riduce il rumore.
- Toglie oggetti dallo sfondo con LaMa e ingrandisce le foto piccole con Real-ESRGAN, solo quando serve.
- Raddrizza la prospettiva solo su richiesta.
- Esporta in WebP, JPEG o PNG in sRGB, senza metadati e quindi senza GPS.

Gli originali non vengono modificati. I risultati vanno nella sottocartella `modificate/` della cartella che contiene le foto.

## Requisiti

- Claude Code
- Python 3 con il modulo `venv` (provato con Python 3.13 su Debian)
- PhotoCraft è facoltativo: serve solo come ripiego per le operazioni che lo script non copre

## Installazione

La skill è in `.claude/skills/foto-ritocco`. Claude Code la trova da solo se lavori in questa cartella. Per usarla in un altro progetto, copia lì la stessa cartella.

Al primo uso la skill crea un ambiente Python in `~/.cache/foto-ritocco/venv`. I modelli si scaricano solo quando servono, in `~/.cache/foto-ritocco/models`, con verifica SHA-256:

| Modello | Dimensione | Licenza dichiarata |
|---|---|---|
| [Real-ESRGAN general x4v3](https://huggingface.co/Heliosoph/realesrgan-onnx) | 5 MB | BSD-3-Clause |
| [LaMa](https://huggingface.co/Carve/LaMa-ONNX) | 208 MB | Apache-2.0 |

## Uso

In una sessione di Claude Code, chiedi per esempio:

```text
Ho le foto del gioco in foto/partita, preparamele per il blog.
```

Lo script funziona anche da solo:

```bash
PY=~/.cache/foto-ritocco/venv/bin/python
E=.claude/skills/foto-ritocco/scripts/restore_engine.py

$PY $E diagnose foto.jpg --preview modificate/.anteprime/foto.jpg
$PY $E process foto.jpg modificate/foto.webp --contrast 0.2 --clarity 0.15 --highlights 0.3 --saturation 0.2 --max-side 1600 --sharpen 0.6
$PY $E compare foto.jpg modificate/foto.webp modificate/.anteprime/confronto.jpg
```

`python restore_engine.py process --help` elenca tutte le opzioni.

## Test

```bash
$PY .claude/skills/foto-ritocco/scripts/test_engine.py
```

Questo controllo non usa i modelli. I casi in `.claude/skills/foto-ritocco/evals/` sono prove con Claude e fanno riferimento a foto in `foto/partita`, che non sono in questo repository: per eseguirli servono foto proprie.

## Limiti

- I valori delle ricette sono stati tarati su 11 foto di un solo gioco, con tappeto verde e tavolo bianco. Vedi [miglioramenti.md](miglioramenti.md).
- Un riflesso forte non si può recuperare, e nemmeno il mosso o il fuori fuoco: in quei casi conviene rifare la foto.
- LaMa inventa ciò che riempie, quindi non va usato su testo o icone.

## Origine

`istruzioni.md` è la specifica iniziale da cui è nata la skill. La skill se ne discosta in alcuni punti, per esempio non usa GFPGAN né CodeFormer.

## Licenza

[MIT](LICENSE). I modelli hanno licenze proprie, indicate nella tabella sopra, e non sono inclusi nel repository.
