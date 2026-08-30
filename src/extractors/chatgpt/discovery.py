"""Orquestra descoberta completa de IDs de convs em todas as fontes.

Unifica: main + archived + shared + project conversations.
Dedupe no final por conversation_id.
"""

import asyncio
import logging
import re
from urllib.parse import unquote, urlparse

from src.extractors.chatgpt.api_client import ChatGPTAPIClient
from src.extractors.chatgpt.models import ConversationMeta, ProjectMeta

logger = logging.getLogger(__name__)

# Page-backed discovery normalizes the metadata inside the browser before it
# crosses the Playwright bridge, so the established 100-item pagination stays
# safe and efficient.
PAGE_SIZE = 100
PROJECT_PAGE_SLEEP_SECONDS = 0.5  # matches migrate.js rate limit
PROJECT_ID_RE = re.compile(r"g-p-[a-f0-9]+")
PROJECT_HOME_ROUTE_RE = re.compile(r"/g/(g-p-[^/]+)/project(?:/|$)")


async def _expand_projects_section(page) -> bool:
    """Expande o botao atual ``Show more`` da secao Projects, se presente.

    O layout atual mantem apenas alguns projetos visiveis inicialmente e usa
    esse botao (separado do menu legado ``More``) para materializar o restante
    da lista. A ausencia do botao e normal quando todos ja estao expostos ou
    em layouts anteriores.
    """
    trigger = page.get_by_role("button", name=re.compile(r"^show more$", re.I))
    try:
        if await trigger.count() == 0:
            return False
        await trigger.first.click(timeout=5_000)
        # A lista e materializada em lotes (observado: 20 -> 40 -> 49), entao
        # esperamos a contagem de botoes estabilizar em vez de usar um atraso
        # fixo dependente do carregamento da pagina.
        buttons = page.get_by_label("Open project home", exact=True)
        previous_count = -1
        stable_checks = 0
        for attempt in range(16):
            current_count = await buttons.count()
            if current_count == previous_count:
                stable_checks += 1
            else:
                stable_checks = 0
                previous_count = current_count
            # A primeira pausa entre lotes pode durar alguns segundos; nao
            # aceite estabilidade antes da janela minima de 3 s.
            if attempt >= 6 and stable_checks >= 2:
                break
            await page.wait_for_timeout(500)
        logger.info(
            f"  Projects: lista expandida pelo botao Show more ({previous_count} botoes)"
        )
        return True
    except Exception as exc:
        logger.warning(f"Show more de Projects falhou: {exc}")
        return False


def _project_meta_from_home_url(url: str) -> ProjectMeta | None:
    """Converte a rota aberta pelo botao ``Open project home`` em metadata."""
    match = PROJECT_HOME_ROUTE_RE.search(urlparse(url).path)
    if not match:
        return None
    route_slug = unquote(match.group(1))
    id_match = PROJECT_ID_RE.match(route_slug)
    if not id_match:
        return None
    project_id = id_match.group()
    name = route_slug.removeprefix(project_id).removeprefix("-").replace("-", " ")
    return ProjectMeta(
        id=project_id,
        name=name or "(unknown)",
        discovered_via="dom_navigation",
    )


