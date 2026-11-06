---
name: foto-ritocco
description: Diagnostica e ritocca in locale foto di giochi da tavolo (carte, plance, scatole, segnalini, miniature) per pubblicarle sul blog, senza falsare colori stampati, testo e icone. Usala ogni volta che l'utente vuole sistemare, migliorare, schiarire, ripulire, correggere o preparare per il blog una foto o una cartella di foto, anche se non dice "ritocco". Casi tipici sono dominante di colore, foto scura, rumore, poca nitidezza, foto piccola da ingrandire, polvere, dita o oggetti da togliere, riflessi, carta da raddrizzare.
---

# Foto ritocco

Le foto sono scattate dall'utente e finiscono sul suo blog. Il risultato deve sembrare la stessa foto scattata meglio: più luminosa, nitida e viva, con un miglioramento che si vede a colpo d'occhio. Una foto solo ridimensionata non è un ritocco, e l'utente lo considera lavoro inutile. Il limite è la fedeltà: forme, testo, icone e tinte dei componenti restano quelli reali. Per questo la skill usa prima correzioni globali deterministiche e i modelli neurali solo quando servono davvero.

## Preparazione

Comandi dalla radice del progetto:

```bash
PY=~/.cache/foto-ritocco/venv/bin/python
E=.claude/skills/foto-ritocco/scripts/restore_engine.py
[ -x "$PY" ] || .claude/skills/foto-ritocco/scripts/setup.sh
```

I modelli si scaricano al primo uso con verifica SHA-256: Real-ESRGAN 5 MB, LaMa 208 MB.

## Procedura

### 1. Diagnosi

`CARTELLA` è la cartella che contiene le foto.

```bash
$PY $E diagnose FOTO --preview CARTELLA/modificate/.anteprime/NOME.jpg
```

Guarda l'anteprima e leggi le misure. Il comando stampa il fattore per convertire le coordinate dell'anteprima in quelle da passare a `process`. Valuta:

- colore ed esposizione: dominanti, foto scura o bruciata, poco contrasto;
- nitidezza: mosso, fuori fuoco, foto troppo piccola;
- difetti: rumore, polvere, dita, oggetti estranei, riflessi;
- zone delicate: testo, numeri, icone, volti illustrati.

Le medie RGB non bastano a dire che c'è una dominante: una plancia rossa ha media rossa anche se la foto è corretta. Decidi guardando le parti che dovrebbero essere neutre.

### 2. Scelta degli interventi

Parti da questa base su ogni foto, poi regola i valori guardando il risultato. Togli un passaggio solo se la foto non ne ha bisogno.

| Passaggio | Opzione di `process` | Valori di partenza |
|---|---|---|
| Bilanciamento del bianco | `--wb-ref x,y,w,h` | Area neutra nella realtà: tavolo bianco, bordo bianco di una tessera, cartoncino grigio |
| Luminosità | `--stretch` e `--gamma` | `--stretch 0.3`, `--gamma 1.15` se la mediana di luminanza è sotto 100 |
| Contrasto | `--contrast` | 0.25 |
| Stacco di superfici piatte o velate | `--clarity` | 0.2 |
| Colori spenti | `--saturation` | 0.2-0.3 |
| Nitidezza finale | `--sharpen` | 0.6 dopo `--max-side`: il ridimensionamento ammorbidisce sempre |

**Bianchi bruciati.** Con superfici bianche ampie, come un tavolo o un muro, la base schiaccia le sfumature e il bianco diventa una macchia piatta, il difetto più evidente per l'utente. In questi casi non usare `--stretch` né `--gamma`: parti da `--contrast 0.2 --clarity 0.15 --highlights 0.3`. `process` stampa `burned whites: prima -> dopo`. Il valore finale deve restare sotto 0.5%: se lo supera, riduci i toni e ripeti. Controlla la misura su ogni foto, perché nel foglio d'insieme il difetto si vede poco. Il bianco deve conservare ombre e passaggi.

