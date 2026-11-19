# jobscout — Especificação de UI 2.0 (Grafite & Menta)

Fonte da verdade visual: `design/jobscoutv2.pen` (boards "Design System", "01–04" e "05–08 · Fluxo").
Assets do design: `design/jobscoutv2-assets/` (logo turazzi.dev).
Este documento descreve **comportamento** — o que cada controle faz — para a implementação.

Legenda: **[existe]** já existe no backend atual · **[novo]** precisa de backend/lógica nova · **[ui]** só front-end.

---

## 1. Tokens

```css
:root {
  --bg: #202022;          --bg-sidebar: #1A1A1C;
  --surface: #28282B;     --surface-2: #313135;   --surface-3: #2E2E32;
  --border: #36363B;      --border-strong: #4A4A50;
  --text: #EDEDEF;        --text-2: #A1A1A8;      --text-3: #6E6E76;
  --accent: #7FD6A8;      --accent-ink: #10291C;  --accent-soft: #7FD6A81A;
  --warn: #E3B76B;        --danger: #F08080;      --danger-soft: #F080801A;
  --overlay: #0E0E10B3;
  --font: "Geist", system-ui, sans-serif;
  --mono: "Geist Mono", ui-monospace, monospace;
}
```

- Raios: botão-ícone 10 · chip/tag 6 · card 14 · compositor 22 · modal 16 · menu 12.
- Sombra de overlay: `0 12px 32px #00000066`.
- Score: ≥ 65% → accent · 45–64% → warn · < 45% → neutro (surface-2 / text-2).
- Ícones: **lucide**, 16–18px, cor `--text-2` (hover `--text`).
- Tipografia: Display 42/500 (-1.3) · Título de tela 32/500 · Título card 16/500 · Corpo 14–15 · Meta 11–12 mono.

## 2. Componentes

| Componente | Estados | Notas |
|---|---|---|
| IconButton 36×36 (32 compacto) | default · hover (surface-2) · ativo (accent-soft + ícone accent) · focus (anel accent 2px) · disabled | Sempre com `aria-label` + Tooltip |
| SendButton 36 redondo | ativo (accent) · desabilitado (surface-2, campo vazio) · **parar** (fill text, ícone square) durante a busca | |
| Tooltip | aparece após 400ms, some ao sair | Rótulo + atalho opcional em mono |
| Tag / Score | — | Tag mono 11; Score com ponto colorido |
| NavItem / HistoryItem | default · hover (surface) · ativo (surface + texto text) · **hover mostra lixeira no lugar da contagem** | |
| JobCard | default · hover (border-strong) · selecionado (borda accent) | Clique abre o painel de detalhe |
| Composer | vazio · digitando · com currículo anexado · bloqueado (buscando) | Enter envia, Shift+Enter quebra linha |
| Menu / MenuItem | item hover (surface-2) · destrutivo (danger) | Teclado: ↑↓, Enter, Esc |
| ConfirmModal | — | Foco inicial em "Cancelar"; Esc/clique fora cancela |
| Toast | sucesso · com "Desfazer" | 6s, canto inferior central da área principal, máx. 1 por vez |

## 3. Telas e comportamentos

### 3.1 Sidebar (todas as telas)
- **Logo** → vai para Nova busca.
- **Lupa** / `Ctrl K` → Paleta de busca (Fluxo 04.1). [ui] busca local em títulos de conversas + vagas salvas.
- **Painel** / `Ctrl B` → recolhe para trilho de 64px (Fluxo 04.2). Persistir em `localStorage`. < 1024px vira gaveta.
- **Nova busca** → limpa a conversa e foca o compositor.
- **Histórico** agrupado em Hoje / Esta semana / Mais antigas, com nº de vagas. Clique abre a conversa.
  - Hover: contagem → lixeira. Clique na lixeira → ConfirmModal (Fluxo 01). [existe: `DELETE /searches/{id}`]
- **Minhas vagas**, **Configurações** → rotas.
- Rodapé: ponto verde "Local · vX.Y.Z" (versão do package) + link GitHub.

### 3.2 Nova busca
- Título fixo + selo "Julius · assistente de vagas".
- Compositor com placeholder de exemplo. Chips de sugestão preenchem o compositor (não enviam direto).
- Clipe → anexar currículo (Fluxo 04.4). **[novo]**
- Rodapé com as fontes ativas (vem de `SOURCES`).