async def _discover_projects_via_project_homes(
    page, projects: list[ProjectMeta], known_ids: set[str]
) -> None:
    """Enumera o layout atual de Projects navegando pelos botoes da sidebar.

    A interface de 2026-08 mostra os projetos como botoes sem href ou ID no
    DOM. Cada ``Open project home`` leva a uma rota que contem ``g-p-...``.
    A volta para a home recolhe a lista; por isso a reexpansao e feita a cada
    iteracao. Erro em um projeto nao impede os demais.
    """
    buttons = page.get_by_label("Open project home", exact=True)
    button_count = await buttons.count()
    if button_count == 0:
        return

    logger.info(f"  Projects: enumerando {button_count} botoes pela navegacao da UI")
    for index in range(button_count):
        try:
            # Depois da primeira volta, a sidebar retorna aos 7 iniciais.
            # Reabre a lista completa antes de selecionar o mesmo indice.
            if index:
                await page.goto(
                    "https://chatgpt.com/", wait_until="domcontentloaded", timeout=30_000
                )
                await page.wait_for_timeout(500)
                await _expand_projects_section(page)

            buttons = page.get_by_label("Open project home", exact=True)
            if await buttons.count() <= index:
                logger.warning(
                    f"Projects UI exibiu menos botoes que o esperado no indice {index}; parando"
                )
                break
            await buttons.nth(index).click(timeout=10_000)
            await page.wait_for_url(PROJECT_HOME_ROUTE_RE, timeout=15_000)
            meta = _project_meta_from_home_url(page.url)
            if meta is None:
                logger.warning("Projects UI abriu uma rota sem ID reconhecivel")
            elif meta.id not in known_ids:
                projects.append(meta)
                known_ids.add(meta.id)
            if (index + 1) % 10 == 0 or index + 1 == button_count:
                logger.info(f"  Projects UI: {index + 1}/{button_count} verificados")
        except Exception as exc:
            logger.warning(f"Projects UI falhou no botao {index + 1}/{button_count}: {exc}")