**Stessa superficie, stesso bianco.** Foto scattate sullo stesso tavolo devono mostrare lo stesso bianco, altrimenti in un articolo la differenza salta all'occhio. Usa per tutte `--wb-ref` con la stessa `--wb-level`, per esempio 215, e la stessa ricetta di tono. Scegli l'area di riferimento su una parte del tavolo ben illuminata e lontana dagli oggetti, mai in un'ombra. `process` stampa `white reference`: se il valore è molto più basso di quello delle altre foto, o i tre canali non sono vicini, l'area è sbagliata, quindi cambiala. La regola vale per ogni gruppo di foto con lo stesso sfondo chiaro, non per il tappeto verde.

Controlla il bilanciamento in ogni foto. Una luce calda rende crema un tavolo bianco, e l'occhio la nota subito. Non serve se l'area neutra risulta già neutra. Il tappeto verde non è un riferimento: resta verde.

Interventi solo per il difetto specifico:

| Difetto | Opzione | Nota |
|---|---|---|
| Velo o riflesso diffuso | `--highlights 0.25` con `--clarity 0.3` | Attenua, ma scurisce anche i bianchi veri |
| Riflesso forte | nessuna | La stampa sotto non è recuperabile: dillo e consiglia di rifare la foto con luce laterale o filtro polarizzatore |
| Dominante senza riferimento neutro | chiedi all'utente | `--wb-grayworld` solo se la scena non ha un colore prevalente |
| Ombre chiuse | `--clahe 1.2` | Ultima scelta: su superfici piatte può creare aloni |
| Rumore | `--denoise 3` | Da 3 a 6: valori alti cancellano la texture di carta e legno |
| Mosso o fuori fuoco | `--sharpen` fino a 1 | Non recupera il dettaglio perso: dillo e consiglia di rifare la foto |
| Foto piccola | `--upscale` | Real-ESRGAN 4x, vedi sotto |
| Polvere, dita, oggetti | `--inpaint-poly` | LaMa, vedi sotto |
| Carta o plancia storta | `--perspective` | Solo su richiesta, vedi sotto |

Lo script applica i passaggi sempre in quest'ordine: prospettiva, rimozione, bianco, tono, saturazione, rumore, ingrandimento, ridimensionamento, nitidezza.

**Prospettiva e composizione.** Inquadrature in prospettiva, angolazioni e ritagli sono spesso scelte volute. Non correggerli di tua iniziativa. Se una carta sembra storta per errore, segnala il dubbio con `AskUserQuestion` e procedi solo con una risposta. Lo stesso vale per ritaglio e rimozione dello sfondo.

**Real-ESRGAN.** Può inventare o deformare lettere e simboli piccoli e crea aloni sui bordi netti. Usalo solo se la foto è più piccola della misura finale. `--tile 256` riduce la RAM necessaria.

**LaMa.** Inventa ciò che riempie, quindi va bene su sfondi e superfici uniformi. Tutto ciò che cade nell'area viene sostituito, anche la scatola accanto all'oggetto. Traccia quindi un poligono con `--inpaint-poly "x1,y1;x2,y2;..."` che segue il contorno dell'oggetto e si ferma prima del soggetto, invece di un rettangolo. Usa `--inpaint-rect` solo se il rettangolo tocca esclusivamente lo sfondo. Non usarlo sopra testo, numeri o icone: se il difetto li tocca, avvisa l'utente e chiedi. Non può recuperare la stampa sotto un riflesso forte: consiglia di rifare la foto. Lavora a 512 px: su aree grandi il riempimento risulta morbido e lo script lo segnala.

### 3. Esecuzione

```bash
$PY $E process FOTO CARTELLA/modificate/NOME.webp [opzioni] --max-side 1600
```

