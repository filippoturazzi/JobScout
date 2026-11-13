# Jobscout — Design System 2.0 · Grafite & Menta

Guia da identidade visual do Jobscout para quem desenvolve (pessoas e o Claude Code). **Siga este arquivo em toda UI do projeto.**

Jobscout é um buscador open source de vagas de tecnologia que roda localmente com as chaves de API de cada pessoa. A pessoa descreve em um parágrafo a vaga que quer e o **Julius**, o assistente, varre várias plataformas e devolve as vagas que combinam, com nota de aderência. A identidade é **grafite + menta**: uma interface de assistente de IA, minimalista e direta, em cinza (nunca preto), com um único acento menta que significa "deu match".

Fonte da verdade visual: `design/jobscoutv2.pen` (na raiz do repositório), boards **Design System**, **01–04** (telas) e **05–08** (fluxos de interação). Comportamento das telas: `design/JOBSCOUT_UI_SPEC.md`.

## Arquivos

| Arquivo | O que é |
|---|---|
| `tokens.css` | **Fonte da verdade** em CSS custom properties: cores (dark padrão + light), fontes, espaços, raios, tamanhos e classes `.text-*` |
| `tokens.json` | Os mesmos tokens em JSON, gerados do `tokens.css`, com a nota de uso de cada um |
| `components.css` | Componentes base com classes `js-*` (Button, IconButton, Send, Tag, Score, JobCard, Composer, Logo, Highlight) |
| `logos/` | `jobscout-mark.svg` (olho em tile menta: app/favicon), `favicon.svg` (igual), `jobscout-glyph.svg` (só o olho menta), `turazzi-dev.png` (créditos) |
| `examples/index.html` | Página antiga de referência (pré-2.0); a referência atual é o `.pen` |

## Como usar

```html
<html lang="pt-BR" data-theme="dark">  <!-- "light" para o tema claro -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="tokens.css">
<link rel="stylesheet" href="components.css">
```

- **Regras para código:**
  - Nunca escreva hex, px de espaçamento, raio ou fonte soltos: use `var(--token)`. As únicas exceções são bordas de 1px, o anel de foco de 2px, larguras máximas de coluna e breakpoints.
  - Para tokens novos, adicione em `tokens.css` (com comentário de uso) e regenere o `tokens.json`; confira contraste (texto ≥ 4.5:1, bordas de controle e foco ≥ 3:1) nos dois temas.
  - Tema: alterne `data-theme` no `<html>`; respeite a preferência salva do usuário, padrão `dark`.

## Princípios

- **Cinza, não preto.** Fundo `--bg` grafite; a sidebar e o painel de detalhes ficam um degrau abaixo (`--bg-sidebar`); cards e compositor um degrau acima (`--surface`).
- **A menta aponta, não decora.** `--brand` / `--accent-text` só em: botão de enviar, ação principal ("Candidatar-se"), score alto, item ativo, a marca e o progresso da busca.
- **Ações são ícones.** Botões de ação são só ícone (`js-icon-btn`), sempre com `aria-label` e `title`. Texto em botão só quando a ação precisa de palavra: confirmar, cancelar, candidatar-se, buscar de novo.
- **Dados em mono, prosa em sans.** Fonte, datas, score, contadores e rótulos de seção em Geist Mono (`.text-meta`); o resto em Geist.
- **Bordas, não sombras.** Profundidade = degraus de cinza + `--border`. Sombra (`--shadow-overlay`) só em overlays: modal, menu, toast.

## Cor

| Token | Dark | Light | Uso |
|---|---|---|---|
| `--bg` | `#202022` | `#f7f7f5` | Fundo da área principal |
| `--bg-sidebar` | `#1a1a1c` | `#efefec` | Sidebar, painel de detalhes, rodapés de card |
| `--surface` | `#28282b` | `#ffffff` | Cards, compositor, menus, modais |
| `--surface-raised` | `#313135` | `#ebebe8` | Hover, item ativo, tags, bolha do usuário |
| `--border` | `#36363b` | `#e0e0dc` | Contorno de cards, divisórias |
| `--border-strong` | `#74747c` | `#8a8a90` | Contorno de controles (≥3:1) |
| `--ink` | `#ededef` | `#18181a` | Texto principal |
| `--ink-muted` | `#a1a1a8` | `#55555c` | Texto secundário |
| `--ink-subtle` | `#8e8e96` | `#67676e` | Metadados em mono, rótulos de seção, placeholder |
| `--brand` | `#7fd6a8` | `#7fd6a8` | Menta: enviar, botão primário, marca |
| `--on-brand` | `#10291c` | `#10291c` | Texto/ícone sobre menta (**nunca branco**) |
| `--accent-text` | `#7fd6a8` | `#1d7a4e` | Menta como texto: score alto, ícone ativo, logo |
| `--accent-subtle` | menta 10% | verde 10% | Fundo do score alto e do ícone ativo |
| `--warn` / `--warn-subtle` | `#e3b76b` | `#8f6210` | Score médio, vaga salva |
| `--danger` / `--danger-subtle` | `#f08080` | `#b42318` | Erros e exclusão |
| `--success` | `#7fd6a8` | `#1d7a4e` | Candidatada, chave encontrada, fonte ativa |
| `--info` | `#9aa6f5` | `#3f51c9` | Avisos neutros |