async def discover_all(
    client: ChatGPTAPIClient, page=None
) -> tuple[list[ConversationMeta], dict[str, str]]:
    """Descoberta completa — todas as fontes + dedup.

    Args:
        client: ChatGPTAPIClient autenticado.
        page: opcional, playwright.Page pra DOM fallback de projects (nao usado no MVP).

    Returns:
        (convs_deduplicadas, project_names_by_id) — mapa pra enriquecer raws
        com _project_name no orchestrator (senao so temos _project_id).
    """
    by_id: dict[str, ConversationMeta] = {}

    # Main
    logger.info("Descobrindo convs principais (paginado)...")
    async for meta in _paginate(client.list_conversations):
        by_id[meta.id] = meta
    logger.info(f"  Main: {len(by_id)} convs")

    # Archived
    logger.info("Descobrindo convs arquivadas (paginado)...")
    count_before = len(by_id)
    async for meta in _paginate(client.list_archived):
        by_id[meta.id] = meta  # pode sobrescrever main (archived tem is_archived=true)
    logger.info(f"  Archived: +{len(by_id) - count_before} convs novas")

    # Shared
    logger.info("Descobrindo convs compartilhadas...")
    count_before = len(by_id)
    async for meta in _paginate(client.list_shared):
        by_id[meta.id] = meta
    logger.info(f"  Shared: +{len(by_id) - count_before} convs novas")

    # Projects — 5-method cascade (methods 2+3 em api_client.list_projects, 1+5 aqui)
    logger.info("Descobrindo projetos + suas convs...")
    projects = await client.list_projects()  # métodos 2 (/projects) + 3 (/gizmos/discovery/mine)
    known_ids = {p.id for p in projects}

    # Método 1: scan gizmo_id / conversation_template_id / workspace_id das convs ja descobertas
    for meta in by_id.values():
        pid = meta.project_id
        if pid and pid.startswith("g-p-") and pid not in known_ids:
            projects.append(ProjectMeta(id=pid, name="(unknown)", discovered_via="conversation_scan"))
            known_ids.add(pid)

    # Métodos DOM/NextData sao fallback apenas quando as APIs e o scan de
    # conversas nao forneceram projects. No layout atual, a API Snorlax e a
    # fonte autoritativa; nao navegamos a UI desnecessariamente.
    if page is not None and not projects:
        try:
            await page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=30000)
            # ChatGPT nunca fica "networkidle" (websocket ativo) — esperamos o nav + damos tempo
            try:
                await page.wait_for_selector("nav", timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)

            # 4a: Expandir sidebar se colapsada (toggle em botao com aria-label)
            await page.evaluate(
                """() => {
                    const toggles = document.querySelectorAll('button[aria-label]');
                    for (const t of toggles) {
                        const label = (t.getAttribute('aria-label') || '').toLowerCase();
                        if (label.includes('open sidebar') || label.includes('expand sidebar')) {
                            t.click();
                            return;
                        }
                    }
                }"""
            )
            await page.wait_for_timeout(1000)

            # 4b: Scroll agressivo em todos os containers potenciais da sidebar
            # Repete ate nao rolar mais (fim atingido) ou 15 tentativas
            for _ in range(15):
                scrolled_any = await page.evaluate(
                    """() => {
                        const containers = [
                            ...document.querySelectorAll('nav'),
                            ...document.querySelectorAll('aside'),
                            ...document.querySelectorAll('[class*="scroll" i]'),
                            ...document.querySelectorAll('[class*="sidebar" i]'),
                        ];
                        let progressed = false;
                        for (const el of containers) {
                            if (el.scrollHeight <= el.clientHeight) continue;
                            const before = el.scrollTop;
                            el.scrollTop = el.scrollHeight;
                            if (el.scrollTop > before) progressed = true;
                        }
                        return progressed;
                    }"""
                )
                await page.wait_for_timeout(800)
                if not scrolled_any:
                    break

            # 4c: Layout atual: "Show more" pertence a Projects e revela a
            # lista completa antes dos seletores DOM. Nao confundir com o
            # menu global legado "More" abaixo.
            await _expand_projects_section(page)
            await _discover_projects_via_project_homes(page, projects, known_ids)

            # 4d: Layout legado: abre dropdown "More" da secao Projects (Radix menu)
            # Descobrimento via debug: o botao "More" fica dentro de <li> na secao Projects,
            # trigger e o div com aria-haspopup="menu". Precisa click REAL (pointer events),
            # click() via JS so dispara focus — Radix nao abre o menu.
            try:
                # page.locator em vez de JS — simula mouse real (pointerdown + up + click)
                more_trigger = page.locator(
                    "nav li:has-text('More') [aria-haspopup='menu']"
                ).first
                try:
                    await more_trigger.wait_for(state="visible", timeout=10000)
                    await more_trigger.click(timeout=5000)
                    opened = True
                except Exception as exc:
                    logger.warning(f"More trigger click falhou: {exc}")
                    opened = False

                if opened:
                    await page.wait_for_timeout(2500)  # tempo extra pro menu montar
                    # Scroll iterativo no menu — usa scrollIntoView no ultimo item
                    # (virtualizado: renderiza em janela). Repete ate estabilizar.
                    prev_count = -1
                    stable_iters = 0
                    for _ in range(50):
                        count = await page.evaluate(
                            """() => {
                                const menu = document.querySelector('[role="menu"]');
                                if (!menu) return 0;
                                // 1. Scroll todos os containers scrollaveis
                                const scrollables = [menu, ...menu.querySelectorAll('*')];
                                for (const el of scrollables) {
                                    if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
                                }
                                // 2. scrollIntoView no ultimo item (dispara lazy load virtualizado)
                                const items = menu.querySelectorAll('[role="menuitem"], a[href*="g-p-"]');
                                if (items.length > 0) {
                                    items[items.length - 1].scrollIntoView({block: 'end', behavior: 'instant'});
                                }
                                return menu.querySelectorAll('a[href*="g-p-"]').length;
                            }"""
                        )
                        if count == prev_count:
                            stable_iters += 1
                            if stable_iters >= 3 and count > 0:
                                break
                        else:
                            stable_iters = 0
                        prev_count = count
                        await page.wait_for_timeout(500)

                    # Coleta os hrefs do menu antes de fechar
                    menu_items = await page.evaluate(
                        """() => {
                            const menu = document.querySelector('[role="menu"]');
                            if (!menu) return [];
                            return Array.from(menu.querySelectorAll('a[href*="g-p-"]')).map(a => ({
                                href: a.getAttribute('href'),
                                text: (a.textContent || '').trim(),
                            }));
                        }"""
                    )
                    for item in menu_items:
                        href = item.get("href", "")
                        m = PROJECT_ID_RE.search(href)
                        if not m:
                            continue
                        pid = m.group()
                        if pid in known_ids:
                            continue
                        name = item.get("text", "").strip() or "(unknown)"
                        projects.append(ProjectMeta(id=pid, name=name, discovered_via="dom_scrape"))
                        known_ids.add(pid)

                    # Fecha menu (ESC) pra nao atrapalhar
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)
            except Exception as exc:
                logger.warning(f"More-dropdown click falhou: {exc}")

            # Método 4: DOM scrape via 5 seletores + deep fallback (replica migrate.js)
            dom_selectors = [
                'a[href*="/g/g-p-"]',
                'a[href*="/project/"]',
                'nav a[href*="g-p-"]',
                '[data-testid*="project"] a',
                'li a[href*="g-p-"]',
            ]
            for sel in dom_selectors:
                try:
                    links = await page.query_selector_all(sel)
                except Exception:
                    continue
                for link in links:
                    href = (await link.get_attribute("href")) or ""
                    if "/c/" in href:
                        continue  # skip conv links
                    m = PROJECT_ID_RE.search(href)
                    if not m:
                        continue
                    pid = m.group()
                    if pid in known_ids:
                        continue
                    text = (await link.text_content() or "").strip()
                    slug_match = re.search(r"g-p-[a-f0-9]+-([^/]+)", href)
                    name = text or (slug_match.group(1).replace("-", " ") if slug_match else "(unknown)")
                    projects.append(ProjectMeta(id=pid, name=name, discovered_via="dom_scrape"))
                    known_ids.add(pid)

            # Deep fallback: se selectors nao acharam nada, varre todo <a href>
            if not any(p.discovered_via == "dom_scrape" for p in projects):
                all_anchors = await page.query_selector_all("a[href]")
                for link in all_anchors:
                    href = (await link.get_attribute("href")) or ""
                    if "/c/" in href:
                        continue
                    m = PROJECT_ID_RE.search(href)
                    if not m:
                        continue
                    pid = m.group()
                    if pid in known_ids:
                        continue
                    projects.append(ProjectMeta(id=pid, name="(unknown)", discovered_via="dom_scrape"))
                    known_ids.add(pid)

            # Método 5: __NEXT_DATA__ scan via regex
            next_data = await page.evaluate(
                "() => { const el = document.getElementById('__NEXT_DATA__');"
                " return el ? (el.textContent || el.innerText || '') : ''; }"
            )
            for pid in set(PROJECT_ID_RE.findall(next_data or "")):
                if pid not in known_ids:
                    projects.append(ProjectMeta(id=pid, name="(unknown)", discovered_via="next_data"))
                    known_ids.add(pid)
        except Exception as exc:
            logger.warning(f"DOM/__NEXT_DATA__ scan falhou: {exc}")

    logger.info(f"  Projects descobertos: {len(projects)} (métodos: {_discovery_breakdown(projects)})")

    count_before = len(by_id)
    for proj in projects:
        cursor: int | str | None = 0
        while True:
            page_metas, next_cursor = await client.list_project_conversations(
                proj.id, cursor=cursor
            )
            for meta in page_metas:
                by_id[meta.id] = meta
            if next_cursor is None or not page_metas:
                break
            cursor = next_cursor
            await asyncio.sleep(PROJECT_PAGE_SLEEP_SECONDS)
    logger.info(
        f"  Projects: {len(projects)} projetos, +{len(by_id) - count_before} convs novas"
    )

    # Mapa project_id -> nome (ultimo nome ganha se houver colisao, mas projects
    # tem id unico). Filtra placeholders "(unknown)" quando temos nome real.
    project_names: dict[str, str] = {}
    for proj in projects:
        if proj.id in project_names and project_names[proj.id] != "(unknown)":
            continue
        project_names[proj.id] = proj.name

    return list(by_id.values()), project_names


def _discovery_breakdown(projects: list[ProjectMeta]) -> str:
    """Conta projects por metodo de descoberta pra log."""
    counts: dict[str, int] = {}
    for p in projects:
        counts[p.discovered_via] = counts.get(p.discovered_via, 0) + 1
    return ", ".join(f"{k}={v}" for k, v in counts.items()) or "nenhum"


async def _paginate(list_fn, page_size: int = PAGE_SIZE):
    """Generator assincrono que itera paginas ate esgotar.

    Para endpoints offset-based (list_conversations, list_archived, list_shared).
    """
    offset = 0
    while True:
        batch = await list_fn(offset=offset, limit=page_size)
        if not batch:
            return
        for meta in batch:
            yield meta
        if len(batch) < page_size:
            return
        offset += page_size