### 3.3 Conversa / Resultados
1. Mensagem do usuário (bolha à direita).
2. Julius responde (Fluxo 03.1):
   - "Entendi sua busca" + bloco **Critérios** (Cargo, Nível, Modelo, Local, Skills).
   - Progresso por fonte com contador; cards esqueleto. **[novo: precisa de progresso por fonte — hoje há `GET /searches/{id}/runs/{run_id}` para polling]**
   - Botão enviar vira **parar** (Esc). Parar mantém o que já chegou.
   - Ao final: "Encontrei N vagas" + cards ordenados por aderência (mostra 10, "Ver todas" carrega o resto).
3. **Editar critérios** (lápis) → modo edição (Fluxo 03.2): chips removíveis, "+" adiciona, "Refazer busca" cria nova rodada na mesma conversa.
4. Compositor fixo embaixo: texto livre refina a busca (nova rodada). [existe: `POST /searches/{id}/refinements`]
5. Barra superior: título da conversa + nº de vagas + "⋯" → Renomear (inline) · Exportar CSV **[novo]** · Excluir.
6. **Painel de detalhe** (440px, à direita) ao clicar num card:
   - Ações: Salvar (bookmark ↔ bookmark-check) · Abrir original · Fechar (Esc).
   - Empresa, título, tags, bloco de aderência (barra de 10 segmentos + análise do Julius), Combina / Falta, Sobre a vaga + "Ver descrição completa".
   - Rodapé: "Candidatar-se no {fonte}" abre em nova aba; ao voltar o foco para a janela, pergunta "Você se candidatou?" (Fluxo 03.3). Botão ✓ marca como candidatada direto.
   - Toda mudança de status → Toast com Desfazer. [existe: `PATCH /matches/{id}`]

### 3.4 Minhas vagas
- Abas com contagem: Todas · Salvas · Candidatadas · Descartadas.
- Seletor "Todas as buscas" → dropdown com a lista de conversas (filtra por origem).
- Lupa → expande um campo de busca inline (título/empresa).
- Ordenar → menu: Maior aderência (padrão) · Mais recentes · Empresa A–Z.
- **Filtros** → popover (Fluxo 02):
  - Aderência mínima: Todas / ≥30 / ≥50 / ≥70 (segmentado)
  - Modelo: Remoto / Híbrido / Presencial (chips multi)
  - Fonte: fontes ativas (chips multi)
  - Publicada: 24h / 7 dias / 30 dias / Sempre
  - Aplica ao vivo; botão "Ver N vagas" fecha; "Limpar" zera.
  - Aplicados: ícone ativo + badge com nº de filtros; chips removíveis abaixo das abas; "Limpar tudo".
  - Estado nos query params: `?min=50&modo=remoto&fonte=indeed&desde=7d&ordem=score`.
- Linha da tabela: clique abre o mesmo painel de detalhe (como drawer). Hover mostra ações: Salvar · Abrir original.
- Estado vazio (sem resultados / aba vazia) com ação "Limpar filtros".
- Paginação: 20 por página.

### 3.5 Configurações
- Somente leitura (vem do `.env`): Modelo (provedor, modelo, embeddings, status da chave), Fontes (Ativa / Desligada).
- Editável no app: Tema (Escuro / Claro / Sistema) e Idioma (PT / EN) → `localStorage` / `PUT /me/locale`.
- Sobre: versão, licença MIT, links GitHub / Docs / Reportar problema.
- Créditos: "Desenvolvido por turazzi.dev" (logo em `jobscoutv2-assets/turazzi-dev.png`).

## 4. Atalhos
| Atalho | Ação |
|---|---|
| Ctrl K | Paleta de busca |
| Ctrl Shift O | Nova busca |
| Ctrl B | Recolher sidebar |
| Enter / Shift+Enter | Enviar / nova linha |
| Esc | Fecha overlay · para a busca em andamento |

## 5. Acessibilidade
- Todo botão só-ícone: `aria-label` + tooltip.
- Foco visível: anel `--accent` 2px com offset 2px.
- Modal e paleta prendem o foco e devolvem o foco ao gatilho ao fechar.
- Contraste: texto `--text-3` só para metadado, nunca para conteúdo essencial.