- **Score:** ≥ 65% → menta · 45–64% → âmbar (`--warn`) · < 45% → neutro. Use `scoreLevel()` de `js/format.js` e `data-level` no `.js-tag--match`.
- Status sempre com palavra ou ícone junto, nunca só a cor.
- Todo elemento interativo: `:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }`.

## Tipografia (Geist / Geist Mono)

| Classe | Tamanho/altura | Peso | Uso |
|---|---|---|---|
| `.text-title` | 42/50, -0.03em | 500 | Pergunta central da home (2ª linha em `--ink-subtle`) |
| `.text-h1` | 26/32, -0.025em | 500 | Título de tela, título da vaga no painel |
| `.text-h2` | 16/22, -0.01em | 500 | Título da vaga no card, títulos de seção |
| `.text-body` | 15/23 | 400 | Texto corrido, compositor |
| `.text-body-sm` | 13/19 | 400 | Empresa, local, ajuda, itens da sidebar |
| `.text-label` | 13/16 | 500 | Botões e rótulos |
| `.text-meta` | 11/16, mono, 0.02em | 400 | Fonte, datas, score, contadores |

## Espaço, raio e layout

- Espaço: `--space-0-5` 2 · `1` 4 · `1-5` 6 · `2` 8 · `2-5` 10 · `3` 12 · `3-5` 14 · `4` 16 · `4-5` 18 · `6` 24 · `7` 28 · `8` 32 · `12` 48.
- Raio: `--radius-xs` 2 (medidor) · `sm` 6 (tags, chips) · `md` 10 (botões, menus) · `lg` 14 (cards) · `xl` 22 (compositor) · `pill` (enviar, avatar, chips de sugestão).
- **Shell:** sidebar `--sidebar-width` (264) | área principal (coluna de 720, ou 1040 nas telas largas) | painel de detalhes `--detail-width` (440) à direita quando aberto. Abaixo de 800px a sidebar vira gaveta e o painel ocupa a tela.

## Componentes (`components.css`)

- **Button** — `js-btn` + `--primary | --secondary | --ghost | --danger`. Primário (menta) no máximo um por área: "Candidatar-se no {fonte}".
- **IconButton** — `js-btn js-btn--ghost js-icon-btn` (36×36; `--sm` 32×32; `--outline` com borda). Ligado/desligado com `aria-pressed`. Sempre `aria-label` + `title`.
- **Send** — `js-send`: círculo menta com `arrow-up`; desabilitado em `--surface-raised`. O texto do envio fica em `.sr-only`.
- **Tag** — `js-tag`: mono, caixa normal, fundo `--surface-raised`. **Score** — `js-tag js-tag--match` + `data-level`: ponto + número.
- **JobCard** — `article.js-card`: linha de topo (quadrado com a inicial da empresa `js-card__logo`, empresa e local, score) → título → tags e data. Selecionado = borda menta.
- **Linha de Minhas vagas** — `jobRow()` / `.jr`: Vaga · Aderência · Fonte · Status · Busca · Data; em telas estreitas fica Vaga · Aderência · Data.
- **Composer** — `form.js-pref.composer`: raio `xl`, sem borda própria no textarea; na home é multilinha com o Send embaixo à direita; na conversa é uma linha só.
- **Highlight** — `js-highlight`: onde uma busca começa ("Nova busca" na sidebar). Em 2.0 é só superfície + borda, sem tracejado.
- **Toast** — `showToast()` de `js/toast.js` (`.toast` em `app.css`): um por vez, embaixo no centro da área principal, some em 6s (pausa com hover/foco). Toda mudança de status de vaga mostra um com "Desfazer"; excluir conversa também (o DELETE só sai quando o toast some).
- **Logo** — `a.js-logo`: `logoMark()` de `js/icons.js` (SVG inline em `currentColor`, pintado com `--accent-text`) + o texto `jobscout`.

## Marca

- Símbolo: um **olho** com a pupila deslocada ("achei"). Menta sobre grafite; no app/favicon, olho escuro (`--on-brand`) num tile menta.
- Wordmark é texto: `jobscout`, **sempre minúsculo**, Geist 600, -0.03em, cor `--ink`.
- Nunca recolorir fora da paleta, distorcer, aplicar sombra/gradiente ou escrever "JobScout".
- Ícones de UI: Lucide, traço 1.75, 14–18px, `currentColor`. Sem ícones preenchidos coloridos, sem emoji.

## Conteúdo e tom

- Português do Brasil e inglês (`locales/*.json`), "você", frases curtas, sentence case.
- O assistente se chama **Julius** ("o Julius").
- Números concretos: "92%", "há 2h", "R$ 6–8 mil". Nunca invente dados que a plataforma não forneceu.
- Erros dizem o que houve e o que fazer.

## Não fazer

Fundo preto puro, laranja, gradientes decorativos, sombras fora de overlays, cards com borda lateral colorida, emoji decorativo, menta em grandes áreas de fundo, texto branco sobre menta, botão de ação com texto quando um ícone com tooltip resolve.
