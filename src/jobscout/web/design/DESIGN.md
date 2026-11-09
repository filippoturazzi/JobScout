# Jobscout — Design System

Guia da identidade visual do Jobscout para quem desenvolve (pessoas e o Claude Code). **Siga este arquivo em toda UI do projeto.**

Jobscout é um buscador open source de vagas de tecnologia: a pessoa roda localmente com as próprias chaves de API, descreve em um parágrafo a vaga que quer e o Jobscout varre várias plataformas (Brasil e exterior) e devolve as vagas compatíveis. A identidade é **preto + Scout Orange**: ferramenta de dev, técnica e direta, com um único ponto de calor que indica "achei".

## Arquivos

| Arquivo | O que é |
|---|---|
| `tokens.css` | **Fonte da verdade** em CSS custom properties: cores (dark padrão + light), fontes, espaços, raios e classes `.text-*` |
| `tokens.json` | Os mesmos tokens em JSON, com nota de uso de cada um |
| `components.css` | Componentes base com classes `js-*` (Button, Tag, JobCard, PreferenceInput, Logo) |
| `logos/` | `jobscout-mark.svg` (principal), `jobscout-mark-orange.svg`, `jobscout-glyph.svg`, `favicon.svg` |
| `examples/index.html` | Tela principal de referência (abra no navegador) |

## Como usar

```html
<html lang="pt-BR" data-theme="dark">  <!-- "light" para o tema claro -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap">
<link rel="stylesheet" href="tokens.css">
<link rel="stylesheet" href="components.css">
```

- Em React/Next: importe `tokens.css` e `components.css` no CSS global; em Next.js pode trocar o `<link>` das fontes por `next/font/google` mantendo os nomes de família.
- **Regras para código:**
  - Nunca escreva hex, px de espaçamento ou fonte soltos: use `var(--token)`.
  - Para tokens novos, adicione em `tokens.css` **e** `tokens.json`, com comentário de uso, e confira contraste (texto ≥ 4.5:1, bordas de controle e foco ≥ 3:1) nos dois temas.
  - Tema: alterne `data-theme` no `<html>`; respeite a preferência salva do usuário, padrão `dark`.

## Princípios

- **O laranja aponta, não decora.** `--brand` só onde há algo encontrado ou a ação principal: botão primário, card selecionado, score de match, a marca.
- **Dados em mono, prosa em sans.** Plataforma, datas, salário e score em `.text-meta` (JetBrains Mono); textos em `.text-body` (IBM Plex Sans); títulos em Bricolage Grotesque.
- **Escuro primeiro.** `dark` é o padrão; `light` usa os mesmos papéis.
- **Bordas, não sombras.** Profundidade = `--surface` → `--surface-raised` + `--border`. Sem sombras, sem gradientes.

## Cor

| Token | Dark | Light | Uso |
|---|---|---|---|
| `--bg` | `#0b0b0c` | `#faf8f5` | Fundo da página |
| `--surface` | `#141416` | `#ffffff` | Cards, painel de detalhes, campo de preferências |
| `--surface-raised` | `#1c1c1f` | `#f2efea` | Hover, botão secundário |
| `--border` | `#2c2c30` | `#e2dcd2` | Divisórias, contorno de cards |
| `--border-strong` | `#6a6870` | `#8f8a82` | Contorno de controles (≥3:1) |
| `--ink` | `#f4f1ec` | `#141416` | Texto principal |
| `--ink-muted` | `#a8a49c` | `#5c5852` | Texto secundário, placeholder |
| `--brand` | `#ff6a13` | `#ff6a13` | Scout Orange: fundo do botão primário, seleção, marca |
| `--brand-hover` | `#ff8236` | `#e85a08` | Hover do primário |
| `--on-brand` | `#0b0b0c` | `#0b0b0c` | Texto sobre laranja (**sempre preto**) |
| `--accent-text` | `#ff8a3d` | `#b23f08` | Laranja como texto: links, score |
| `--accent-subtle` | `#2b1708` | `#ffe7d6` | Fundo da tag de match |
| `--focus` | `#ff8a3d` | `#b23f08` | Anel de foco 2px, offset 2px |
| `--success` | `#4ade80` | `#11703f` | Candidatado / Nova |
| `--danger` | `#f87171` | `#b42318` | Erros |
| `--info` | `#7cb4ff` | `#1d4ed8` | Remoto, avisos, progresso |

- Nunca branco sobre laranja. Nunca `--brand` como cor de texto (use `--accent-text`).
- Status sempre com palavra ou ícone junto, nunca só a cor.
- Todo elemento interativo: `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }`.

## Tipografia

