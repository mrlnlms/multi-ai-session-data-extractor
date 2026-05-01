"""Abre home, clica '+' campo, hover/click em 'More', tira screenshot do submenu
e captura todos os textos/items visiveis dentro dele."""

import asyncio
from pathlib import Path
from src.extractors.perplexity.auth import load_context

OUTPUT_PNG = Path("/tmp/perplexity-more-submenu.png")


async def main():
    ctx = await load_context(headless=False)
    page = await ctx.new_page()
    print("Abrindo home...")
    await page.goto("https://www.perplexity.ai/", wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(5000)

    # 1. Clicar no botao "+" do campo de ask via Playwright real click
    # (Radix UI exige pointer events, JS .click() nao dispara popover)
    print("Procurando o botao '+' do campo de ask...")
    # Estrategia: pegar boundingbox do botao Computer, identificar o '+' como
    # primeiro botao com svg/icon antes do Computer no composer
    computer_btn = page.get_by_role("button", name="Computer", exact=True).first
    await computer_btn.wait_for(state="visible", timeout=10000)
    cbox = await computer_btn.bounding_box()
    print(f"  Computer btn em {cbox}")

    # Procura todos os botoes na linha do Computer (mesmo Y aproximado)
    plus_box = await page.evaluate(f"""(cy) => {{
        const all = Array.from(document.querySelectorAll('button'));
        const candidates = all.filter(b => {{
            const r = b.getBoundingClientRect();
            return Math.abs(r.top + r.height/2 - cy) < 30  // mesma linha
                && r.width > 10 && r.width < 60  // botao pequeno (icon-only)
                && b.textContent.trim().length === 0;
        }});
        // Pega o mais a esquerda (provavel '+')
        if (candidates.length === 0) return null;
        candidates.sort((a,b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
        const t = candidates[0].getBoundingClientRect();
        return {{x: t.left + t.width/2, y: t.top + t.height/2, w: t.width, h: t.height}};
    }}""", cbox['y'] + cbox['height']/2)
    print(f"  '+' candidato em {plus_box}")

    if plus_box:
        await page.mouse.click(plus_box['x'], plus_box['y'])
        await page.wait_for_timeout(2000)
    else:
        print("  ERRO: '+' nao encontrado")

    # 2. Aguardar popover aparecer e explorar submenus
    await page.wait_for_timeout(2000)

    # Captura XHRs disparados durante hover/click
    rest_calls = []
    page.on("response", lambda r: rest_calls.append({
        "url": r.url, "status": r.status, "method": r.request.method,
        "section": _section_ref[0],
    }) if "perplexity.ai/rest/" in r.url.lower() else None)
    _section_ref = ["init"]

    for label in ["More", "Connectors and sources"]:
        _section_ref[0] = label
        print(f"\nHover em '{label}'...")
        try:
            el = page.get_by_text(label, exact=True).first
            await el.hover(timeout=5000)
            await page.wait_for_timeout(2500)
            print(f"  hover ok")
        except Exception as e:
            print(f"  hover falhou: {str(e)[:80]}")
            continue

        # Captura items de TODOS os menus abertos
        items = await page.evaluate("""() => {
            const menus = Array.from(document.querySelectorAll('[role="menu"]'));
            return menus.map((m, idx) => {
                const items = Array.from(m.querySelectorAll('[role="menuitem"]'));
                return {idx, items: items.map(i => i.textContent.trim())};
            });
        }""")
        print(f"  Menus abertos ({len(items)}):")
        for menu in items:
            print(f"    [menu#{menu['idx']}]")
            for it in menu['items']:
                print(f"      - {it}")

    print(f"\nXHRs disparados ({len(rest_calls)}):")
    seen = set()
    for c in rest_calls:
        path = c["url"].split("?")[0].split("/rest/", 1)[-1]
        key = (c["section"], path)
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{c['section']}] [{c['status']}] {c['method']:5} {path}")

    # 3. Screenshot do estado atual
    print(f"\nScreenshot em {OUTPUT_PNG}")
    await page.screenshot(path=str(OUTPUT_PNG), full_page=False)

    # 4. Pega texto visivel de todos os items do popover/submenu
    print("\nItems visiveis nos popovers/menus:")
    items = await page.evaluate("""() => {
        // Procura todos elementos com role=menu, role=menuitem, ou popover
        const containers = Array.from(document.querySelectorAll(
            '[role="menu"], [role="menuitem"], [data-radix-popper-content-wrapper], [role="dialog"]'
        ));
        const out = [];
        for (const c of containers) {
            const text = c.innerText.replace(/\\s+/g, ' ').trim().slice(0, 600);
            if (text) out.push({role: c.getAttribute('role') || c.tagName, text});
        }
        return out;
    }""")
    for it in items:
        print(f"  [{it['role']}] {it['text']}")

    await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