Scrivi le immagini finali sempre nella sottocartella `modificate/` della cartella che contiene le foto: per `foto/partita/foto.jpg` il risultato va in `foto/partita/modificate/foto.webp`. Anteprime e confronti vanno in `modificate/.anteprime/`. Non sovrascrivere altri file. Lo script legge l'originale senza modificarlo e rifiuta un output uguale all'input. Tiene l'orientamento della foto, converte i colori in sRGB e toglie tutti i metadati, GPS compreso.

Formato predefinito per il blog: WebP, qualità 85, lato lungo 1600 px. Se l'utente indica un altro formato o misura, segui quello. Sono supportati `.webp`, `.jpg` e `.png`.

### 4. Verifica

```bash
$PY $E compare FOTO CARTELLA/modificate/NOME.webp CARTELLA/modificate/.anteprime/NOME-confronto.jpg
```

Guarda il confronto. Se hai usato `--max-side`, `compare` adatta la seconda immagine alla prima. Con `--crop x,y,w,h` controlla da vicino il testo più piccolo, in coordinate della foto originale. Dopo `--perspective` o `--upscale` confronta senza `--crop`, perché le coordinate cambiano.

Controlla che:

- testo, numeri e icone siano leggibili e identici all'originale;
- i colori stampati siano credibili e non virati;
- non ci siano aloni, giunture o texture plastificate.

Se qualcosa è peggiorato, riduci o togli quel passaggio e ripeti. Se il prima e il dopo sembrano quasi uguali, il ritocco non è finito: rafforza la base.

Dopo una rimozione, il confronto intero non basta: i danni si vedono solo da vicino. Fai sempre un `compare --crop` attorno all'area rimossa, a piena risoluzione, e guarda il confine con il soggetto e le linee dello sfondo. Scrivi che il soggetto è intatto solo dopo questo controllo.

### 5. Risposta

Indica il file finale, i difetti trovati, i comandi applicati, ciò che hai lasciato com'era e i limiti rimasti. Segnala sempre le zone ricostruite da LaMa o ingrandite con Real-ESRGAN.

## Più foto insieme

Per foto dello stesso set parti dagli stessi valori di tono e saturazione, ma diagnostica ogni foto e distingui le foto su fondo bianco da quelle su fondo scuro o colorato, che vogliono ricette diverse: `--wb-ref` usa coordinate proprie e foto scure o velate richiedono valori diversi. Regola la ricetta su una foto campione, poi applicala alle altre e controllale tutte in un solo foglio, che costa meno token di un'anteprima per foto:

```bash
$PY $E sheet CARTELLA/modificate/.anteprime/foglio.jpg FOTO1 CARTELLA/modificate/NOME1.webp FOTO2 CARTELLA/modificate/NOME2.webp
```

Rifai la singola foto se nel foglio non migliora o peggiora. Confronta anche le foto tra loro, non solo con il proprio originale: stesse superfici devono avere lo stesso tono.

## Fallback: PhotoCraft

Usa PhotoCraft per ciò che lo script non copre, per esempio rimozione dello sfondo, o se un modello fallisce. Lavora sempre con `--out` su un file diverso e non usare `--in-place`.

```bash
photocraft-cli commands --json --filter NOME_COMANDO   # parametri del comando
photocraft-cli run FOTO --cmd image.autoTone --out CARTELLA/modificate/NOME.png
```

Comandi utili: `image.autoTone`, `image.adjustments.shadowsHighlights`, `filter.noise.reduceNoise`, `filter.sharpen.smartSharpen`, `edit.contentAwareFill`, `layer.removeBackground`. Per ritocchi manuali, copia la foto in `CARTELLA/modificate/` e apri la copia con `photocraft COPIA`.

Se la foto è HEIC o RAW e lo script non la apre, prova a convertirla in una copia con `photocraft-cli convert`.

## Quando chiedere

Usa `AskUserQuestion` se una correzione può cambiare il contenuto o la scelta fotografica: prospettiva dubbia, difetto sopra il testo, nessun riferimento neutro su una foto con colore prevalente, ritaglio o sfondo non richiesti.