| Classe | Fonte | Tamanho/altura | Peso | Uso |
|---|---|---|---|---|
| `.text-display` | Bricolage Grotesque | 48/52, -0.03em | 700 | Wordmark, telas vazias (1 por tela) |
| `.text-title` | Bricolage Grotesque | 36/42, -0.025em | 700 | Pergunta central da home, acima do campo |
| `.text-h1` | Bricolage Grotesque | 28/34, -0.02em | 700 | Título da vaga nos detalhes |
| `.text-h2` | Bricolage Grotesque | 18/24, -0.01em | 600 | Título no card, seções |
| `.text-body` | IBM Plex Sans | 15/22 | 400 | Descrição, campo de preferências |
| `.text-body-sm` | IBM Plex Sans | 13/18 | 400 | Empresa, local, ajuda |
| `.text-label` | IBM Plex Sans | 13/16 | 600 | Botões, rótulos |
| `.text-meta` | JetBrains Mono | 12/16, 0.02em | 500 | Plataforma, datas, salário, score |

## Espaço, raio e layout

- Espaço: `--space-1` 4 · `--space-2` 8 · `--space-3` 12 · `--space-4` 16 · `--space-6` 24 · `--space-8` 32. Não use valores fora da escala.
- Raio: `--radius-sm` 6 (tags) · `--radius-md` 10 (botões, textarea) · `--radius-lg` 16 (cards, painéis) · `--radius-pill` (score).
- **Tela principal:** header com logo → `PreferenceInput` em largura total → abaixo, lista de `JobCard` à esquerda (~400px, gap `--space-4`) e painel de detalhes à direita (`--surface`, padding `--space-6`, título `.text-h1`, sticky). Abaixo de 800px: uma coluna; lista e detalhes viram telas separadas. Largura máxima 1200px.

## Componentes (`components.css`)

- **Button** — `js-btn` + `js-btn--primary | --secondary | --ghost`. Primário **no máximo um por tela** ("Buscar vagas", "Candidatar-se"). Secundário: "Salvar vaga", "Abrir original". Ghost: "Ignorar", "Limpar".
- **Tag** — `js-tag` (plataforma, senioridade, modalidade), `js-tag--match` (score, pill laranja suave, uma por card), `js-tag--remote`, `js-tag--success`. Mono, caixa alta, até ~16 caracteres, máx. 4 por card.
- **JobCard** — `article.js-card` com `aria-selected`. Ordem fixa: título (`js-card__title`) → empresa · local (`js-card__company`) → tags (`js-card__tags`) → linha `js-meta` (salário · tempo). Score no canto superior direito. Selecionado = borda `--brand`; só um por vez. Sem salário, omita (não invente "A combinar"). Sem logos de empresa, sem borda lateral colorida, sem sombra.
  - Dados: `title, company, location, source, workMode, seniority, matchScore (0–100), salary?, postedAt, selected`.
- **PreferenceInput** — `form.js-pref` com `label` ("Que vaga você procura?"), `textarea` (placeholder = exemplo concreto completo) e rodapé `js-pref__foot` (status em `js-meta` à esquerda, botão primário à direita). Buscando: botão "Buscando…" desabilitado e progresso por plataforma em `--info`.
- **Logo** — `span.js-logo` com `<img src="logos/jobscout-mark.svg" alt="">` + texto `jobscout`.

## Marca

- Símbolo: lente com ponto central ("mirei e achei"). Principal: lente laranja em tile preto. Alternativa: lente preta em tile laranja.
- Wordmark é texto: `jobscout`, **sempre minúsculo**, Bricolage Grotesque 700, -0.03em, cor `--ink`. Gap `--space-2` entre símbolo e texto.
- Nunca recolorir, distorcer, aplicar sombra/gradiente ou escrever "JobScout".
- Ícones de UI: traço 1.5–2px, 16/20px, `currentColor` (sugestão: Lucide). Sem ícones preenchidos coloridos, sem emoji.

## Conteúdo e tom

- Português do Brasil, "você", frases curtas, sentence case (inclusive botões).
- Ações no infinitivo: "Buscar vagas", "Salvar vaga", "Candidatar-se".
- Números concretos: "92% match", "há 2h", "R$ 6–8 mil". Nunca invente dados que a plataforma não forneceu.
- Erros dizem o que houve e o que fazer: "Chave da API do LinkedIn inválida. Confira em Configurações → Plataformas."

## Não fazer

Gradientes azul/roxo, sombras pesadas, cards com borda lateral colorida, emoji decorativo, Inter/Roboto, laranja em grandes áreas de fundo, texto branco sobre laranja.
